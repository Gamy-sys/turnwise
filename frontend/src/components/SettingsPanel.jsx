import React from "react";

// Per-job settings used at upload time. Secrets (tokens/keys) are sent to the
// backend only when non-empty and are never echoed back.
export default function SettingsPanel({ settings, onChange }) {
  const set = (k, v) => onChange({ ...settings, [k]: v });
  const setTh = (k, v) =>
    onChange({ ...settings, thresholds: { ...(settings.thresholds || {}), [k]: v } });

  const th = settings.thresholds || {};

  return (
    <div className="settings">
      <h3>Transcription</h3>
      <label className="field">
        <span>Transcript layout</span>
        <select
          value={settings.transcript_layout || "standard"}
          onChange={(e) => {
            const layout = e.target.value;
            onChange({
              ...settings,
              transcript_layout: layout,
              language: layout === "japanese_four_line" ? "ja" : null,
              whisper_model:
                layout === "japanese_four_line"
                  ? "large-v3"
                  : settings.whisper_model,
              verbatim: true,
              vad_filter: false,
              thresholds: {
                ...(settings.thresholds || {}),
                enable_elongation:
                  layout === "japanese_four_line"
                    ? false
                    : settings.thresholds?.enable_elongation,
              },
            });
          }}
        >
          <option value="standard">Standard Jefferson transcript</option>
          <option value="japanese_four_line">
            Japanese · romanization · direct · natural
          </option>
        </select>
      </label>
      {settings.transcript_layout === "japanese_four_line" && (
        <>
          <p className="hint">
            Japanese is forced as the ASR language. <b>large-v3</b> is recommended.
            Set <b>Number of speakers</b> to the real count (e.g. 4). Overlapping
            talk is transcribed per speaker. Romanization works offline. Direct
            and natural English rows require OpenAI below and remain editable.
            Automatic elongation is disabled because Japanese morpheme timestamps
            otherwise create false colons; add verified CA colons in the editor.
          </p>
          <label className="field checkbox">
            <input
              type="checkbox"
              checked={settings.japanese_auto_translate !== false}
              onChange={(e) => set("japanese_auto_translate", e.target.checked)}
            />
            <span>Generate direct + natural English automatically</span>
          </label>
        </>
      )}
      <label className="field">
        <span>Whisper model</span>
        <select value={settings.whisper_model} onChange={(e) => set("whisper_model", e.target.value)}>
          {["tiny", "base", "small", "medium", "large-v3"].map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
          <option value="nyrahealth/faster_CrisperWhisper">CrisperWhisper (verbatim — keeps um/uh/stutters)</option>
        </select>
      </label>
      <p className="hint">For Japanese use <b>large-v3</b>. tiny/base/small = fast, less accurate. <b>medium</b> = good English balance. large-v3 = multilingual but slow. <b>CrisperWhisper</b> is English-focused.</p>
      <label className="field">
        <span>Language</span>
        <select
          value={
            settings.transcript_layout === "japanese_four_line"
              ? "ja"
              : (settings.language || "")
          }
          disabled={settings.transcript_layout === "japanese_four_line"}
          onChange={(e) => set("language", e.target.value || null)}
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
        <span>Compute type</span>
        <select value={settings.compute_type} onChange={(e) => set("compute_type", e.target.value)}>
          {["int8", "int8_float16", "float16", "float32"].map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </label>
      <label className="field checkbox">
        <input type="checkbox" checked={settings.verbatim} onChange={(e) => set("verbatim", e.target.checked)} />
        <span>Verbatim (keep uh/um, repeats, false starts)</span>
      </label>
      <label className="field checkbox">
        <input type="checkbox" checked={settings.vad_filter ?? false} onChange={(e) => set("vad_filter", e.target.checked)} />
        <span>Voice-activity filter (leave OFF to keep quiet/short words like backchannels)</span>
      </label>
      <label className="field">
        <span>Vocabulary hint / context (optional — helps names &amp; jargon)</span>
        <textarea
          rows="2"
          placeholder="e.g. names, places, uncommon words likely in this audio"
          value={settings.initial_prompt || ""}
          onChange={(e) => set("initial_prompt", e.target.value)}
        />
      </label>

      <h3>CA cues (auto)</h3>
      <p className="hint">Off by default = cleaner transcript. All cues stay editable per-word.</p>
      {[
        ["enable_elongation", "Elongation ( so:: )"],
        ["enable_laughter", "Laughter ( hhh hhh ) + its overlaps"],
        ["enable_breath", "Breath ( .hhh ) — noisier"],
        ["enable_intonation", "Terminal intonation ( . , ? ↑ )"],
        ["enable_volume", "Volume ( CAPS / °quiet° / stress )"],
        ["enable_tempo", "Tempo ( >fast< / <slow> )"],
      ].map(([k, label]) => (
        <label key={k} className="field checkbox">
          <input
            type="checkbox"
            checked={(settings.thresholds || {})[k] ?? false}
            onChange={(e) => setTh(k, e.target.checked)}
          />
          <span>{label}</span>
        </label>
      ))}

      <h3>Speakers &amp; diarization</h3>
      <p className="hint">
        Diarization is <b>on by default</b> (2 speakers). A saved Hugging Face token
        is used automatically when present.
      </p>
      <label className="field checkbox">
        <input
          type="checkbox"
          checked={settings.enable_diarization !== false}
          onChange={(e) => set("enable_diarization", e.target.checked)}
        />
        <span>Diarization + overlap detection</span>
      </label>
      <label className="field">
        <span>Hugging Face token {settings.hf_token === true ? "(saved on server)" : ""}</span>
        <input
          type="password"
          placeholder="hf_... (paste once — never erased if left blank)"
          onChange={(e) => set("hf_token", e.target.value)}
        />
      </label>
      <label className="field">
        <span>Number of speakers (blank = auto-detect)</span>
        <input
          type="number"
          min="1"
          placeholder="2"
          value={settings.num_speakers ?? ""}
          onChange={(e) =>
            set("num_speakers", e.target.value ? parseInt(e.target.value, 10) : null)
          }
        />
      </label>
      <p className="hint">
        Set this to the real count (e.g. 4 for a four-party Japanese conversation).
        Wrong values merge speakers. Overlapping talk is transcribed per speaker.
      </p>

      <h3>OpenAI (optional)</h3>
      <label className="field checkbox">
        <input type="checkbox" checked={settings.enable_openai} onChange={(e) => set("enable_openai", e.target.checked)} />
        <span>Enable OpenAI refinement</span>
      </label>
      <label className="field">
        <span>
          API key {settings.openai_api_key === true ? "(saved on server)" : ""}
          {settings.transcript_layout === "japanese_four_line"
            ? " — required for direct + natural English"
            : ""}
        </span>
        <input type="password" placeholder="sk-..." onChange={(e) => set("openai_api_key", e.target.value)} />
      </label>
      <label className="field">
        <span>OpenAI model</span>
        <input
          value={settings.openai_model || "gpt-4o-mini"}
          onChange={(e) => set("openai_model", e.target.value)}
        />
      </label>

      <details className="thresholds">
        <summary>Advanced: CA thresholds</summary>
        {[
          ["timed_pause_min", "Timed pause min (s)"],
          ["micropause_min", "Micropause min (s)"],
          ["min_overlap_dur", "Overlap min duration (s)"],
          ["crosstalk_db", "Cross-talk reject (dB, high = off)"],
          ["laughter_min_db", "Laughter energy (dB over floor)"],
          ["elongation_ratio", "Elongation ratio"],
          ["rise_strong_st", "Rise → ? (semitones)"],
          ["fall_st", "Fall → . (semitones)"],
          ["loud_db", "Loud (dB over median)"],
          ["quiet_db", "Quiet (dB under median)"],
          ["fast_ratio", "Fast tempo ratio"],
          ["slow_ratio", "Slow tempo ratio"],
        ].map(([k, label]) => (
          <label key={k} className="field">
            <span>{label}</span>
            <input
              type="number"
              step="0.1"
              value={th[k] ?? ""}
              onChange={(e) => setTh(k, parseFloat(e.target.value))}
            />
          </label>
        ))}
      </details>
    </div>
  );
}
