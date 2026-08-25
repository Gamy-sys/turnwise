import React, { useEffect, useState } from "react";
import * as api from "../api.js";

const FORMAT_HELP = {
  pptx: "PowerPoint — native word-highlight animation (Strategy A)",
  pptm: "PowerPoint macro-enabled — VBA runtime highlighting (Strategy B)",
  odp: "LibreOffice Impress — Basic/UNO runtime highlighting (Strategy C)",
  pdf: "PDF slides (static)",
  srt: "SubRip subtitles",
  vtt: "WebVTT subtitles",
  txt: "Plain transcript",
  json: "Universal project (all timing data)",
};

export default function PresentationModal({ pid, defaultTitle, onClose, onToast }) {
  const [formats, setFormats] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [opts, setOpts] = useState({
    title: defaultTitle || "Transcript",
    subtitle: "",
    theme: "dark",
    font_size: 20,
    chunk_mode: "auto",
    seconds_per_slide: 20,
    karaoke: "auto",
    include_audio: true,
    include_notes: true,
    include_title_slide: true,
    line_numbers: true,
    formats: ["pptx", "pdf", "srt"],
  });

  useEffect(() => {
    api.presentationFormats().then((d) => setFormats(d.formats || [])).catch(() => {});
  }, []);

  const set = (k, v) => setOpts((o) => ({ ...o, [k]: v }));
  const toggleFormat = (id) =>
    setOpts((o) => ({
      ...o,
      formats: o.formats.includes(id)
        ? o.formats.filter((f) => f !== id)
        : [...o.formats, id],
    }));

  const generate = async () => {
    if (opts.formats.length === 0) {
      onToast && onToast("Pick at least one output format");
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const res = await api.generatePresentation(pid, opts);
      setResult(res);
      onToast && onToast(`Generated ${res.files.length} file(s) · ${res.slides} slides`);
    } catch (e) {
      onToast && onToast("Generation failed: " + e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Generate presentation</h2>
          <button className="x" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          <div className="opt-grid">
            <label>Title
              <input value={opts.title} onChange={(e) => set("title", e.target.value)} />
            </label>
            <label>Subtitle
              <input value={opts.subtitle} onChange={(e) => set("subtitle", e.target.value)} />
            </label>
            <label>Theme
              <select value={opts.theme} onChange={(e) => set("theme", e.target.value)}>
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </label>
            <label>Font size
              <input type="number" min="8" max="60" value={opts.font_size}
                     onChange={(e) => set("font_size", +e.target.value)} />
            </label>
            <label>Slide chunking
              <select value={opts.chunk_mode} onChange={(e) => set("chunk_mode", e.target.value)}>
                <option value="auto">Auto (fit to slide)</option>
                <option value="time">Fixed time window</option>
              </select>
            </label>
            {opts.chunk_mode === "time" && (
              <label>Seconds / slide
                <input type="number" min="4" max="120" value={opts.seconds_per_slide}
                       onChange={(e) => set("seconds_per_slide", +e.target.value)} />
              </label>
            )}
            <label>Karaoke highlight
              <select value={opts.karaoke} onChange={(e) => set("karaoke", e.target.value)}>
                <option value="auto">Auto (best per format)</option>
                <option value="none">None (static)</option>
              </select>
            </label>
          </div>

          <div className="opt-checks">
            <label><input type="checkbox" checked={opts.include_title_slide}
              onChange={(e) => set("include_title_slide", e.target.checked)} /> Title slide</label>
            <label><input type="checkbox" checked={opts.include_notes}
              onChange={(e) => set("include_notes", e.target.checked)} /> Speaker notes</label>
            <label><input type="checkbox" checked={opts.include_audio}
              onChange={(e) => set("include_audio", e.target.checked)} /> Embed / bundle audio</label>
            <label><input type="checkbox" checked={opts.line_numbers}
              onChange={(e) => set("line_numbers", e.target.checked)} /> Line numbers</label>
          </div>

          <h4>Output formats</h4>
          <div className="fmt-list">
            {formats.map((f) => (
              <label key={f.id} className="fmt-row" title={FORMAT_HELP[f.id] || ""}>
                <input type="checkbox" checked={opts.formats.includes(f.id)}
                       onChange={() => toggleFormat(f.id)} />
                <span className="fmt-name">.{f.extension}</span>
                <span className="fmt-desc">{f.label}{f.karaoke ? " · karaoke" : ""}</span>
              </label>
            ))}
          </div>

          {result && (
            <div className="gen-result">
              <div className="gen-head">
                Done — {result.slides} slides, {result.words} words. Download:
              </div>
              <div className="gen-files">
                <a className="chip primary" href={api.presentationFileUrl(pid, result.bundle)} download>
                  ⬇ All (zip)
                </a>
                {result.files.filter((n) => n !== result.bundle).map((n) => (
                  <a key={n} className="chip" href={api.presentationFileUrl(pid, n)} download>{n}</a>
                ))}
              </div>
              <p className="hint">
                Karaoke .pptm/.odp read <code>timing.txt</code> and the audio from the same
                folder — keep the zip contents together. VBA/Basic macros are included as
                importable source (enable macros to run; signing needs your own certificate).
              </p>
            </div>
          )}
        </div>

        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Close</button>
          <button className="btn primary" onClick={generate} disabled={busy}>
            {busy ? "Generating…" : "Generate"}
          </button>
        </div>
      </div>
    </div>
  );
}
