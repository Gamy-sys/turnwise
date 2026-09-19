"""In-app updates via git pull.

Designed for installs that were `git clone`d (or zip installs that later
connected a remote). User data under data/ is never touched — it is gitignored.
After a successful pull the UI is rebuilt so friends get the latest frontend
without running npm by hand.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .config import DATA_DIR, PROJECT_DIR

UPDATE_CONFIG_FILE = DATA_DIR / "update_config.json"
APP_VERSION = "0.2.0"

_lock = threading.Lock()
_job: dict | None = None


def _run(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 120,
    env: dict | None = None,
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode, out
    except FileNotFoundError:
        return 127, f"command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {' '.join(args)}"


def load_update_config() -> dict:
    cfg: dict = {}
    try:
        cfg = json.loads(UPDATE_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    remote = (
        os.environ.get("CA_UPDATE_REMOTE")
        or cfg.get("remote_url")
        or ""
    ).strip()
    branch = (
        os.environ.get("CA_UPDATE_BRANCH")
        or cfg.get("branch")
        or "main"
    ).strip() or "main"
    return {"remote_url": remote, "branch": branch}


def save_update_config(remote_url: str | None = None, branch: str | None = None) -> dict:
    cfg = load_update_config()
    if remote_url is not None:
        cfg["remote_url"] = (remote_url or "").strip()
    if branch is not None:
        cfg["branch"] = (branch or "main").strip() or "main"
    # Don't persist env-only overrides as empty wipe
    UPDATE_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def find_git_root(start: Path | None = None) -> Path | None:
    """Locate the git checkout used for updates.

    Prefer a `.git` inside the Turnwise folder itself so a parent monorepo
    (unrelated projects) is not mutated. Walk up only when
    CA_UPDATE_ALLOW_PARENT=1 or update_config.allow_parent is true.
    """
    start = (start or PROJECT_DIR).resolve()
    if (start / ".git").exists():
        return start

    cfg = {}
    try:
        cfg = json.loads(UPDATE_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    allow_parent = (
        os.environ.get("CA_UPDATE_ALLOW_PARENT", "").strip() in ("1", "true", "yes")
        or bool(cfg.get("allow_parent"))
    )
    if not allow_parent:
        return None

    cur = start.parent
    for _ in range(8):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _git(root: Path, *args: str, timeout: int = 120) -> tuple[int, str]:
    return _run(["git", "-C", str(root), *args], timeout=timeout)


def _preserve_clean_excludes() -> list[str]:
    """Paths git clean must never delete (user data + heavy local installs)."""
    return [
        "data",
        "backend/.venv",
        "frontend/node_modules",
        "frontend/dist",
        "desktop/node_modules",
        "desktop/dist",
        "dist-mac",
        "BUILD-LOG.txt",
        ".turnwise-server.log",
        ".turnwise-server.pid",
        ".turnwise.port",
        "packaging/friend-secrets.json",
    ]


def _make_tree_safe_for_checkout(root: Path) -> tuple[bool, str]:
    """Drop local app-file conflicts so checkout/reset can reach origin.

    Zip installs and Mac reinstalls leave untracked copies of frontend/, run.sh,
    etc. Git refuses to overwrite those on checkout. User projects and secrets
    live under data/ and are excluded.
    """
    logs: list[str] = []
    # Discard tracked local edits when a commit exists
    code, _ = _git(root, "rev-parse", "--verify", "HEAD")
    if code == 0:
        code, out = _git(root, "reset", "--hard", "HEAD")
        if code != 0:
            logs.append(out[-300:])
        else:
            logs.append("reset local tracked edits")

    clean_args = ["clean", "-fd"]
    for excl in _preserve_clean_excludes():
        clean_args.extend(["-e", excl])
    code, out = _git(root, *clean_args, timeout=180)
    if code != 0:
        return False, f"git clean failed: {out[-500:]}"
    logs.append("cleared conflicting untracked app files (data/ kept)")
    return True, "; ".join(logs)


def _short(s: str, n: int = 7) -> str:
    s = (s or "").strip()
    return s[:n] if s else ""


@dataclass
class UpdateStatus:
    ok: bool = True
    app_version: str = APP_VERSION
    git_available: bool = False
    is_repo: bool = False
    root: str | None = None
    remote_url: str = ""
    branch: str = "main"
    current_commit: str | None = None
    current_subject: str | None = None
    remote_commit: str | None = None
    behind: int | None = None
    ahead: int | None = None
    dirty: bool = False
    update_available: bool = False
    message: str = ""
    job: dict | None = None
    hint: str = ""
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "ok": self.ok,
            "app_version": self.app_version,
            "git_available": self.git_available,
            "is_repo": self.is_repo,
            "root": self.root,
            "remote_url": self.remote_url,
            "branch": self.branch,
            "current_commit": self.current_commit,
            "current_subject": self.current_subject,
            "remote_commit": self.remote_commit,
            "behind": self.behind,
            "ahead": self.ahead,
            "dirty": self.dirty,
            "update_available": self.update_available,
            "message": self.message,
            "job": self.job,
            "hint": self.hint,
        }
        d.update(self.extras)
        return d


def get_status(fetch: bool = False) -> dict:
    """Return whether an update is available. Optionally `git fetch` first."""
    global _job
    cfg = load_update_config()
    st = UpdateStatus(
        remote_url=cfg["remote_url"],
        branch=cfg["branch"],
        job=_job,
    )

    code, _ = _run(["git", "--version"], timeout=10)
    st.git_available = code == 0
    if not st.git_available:
        st.ok = False
        st.message = "git is not installed on this machine"
        st.hint = "Install git (Mac: xcode-select --install or brew install git), then restart Turnwise."
        return st.to_dict()

    root = find_git_root()
    if not root:
        st.message = "This install is not a git checkout"
        st.hint = (
            "Install with git clone so Update works, or paste your repo URL below "
            "and click Connect. Zip-only installs cannot pull updates."
        )
        return st.to_dict()

    st.is_repo = True
    st.root = str(root)

    code, out = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if code == 0 and out and out != "HEAD":
        st.branch = out.strip()
    elif cfg["branch"]:
        st.branch = cfg["branch"]

    code, out = _git(root, "rev-parse", "HEAD")
    if code == 0:
        st.current_commit = _short(out, 40)
    code, out = _git(root, "log", "-1", "--pretty=%s")
    if code == 0:
        st.current_subject = out.strip()[:120]

    code, out = _git(root, "status", "--porcelain")
    st.dirty = bool(out.strip()) if code == 0 else False

    # Resolve remote URL: config override → origin
    remote_url = cfg["remote_url"]
    if not remote_url:
        code, out = _git(root, "remote", "get-url", "origin")
        if code == 0:
            remote_url = out.strip()
            st.remote_url = remote_url
    else:
        st.remote_url = remote_url

    if not remote_url:
        st.message = "No git remote configured"
        st.hint = "Paste the GitHub/GitLab clone URL and click Save remote, then Update."
        return st.to_dict()

    # Ensure origin points at the configured URL when set
    if cfg["remote_url"]:
        code, cur = _git(root, "remote", "get-url", "origin")
        if code != 0:
            _git(root, "remote", "add", "origin", cfg["remote_url"])
        elif cur.strip() != cfg["remote_url"]:
            _git(root, "remote", "set-url", "origin", cfg["remote_url"])

    if fetch:
        code, out = _git(root, "fetch", "--prune", "origin", timeout=180)
        if code != 0:
            st.ok = False
            st.message = "Could not reach the remote"
            st.hint = out[-500:] if out else "Check network / repo access."
            return st.to_dict()

    # Compare to origin/<branch>
    ref = f"origin/{st.branch}"
    code, out = _git(root, "rev-parse", "--verify", ref)
    if code != 0:
        # try default branch names
        for guess in ("main", "master"):
            code, out = _git(root, "rev-parse", "--verify", f"origin/{guess}")
            if code == 0:
                st.branch = guess
                ref = f"origin/{guess}"
                break
        else:
            st.message = "Remote branch not found yet — fetch first or check the branch name"
            st.hint = f"Expected origin/{cfg['branch']}"
            return st.to_dict()

    st.remote_commit = _short(out, 40)
    code, out = _git(root, "rev-list", "--left-right", "--count", f"HEAD...{ref}")
    if code == 0:
        parts = out.strip().split()
        if len(parts) == 2:
            try:
                st.ahead = int(parts[0])
                st.behind = int(parts[1])
            except ValueError:
                pass

    st.update_available = bool(st.behind and st.behind > 0)
    if st.update_available:
        st.message = f"{st.behind} update{'s' if st.behind != 1 else ''} available"
    elif st.dirty:
        st.message = "Up to date with remote (local edits present — update may fail)"
    else:
        st.message = "Already up to date"

    return st.to_dict()


def connect_remote(remote_url: str, branch: str = "main") -> dict:
    """Attach a remote to an existing folder (zip install → git updates).

    Initializes a repo in the Turnwise folder if needed, adds origin, fetches,
    and fast-forwards to the remote branch. Local data/ and venvs stay put
    because they are gitignored / untracked.
    """
    remote_url = (remote_url or "").strip()
    branch = (branch or "main").strip() or "main"
    if not remote_url:
        return {"ok": False, "message": "Remote URL is required"}

    code, _ = _run(["git", "--version"], timeout=10)
    if code != 0:
        return {"ok": False, "message": "git is not installed"}

    save_update_config(remote_url=remote_url, branch=branch)
    root = find_git_root() or PROJECT_DIR

    if not (root / ".git").exists():
        # Prefer initializing inside Turnwise itself (not a parent mono-repo)
        root = PROJECT_DIR
        code, out = _git(root, "init", "-b", branch)
        if code != 0:
            code, out = _git(root, "init")
            if code != 0:
                return {"ok": False, "message": f"git init failed: {out}"}

    code, _ = _git(root, "remote", "get-url", "origin")
    if code != 0:
        code, out = _git(root, "remote", "add", "origin", remote_url)
    else:
        code, out = _git(root, "remote", "set-url", "origin", remote_url)
    if code != 0:
        return {"ok": False, "message": f"Could not set remote: {out}"}

    code, out = _git(root, "fetch", "--prune", "origin", timeout=300)
    if code != 0:
        return {"ok": False, "message": f"Fetch failed: {out[-800:]}"}

    # Prefer a clean checkout of the remote tip without deleting untracked data/
    ref = f"origin/{branch}"
    code, _ = _git(root, "rev-parse", "--verify", ref)
    if code != 0:
        for guess in ("main", "master"):
            code, _ = _git(root, "rev-parse", "--verify", f"origin/{guess}")
            if code == 0:
                branch = guess
                ref = f"origin/{guess}"
                save_update_config(branch=branch)
                break
        else:
            return {"ok": False, "message": f"Branch not found on remote (tried {branch})"}

    # If no commits yet locally, just check out tracking branch
    code, _ = _git(root, "rev-parse", "--verify", "HEAD")
    if code != 0:
        ok_clean, clean_msg = _make_tree_safe_for_checkout(root)
        if not ok_clean:
            return {"ok": False, "message": clean_msg}
        code, out = _git(root, "checkout", "-B", branch, ref)
        if code != 0:
            return {"ok": False, "message": f"Checkout failed: {out[-500:]}"}
    else:
        ok_clean, clean_msg = _make_tree_safe_for_checkout(root)
        if not ok_clean:
            return {"ok": False, "message": clean_msg}
        code, out = _git(root, "checkout", "-B", branch, ref)
        if code != 0:
            # fall back to reset --hard of tracked files only
            code2, out2 = _git(root, "reset", "--hard", ref)
            if code2 != 0:
                return {"ok": False, "message": f"Could not sync: {out[-400:]}\n{out2[-400:]}"}

    # After first connect, rebuild UI
    rebuild = _rebuild_frontend()
    return {
        "ok": True,
        "message": f"Connected to {remote_url} ({branch})",
        "rebuild": rebuild,
        "status": get_status(fetch=False),
    }


def _rebuild_frontend() -> dict:
    frontend = PROJECT_DIR / "frontend"
    if not (frontend / "package.json").exists():
        return {"ok": False, "message": "frontend/ not found"}
    npm = shutil.which("npm")
    if not npm:
        return {
            "ok": False,
            "message": "npm not found — UI source updated but not rebuilt. Install Node.js and rebuild.",
        }
    code, out = _run([npm, "install"], cwd=frontend, timeout=600)
    if code != 0:
        return {"ok": False, "message": f"npm install failed: {out[-600:]}"}
    code, out = _run([npm, "run", "build"], cwd=frontend, timeout=600)
    if code != 0:
        return {"ok": False, "message": f"npm run build failed: {out[-600:]}"}
    return {"ok": True, "message": "Frontend rebuilt"}


def _refresh_python_deps() -> dict:
    req = PROJECT_DIR / "backend" / "requirements.txt"
    if not req.exists():
        return {"ok": True, "message": "no requirements.txt"}
    pip = [sys.executable, "-m", "pip", "install", "-r", str(req)]
    code, out = _run(pip, cwd=PROJECT_DIR / "backend", timeout=900)
    if code != 0:
        return {"ok": False, "message": f"pip install failed: {out[-500:]}"}
    return {"ok": True, "message": "Python deps refreshed"}


def apply_update() -> dict:
    """Fetch + fast-forward pull, rebuild UI, refresh deps. Serialized."""
    global _job
    if not _lock.acquire(blocking=False):
        return {"ok": False, "message": "An update is already running", "job": _job}

    try:
        _job = {"state": "running", "stage": "check", "log": []}
        st = get_status(fetch=True)
        if not st.get("is_repo"):
            _job = {"state": "error", "stage": "check", "log": [st.get("message", "")]}
            return {"ok": False, "message": st.get("message") or "Not a git install", "status": st, "job": _job}
        if not st.get("ok") and st.get("behind") is None:
            _job = {"state": "error", "stage": "fetch", "log": [st.get("message", "")]}
            return {"ok": False, "message": st.get("message") or "Fetch failed", "status": st, "job": _job}

        root = Path(st["root"])
        branch = st.get("branch") or load_update_config()["branch"]
        ref = f"origin/{branch}"

        if not st.get("update_available"):
            _job = {"state": "done", "stage": "idle", "log": ["Already up to date"]}
            return {
                "ok": True,
                "changed": False,
                "message": "Already up to date",
                "status": st,
                "job": _job,
                "restart_recommended": False,
            }

        _job = {"state": "running", "stage": "pull", "log": [f"Pulling {ref}…"]}
        # Prefer fast-forward only so we never invent merge commits for the friend
        code, out = _git(root, "merge", "--ff-only", ref, timeout=180)
        if code != 0:
            ok_clean, clean_msg = _make_tree_safe_for_checkout(root)
            _job["log"].append(clean_msg)
            code2, out2 = _git(root, "reset", "--hard", ref, timeout=120)
            if code2 != 0 and ok_clean:
                # Untracked blockers may remain after soft failure; try once more
                _make_tree_safe_for_checkout(root)
                code2, out2 = _git(root, "reset", "--hard", ref, timeout=120)
            if code2 != 0:
                _job = {
                    "state": "error",
                    "stage": "pull",
                    "log": [out[-400:], out2[-400:]],
                }
                return {
                    "ok": False,
                    "message": (
                        "Could not update — local files conflict with the remote. "
                        "In Terminal, from the Turnwise folder, run:\n"
                        "  git fetch origin && git clean -fd -e data -e backend/.venv "
                        "-e frontend/node_modules && git reset --hard origin/main"
                    ),
                    "detail": (out + "\n" + out2)[-800:],
                    "job": _job,
                }

        _job = {"state": "running", "stage": "frontend", "log": ["Rebuilding UI…"]}
        rebuild = _rebuild_frontend()

        _job = {"state": "running", "stage": "deps", "log": ["Refreshing Python packages…"]}
        deps = _refresh_python_deps()

        final = get_status(fetch=False)
        logs = [
            "Pull OK",
            rebuild.get("message", ""),
            deps.get("message", ""),
        ]
        _job = {
            "state": "done",
            "stage": "done",
            "log": [x for x in logs if x],
            "rebuild_ok": rebuild.get("ok"),
            "deps_ok": deps.get("ok"),
        }
        return {
            "ok": True,
            "changed": True,
            "message": "Updated. Reload the page (or restart Turnwise) to use the new version.",
            "status": final,
            "rebuild": rebuild,
            "deps": deps,
            "job": _job,
            "restart_recommended": True,
        }
    finally:
        _lock.release()
