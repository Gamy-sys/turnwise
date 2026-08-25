/**
 * Turnwise desktop shell.
 *
 * Starts the local Python backend (uvicorn) and opens the UI in a BrowserWindow.
 * On first launch it creates a user-data Python venv if needed.
 */
const { app, BrowserWindow, dialog, shell, Menu } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");
const os = require("os");

const PORT_START = 8741;
let serverProc = null;
let mainWindow = null;
let boundPort = PORT_START;

function isPackaged() {
  return app.isPackaged;
}

function appRoot() {
  // Dev: desktop/ → ca-studio/
  // Packaged: Contents/Resources/
  if (isPackaged()) return process.resourcesPath;
  return path.resolve(__dirname, "..");
}

function userDataRoot() {
  return path.join(app.getPath("userData"), "runtime");
}

function pythonBin() {
  const venv = path.join(userDataRoot(), "venv");
  return process.platform === "win32"
    ? path.join(venv, "Scripts", "python.exe")
    : path.join(venv, "bin", "python");
}

function waitForHttp(port, tries = 90) {
  return new Promise((resolve, reject) => {
    let n = 0;
    const tick = () => {
      const req = http.get({ host: "127.0.0.1", port, path: "/", timeout: 800 }, (res) => {
        res.resume();
        resolve(port);
      });
      req.on("error", () => {
        if (++n >= tries) reject(new Error("Turnwise backend did not start in time"));
        else setTimeout(tick, 500);
      });
      req.on("timeout", () => {
        req.destroy();
        if (++n >= tries) reject(new Error("Turnwise backend did not start in time"));
        else setTimeout(tick, 500);
      });
    };
    tick();
  });
}

function portFree(port) {
  return new Promise((resolve) => {
    const server = require("net").createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen(port, "127.0.0.1");
  });
}

async function pickPort() {
  for (let p = PORT_START; p < PORT_START + 20; p++) {
    if (await portFree(p)) return p;
  }
  return PORT_START;
}

async function ensurePython() {
  const root = userDataRoot();
  const venv = path.join(root, "venv");
  const py = pythonBin();
  fs.mkdirSync(root, { recursive: true });

  if (!fs.existsSync(py)) {
    await new Promise((resolve, reject) => {
      const setup = spawn("python3", ["-m", "venv", venv], { stdio: "inherit" });
      setup.on("exit", (code) => (code === 0 ? resolve() : reject(new Error("venv failed"))));
    });
  }

  // Install / refresh deps from the bundled requirements
  const req = path.join(appRoot(), "backend", "requirements.txt");
  if (fs.existsSync(req)) {
    await new Promise((resolve) => {
      const pip = spawn(py, ["-m", "pip", "install", "-r", req], { stdio: "inherit" });
      pip.on("exit", () => resolve());
    });
  }
  return py;
}

async function startBackend() {
  boundPort = await pickPort();
  const py = await ensurePython();
  const backend = path.join(appRoot(), "backend");
  const env = {
    ...process.env,
    CA_DATA_DIR: path.join(userDataRoot(), "data"),
    PYTHONPATH: backend,
  };
  serverProc = spawn(
    py,
    ["-m", "uvicorn", "app.main:app", "--app-dir", backend, "--host", "127.0.0.1", "--port", String(boundPort)],
    { cwd: backend, env, stdio: "inherit" }
  );
  serverProc.on("exit", (code) => {
    serverProc = null;
    if (mainWindow && code && code !== 0) {
      dialog.showErrorBox("Turnwise", `Backend exited unexpectedly (code ${code}).`);
    }
  });
  await waitForHttp(boundPort);
  return boundPort;
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    title: "Turnwise",
    backgroundColor: "#0d1117",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function buildMenu() {
  const template = [
    ...(process.platform === "darwin"
      ? [{
          label: app.name,
          submenu: [
            { role: "about" },
            { type: "separator" },
            { role: "services" },
            { type: "separator" },
            { role: "hide" },
            { role: "hideOthers" },
            { role: "unhide" },
            { type: "separator" },
            { role: "quit" },
          ],
        }]
      : []),
    {
      label: "File",
      submenu: [
        {
          label: "Open data folder",
          click: () => shell.openPath(path.join(userDataRoot(), "data")),
        },
        { type: "separator" },
        process.platform === "darwin" ? { role: "close" } : { role: "quit" },
      ],
    },
    { role: "editMenu" },
    { role: "viewMenu" },
    { role: "windowMenu" },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function boot() {
  buildMenu();
  try {
    const port = await startBackend();
    createWindow(port);
  } catch (err) {
    dialog.showErrorBox(
      "Turnwise failed to start",
      `${err.message}\n\nMake sure Python 3.10+, ffmpeg, and Node deps are available.\nOn first launch Turnwise installs Python packages — that can take several minutes.`
    );
    app.quit();
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  app.whenReady().then(boot);
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("activate", () => {
    if (!mainWindow && boundPort) createWindow(boundPort);
  });
  app.on("before-quit", () => {
    if (serverProc) {
      try { serverProc.kill("SIGTERM"); } catch (_) {}
      serverProc = null;
    }
  });
}
