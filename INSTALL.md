# Turnwise — install from zip

Turnwise transcribes audio with Conversation Analysis (Jefferson) notation.
This zip contains the app source and a **pre-built UI**. Your friend does **not**
need your projects, API keys, or downloaded Whisper models — those are created on
first run.

---

## Recommended: install from Git (so Update works)

If you want the in-app **↻ Update from Git** button (friend clicks it after you
push new commits), install with git instead of a zip:

```bash
git clone https://github.com/Gamy-sys/turnwise.git
cd turnwise          # folder that contains run.sh
chmod +x run.sh
./run.sh
```

Then open http://127.0.0.1:8000 → top-right **Update from Git** → **Check** /
**Update now**. Projects and API keys in `data/` are kept across updates.

**Publisher (you):** push to that same repo when you have a new version ready.
Your friend only needs to click Update.

Zip installs can still use Update: open **Update from Git**, paste the same
clone URL, click **Connect** once (requires `git` + `npm` on the machine).

---

## What you need first

| Tool | Linux | macOS |
|------|-------|-------|
| **Python 3.10+** | `sudo apt install python3 python3-venv python3-pip` | `brew install python@3.12` or python.org |
| **ffmpeg** | `sudo apt install ffmpeg` | `brew install ffmpeg` |
| **git** | `sudo apt install git` | `xcode-select --install` or `brew install git` |
| **Node.js 18+** | Needed for **Update from Git** (rebuilds UI) | Same (`brew install node`) |
| **Internet** | First run downloads Whisper + optional models | Same |

Disk: allow **~2–5 GB** free for Python packages and at least one Whisper model.

---

## Quick start (Linux or macOS — browser)

1. **Unzip** this folder anywhere, e.g. `~/Turnwise`  
   *(or use `git clone` above)*

2. **Open a terminal** in the folder that contains `run.sh`.

3. **Run:**

   ```bash
   chmod +x run.sh desktop-launch.sh
   ./run.sh
   ```

4. **Open in your browser:** http://127.0.0.1:8000

   - **Simple** — batch transcribe many files (input folder → output folder)
   - **Advanced** — full editor (waveform, pitch, collections, exports)
   - **↻ Update from Git** (top-right) — pull the latest version you published

5. **Stop the server:** press `Ctrl+C` in the terminal.

The first launch installs Python packages into `backend/.venv` (several minutes).
The first transcription downloads the Whisper model you pick in settings.

---

## Optional: desktop shortcut (Linux)

```bash
chmod +x desktop-launch.sh
./desktop-launch.sh
```

Starts the server if needed and opens the default browser.

---

## macOS app (.dmg) — build on a Mac only

If your friend has a **Mac** and wants a normal **Turnwise.app**:

1. Install prerequisites:

   ```bash
   xcode-select --install          # if not already
   brew install ffmpeg python@3.12 node git
   ```

2. From the unzipped (or cloned) folder:

   ```bash
   chmod +x scripts/build-mac.sh
   ./scripts/build-mac.sh
   ```

3. Open `desktop/dist/Turnwise-*.dmg`, drag **Turnwise** into **Applications**.

4. First launch: allow the app if macOS warns about an unsigned developer.
   Turnwise installs Python deps under  
   `~/Library/Application Support/Turnwise` — wait a few minutes.

**Note:** The packaged `.app` bundles a snapshot of the code. For easy
**Update from Git**, prefer running from a `git clone` via `./run.sh` (or rebuild
the `.dmg` after each update).

---

## Settings & API keys (optional)

- **Hugging Face token** — speaker diarization (free account at huggingface.co).
  In **Advanced**, open a project → **⚙** next to the project name → paste token once.
  Keys are saved locally on that machine; they are **not** included in this zip.

- **OpenAI key** — only for Japanese 4-line direct/natural English translations.
  Same ⚙ project settings panel.

---

## Folder layout (after unzip)

```
turnwise/
  run.sh              ← start here
  INSTALL.md          ← this file
  README.md           ← full documentation
  backend/            ← Python server + transcription pipeline
  frontend/dist/      ← built UI (served by run.sh)
  frontend/src/       ← source (only needed to rebuild UI)
  desktop/            ← Mac Electron wrapper (optional)
  scripts/            ← build-mac.sh, etc.
  icons/
  sample.mp3          ← tiny demo file (optional test)
```

User data is stored in `data/` (created on first run): projects, models, secrets.

---

## Troubleshooting

**`ffmpeg not found`** — install ffmpeg (see table above).

**`python3: command not found`** — install Python 3.10+.

**Port 8000 in use** — `run.sh` picks the next free port (8001, 8002, …); read the terminal line that says `Turnwise on http://127.0.0.1:XXXX`.

**Transcription very slow** — CPU is normal; use a smaller model (`tiny` / `base` / `small`) in Simple or project ⚙ settings.

**Update from Git failed** — install `git` and `node`/`npm`. Confirm the repo URL is correct and the machine can reach GitHub/GitLab. Local project files in `data/` are never overwritten.

**Rebuild UI** (only if you changed frontend code by hand):

```bash
cd frontend && npm install && npm run build && cd ..
./run.sh
```

---

## Support

Full feature list and CA notation details: see `README.md`.
