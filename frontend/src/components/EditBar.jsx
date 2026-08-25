import React, { useEffect, useState } from "react";

/**
 * Editing toolbar: add a word/phrase timed from the waveform selection,
 * or re-ASR only the selected range with adjustable settings.
 */
export default function EditBar({
  region,
  speakers,
  settings,
  busy,
  onAddPhrase,
  onApplyTimingToSelected,
  onRerunRange,
  onAbortRerun,
  onPlayRegion,
  selectedToken,
}) {
  const [mode, setMode] = useState(null); // null | "add" | "rerun"
  const [phrase, setPhrase] = useState("");
  const [speaker, setSpeaker] = useState(speakers?.[0]?.id || "A");
  const [localSettings, setLocalSettings] = useState(null);

  useEffect(() => {
    if (speakers?.length && !speakers.find((s) => s.id === speaker)) {
      setSpeaker(speakers[0].id);
    }
  }, [speakers, speaker]);

  useEffect(() => {
    if (mode === "rerun" && settings && !localSettings) {
      setLocalSettings({
        whisper_model: settings.whisper_model,
        beam_size: settings.beam_size,
        vad_filter: !!settings.vad_filter,
        language: settings.language || "",
        verbatim: settings.verbatim !== false,
        compute_type: settings.compute_type,
        device: settings.device,
      });
    }
  }, [mode, settings, localSettings]);

  const hasRegion = region && region.end > region.start;
  const fmt = (s) => (s == null ? "—" : Number(s).toFixed(2) + "s");

  const setLS = (k, v) => setLocalSettings((prev) => ({ ...prev, [k]: v }));

  return (
    <div className="edit-bar">
      <div className="edit-bar-row">
        <span className="edit-label">Edit tools</span>
        <button
          className={"chip" + (mode === "add" ? " on" : "")}
          onClick={() => setMode(mode === "add" ? null : "add")}
          title="Type a word or phrase, then drag on the waveform to set its timing"
        >
          + Add from wave
        </button>
        <button
          className={"chip" + (mode === "rerun" ? " on" : "")}
          disabled={!hasRegion}
          onClick={() => setMode(mode === "rerun" ? null : "rerun")}
          title="Re-transcribe only the waveform selection (rest of transcript kept)"
        >
          ↻ Rerun selected
        </button>
        <button
          className="chip"
          disabled={!hasRegion || !selectedToken}
          onClick={() => hasRegion && onApplyTimingToSelected(region.start, region.end)}
          title="Apply the waveform selection as start/end of the selected word"
        >
          ↕ Timing → word
        </button>
        <button className="chip" disabled={!hasRegion} onClick={onPlayRegion}>
          ▶ Preview sel
        </button>
        <span className="edit-region muted">
          {hasRegion
            ? `Selection ${fmt(region.start)} → ${fmt(region.end)} (${(region.end - region.start).toFixed(2)}s)`
            : "Drag on the waveform to select a range"}
        </span>
      </div>

      {mode === "add" && (
        <div className="edit-panel">
          <p className="hint">
            Type a word or phrase. Drag on the waveform to mark begin→end. Confirm to insert —
            each word in a phrase is added as its own timed token (times split by length).
          </p>
          <div className="edit-form">
            <input
              className="phrase-input"
              placeholder="word or phrase…"
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && phrase.trim() && hasRegion) {
                  onAddPhrase(phrase, region.start, region.end, speaker);
                  setPhrase("");
                }
              }}
              autoFocus
            />
            <select value={speaker} onChange={(e) => setSpeaker(e.target.value)}>
              {(speakers || [{ id: "A", label: "A" }]).map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
            <button
              className="btn primary"
              disabled={!phrase.trim() || !hasRegion || busy}
              onClick={() => {
                onAddPhrase(phrase, region.start, region.end, speaker);
                setPhrase("");
              }}
            >
              Insert {phrase.trim().split(/\s+/).filter(Boolean).length || 0} word(s)
            </button>
            <button className="btn" onClick={() => setMode(null)}>Cancel</button>
          </div>
        </div>
      )}

      {mode === "rerun" && localSettings && (
        <div className="edit-panel">
          <p className="hint">
            Only the selected range is re-transcribed. Everything outside it is kept.
            Adjust parameters for this run only (does not change global Settings).
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
                placeholder="auto"
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
              VAD filter
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={!!localSettings.verbatim}
                onChange={(e) => setLS("verbatim", e.target.checked)}
              />
              Verbatim
            </label>
            <label>
              Speaker
              <select value={speaker} onChange={(e) => setSpeaker(e.target.value)}>
                <option value="">auto (from replaced words)</option>
                {(speakers || []).map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="edit-form">
            <button
              className="btn primary"
              disabled={!hasRegion || busy}
              onClick={() => onRerunRange(region.start, region.end, localSettings, speaker || null)}
            >
              {busy ? "Re-transcribing…" : `Rerun ${fmt(region.start)}–${fmt(region.end)}`}
            </button>
            {busy ? (
              <button
                className="btn danger"
                type="button"
                onClick={() => onAbortRerun && onAbortRerun()}
                title="Stop this range transcription"
              >
                ■ Abort
              </button>
            ) : (
              <button className="btn" onClick={() => { setMode(null); setLocalSettings(null); }}>
                Cancel
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
