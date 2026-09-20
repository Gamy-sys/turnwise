import React, { useEffect, useMemo, useRef, useState } from "react";
import { renderTokenText, cueColor, CUE_LABELS } from "../caRender.js";

// Karaoke transcript with inline text editing and turn→waveform selection.
// CA line layout: number + 3 spaces + name + 2 spaces + : + 4 spaces + talk
export default function TranscriptView({
  transcript,
  currentTime,
  onSeek,
  selectedId,
  onSelect,
  onUpdateToken,
  onUpdateJapanese,
  onSelectTurnRange,
}) {
  const activeRef = useRef(null);
  const containerRef = useRef(null);
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState("");
  const [editingLayer, setEditingLayer] = useState(null);
  const [layerDraft, setLayerDraft] = useState("");

  const activeId = useMemo(() => {
    if (!transcript) return null;
    for (const turn of transcript.turns) {
      for (const tok of turn.tokens) {
        if (currentTime >= tok.start && currentTime < tok.end) return tok.id;
      }
    }
    return null;
  }, [transcript, currentTime]);

  const numWidth = useMemo(() => {
    const n = transcript?.turns?.length || 1;
    return String(n).length;
  }, [transcript]);

  useEffect(() => {
    if (!activeId || editingId) return;
    // Wait one frame so the active word has laid out before measuring.
    const raf = requestAnimationFrame(() => {
      const el = activeRef.current;
      const c = containerRef.current;
      if (!el || !c) return;
      const er = el.getBoundingClientRect();
      const cr = c.getBoundingClientRect();
      if (cr.height < 40) return;
      // Pin the speaking word near ~30% from the top so turn-taking and
      // wrap lines stay in view. Instant scrollTop (no smooth) avoids
      // queued animations when speakers change quickly.
      const target = cr.top + cr.height * 0.3;
      const delta = er.top - target;
      // Tiny dead zone only — follow the talk closely without jitter.
      if (Math.abs(delta) < 12) return;
      c.scrollTop += delta;
    });
    return () => cancelAnimationFrame(raf);
  }, [activeId, editingId]);

  if (!transcript) return null;

  const commitEdit = (tok) => {
    const text = draft.trim();
    setEditingId(null);
    if (!text || text === tok.text) return;
    onUpdateToken && onUpdateToken({ ...tok, text });
  };

  const startEdit = (tok) => {
    setEditingId(tok.id);
    setDraft(tok.text);
    onSelect(tok.id);
  };

  const startLayerEdit = (turn, field) => {
    setEditingLayer({ turnId: turn.id, field });
    setLayerDraft(turn.japanese?.[field] || "");
  };

  const commitLayerEdit = (turn) => {
    if (!editingLayer || editingLayer.turnId !== turn.id) return;
    const field = editingLayer.field;
    setEditingLayer(null);
    onUpdateJapanese && onUpdateJapanese(turn.id, {
      ...(turn.japanese || {}),
      [field]: layerDraft,
    });
  };

  const layerRow = (turn, no, spfx, field, className, placeholder) => {
    const isEditing =
      editingLayer?.turnId === turn.id && editingLayer?.field === field;
    const value = turn.japanese?.[field] || "";
    return (
      <div
        key={`${turn.id}-${field}`}
        className={`turn japanese-layer ${className}`}
      >
        <span className="lineno">{" ".repeat(no.length)}</span>
        <span className="ca-gap3">{"   "}</span>
        <span className="spk-gutter muted">{" ".repeat(spfx.length)}</span>
        <span
          className="turn-body japanese-layer-body"
          style={
            field === "natural_translation"
              ? {
                  color:
                    !turn.japanese?.natural_color ||
                    turn.japanese.natural_color.toLowerCase() === "#000000"
                      ? "var(--text)"
                      : turn.japanese.natural_color,
                }
              : undefined
          }
          onDoubleClick={() => startLayerEdit(turn, field)}
          title="Double-click to edit this row"
        >
          {isEditing ? (
            <textarea
              className="japanese-layer-edit"
              value={layerDraft}
              autoFocus
              rows={2}
              onChange={(e) => setLayerDraft(e.target.value)}
              onBlur={() => commitLayerEdit(turn)}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                  e.preventDefault();
                  commitLayerEdit(turn);
                } else if (e.key === "Escape") {
                  setEditingLayer(null);
                }
              }}
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <span className={value ? "" : "layer-placeholder"}>
              {value || placeholder}
            </span>
          )}
        </span>
        {field === "natural_translation" && (
          <input
            className="natural-color"
            type="color"
            value={turn.japanese?.natural_color || "#000000"}
            title="Natural-translation color"
            onChange={(e) =>
              onUpdateJapanese &&
              onUpdateJapanese(turn.id, {
                ...(turn.japanese || {}),
                natural_color: e.target.value,
              })
            }
          />
        )}
      </div>
    );
  };

  return (
    <div className="transcript" ref={containerRef}>
      {transcript.turns.map((turn, i) => {
        const no = String(i + 1).padStart(numWidth, " ");
        const spfx = `${turn.speaker || ""}  :    `;
        const selectRange = () => {
          if (onSelectTurnRange && turn.start != null && turn.end != null) {
            onSelectTurnRange(turn.start, turn.end);
          }
        };

        if (!turn.speaker) {
          const sym = turn.tokens?.[0]?.cues?.[0]?.symbol || "(.)";
          return (
            <div
              key={turn.id}
              className="turn pause-line"
              onClick={selectRange}
              title="Click to select this gap on the waveform"
            >
              <span className="lineno">{no}</span>
              <span className="ca-gap3">{"   "}</span>
              <span className="spk-gutter muted">{spfx}</span>
              <span className="turn-body pause-body">
                <span className="pausebadge" title="silence">{sym}</span>
              </span>
            </div>
          );
        }
        const sourceRow = (
          <div key={`${turn.id}-source`} className="turn japanese-source">
            <span
              className="lineno clickable"
              onClick={selectRange}
              title="Select this turn on the waveform"
            >{no}</span>
            <span className="ca-gap3">{"   "}</span>
            <span
              className="spk-gutter clickable"
              onClick={selectRange}
              title="Select this turn on the waveform"
            >{spfx}</span>
            <span className="turn-body">
              {turn.latched_to_prev && <span className="latch">=</span>}
              {turn.tokens.map((tok) => {
                const { text, terminal, stress } = renderTokenText(tok);
                const isActive = tok.id === activeId;
                const isSel = tok.id === selectedId;
                const cueTypes = (tok.cues || []).map((c) => c.type);
                if (editingId === tok.id) {
                  return (
                    <input
                      key={tok.id}
                      className="inline-edit"
                      value={draft}
                      autoFocus
                      size={Math.max(2, draft.length + 1)}
                      onChange={(e) => setDraft(e.target.value)}
                      onBlur={() => commitEdit(tok)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          commitEdit(tok);
                        } else if (e.key === "Escape") {
                          setEditingId(null);
                        }
                        e.stopPropagation();
                      }}
                      onClick={(e) => e.stopPropagation()}
                    />
                  );
                }
                return (
                  <React.Fragment key={tok.id}>
                    {tok.pre_pause && (
                      <span className="inline-pause" title={`pause ${tok.pre_pause.value}s`}>
                        {tok.pre_pause.symbol}
                      </span>
                    )}
                    <span
                      ref={isActive ? activeRef : null}
                      className={
                        "word" +
                        (isActive ? " active" : "") +
                        (isSel ? " selected" : "") +
                        (stress ? " stress" : "")
                      }
                      onClick={() => {
                        onSeek(tok.start);
                        onSelect(tok.id);
                      }}
                      onDoubleClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        startEdit(tok);
                      }}
                      title={(cueTypes.map((t) => CUE_LABELS[t]).filter(Boolean).join(", ") || "word")
                        + " · double-click to edit"}
                    >
                      {text}
                      {terminal && <span className="terminal">{terminal}</span>}
                      {cueTypes.length > 0 && (
                        <span className="cuebar">
                          {cueTypes.map((t, i) => (
                            <span key={i} className="cuedot" style={{ background: cueColor(t) }} />
                          ))}
                        </span>
                      )}
                    </span>{" "}
                  </React.Fragment>
                );
              })}
            </span>
          </div>
        );

        if (transcript.layout !== "japanese_four_line") return sourceRow;
        return (
          <React.Fragment key={turn.id}>
            {sourceRow}
            {layerRow(
              turn,
              no,
              spfx,
              "transliteration",
              "japanese-transliteration",
              "Romanization — double-click to edit"
            )}
            {layerRow(
              turn,
              no,
              spfx,
              "direct_translation",
              "japanese-direct",
              "Direct translation — generate or double-click to edit"
            )}
            {layerRow(
              turn,
              no,
              spfx,
              "natural_translation",
              "japanese-natural",
              "Natural translation — generate or double-click to edit"
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}
