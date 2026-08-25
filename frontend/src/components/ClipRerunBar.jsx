import React, { useEffect, useState } from "react";
import * as api from "../api.js";

/**
 * Re-transcribe the open collection clip from its own audio.
 * Shown under the waveform while viewing a clip.
 */
export default function ClipRerunBar({
  pid,
  viewing,
  settings,
  onToast,
  onUpdated,
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [localSettings, setLocalSettings] = useState(null);

  useEffect(() => {
    setOpen(false);
    setLocalSettings(null);
  }, [viewing?.eid, viewing?.cid]);

  useEffect(() => {
    if (open && settings && !localSettings) {
      setLocalSettings({
        whisper_model:
          settings.whisper_model === "nyrahealth/faster_CrisperWhisper"
            ? "medium"
            : settings.whisper_model || "medium",
        beam_size: settings.beam_size || 5,
        vad_filter: false,
        language: settings.language || "en",
        verbatim: settings.verbatim !== false,
        compute_type: settings.compute_type || "int8",
        device: settings.device || "auto",
      });
    }
  }, [open, settings, localSettings]);

  if (!viewing || !pid) return null;

  const setLS = (k, v) => setLocalSettings((prev) => ({ ...prev, [k]: v }));

  const run = async () => {
    if (!localSettings) return;
    setBusy(true);
    try {
      const res = await api.reprocessCollectionElement(pid, viewing.cid, viewing.eid, {
        settings: { ...(settings || {}), ...localSettings },
        speaker: null,
      });
      onToast && onToast(
        `Re-ran “${res.meta?.label || viewing.label}” → ${res.added} word(s)`
      );
      onUpdated && onUpdated(res);
      setOpen(false);
    } catch (e) {
      onToast && onToast(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wave-clip-rerun">
      <div className="wave-quick-add">
        <button
          type="button"
          className={"btn" + (open ? " primary" : "")}
          disabled={busy}
          onClick={() => setOpen((v) => !v)}
          title="Re-transcribe this clip from its own audio"
        >
          {busy ? "Re-transcribing…" : "↻ Rerun transcription"}
        </button>
        <span className="wave-quick-meta muted">
          Re-ASR this clip only — parent project unchanged
        </span>
      </div>

      {open && localSettings && (
        <div className="elem-rerun-panel wave-rerun-panel">
          <p className="hint">
            Prefer medium/small over CrisperWhisper for short clips.
          </p>
          <div className="rerun-grid">
            <label>
              Model
              <select
                value={localSettings.whisper_model}
                onChange={(e) => setLS("whisper_model", e.target.value)}
              >
                {["tiny", "base", "small", "medium", "large-v3"].map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </label>
            <label>
              Beam
              <input
                type="number"
                min={1}
                max={10}
                value={localSettings.beam_size}
                onChange={(e) => setLS("beam_size", parseInt(e.target.value) || 5)}
              />
            </label>
            <label>
              Language
              <input
                value={localSettings.language || ""}
                onChange={(e) => setLS("language", e.target.value || null)}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={!!localSettings.vad_filter}
                onChange={(e) => setLS("vad_filter", e.target.checked)}
              />
              VAD
            </label>
          </div>
          <div className="edit-form">
            <button className="btn primary tiny" disabled={busy} onClick={run}>
              {busy ? "Re-transcribing…" : "Run"}
            </button>
            <button className="btn tiny" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
