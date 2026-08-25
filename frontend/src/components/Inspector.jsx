import React from "react";
import { ALL_CUE_TYPES, CUE_LABELS } from "../caRender.js";

// Default symbol to use when a user manually adds a cue.
const DEFAULT_SYMBOL = {
  elongation: "::",
  intonation: ".",
  stress: "_",
  loud: "CAPS",
  quiet: "°",
  fast: "><",
  slow: "<>",
  cutoff: "-",
  overlap: "[]",
  in_breath: ".hh",
  out_breath: "hh",
  laughter: "£",
  pause: "(0.5)",
  micropause: "(.)",
  latch: "=",
};

export default function Inspector({
  token, speakers, onChange, onInsertBefore, onInsertAfter, onDelete,
  onSeek, playerRef, region, onApplyRegionTiming, onSetRegionFromWord,
}) {
  if (!token) {
    return (
      <div className="inspector empty">
        <p>Select a word in the transcript to inspect its measurements and hand-correct it.</p>
        <p className="hint">
          Double-click a word to edit inline. Drag on the waveform to select a range,
          then use <b>+ Add from wave</b> or <b>↻ Rerun selected</b>.
        </p>
      </div>
    );
  }

  const cueTypes = new Set((token.cues || []).map((c) => c.type));

  const setText = (text) => onChange({ ...token, text });
  const setNum = (key, v) => {
    const n = parseFloat(v);
    if (!isNaN(n)) onChange({ ...token, [key]: n });
  };
  const nudge = (key, delta) => onChange({ ...token, [key]: Math.max(0, +(token[key] + delta).toFixed(3)) });
  const setSpeaker = (sp) => onChange({ ...token, speaker: sp });
  const previewRange = () => {
    if (playerRef?.current) {
      onSeek(token.start);
      playerRef.current.play();
      setTimeout(() => playerRef.current && playerRef.current.pause(), Math.max(150, (token.end - token.start) * 1000));
    }
  };

  const toggleCue = (type) => {
    let cues = [...(token.cues || [])];
    if (cueTypes.has(type)) {
      cues = cues.filter((c) => c.type !== type);
    } else {
      cues.push({ type, symbol: DEFAULT_SYMBOL[type] || "", source: "user", confidence: 1.0, evidence: {} });
    }
    onChange({ ...token, cues });
  };

  const editSymbol = (type, symbol) => {
    const cues = (token.cues || []).map((c) =>
      c.type === type ? { ...c, symbol, source: "user" } : c
    );
    onChange({ ...token, cues });
  };

  const hasRegion = region && region.end > region.start;

  return (
    <div className="inspector">
      <h3>Word</h3>
      <input className="word-edit" value={token.text} onChange={(e) => setText(e.target.value)} />

      <div className="struct-btns">
        <button className="btn tiny" onClick={() => onInsertBefore(token.id)}>+ before</button>
        <button className="btn tiny" onClick={() => onInsertAfter(token.id)}>+ after</button>
        <button className="btn tiny danger" onClick={() => onDelete(token.id)}>🗑 delete</button>
      </div>

      <h3>Timing (drives the highlight)</h3>
      <div className="timing-edit">
        <label>
          <span>start (s)</span>
          <div className="nudge">
            <button onClick={() => nudge("start", -0.05)}>−</button>
            <input type="number" step="0.01" value={token.start}
                   onChange={(e) => setNum("start", e.target.value)} />
            <button onClick={() => nudge("start", 0.05)}>+</button>
          </div>
        </label>
        <label>
          <span>end (s)</span>
          <div className="nudge">
            <button onClick={() => nudge("end", -0.05)}>−</button>
            <input type="number" step="0.01" value={token.end}
                   onChange={(e) => setNum("end", e.target.value)} />
            <button onClick={() => nudge("end", 0.05)}>+</button>
          </div>
        </label>
      </div>
      <div className="timing-row">
        <span className="dur">dur {(token.end - token.start).toFixed(2)}s</span>
        <button className="btn tiny" onClick={previewRange}>▶ preview</button>
        <button className="btn tiny" onClick={() => onSetRegionFromWord && onSetRegionFromWord(token)}
                title="Put this word's span on the waveform">
          → wave
        </button>
        <button className="btn tiny" disabled={!hasRegion}
                onClick={() => onApplyRegionTiming && onApplyRegionTiming(region.start, region.end)}
                title="Set this word's start/end from the waveform selection">
          ← from sel
        </button>
      </div>

      {speakers && speakers.length > 0 && (
        <>
          <h3>Speaker</h3>
          <div className="spk-pick">
            {speakers.map((s) => (
              <button
                key={s.id}
                className={"chip" + (token.speaker === s.id ? " on" : "")}
                onClick={() => setSpeaker(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </>
      )}

      <h3>CA cues</h3>
      <div className="cue-list">
        {ALL_CUE_TYPES.filter((t) => !["pause", "micropause", "latch"].includes(t)).map((type) => {
          const active = cueTypes.has(type);
          const cue = (token.cues || []).find((c) => c.type === type);
          return (
            <div key={type} className={"cue-row" + (active ? " on" : "")}>
              <label>
                <input type="checkbox" checked={active} onChange={() => toggleCue(type)} />
                <span className="cue-name">{CUE_LABELS[type]}</span>
              </label>
              {active && (
                <input
                  className="sym-edit"
                  value={cue?.symbol || ""}
                  onChange={(e) => editSymbol(type, e.target.value)}
                />
              )}
              {active && cue?.source === "auto" && (
                <span className="auto-badge" title={JSON.stringify(cue.evidence)}>
                  auto {cue.value != null ? `· ${cue.value}` : ""}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {token.pre_pause && (
        <div className="prepause">
          <h3>Pause before</h3>
          <input
            value={token.pre_pause.symbol}
            onChange={(e) => onChange({ ...token, pre_pause: { ...token.pre_pause, symbol: e.target.value, source: "user" } })}
          />
          <button className="btn tiny" onClick={() => onChange({ ...token, pre_pause: null })}>
            remove
          </button>
        </div>
      )}
    </div>
  );
}
