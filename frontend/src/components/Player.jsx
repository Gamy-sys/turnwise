import React, { useEffect, useRef, useState, forwardRef, useImperativeHandle, useCallback } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";

function fmtMs(s) {
  if (s == null || Number.isNaN(s)) return "—";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, "0")}`;
}

function parseTime(str) {
  const t = String(str || "").trim();
  if (!t) return null;
  if (t.includes(":")) {
    const [a, b] = t.split(":");
    const m = parseFloat(a);
    const s = parseFloat(b);
    if (Number.isNaN(m) || Number.isNaN(s)) return null;
    return m * 60 + s;
  }
  const n = parseFloat(t);
  return Number.isNaN(n) ? null : n;
}

// Waveform + zoom + ms-precise selection region.
const Player = forwardRef(function Player({ url, onTime, onReady, onRegionChange }, ref) {
  const containerRef = useRef(null);
  const wsRef = useRef(null);
  const regionsRef = useRef(null);
  const activeRef = useRef(null);
  const onRegionChangeRef = useRef(onRegionChange);
  onRegionChangeRef.current = onRegionChange;

  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [duration, setDuration] = useState(0);
  const [current, setCurrent] = useState(0);
  const [region, setRegion] = useState(null);
  const [zoom, setZoom] = useState(50); // px per second
  const [startStr, setStartStr] = useState("");
  const [endStr, setEndStr] = useState("");

  const emitRegion = useCallback((r) => {
    const payload = r
      ? { start: Math.round(r.start * 1000) / 1000, end: Math.round(r.end * 1000) / 1000 }
      : null;
    setRegion(payload);
    if (payload) {
      setStartStr(payload.start.toFixed(3));
      setEndStr(payload.end.toFixed(3));
    } else {
      setStartStr("");
      setEndStr("");
    }
    onRegionChangeRef.current && onRegionChangeRef.current(payload);
  }, []);

  const ensureRegion = useCallback((start, end, { drag = true, resize = true, color } = {}) => {
    const regions = regionsRef.current;
    if (!regions) return null;
    const d = wsRef.current?.getDuration() || 1;
    let s = Math.max(0, Math.min(start, d));
    let e = Math.max(s + 0.001, Math.min(end, d));
    if (activeRef.current) {
      try { activeRef.current.remove(); } catch (_) {}
      activeRef.current = null;
    }
    const reg = regions.addRegion({
      id: "selection",
      start: s,
      end: e,
      drag,
      resize,
      color: color || "rgba(88, 166, 255, 0.28)",
    });
    activeRef.current = reg;
    emitRegion(reg);
    return reg;
  }, [emitRegion]);

  useEffect(() => {
    if (!containerRef.current) return;
    const regions = RegionsPlugin.create();
    regionsRef.current = regions;
    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: "#3b4048",
      progressColor: "#58a6ff",
      cursorColor: "#f0c674",
      height: 110,
      barWidth: 2,
      barGap: 1,
      minPxPerSec: 20,
      url,
      plugins: [regions],
    });
    wsRef.current = ws;

    regions.enableDragSelection({ color: "rgba(88, 166, 255, 0.28)" });

    regions.on("region-created", (reg) => {
      for (const r of regions.getRegions()) {
        if (r !== reg) {
          try { r.remove(); } catch (_) {}
        }
      }
      try { reg.setOptions({ id: "selection" }); } catch (_) { reg.id = "selection"; }
      activeRef.current = reg;
      emitRegion(reg);
    });
    regions.on("region-updated", (reg) => {
      if (reg === activeRef.current || reg.id === "selection") {
        activeRef.current = reg;
        emitRegion(reg);
      }
    });
    regions.on("region-removed", (reg) => {
      if (reg === activeRef.current) {
        activeRef.current = null;
        emitRegion(null);
      }
    });

    ws.on("ready", () => {
      setDuration(ws.getDuration());
      try { ws.zoom(zoom); } catch (_) {}
      onReady && onReady(ws.getDuration());
    });
    ws.on("timeupdate", (t) => {
      setCurrent(t);
      onTime && onTime(t);
    });
    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("finish", () => setPlaying(false));
    return () => {
      activeRef.current = null;
      ws.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  // Apply zoom when slider changes
  useEffect(() => {
    const ws = wsRef.current;
    if (!ws) return;
    try { ws.zoom(zoom); } catch (_) {}
  }, [zoom]);

  useImperativeHandle(ref, () => ({
    seek(seconds) {
      const ws = wsRef.current;
      if (!ws) return;
      const d = ws.getDuration() || 1;
      ws.setTime(Math.max(0, Math.min(seconds, d)));
    },
    play() { wsRef.current && wsRef.current.play(); },
    pause() { wsRef.current && wsRef.current.pause(); },
    playPause() { wsRef.current && wsRef.current.playPause(); },
    getRegion() { return region; },
    setRegion(start, end, opts) { return ensureRegion(start, end, opts); },
    clearRegion() {
      if (activeRef.current) {
        try { activeRef.current.remove(); } catch (_) {}
        activeRef.current = null;
      }
      emitRegion(null);
    },
    playRegion() {
      const r = activeRef.current;
      const ws = wsRef.current;
      if (!r || !ws) return;
      ws.setTime(r.start);
      ws.play(r.start, r.end);
    },
    setZoom(px) {
      setZoom(px);
    },
  }), [region, ensureRegion, emitRegion]);

  const nudge = (which, deltaMs) => {
    if (!region) return;
    const delta = deltaMs / 1000;
    let s = region.start;
    let e = region.end;
    if (which === "start") s = Math.max(0, Math.min(e - 0.001, s + delta));
    else if (which === "end") e = Math.min(duration || 1e9, Math.max(s + 0.001, e + delta));
    else if (which === "both") {
      s = Math.max(0, s + delta);
      e = Math.min(duration || 1e9, e + delta);
      if (e <= s) e = s + 0.001;
    }
    ensureRegion(s, e);
  };

  const applyTyped = () => {
    const s = parseTime(startStr);
    const e = parseTime(endStr);
    if (s == null || e == null || e <= s) return;
    ensureRegion(s, e);
  };

  const changeRate = (r) => {
    setRate(r);
    wsRef.current && wsRef.current.setPlaybackRate(r, false);
  };

  const zoomToSelection = () => {
    if (!region || !duration) return;
    const span = Math.max(0.05, region.end - region.start);
    // Fit selection to ~70% of visible width (~800px assumed)
    const px = Math.min(2000, Math.max(40, Math.round(560 / span)));
    setZoom(px);
  };

  return (
    <div className="player">
      <div
        ref={containerRef}
        className="waveform"
        title="Drag to select · scroll zoom with the slider below"
      />

      <div className="zoom-row">
        <span className="muted">Zoom</span>
        <button type="button" className="chip" onClick={() => setZoom((z) => Math.max(20, z - 25))}>−</button>
        <input
          type="range"
          min={20}
          max={800}
          step={5}
          value={zoom}
          onChange={(e) => setZoom(parseInt(e.target.value, 10))}
          title={`${zoom} px/s`}
        />
        <button type="button" className="chip" onClick={() => setZoom((z) => Math.min(800, z + 25))}>+</button>
        <button type="button" className="chip" onClick={() => setZoom(50)}>Fit</button>
        <button type="button" className="chip" disabled={!region} onClick={zoomToSelection}>
          Zoom to sel
        </button>
        <span className="muted">{zoom} px/s</span>
      </div>

      <div className="transport">
        <button className="btn primary" onClick={() => wsRef.current && wsRef.current.playPause()}>
          {playing ? "⏸ Pause" : "▶ Play"}
        </button>
        <span className="time">{fmtMs(current)} / {fmtMs(duration)}</span>
        <div className="rate">
          <span>speed</span>
          {[0.5, 0.75, 1, 1.5].map((r) => (
            <button key={r} className={"chip" + (rate === r ? " on" : "")} onClick={() => changeRate(r)}>
              {r}×
            </button>
          ))}
        </div>
      </div>

      <div className="sel-precise">
        <span className="edit-label">Selection (ms)</span>
        <label>
          Start
          <input
            value={startStr}
            placeholder="0.000"
            onChange={(e) => setStartStr(e.target.value)}
            onBlur={applyTyped}
            onKeyDown={(e) => e.key === "Enter" && applyTyped()}
          />
          <span className="nudge-btns">
            <button type="button" disabled={!region} onClick={() => nudge("start", -100)} title="−100 ms">−−</button>
            <button type="button" disabled={!region} onClick={() => nudge("start", -10)} title="−10 ms">−</button>
            <button type="button" disabled={!region} onClick={() => nudge("start", -1)} title="−1 ms">·</button>
            <button type="button" disabled={!region} onClick={() => nudge("start", 1)} title="+1 ms">·</button>
            <button type="button" disabled={!region} onClick={() => nudge("start", 10)} title="+10 ms">+</button>
            <button type="button" disabled={!region} onClick={() => nudge("start", 100)} title="+100 ms">++</button>
          </span>
        </label>
        <label>
          End
          <input
            value={endStr}
            placeholder="0.000"
            onChange={(e) => setEndStr(e.target.value)}
            onBlur={applyTyped}
            onKeyDown={(e) => e.key === "Enter" && applyTyped()}
          />
          <span className="nudge-btns">
            <button type="button" disabled={!region} onClick={() => nudge("end", -100)} title="−100 ms">−−</button>
            <button type="button" disabled={!region} onClick={() => nudge("end", -10)} title="−10 ms">−</button>
            <button type="button" disabled={!region} onClick={() => nudge("end", -1)} title="−1 ms">·</button>
            <button type="button" disabled={!region} onClick={() => nudge("end", 1)} title="+1 ms">·</button>
            <button type="button" disabled={!region} onClick={() => nudge("end", 10)} title="+10 ms">+</button>
            <button type="button" disabled={!region} onClick={() => nudge("end", 100)} title="+100 ms">++</button>
          </span>
        </label>
        <span className="sel-dur muted">
          {region
            ? `len ${((region.end - region.start) * 1000).toFixed(0)} ms · ${fmtMs(region.start)} → ${fmtMs(region.end)}`
            : "Drag on the waveform, then fine-tune here"}
        </span>
        <button
          type="button"
          className="chip"
          disabled={!region}
          onClick={() => {
            const r = activeRef.current;
            const ws = wsRef.current;
            if (!r || !ws) return;
            ws.setTime(r.start);
            ws.play(r.start, r.end);
          }}
        >
          ▶ Preview
        </button>
        <button
          type="button"
          className="chip"
          disabled={!region}
          onClick={() => {
            if (activeRef.current) {
              try { activeRef.current.remove(); } catch (_) {}
              activeRef.current = null;
            }
            emitRegion(null);
          }}
        >Clear</button>
      </div>
    </div>
  );
});

export default Player;
