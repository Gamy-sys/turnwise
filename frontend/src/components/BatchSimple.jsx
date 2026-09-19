import React, { useEffect, useRef, useState } from "react";
import * as api from "../api.js";

/**
 * Simple mode: folder → folder batch transcription for consecutive jobs.
 * Intentionally small surface — Advanced mode keeps the full editor.
 */
export default function BatchSimple({ defaults, onToast, onOpenProject }) {
  const [inputDir, setInputDir] = useState(() => localStorage.getItem("tw-batch-in") || "");
  const [outputDir, setOutputDir] = useState(() => localStorage.getItem("tw-batch-out") || "");
  const [recursive, setRecursive] = useState(false);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState(null);
  const pollRef = useRef(null);

  const [model, setModel] = useState(defaults?.whisper_model || "medium");
  const [language, setLanguage] = useState(defaults?.language || "");
  const [layout, setLayout] = useState(defaults?.transcript_layout || "standard");
  const [diarize, setDiarize] = useState(defaults?.enable_diarization !== false);
  const [numSpeakers, setNumSpeakers] = useState(
    defaults?.num_speakers != null ? String(defaults.num_speakers) : "2"
  );
  const [hfToken, setHfToken] = useState("");
  const [initialPrompt, setInitialPrompt] = useState("");
  const [formats, setFormats] = useState(["txt"]);

  const loadSimplePrefs = (d) => {
    if (!d) return;
    setModel(d.whisper_model || "medium");
    setLanguage(d.language || "");
    setLayout(d.transcript_layout || "standard");
    setDiarize(d.enable_diarization !== false);
    setNumSpeakers(d.num_speakers != null ? String(d.num_speakers) : "2");
    setInitialPrompt(d.initial_prompt || "");
    try {
      const raw = localStorage.getItem("tw-batch-formats");
      if (raw) setFormats(JSON.parse(raw));
    } catch (_) {}
  };

  useEffect(() => {
    loadSimplePrefs(defaults);
  }, [defaults]);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  const persistDirs = (inn, out) => {
    try {
      localStorage.setItem("tw-batch-in", inn || "");
      localStorage.setItem("tw-batch-out", out || "");
    } catch (_) {}
  };

  const doPreview = async () => {
    if (!inputDir.trim()) {
      onToast && onToast("Choose an input folder");
      return;
    }
    setBusy(true);
    try {
      const res = await api.previewBatch(inputDir.trim(), recursive);
      setPreview(res);
      onToast && onToast(
        res.count
          ? `Found ${res.count} audio file${res.count === 1 ? "" : "s"}`
          : "No audio files in that folder"
      );
    } catch (e) {
      setPreview(null);
      onToast && onToast(e.message);
    } finally {
      setBusy(false);
    }
  };

  const toggleFormat = (id) => {
    setFormats((prev) => {
      if (prev.includes(id)) {
        const next = prev.filter((f) => f !== id);
        return next.length ? next : ["txt"];
      }
      return [...prev, id];
    });
  };

  const buildSettings = () => {
    const settings = {
      ...(defaults || {}),
      whisper_model: model,
      language: language || null,
      transcript_layout: layout,
      enable_diarization: diarize,
      num_speakers: numSpeakers ? parseInt(numSpeakers, 10) : null,
      initial_prompt: initialPrompt.trim() || null,
      japanese_auto_translate: layout === "japanese_four_line",
      verbatim: true,
      vad_filter: false,
    };
    if (hfToken.trim()) settings.hf_token = hfToken.trim();
    if (layout === "japanese_four_line") {
      settings.language = "ja";
      settings.whisper_model = model === "tiny" || model === "base" || model === "small" || model === "medium"
        ? "large-v3"
        : model;
    }
    return settings;
  };

  const saveDefaults = async () => {
    setBusy(true);
    try {
      const saved = await api.saveDefaults(buildSettings());
      onToast && onToast("Batch settings saved (used for future jobs)");
      try { localStorage.setItem("tw-batch-formats", JSON.stringify(formats)); } catch (_) {}
      setHfToken("");
      loadSimplePrefs(saved);
    } catch (e) {
      onToast && onToast("Save failed: " + e.message);
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!inputDir.trim() || !outputDir.trim()) {
      onToast && onToast("Set both input and output folders");
      return;
    }
    persistDirs(inputDir.trim(), outputDir.trim());
    setBusy(true);
    try {
      const settings = buildSettings();
      await api.saveDefaults(settings);
      const job = await api.startBatch({
        input_dir: inputDir.trim(),
        output_dir: outputDir.trim(),
        settings,
        formats,
        recursive,
      });
      setBatch(job);
      onToast && onToast(`Batch started · ${job.total} file(s)`);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const st = await api.getBatch(job.batch_id);
          setBatch(st);
          if (st.state === "done" || st.state === "error" || st.state === "cancelled") {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setBusy(false);
            onToast && onToast(st.message || st.state);
          }
        } catch (_) {}
      }, 1200);
    } catch (e) {
      setBusy(false);
      onToast && onToast(e.message);
    }
  };

  const cancel = async () => {
    if (!batch?.batch_id) return;
    try {
      const st = await api.cancelBatch(batch.batch_id);
      setBatch(st);
      onToast && onToast("Cancelling batch…");
    } catch (e) {
      onToast && onToast(e.message);
    }
  };

  const running = batch && (batch.state === "queued" || batch.state === "running");
  const pct = batch && batch.total
    ? Math.round(((batch.done + (running ? 0.35 : 0)) / batch.total) * 100)
    : 0;

  return (
    <div className="simple-mode">
      <header className="simple-hero">
        <h1>Batch transcribe</h1>
        <p>
          Point Turnwise at a folder of audio files, pick where transcripts should go,
          and it will work through them one after another.
        </p>
      </header>

      <section className="simple-card">
        <h2>Folders</h2>
        <label className="field">
          <span>Input folder</span>
          <input
            value={inputDir}
            placeholder="/path/to/audio"
            onChange={(e) => {
              setInputDir(e.target.value);
              persistDirs(e.target.value, outputDir);
            }}
          />
        </label>
        <label className="field">
          <span>Output folder</span>
          <input
            value={outputDir}
            placeholder="/path/to/transcripts"
            onChange={(e) => {
              setOutputDir(e.target.value);
              persistDirs(inputDir, e.target.value);
            }}
          />
        </label>
        <label className="field checkbox">
          <input
            type="checkbox"
            checked={recursive}
            onChange={(e) => setRecursive(e.target.checked)}
          />
          <span>Include subfolders</span>
        </label>
        <div className="simple-actions">
          <button type="button" className="btn" disabled={busy && !running} onClick={doPreview}>
            Scan folder
          </button>
          {preview && (
            <span className="muted">
              {preview.count} file{preview.count === 1 ? "" : "s"} ready
              {preview.truncated ? " (list truncated)" : ""}
            </span>
          )}
        </div>
        {preview?.files?.length > 0 && (
          <ul className="simple-file-list">
            {preview.files.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="simple-card">
        <h2>Basic settings</h2>
        <div className="simple-grid">
          <label className="field">
            <span>Whisper model</span>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {["tiny", "base", "small", "medium", "large-v3"].map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Language</span>
            <select
              value={layout === "japanese_four_line" ? "ja" : (language || "")}
              disabled={layout === "japanese_four_line"}
              onChange={(e) => setLanguage(e.target.value)}
            >
              <option value="">Auto-detect</option>
              <option value="en">English</option>
              <option value="ja">Japanese</option>
              <option value="es">Spanish</option>
              <option value="fr">French</option>
              <option value="de">German</option>
              <option value="zh">Chinese</option>
              <option value="ko">Korean</option>
            </select>
          </label>
          <label className="field">
            <span>Transcript layout</span>
            <select
              value={layout}
              onChange={(e) => {
                const v = e.target.value;
                setLayout(v);
                if (v === "japanese_four_line") {
                  setLanguage("ja");
                  if (!formats.includes("docx")) setFormats((f) => [...f, "docx"]);
                }
              }}
            >
              <option value="standard">Standard Jefferson</option>
              <option value="japanese_four_line">Japanese · 4-line</option>
            </select>
          </label>
        </div>
        <label className="field checkbox">
          <input type="checkbox" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} />
          <span>Speaker diarization (labels who is speaking)</span>
        </label>
        {diarize && (
          <div className="simple-diarize">
            <label className="field">
              <span>
                Hugging Face token
                {defaults?.hf_token === true ? " (saved on server)" : ""}
              </span>
              <input
                type="password"
                value={hfToken}
                placeholder="hf_... paste once — blank keeps saved key"
                onChange={(e) => setHfToken(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Number of speakers (blank = auto)</span>
              <input
                type="number"
                min="1"
                placeholder="auto"
                value={numSpeakers}
                onChange={(e) => setNumSpeakers(e.target.value)}
              />
            </label>
          </div>
        )}
        <label className="field">
          <span>Names / keywords / vocabulary hint</span>
          <textarea
            rows="2"
            placeholder="e.g. proper names, places, jargon likely in these recordings"
            value={initialPrompt}
            onChange={(e) => setInitialPrompt(e.target.value)}
          />
        </label>
        <div className="simple-formats">
          <span className="muted">Export</span>
          {[
            ["txt", "Text (.txt)"],
            ["json", "JSON (.json)"],
            ["docx", "DOCX 4-line"],
          ].map(([id, label]) => (
            <label key={id} className="field checkbox">
              <input
                type="checkbox"
                checked={formats.includes(id)}
                onChange={() => toggleFormat(id)}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="simple-card simple-run">
        <div className="simple-actions">
          <button type="button" className="btn" disabled={busy && !running} onClick={saveDefaults}>
            Save settings
          </button>
          {!running ? (
            <button type="button" className="btn primary" disabled={busy} onClick={start}>
              {busy ? "Starting…" : "Start batch"}
            </button>
          ) : (
            <button type="button" className="btn danger" onClick={cancel}>
              ■ Cancel batch
            </button>
          )}
        </div>

        {batch && (
          <div className="simple-progress">
            <div className="bar"><div className="fill" style={{ width: `${Math.min(100, pct)}%` }} /></div>
            <p className="stage">
              {batch.message}
              {batch.total ? ` · ${batch.done}/${batch.total} done` : ""}
              {batch.failed ? ` · ${batch.failed} failed` : ""}
            </p>
            <ul className="simple-batch-items">
              {batch.items.map((it) => (
                <li key={it.path} className={"batch-item " + it.state}>
                  <span className="bname">{it.filename}</span>
                  <span className="bstate">{it.state}</span>
                  <span className="bmsg muted">{it.message}</span>
                  {it.state === "done" && it.project_id && onOpenProject && (
                    <button
                      type="button"
                      className="chip tiny"
                      onClick={() => onOpenProject(it.project_id)}
                    >
                      Open
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
