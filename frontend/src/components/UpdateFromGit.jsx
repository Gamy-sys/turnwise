import React, { useCallback, useEffect, useState } from "react";
import * as api from "../api.js";

/**
 * Top-bar control: check for / apply git updates.
 * Friend installs via git clone (or Connect with a repo URL once), then clicks Update.
 */
export default function UpdateFromGit({ onToast }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [remoteUrl, setRemoteUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [log, setLog] = useState("");

  const toast = (msg) => onToast && onToast(msg);

  const refresh = useCallback(async (doFetch = false) => {
    try {
      const st = await api.getUpdateStatus(doFetch);
      setStatus(st);
      if (st.remote_url) setRemoteUrl(st.remote_url);
      if (st.branch) setBranch(st.branch);
      return st;
    } catch (e) {
      toast(e.message || "Could not check for updates");
      return null;
    }
  }, [onToast]);

  useEffect(() => {
    refresh(false);
  }, [refresh]);

  const check = async () => {
    setBusy(true);
    setLog("");
    try {
      const st = await refresh(true);
      if (!st) return;
      toast(st.message || (st.update_available ? "Update available" : "Up to date"));
    } finally {
      setBusy(false);
    }
  };

  const saveRemote = async () => {
    setBusy(true);
    try {
      const res = await api.saveUpdateConfig({ remote_url: remoteUrl.trim(), branch: branch.trim() || "main" });
      setStatus(res.status || res);
      toast("Remote saved");
    } catch (e) {
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };

  const connect = async () => {
    if (!remoteUrl.trim()) {
      toast("Paste the git clone URL first");
      return;
    }
    if (!confirm("Connect this install to the git repo? Existing projects in data/ are kept.")) return;
    setBusy(true);
    setLog("Connecting…");
    try {
      const res = await api.connectUpdate({ remote_url: remoteUrl.trim(), branch: branch.trim() || "main" });
      setStatus(res.status || null);
      setLog(res.message || "Connected");
      toast(res.message || "Connected");
      await refresh(false);
    } catch (e) {
      setLog(e.message);
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!confirm("Pull the latest version from git, rebuild the UI, and refresh packages?")) return;
    setBusy(true);
    setLog("Updating… this can take a few minutes");
    try {
      const res = await api.applyUpdate();
      setStatus(res.status || null);
      const bits = [res.message];
      if (res.rebuild?.message) bits.push(res.rebuild.message);
      if (res.deps?.message) bits.push(res.deps.message);
      setLog(bits.filter(Boolean).join("\n"));
      toast(res.message || "Updated");
      if (res.restart_recommended || res.changed) {
        setTimeout(() => {
          if (confirm("Update applied. Reload the page now?")) window.location.reload();
        }, 400);
      }
    } catch (e) {
      setLog(e.message);
      toast(e.message);
    } finally {
      setBusy(false);
      refresh(false);
    }
  };

  const badge = status?.update_available
    ? "update"
    : status?.is_repo
      ? "ok"
      : "warn";

  return (
    <div className="update-git">
      <button
        type="button"
        className={"btn update-git-btn " + badge}
        disabled={busy}
        onClick={() => {
          setOpen((v) => !v);
          if (!open) refresh(false);
        }}
        title="Update Turnwise from git"
      >
        {busy ? "…" : status?.update_available ? "↓ Update" : "↻ Update from Git"}
      </button>

      {open && (
        <div className="update-git-panel">
          <div className="update-git-head">
            <strong>Update from Git</strong>
            <button type="button" className="x" onClick={() => setOpen(false)}>✕</button>
          </div>
          <p className="hint">
            v{status?.app_version || "?"}
            {status?.current_commit ? ` · ${status.current_commit.slice(0, 7)}` : ""}
            {status?.current_subject ? ` — ${status.current_subject}` : ""}
          </p>
          <p className={"update-msg " + badge}>{status?.message || "Checking…"}</p>
          {status?.hint && <p className="hint">{status.hint}</p>}

          <label className="field">
            <span>Repo URL (HTTPS or SSH)</span>
            <input
              value={remoteUrl}
              placeholder="https://github.com/you/turnwise.git"
              onChange={(e) => setRemoteUrl(e.target.value)}
              disabled={busy}
            />
          </label>
          <label className="field">
            <span>Branch</span>
            <input
              value={branch}
              placeholder="main"
              onChange={(e) => setBranch(e.target.value)}
              disabled={busy}
            />
          </label>

          <div className="update-git-actions">
            <button type="button" className="btn" disabled={busy} onClick={saveRemote}>
              Save remote
            </button>
            {!status?.is_repo && (
              <button type="button" className="btn" disabled={busy} onClick={connect}>
                Connect
              </button>
            )}
            <button type="button" className="btn" disabled={busy} onClick={check}>
              Check
            </button>
            <button
              type="button"
              className="btn primary"
              disabled={busy || !status?.update_available}
              onClick={apply}
              title={status?.update_available ? "Pull and rebuild" : "Nothing new to pull"}
            >
              {busy ? "Working…" : "Update now"}
            </button>
          </div>
          {log && <pre className="update-log">{log}</pre>}
        </div>
      )}
    </div>
  );
}
