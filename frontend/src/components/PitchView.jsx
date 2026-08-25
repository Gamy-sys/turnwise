import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { exportUrl } from "../api.js";

/**
 * Praat-style pitch + intensity editor.
 *
 * - Blue F0 contour (left axis, Hz) and green intensity (right axis, dB)
 * - Wheel = zoom around the mouse; Shift+wheel or Shift+drag = pan
 * - Click places a red analysis cursor (reads F0/dB at that instant, seeks audio)
 * - Drag selects a time range (pink, red edges) and syncs the waveform region
 * - Bottom word tier (TextGrid style): click a word to select exactly that word
 * - all / in / out / sel view buttons like Praat's editor window
 */

const MARGIN_L = 46;
const MARGIN_R = 50;
const MARGIN_T = 16;
const TIER_H = 26;
const AXIS_B = 4;

function fmt(t) {
  return t >= 60 ? `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, "0")}` : t.toFixed(3);
}

export default function PitchView({
  transcript,
  currentTime,
  pid,
  selectedId,
  onSelectToken,
  onSeek,
  onSelectRange,
  onPlayRange,
}) {
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const dur = transcript?.meta?.duration || 1;

  const [view, setView] = useState({ t0: 0, t1: dur });
  const [sel, setSel] = useState(null); // {a, b} seconds
  const [cursor, setCursor] = useState(null); // seconds
  const dragRef = useRef(null);

  // Reset view when the document changes
  useEffect(() => {
    setView({ t0: 0, t1: dur });
    setSel(null);
    setCursor(null);
  }, [pid, dur]);

  const tokens = useMemo(() => {
    if (!transcript) return [];
    const out = [];
    for (const turn of transcript.turns || []) {
      if (!turn.speaker) continue;
      for (const tok of turn.tokens || []) out.push(tok);
    }
    return out.sort((x, y) => x.start - y.start);
  }, [transcript]);

  const pitch = transcript?.pitch || [];
  const intensity = transcript?.intensity || [];

  // Stable Hz range across zooming (Praat keeps the pitch range fixed)
  const [fMin, fMax] = useMemo(() => {
    const voiced = pitch.filter((p) => p.f0 > 0).map((p) => p.f0);
    if (!voiced.length) return [75, 500];
    const lo = Math.max(40, Math.floor(Math.min(...voiced) / 25) * 25 - 25);
    const hi = Math.min(800, Math.ceil(Math.max(...voiced) / 25) * 25 + 25);
    return [lo, Math.max(hi, lo + 50)];
  }, [pitch]);

  const [iMin, iMax] = useMemo(() => {
    const vals = intensity.map((p) => p.f0).filter((v) => isFinite(v));
    if (!vals.length) return [0, 100];
    return [Math.floor(Math.min(...vals) / 5) * 5, Math.ceil(Math.max(...vals) / 5) * 5 || 5];
  }, [intensity]);

  const nearest = (series, t, tol = 0.05) => {
    let best = null;
    let bestD = tol;
    for (const p of series) {
      const d = Math.abs(p.t - t);
      if (d < bestD) { best = p; bestD = d; }
    }
    return best;
  };

  const cursorF0 = cursor != null ? nearest(pitch.filter((p) => p.f0 > 0), cursor) : null;
  const cursorDb = cursor != null ? nearest(intensity, cursor) : null;

  const selStats = useMemo(() => {
    if (!sel) return null;
    const [a, b] = [Math.min(sel.a, sel.b), Math.max(sel.a, sel.b)];
    const f0s = pitch.filter((p) => p.f0 > 0 && p.t >= a && p.t <= b).map((p) => p.f0);
    const dbs = intensity.filter((p) => p.t >= a && p.t <= b).map((p) => p.f0);
    const mean = (xs) => xs.reduce((s, v) => s + v, 0) / xs.length;
    return {
      a, b, dur: b - a,
      f0min: f0s.length ? Math.min(...f0s) : null,
      f0max: f0s.length ? Math.max(...f0s) : null,
      f0mean: f0s.length ? mean(f0s) : null,
      dbmean: dbs.length ? mean(dbs) : null,
    };
  }, [sel, pitch, intensity]);

  // ---- view helpers -------------------------------------------------------
  const clampView = (t0, t1) => {
    let span = Math.min(dur, Math.max(0.05, t1 - t0));
    let a = Math.max(0, Math.min(t0, dur - span));
    return { t0: a, t1: a + span };
  };
  const zoomAll = () => setView({ t0: 0, t1: dur });
  const zoomBy = (factor, anchor) => {
    setView((v) => {
      const span = (v.t1 - v.t0) * factor;
      const mid = anchor != null ? anchor : (v.t0 + v.t1) / 2;
      const frac = anchor != null ? (anchor - v.t0) / (v.t1 - v.t0) : 0.5;
      return clampView(mid - span * frac, mid + span * (1 - frac));
    });
  };
  const zoomSel = () => {
    if (!sel) return;
    const [a, b] = [Math.min(sel.a, sel.b), Math.max(sel.a, sel.b)];
    const pad = Math.max(0.02, (b - a) * 0.08);
    setView(clampView(a - pad, b + pad));
  };
  const pan = (frac) => {
    setView((v) => {
      const shift = (v.t1 - v.t0) * frac;
      return clampView(v.t0 + shift, v.t1 + shift);
    });
  };

  // ---- geometry -----------------------------------------------------------
  const geo = () => {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const plotW = rect.width - MARGIN_L - MARGIN_R;
    const plotH = rect.height - MARGIN_T - TIER_H - AXIS_B;
    return { rect, plotW, plotH };
  };
  const pxToT = (clientX) => {
    const { rect, plotW } = geo();
    const frac = (clientX - rect.left - MARGIN_L) / plotW;
    return Math.max(0, Math.min(dur, view.t0 + frac * (view.t1 - view.t0)));
  };

  const applySelection = useCallback((a, b) => {
    const s = { a: Math.min(a, b), b: Math.max(a, b) };
    setSel(s);
    onSelectRange && onSelectRange(s.a, s.b);
  }, [onSelectRange]);

  const selectWordAt = useCallback((t) => {
    const tok = tokens.find((k) => t >= k.start && t <= k.end)
      || tokens.find((k) => t >= k.start - 0.03 && t <= k.end + 0.03);
    if (!tok) return;
    applySelection(tok.start, tok.end);
    onSelectToken && onSelectToken(tok.id);
  }, [tokens, applySelection, onSelectToken]);

  // ---- mouse --------------------------------------------------------------
  const onMouseDown = (e) => {
    if (!transcript) return;
    const { rect, plotH } = geo();
    const y = e.clientY - rect.top;
    const t = pxToT(e.clientX);
    if (y > MARGIN_T + plotH) { // word tier
      selectWordAt(t);
      return;
    }
    dragRef.current = { t, pan: e.shiftKey, view0: { ...view }, x0: e.clientX, moved: false };
  };

  const onMouseMove = (e) => {
    const drag = dragRef.current;
    if (!drag) return;
    const { plotW } = geo();
    if (Math.abs(e.clientX - drag.x0) > 3) drag.moved = true;
    if (drag.pan) {
      const dt = ((drag.x0 - e.clientX) / plotW) * (drag.view0.t1 - drag.view0.t0);
      setView(clampView(drag.view0.t0 + dt, drag.view0.t1 + dt));
    } else if (drag.moved) {
      setSel({ a: drag.t, b: pxToT(e.clientX) });
    }
  };

  const onMouseUp = (e) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.pan) return;
    const t = pxToT(e.clientX);
    if (!drag.moved) {
      setCursor(t);
      setSel(null);
      onSeek && onSeek(t);
    } else {
      applySelection(drag.t, t);
    }
  };

  const onDoubleClick = (e) => selectWordAt(pxToT(e.clientX));

  const onWheel = useCallback((e) => {
    e.preventDefault();
    if (e.shiftKey) {
      pan(e.deltaY > 0 ? 0.15 : -0.15);
    } else {
      zoomBy(e.deltaY > 0 ? 1.3 : 1 / 1.3, pxToT(e.clientX));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, dur]);

  // non-passive wheel listener so preventDefault works
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [onWheel]);

  // Selecting a word elsewhere (transcript/inspector) highlights it here
  useEffect(() => {
    if (!selectedId) return;
    const tok = tokens.find((k) => k.id === selectedId);
    if (!tok) return;
    setSel({ a: tok.start, b: tok.end });
    setView((v) => {
      if (tok.start >= v.t0 && tok.end <= v.t1) return v;
      const span = Math.max(v.t1 - v.t0, (tok.end - tok.start) * 3);
      return clampView((tok.start + tok.end) / 2 - span / 2, (tok.start + tok.end) / 2 + span / 2);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // ---- drawing ------------------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !transcript) return;
    const dpr = devicePixelRatio || 1;
    const cssW = canvas.clientWidth;
    const cssH = 230;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, cssW, cssH);

    const plotW = cssW - MARGIN_L - MARGIN_R;
    const plotH = cssH - MARGIN_T - TIER_H - AXIS_B;
    const tierY = MARGIN_T + plotH;
    const { t0, t1 } = view;
    const span = t1 - t0 || 1;

    const x = (t) => MARGIN_L + ((t - t0) / span) * plotW;
    const yF = (f) => MARGIN_T + plotH - ((f - fMin) / (fMax - fMin || 1)) * plotH;
    const yI = (v) => MARGIN_T + plotH - ((v - iMin) / (iMax - iMin || 1)) * plotH;

    // plot background
    ctx.fillStyle = "#0b0f14";
    ctx.fillRect(MARGIN_L, MARGIN_T, plotW, plotH);

    // selection shading (Praat pink)
    if (sel) {
      const a = Math.max(t0, Math.min(sel.a, sel.b));
      const b = Math.min(t1, Math.max(sel.a, sel.b));
      if (b > a) {
        ctx.fillStyle = "rgba(244, 114, 142, 0.16)";
        ctx.fillRect(x(a), MARGIN_T, x(b) - x(a), plotH + TIER_H);
        ctx.strokeStyle = "#f4728e";
        ctx.lineWidth = 1;
        for (const t of [Math.min(sel.a, sel.b), Math.max(sel.a, sel.b)]) {
          if (t >= t0 && t <= t1) {
            ctx.beginPath();
            ctx.moveTo(x(t), MARGIN_T);
            ctx.lineTo(x(t), tierY + TIER_H);
            ctx.stroke();
          }
        }
      }
    }

    // time ticks (top)
    const target = span / Math.max(3, Math.floor(plotW / 90));
    const steps = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30, 60];
    const step = steps.find((s) => s >= target) || 60;
    ctx.font = "10px monospace";
    ctx.fillStyle = "#8b949e";
    ctx.strokeStyle = "rgba(139,148,158,0.18)";
    ctx.lineWidth = 1;
    ctx.textAlign = "center";
    for (let t = Math.ceil(t0 / step) * step; t <= t1 + 1e-9; t += step) {
      const px = x(t);
      ctx.beginPath();
      ctx.moveTo(px, MARGIN_T);
      ctx.lineTo(px, MARGIN_T + plotH);
      ctx.stroke();
      ctx.fillText(t.toFixed(step < 0.1 ? 2 : step < 1 ? 1 : 0), px, MARGIN_T - 4);
    }

    // Hz gridlines + labels (left)
    ctx.textAlign = "right";
    const fStep = (fMax - fMin) > 300 ? 100 : 50;
    for (let f = Math.ceil(fMin / fStep) * fStep; f <= fMax; f += fStep) {
      const py = yF(f);
      ctx.strokeStyle = "rgba(88,166,255,0.10)";
      ctx.beginPath();
      ctx.moveTo(MARGIN_L, py);
      ctx.lineTo(MARGIN_L + plotW, py);
      ctx.stroke();
      ctx.fillStyle = "#58a6ff";
      ctx.fillText(String(f), MARGIN_L - 5, py + 3);
    }
    // dB labels (right)
    ctx.textAlign = "left";
    ctx.fillStyle = "#7ee787";
    for (let v = iMin; v <= iMax; v += Math.max(5, Math.round((iMax - iMin) / 4 / 5) * 5)) {
      ctx.fillText(`${v} dB`, MARGIN_L + plotW + 5, yI(v) + 3);
    }
    ctx.fillStyle = "#58a6ff";
    ctx.fillText("Hz", 4, MARGIN_T + 8);

    // intensity (green line, Praat style)
    ctx.strokeStyle = "rgba(126,231,135,0.85)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    let pen = false;
    for (const p of intensity) {
      if (p.t < t0 || p.t > t1) { pen = false; continue; }
      if (!pen) { ctx.moveTo(x(p.t), yI(p.f0)); pen = true; }
      else ctx.lineTo(x(p.t), yI(p.f0));
    }
    ctx.stroke();

    // pitch (blue dots+line, break on unvoiced)
    ctx.strokeStyle = "#58a6ff";
    ctx.fillStyle = "#58a6ff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    pen = false;
    for (const p of pitch) {
      if (p.t < t0 || p.t > t1) { pen = false; continue; }
      if (p.f0 > 0) {
        if (!pen) { ctx.moveTo(x(p.t), yF(p.f0)); pen = true; }
        else ctx.lineTo(x(p.t), yF(p.f0));
      } else pen = false;
    }
    ctx.stroke();
    if (span < 4) { // dots visible when zoomed in, like Praat's speckles
      for (const p of pitch) {
        if (p.f0 > 0 && p.t >= t0 && p.t <= t1) {
          ctx.beginPath();
          ctx.arc(x(p.t), yF(p.f0), 1.6, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // word tier
    ctx.fillStyle = "#11161d";
    ctx.fillRect(MARGIN_L, tierY, plotW, TIER_H);
    ctx.strokeStyle = "#30363d";
    ctx.strokeRect(MARGIN_L, tierY, plotW, TIER_H);
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    for (const tok of tokens) {
      if (tok.end < t0 || tok.start > t1) continue;
      const xa = Math.max(MARGIN_L, x(tok.start));
      const xb = Math.min(MARGIN_L + plotW, x(tok.end));
      if (tok.id === selectedId) {
        ctx.fillStyle = "rgba(240,198,116,0.25)";
        ctx.fillRect(xa, tierY, xb - xa, TIER_H);
      }
      ctx.strokeStyle = "#30363d";
      ctx.beginPath();
      ctx.moveTo(x(tok.start), tierY);
      ctx.lineTo(x(tok.start), tierY + TIER_H);
      ctx.stroke();
      const w = xb - xa;
      if (w > 14) {
        let label = tok.text || "";
        while (label.length > 1 && ctx.measureText(label).width > w - 6) {
          label = label.slice(0, -1);
        }
        ctx.fillStyle = tok.id === selectedId ? "#f0c674" : "#c9d1d9";
        ctx.fillText(label, (xa + xb) / 2, tierY + TIER_H / 2 + 4);
      }
    }

    // analysis cursor (red dashed) + value readouts, Praat style
    if (cursor != null && cursor >= t0 && cursor <= t1) {
      ctx.strokeStyle = "#f85149";
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x(cursor), MARGIN_T);
      ctx.lineTo(x(cursor), tierY + TIER_H);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.textAlign = "left";
      if (cursorF0) {
        ctx.fillStyle = "#58a6ff";
        ctx.fillText(`${cursorF0.f0.toFixed(1)} Hz`, x(cursor) + 4, yF(cursorF0.f0) - 4);
      }
      if (cursorDb) {
        ctx.fillStyle = "#7ee787";
        ctx.fillText(`${cursorDb.f0.toFixed(1)} dB`, x(cursor) + 4, yI(cursorDb.f0) + 12);
      }
    }

    // playhead (yellow)
    if (currentTime >= t0 && currentTime <= t1) {
      ctx.strokeStyle = "#f0c674";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x(currentTime), MARGIN_T);
      ctx.lineTo(x(currentTime), tierY + TIER_H);
      ctx.stroke();
    }
  }, [transcript, currentTime, view, sel, cursor, selectedId, tokens, pitch, intensity,
      fMin, fMax, iMin, iMax, cursorF0, cursorDb]);

  // redraw on container resize
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setView((v) => ({ ...v })));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const selOrdered = sel ? { a: Math.min(sel.a, sel.b), b: Math.max(sel.a, sel.b) } : null;

  return (
    <div className="pitchview praat" ref={wrapRef}>
      <div className="pitch-head">
        <span className="legend"><i style={{ background: "#58a6ff" }} /> pitch (Hz)</span>
        <span className="legend"><i style={{ background: "#7ee787" }} /> intensity (dB)</span>
        <span className="praat-zoom">
          <button type="button" className="chip" onClick={zoomAll} title="Show whole file">all</button>
          <button type="button" className="chip" onClick={() => zoomBy(0.5)} title="Zoom in">in</button>
          <button type="button" className="chip" onClick={() => zoomBy(2)} title="Zoom out">out</button>
          <button type="button" className="chip" disabled={!sel} onClick={zoomSel} title="Zoom to selection">sel</button>
          <button type="button" className="chip" onClick={() => pan(-0.5)} title="Pan left">‹</button>
          <button type="button" className="chip" onClick={() => pan(0.5)} title="Pan right">›</button>
        </span>
        <span className="praat-play">
          <button
            type="button" className="chip" disabled={!sel}
            onClick={() => selOrdered && onPlayRange && onPlayRange(selOrdered.a, selOrdered.b)}
            title="Play selection"
          >▶ sel</button>
          <button
            type="button" className="chip"
            onClick={() => onPlayRange && onPlayRange(view.t0, view.t1)}
            title="Play visible window"
          >▶ window</button>
        </span>
        <a className="btn tiny" href={exportUrl(pid, "midi")} download>⬇ MIDI</a>
      </div>

      <canvas
        ref={canvasRef}
        className="pitch-canvas praat-canvas"
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={() => { dragRef.current = null; }}
        onDoubleClick={onDoubleClick}
        title="Click = cursor · drag = select · double-click = select word · wheel = zoom · Shift+drag/wheel = pan · click a word below to select it"
      />

      <div className="praat-readout">
        <span>
          View {fmt(view.t0)}–{fmt(view.t1)} s ({(view.t1 - view.t0).toFixed(3)} s)
        </span>
        {cursor != null && (
          <span className="cursor-vals">
            Cursor {fmt(cursor)} s
            {cursorF0 ? ` · F0 ${cursorF0.f0.toFixed(1)} Hz` : " · unvoiced"}
            {cursorDb ? ` · ${cursorDb.f0.toFixed(1)} dB` : ""}
          </span>
        )}
        {selStats && (
          <span className="sel-vals">
            Sel {fmt(selStats.a)}–{fmt(selStats.b)} s ({(selStats.dur * 1000).toFixed(0)} ms)
            {selStats.f0mean != null &&
              ` · F0 ${selStats.f0min.toFixed(0)}–${selStats.f0max.toFixed(0)} Hz, mean ${selStats.f0mean.toFixed(1)}`}
            {selStats.dbmean != null && ` · mean ${selStats.dbmean.toFixed(1)} dB`}
          </span>
        )}
      </div>
    </div>
  );
}
