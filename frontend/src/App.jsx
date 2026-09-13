import React, { useCallback, useEffect, useRef, useState } from "react";
import Player from "./components/Player.jsx";
import TranscriptView from "./components/TranscriptView.jsx";
import Inspector from "./components/Inspector.jsx";
import PitchView from "./components/PitchView.jsx";
import SettingsPanel from "./components/SettingsPanel.jsx";
import ModelsManager from "./components/ModelsManager.jsx";
import PresentationModal from "./components/PresentationModal.jsx";
import EditBar from "./components/EditBar.jsx";
import ProjectTree from "./components/ProjectTree.jsx";
import ClipRerunBar from "./components/ClipRerunBar.jsx";
import BatchSimple from "./components/BatchSimple.jsx";
import UpdateFromGit from "./components/UpdateFromGit.jsx";
import {
  CollapsiblePanel,
  ResizeHandle,
  usePersistedBool,
  usePersistedNumber,
} from "./components/PanelLayout.jsx";
import * as api from "./api.js";
import { audioUrl, exportUrl } from "./api.js";

function genId() {
  return "u" + Math.random().toString(36).slice(2, 9);
}

const STOP = new Set(
  "a an the and or but to of in on at for is are was were be been being i i'm you he she we they it this that with not no so if as my me your".split(" ")
);

/** Name a clip from transcript keywords in [start,end] plus the time range. */
export function clipLabelFromSelection(transcript, start, end) {
  const time = `${Number(start).toFixed(2)}–${Number(end).toFixed(2)}s`;
  if (!transcript) return time;
  const words = [];
  for (const turn of transcript.turns || []) {
    if (!turn.speaker) continue;
    for (const tok of turn.tokens || []) {
      const mid = (tok.start + tok.end) / 2;
      if (mid < start || mid > end) continue;
      let t = String(tok.text || "").trim();
      t = t.replace(/^[=,[\]°_?#£~]+|[.,!?;:°_"'\]]+$/g, "").trim();
      if (!t || /^\(.*\)$/.test(t)) continue;
      words.push(t);
    }
  }
  if (!words.length) return time;
  // Prefer a contentful keyword (longest non-stopword), else first word
  const scored = words
    .map((w) => ({ w, score: STOP.has(w.toLowerCase()) ? 0 : w.length }))
    .sort((a, b) => b.score - a.score || b.w.length - a.w.length);
  const keyword = (scored[0] && scored[0].score > 0 ? scored[0].w : words[0]);
  return `${keyword} ${time}`;
}

function lastCollectionKey(pid) {
  return `ca-last-collection:${pid}`;
}

function readLastCollection(pid) {
  try {
    return localStorage.getItem(lastCollectionKey(pid)) || null;
  } catch (_) {
    return null;
  }
}

function writeLastCollection(pid, cid) {
  try {
    if (cid) localStorage.setItem(lastCollectionKey(pid), cid);
  } catch (_) {}
}

/** Split a phrase into individually timed tokens across [start, end]. */
function phraseToTokens(text, start, end, speaker) {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const dur = Math.max(0.08, end - start);
  const weights = words.map((w) => Math.max(1, w.replace(/[^a-zA-Z0-9']/g, "").length || w.length));
  const total = weights.reduce((a, b) => a + b, 0);
  let t = start;
  return words.map((w, i) => {
    const slice = dur * (weights[i] / total);
    const s = t;
    const e = i === words.length - 1 ? end : Math.min(end, t + slice);
    t = e;
    return {
      id: genId(),
      text: w,
      start: +s.toFixed(3),
      end: +Math.max(s + 0.04, e).toFixed(3),
      speaker,
      phonemes: [],
      cues: [],
      pre_pause: null,
    };
  });
}

export default function App() {
  const [defaults, setDefaults] = useState(null);
  const [settings, setSettings] = useState(null);
  const [projects, setProjects] = useState([]);
  const [pid, setPid] = useState(null);
  const [transcript, setTranscript] = useState(null);
  const [status, setStatus] = useState(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("new"); // new | project
  const [mode, setMode] = useState(() => {
    try { return localStorage.getItem("tw-mode") || "simple"; } catch (_) { return "simple"; }
  }); // simple | advanced
  const [toast, setToast] = useState("");
  const [showPresent, setShowPresent] = useState(false);
  const [region, setRegion] = useState(null);
  const [rangeBusy, setRangeBusy] = useState(false);
  const [japaneseBusy, setJapaneseBusy] = useState(false);
  const [viewing, setViewing] = useState(null); // {cid, eid, label} | null
  const [parentSnapshot, setParentSnapshot] = useState(null); // transcript backup when viewing element
  const [currentCollection, setCurrentCollection] = useState(null); // {id, label} | null
  const [quickAddBusy, setQuickAddBusy] = useState(false);
  const [collectionsTick, setCollectionsTick] = useState(0);
  const playerRef = useRef(null);
  const unsubRef = useRef(null);
  const rangeAbortRef = useRef(null);

  useEffect(() => {
    api.getDefaults().then((d) => {
      setDefaults(d);
      if (!pid) setSettings(d);
    });
    refreshProjects();
  }, []);

  useEffect(() => {
    if (mode !== "advanced" || tab !== "settings") return;
    if (pid) {
      api.getProjectSettings(pid).then(setSettings).catch(() => {
        if (defaults) setSettings(defaults);
      });
    } else if (defaults) {
      setSettings(defaults);
    }
  }, [tab, pid, mode]);

  const refreshProjects = () => api.listProjects().then(setProjects);
  const setAppMode = (m) => {
    setMode(m);
    try { localStorage.setItem("tw-mode", m); } catch (_) {}
  };

  const flash = (m) => {
    setToast(m);
    setTimeout(() => setToast(""), 2500);
  };

  const clearOpenIf = (ids) => {
    if (pid && ids.includes(pid)) {
      if (unsubRef.current) unsubRef.current();
      setPid(null);
      setTranscript(null);
      setStatus(null);
    }
  };

  const removeProject = async (e, id) => {
    e.stopPropagation();
    if (!confirm("Delete this project and all its files (audio, transcript, exports)? This cannot be undone.")) return;
    try {
      await api.deleteProject(id);
      clearOpenIf([id]);
      refreshProjects();
      flash("Project deleted");
    } catch (err) {
      flash("Delete failed: " + err.message);
    }
  };

  const removeAllProjects = async () => {
    if (projects.length === 0) return;
    if (!confirm(`Delete ALL ${projects.length} projects and their audio files? This cannot be undone.`)) return;
    try {
      const ids = projects.map((p) => p.project_id);
      await Promise.all(ids.map((id) => api.deleteProject(id)));
      clearOpenIf(ids);
      refreshProjects();
      flash("All projects deleted");
    } catch (err) {
      flash("Delete failed: " + err.message);
    }
  };

  const doUpload = async (file) => {
    if (!file) return;
    try {
      // New projects start from server defaults; tune them afterwards via the
      // project's own ⚙ settings (saved API keys are reused automatically).
      const { project_id } = await api.uploadAudio(file, settings || defaults || {});
      setPid(project_id);
      setTranscript(null);
      setTab("project");
      setStatus({ state: "queued", progress: 0, stage: "queued" });
      watchProgress(project_id);
      refreshProjects();
    } catch (e) {
      flash("Upload failed: " + e.message);
    }
  };

  const watchProgress = (project_id) => {
    if (unsubRef.current) unsubRef.current();
    unsubRef.current = api.subscribeProgress(project_id, async (st) => {
      setStatus(st);
      if (st.state === "done") {
        const tr = await api.getTranscript(project_id);
        setTranscript(tr);
        setDirty(false);
        refreshProjects();
      } else if (st.state === "cancelled") {
        refreshProjects();
        // Keep any previous transcript if one exists on disk
        try {
          const tr = await api.getTranscript(project_id);
          setTranscript(tr);
          setDirty(false);
        } catch (_) {
          setTranscript(null);
        }
        flash("Transcription aborted");
      }
    });
  };

  const abortTranscription = async () => {
    if (!pid) return;
    try {
      await api.abortProject(pid);
      flash("Aborting transcription…");
    } catch (e) {
      flash("Abort failed: " + e.message);
    }
  };

  const rerun = async () => {
    if (!pid) return;
    if (!confirm("Re-run transcription with this project's settings? This replaces the transcript (manual edits will be lost).")) return;
    try {
      setTranscript(null);
      setSelectedId(null);
      setStatus({ state: "queued", progress: 0, stage: "queued" });
      await api.reprocess(pid, settings);
      watchProgress(pid);
      flash("Re-running transcription…");
    } catch (e) {
      flash("Re-run failed: " + e.message);
    }
  };

  const openProject = async (project_id) => {
    setPid(project_id);
    setTab("project");
    setSelectedId(null);
    setTranscript(null);
    setViewing(null);
    setParentSnapshot(null);
    setRegion(null);
    setCurrentCollection(null);
    // Load this project's own settings (falls back to defaults server-side)
    api.getProjectSettings(project_id).then(setSettings).catch(() => {
      if (defaults) setSettings(defaults);
    });
    const st = await api.getStatus(project_id);
    setStatus(st);
    if (st.state === "done") {
      const tr = await api.getTranscript(project_id);
      setTranscript(tr);
      setDirty(false);
    } else if (st.state !== "error") {
      watchProgress(project_id);
    }
    // Restore last-used collection for this project
    try {
      const res = await api.listCollections(project_id);
      const list = res.collections || [];
      const last = readLastCollection(project_id);
      const hit = list.find((c) => c.id === last) || list[0] || null;
      if (hit) {
        setCurrentCollection({ id: hit.id, label: hit.label });
        writeLastCollection(project_id, hit.id);
      }
    } catch (_) {}
  };

  const openProjectSettings = async (project_id) => {
    if (project_id !== pid) await openProject(project_id);
    try {
      setSettings(await api.getProjectSettings(project_id));
    } catch (_) {}
    setTab("settings");
  };

  const saveSettings = async () => {
    try {
      if (pid) {
        const saved = await api.saveProjectSettings(pid, settings);
        setSettings(saved);
        flash("Settings saved for this project");
        return saved;
      }
      const saved = await api.saveDefaults(settings);
      setSettings(saved);
      setDefaults(saved);
      flash("Default settings saved");
      return saved;
    } catch (e) {
      flash("Settings save failed: " + e.message);
      return null;
    }
  };

  const updateTranscript = async () => {
    if (!pid) {
      flash("Open a project first");
      return;
    }
    if (
      !confirm(
        "Update transcript with the current settings? This re-runs transcription and replaces manual edits."
      )
    ) {
      return;
    }
    const saved = await saveSettings();
    if (!saved) return;
    try {
      setTranscript(null);
      setSelectedId(null);
      setStatus({ state: "queued", progress: 0, stage: "queued" });
      await api.reprocess(pid, saved);
      watchProgress(pid);
      flash("Updating transcript…");
    } catch (e) {
      flash("Update failed: " + e.message);
    }
  };

  const setActiveCollection = (coll, forPid) => {
    if (!coll?.id) {
      setCurrentCollection(null);
      return;
    }
    setCurrentCollection({ id: coll.id, label: coll.label || coll.id });
    const key = forPid || pid;
    if (key) writeLastCollection(key, coll.id);
  };

  const ensureCurrentCollection = async () => {
    if (!pid) throw new Error("no project open");
    if (currentCollection?.id) return currentCollection;
    const res = await api.listCollections(pid);
    const list = res.collections || [];
    const last = readLastCollection(pid);
    let hit = list.find((c) => c.id === last) || list[0];
    if (!hit) {
      hit = await api.createCollection(pid, "Clips");
    }
    const cur = { id: hit.id, label: hit.label || "Clips" };
    setCurrentCollection(cur);
    writeLastCollection(pid, cur.id);
    return cur;
  };

  const addSelectionToCollection = async () => {
    if (!pid || viewing) return;
    if (!region || region.end <= region.start) {
      flash("Select a range on the waveform first");
      return;
    }
    setQuickAddBusy(true);
    try {
      const coll = await ensureCurrentCollection();
      const label = clipLabelFromSelection(transcript, region.start, region.end);
      const el = await api.addCollectionElement(pid, coll.id, {
        start: region.start,
        end: region.end,
        label,
      });
      writeLastCollection(pid, coll.id);
      setCollectionsTick((n) => n + 1);
      flash(`Added “${el.label}” → ${coll.label}`);
    } catch (e) {
      flash("Add to collection failed: " + e.message);
    } finally {
      setQuickAddBusy(false);
    }
  };

  const openElement = async ({ cid, eid, label, projectId }) => {
    const usePid = projectId || pid;
    if (!usePid) return;
    const switching = usePid !== pid;
    if (switching) {
      await openProject(usePid);
    }
    try {
      let snap = parentSnapshot;
      if (switching || !viewing) {
        if (!switching && transcript && !viewing) {
          snap = transcript;
        } else {
          try {
            snap = await api.getTranscript(usePid);
          } catch (_) {
            snap = null;
          }
        }
      }
      const res = await api.getCollectionElement(usePid, cid, eid);
      if (snap) setParentSnapshot(snap);
      setViewing({ cid, eid, label: label || res.meta?.label || eid });
      try {
        const meta = await api.getCollection(usePid, cid);
        if (meta) setActiveCollection({ id: meta.id, label: meta.label }, usePid);
        else setActiveCollection({ id: cid, label: cid }, usePid);
      } catch (_) {
        setActiveCollection({ id: cid, label: cid }, usePid);
      }
      if (res.transcript) {
        setTranscript(res.transcript);
        setDirty(false);
        setSelectedId(null);
      }
      setCollectionsTick((n) => n + 1);
      flash(`Opened clip “${label || eid}”`);
    } catch (e) {
      flash("Open clip failed: " + e.message);
    }
  };

  const backToParent = async () => {
    if (!pid) return;
    setViewing(null);
    if (parentSnapshot) {
      setTranscript(parentSnapshot);
      setParentSnapshot(null);
    } else {
      try {
        const tr = await api.getTranscript(pid);
        setTranscript(tr);
      } catch (_) {}
    }
    setDirty(false);
    setSelectedId(null);
    setRegion(null);
  };

  const updateToken = (updated) => {
    setTranscript((prev) => {
      if (!prev) return prev;
      const turns = prev.turns.map((turn) => ({
        ...turn,
        tokens: turn.tokens.map((t) => (t.id === updated.id ? updated : t)),
      }));
      return { ...prev, turns };
    });
    setDirty(true);
  };

  const updateJapanese = (turnId, japanese) => {
    setTranscript((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        turns: prev.turns.map((turn) =>
          turn.id === turnId ? { ...turn, japanese } : turn
        ),
      };
    });
    setDirty(true);
  };

  const genIdLocal = genId;

  const findCtx = (id) => {
    for (let ti = 0; ti < transcript.turns.length; ti++) {
      const toks = transcript.turns[ti].tokens;
      for (let k = 0; k < toks.length; k++) if (toks[k].id === id) return { ti, k };
    }
    return null;
  };

  const insertWord = (refId, where) => {
    const ctx = findCtx(refId);
    if (!ctx) return;
    const turn = transcript.turns[ctx.ti];
    const refTok = turn.tokens[ctx.k];
    const next = turn.tokens[ctx.k + 1];
    const prevTok = turn.tokens[ctx.k - 1];
    let start, end;
    if (where === "after") {
      start = refTok.end;
      end = next ? Math.min(next.start, refTok.end + 0.3) : refTok.end + 0.3;
    } else {
      start = prevTok ? prevTok.end : Math.max(0, refTok.start - 0.3);
      end = refTok.start;
    }
    if (end <= start) end = start + 0.2;
    const tok = {
      id: genIdLocal(), text: "word", start: +start.toFixed(3), end: +end.toFixed(3),
      speaker: turn.speaker, phonemes: [], cues: [], pre_pause: null,
    };
    setTranscript((prev) => {
      const turns = prev.turns.map((t, i) => (i === ctx.ti ? { ...t, tokens: [...t.tokens] } : t));
      const idx = where === "after" ? ctx.k + 1 : ctx.k;
      turns[ctx.ti].tokens.splice(idx, 0, tok);
      return { ...prev, turns };
    });
    setDirty(true);
    setSelectedId(tok.id);
  };

  const addPhraseFromWave = async (text, start, end, speaker) => {
    const newToks = phraseToTokens(text, start, end, speaker);
    if (!newToks.length || !transcript) return;
    const kept = [];
    for (const turn of transcript.turns) {
      if (!turn.speaker) continue;
      for (const tok of turn.tokens) {
        if (tok.end <= start || tok.start >= end) kept.push(tok);
      }
    }
    const all = [...kept, ...newToks].sort((a, b) => a.start - b.start || a.end - b.end);
    const turns = [];
    let cur = null;
    for (const tok of all) {
      if (!cur || cur.speaker !== tok.speaker) {
        cur = {
          id: "t" + genIdLocal(),
          speaker: tok.speaker,
          start: tok.start,
          end: tok.end,
          tokens: [tok],
          latched_to_prev: false,
        };
        turns.push(cur);
      } else {
        cur.tokens.push(tok);
        cur.end = tok.end;
      }
    }
    const next = { ...transcript, turns };
    setTranscript(next);
    setSelectedId(newToks[0].id);
    try {
      if (pid) {
        const res = await api.saveTranscript(pid, next);
        if (res.transcript) setTranscript(res.transcript);
        setDirty(false);
        flash(`Inserted ${newToks.length} word(s) and saved`);
      } else {
        setDirty(true);
      }
    } catch (e) {
      setDirty(true);
      flash("Inserted locally · save failed: " + e.message);
    }
  };

  const applyTimingToSelected = (start, end) => {
    const tok = selectedToken();
    if (!tok) return;
    updateToken({ ...tok, start: +start.toFixed(3), end: +Math.max(start + 0.04, end).toFixed(3) });
    flash("Timing updated from waveform");
  };

  const rerunSelectedRange = async (start, end, rangeSettings, speaker) => {
    if (!pid) return;
    if (rangeAbortRef.current) {
      try { rangeAbortRef.current.abort(); } catch (_) {}
    }
    const ac = new AbortController();
    rangeAbortRef.current = ac;
    setRangeBusy(true);
    try {
      const res = await api.reprocessRange(pid, {
        start, end,
        settings: { ...(settings || {}), ...(rangeSettings || {}) },
        speaker: speaker || null,
        signal: ac.signal,
      });
      if (res.transcript) {
        setTranscript(res.transcript);
        setDirty(false);
        setSelectedId(null);
      }
      flash(`Reran ${start.toFixed(2)}–${end.toFixed(2)}s · removed ${res.removed}, added ${res.added}`);
    } catch (e) {
      if (e.name === "AbortError" || /abort/i.test(e.message || "")) {
        flash("Range transcription aborted");
      } else {
        flash("Rerun selected failed: " + e.message);
      }
    } finally {
      if (rangeAbortRef.current === ac) rangeAbortRef.current = null;
      setRangeBusy(false);
    }
  };

  const abortRangeRerun = async () => {
    if (!pid) return;
    try {
      await api.abortProject(pid);
    } catch (_) {}
    if (rangeAbortRef.current) {
      try { rangeAbortRef.current.abort(); } catch (_) {}
    }
  };

  const selectTurnRange = (start, end) => {
    if (playerRef.current?.setRegion) {
      playerRef.current.setRegion(start, end);
    }
  };

  const deleteToken = (id) => {
    setTranscript((prev) => {
      const turns = prev.turns
        .map((t) => ({ ...t, tokens: t.tokens.filter((x) => x.id !== id) }))
        .filter((t) => !t.speaker || t.tokens.length > 0);
      return { ...prev, turns };
    });
    setDirty(true);
    setSelectedId(null);
  };

  const renameSpeaker = (oldL, newL) => {
    newL = (newL || "").trim();
    if (!newL || newL === oldL) return;
    setTranscript((prev) => ({
      ...prev,
      speakers: prev.speakers.map((s) => (s.id === oldL ? { ...s, id: newL, label: newL } : s)),
      turns: prev.turns.map((t) => ({
        ...t,
        speaker: t.speaker === oldL ? newL : t.speaker,
        tokens: t.tokens.map((tk) => ({ ...tk, speaker: tk.speaker === oldL ? newL : tk.speaker })),
      })),
    }));
    setDirty(true);
  };

  const save = async () => {
    if (viewing) {
      const res = await api.saveElementTranscript(pid, viewing.cid, viewing.eid, transcript);
      if (res.transcript) setTranscript(res.transcript);
      setDirty(false);
      setSelectedId(null);
      flash("Clip saved");
      return;
    }
    const res = await api.saveTranscript(pid, transcript);
    if (res.transcript) setTranscript(res.transcript);
    setDirty(false);
    setSelectedId(null);
    flash("Saved · structure & pauses recomputed");
  };

  const insertClipIntoParent = async () => {
    if (!viewing || !pid) return;
    // Persist clip edits first if dirty
    if (dirty) {
      try {
        const res = await api.saveElementTranscript(pid, viewing.cid, viewing.eid, transcript);
        if (res.transcript) setTranscript(res.transcript);
        setDirty(false);
      } catch (e) {
        flash("Save clip failed: " + e.message);
        return;
      }
    }
    try {
      const res = await api.insertElementIntoParent(pid, viewing.cid, viewing.eid);
      setParentSnapshot(res.transcript);
      flash(
        `Inserted ${res.inserted} word(s) into parent at ${res.start.toFixed(3)}–${res.end.toFixed(3)}s `
        + `(removed ${res.removed})`
      );
    } catch (e) {
      flash("Insert failed: " + e.message);
    }
  };

  const refine = async () => {
    flash("Asking OpenAI…");
    const res = await api.refineOpenAI(pid, settings);
    if (res.ok) {
      setTranscript((prev) => ({ ...prev, jefferson: res.text }));
      flash("OpenAI suggestions applied to the Jefferson pane");
    } else {
      flash("OpenAI: " + (res.reason || "unavailable"));
    }
  };

  const generateJapanese = async () => {
    if (!pid) return;
    setJapaneseBusy(true);
    flash("Generating Japanese four-line rows…");
    try {
      const res = await api.generateJapaneseLayers(pid, settings);
      if (res.transcript) {
        setTranscript(res.transcript);
        setDirty(false);
      }
      const untranslated = (res.transcript?.turns || []).filter(
        (t) => t.speaker && !t.japanese?.natural_translation
      ).length;
      flash(
        untranslated
          ? `Romanization ready · ${untranslated} English row(s) need OpenAI or manual editing`
          : "Japanese four-line transcript generated"
      );
    } catch (e) {
      flash("Japanese generation failed: " + e.message);
    } finally {
      setJapaneseBusy(false);
    }
  };

  const selectedToken = () => {
    if (!transcript || !selectedId) return null;
    for (const turn of transcript.turns)
      for (const t of turn.tokens) if (t.id === selectedId) return t;
    return null;
  };

  const pct = status ? Math.round((status.progress || 0) * 100) : 0;

  const [sidebarW, setSidebarW] = usePersistedNumber("ca-layout-sidebar-w", 340, { min: 200, max: 560 });
  const [sidebarOpen, setSidebarOpen] = usePersistedBool("ca-layout-sidebar-open", true);
  const [inspectorW, setInspectorW] = usePersistedNumber("ca-layout-inspector-w", 320, { min: 200, max: 560 });
  const [showPlayer, setShowPlayer] = usePersistedBool("ca-layout-show-player", true);
  const [showPitch, setShowPitch] = usePersistedBool("ca-layout-show-pitch", true);
  const [showEditBar, setShowEditBar] = usePersistedBool("ca-layout-show-editbar", true);
  const [showInspector, setShowInspector] = usePersistedBool("ca-layout-show-inspector", true);
  const [showJefferson, setShowJefferson] = usePersistedBool("ca-layout-show-jefferson", false);
  const [splitH, setSplitH] = usePersistedNumber("ca-layout-split-h", 52, { min: 24, max: 80 }); // vh-ish % of remaining

  const onSidebarDrag = useCallback((x) => {
    setSidebarW(x);
  }, [setSidebarW]);

  const onInspectorDrag = useCallback((x) => {
    // Distance from right edge of the split container — use viewport-relative
    const main = document.querySelector(".main-split");
    if (!main) return;
    const rect = main.getBoundingClientRect();
    const fromRight = rect.right - x;
    setInspectorW(fromRight);
  }, [setInspectorW]);

  const onSplitHeightDrag = useCallback((y) => {
    const workspace = document.querySelector(".workspace");
    if (!workspace) return;
    const rect = workspace.getBoundingClientRect();
    const splitTop = document.querySelector(".main-split")?.getBoundingClientRect()?.top;
    if (!splitTop) return;
    const avail = rect.bottom - splitTop - 8;
    if (avail <= 0) return;
    const h = ((y - splitTop) / avail) * 100;
    setSplitH(h);
  }, [setSplitH]);

  return (
    <div className="app-root">
      <div className="mode-bar">
        <div className="mode-brand">
          <strong>Turnwise</strong>
          <span className="muted">conversation analysis</span>
        </div>
        <div className="mode-tabs">
          <button
            type="button"
            className={mode === "simple" ? "on" : ""}
            onClick={() => setAppMode("simple")}
          >
            Simple
          </button>
          <button
            type="button"
            className={mode === "advanced" ? "on" : ""}
            onClick={() => setAppMode("advanced")}
          >
            Advanced
          </button>
        </div>
        <UpdateFromGit onToast={flash} />
      </div>

      {mode === "simple" ? (
        <BatchSimple
          defaults={defaults || settings}
          onToast={flash}
          onOpenProject={(projectId) => {
            setAppMode("advanced");
            openProject(projectId);
          }}
        />
      ) : (
    <div className={"app" + (sidebarOpen ? "" : " sidebar-collapsed")}>
      {sidebarOpen ? (
        <aside className="sidebar" style={{ width: sidebarW, minWidth: sidebarW, maxWidth: sidebarW }}>
          <div className="brand">
            Turnwise
            <span className="sub">advanced editor</span>
            <button
              type="button"
              className="sidebar-hide"
              title="Hide sidebar"
              onClick={() => setSidebarOpen(false)}
            >⟨</button>
          </div>

        <div className="tabs">
          <button className={tab === "new" ? "on" : ""} onClick={() => setTab("new")}>+ New</button>
          <button className={tab === "project" ? "on" : ""} onClick={() => setTab("project")}>
            Projects{projects.length ? ` (${projects.length})` : ""}
          </button>
          <button className={tab === "settings" ? "on" : ""} onClick={() => setTab("settings")}>
            ⚙ Settings
          </button>
        </div>

        {tab === "new" && (
          <div className="panel">
            <label className="upload">
              <input
                type="file"
                accept="audio/*,.mp3,.wav,.m4a,.flac,.ogg"
                onChange={(e) => doUpload(e.target.files[0])}
              />
              <span>Choose audio file…</span>
            </label>
            <p className="hint">Upload a file, or open <b>⚙ Settings</b> to set model, diarization, names/keywords, and CA options before transcribing.</p>
            <hr className="sep" />
            <ModelsManager onToast={flash} />
          </div>
        )}

        {tab === "settings" && settings && (
          <div className="panel settings-sidebar">
            {pid ? (
              <p className="hint settings-scope">
                Settings for <b>{(projects.find((p) => p.project_id === pid) || {}).filename || pid}</b>
              </p>
            ) : (
              <p className="hint settings-scope">
                Default settings for new uploads and Simple batch mode. Open a project to edit that project only.
              </p>
            )}
            <SettingsPanel settings={settings} onChange={setSettings} />
            <hr className="sep" />
            <ModelsManager onToast={flash} />
            <div className="settings-actions">
              <button type="button" className="btn" onClick={saveSettings}>
                Save settings
              </button>
              {pid && (
                <button
                  type="button"
                  className="btn primary"
                  onClick={updateTranscript}
                  disabled={status && status.state !== "done" && status.state !== "error" && status.state !== "cancelled"}
                  title="Save settings and re-run transcription on this project"
                >
                  ↻ Update transcript
                </button>
              )}
            </div>
          </div>
        )}

        {tab === "project" && (
          <div className="panel">
            <ProjectTree
              projects={projects}
              pid={pid}
              viewing={viewing}
              currentCollectionId={currentCollection?.id || null}
              refreshTick={collectionsTick}
              onOpenProject={openProject}
              onOpenElement={openElement}
              onOpenSettings={openProjectSettings}
              onActiveCollectionChange={setActiveCollection}
              onDeleteProject={removeProject}
              onDeleteAllProjects={removeAllProjects}
              onToast={flash}
            />
          </div>
        )}
        </aside>
      ) : (
        <button
          type="button"
          className="sidebar-rail"
          title="Show sidebar"
          onClick={() => setSidebarOpen(true)}
        >
          ☰
        </button>
      )}

      {sidebarOpen && (
        <ResizeHandle axis="x" onDrag={onSidebarDrag} />
      )}

      <main className="main">
        <div className="layout-chips">
          {!sidebarOpen && (
            <button type="button" className="chip" onClick={() => setSidebarOpen(true)}>Show sidebar</button>
          )}
          {!showPlayer && (
            <button type="button" className="chip" onClick={() => setShowPlayer(true)}>Show waveform</button>
          )}
          {!showPitch && (
            <button type="button" className="chip" onClick={() => setShowPitch(true)}>Show pitch</button>
          )}
          {!showEditBar && !viewing && pid && transcript && (
            <button type="button" className="chip" onClick={() => setShowEditBar(true)}>Show edit tools</button>
          )}
          {!showInspector && pid && transcript && (
            <button type="button" className="chip" onClick={() => setShowInspector(true)}>Show inspector</button>
          )}
          {!showJefferson && pid && transcript && (
            <button type="button" className="chip" onClick={() => setShowJefferson(true)}>Show Jefferson</button>
          )}
        </div>

        {!pid && <div className="empty-main"><h1>Turnwise</h1><p>Upload an audio file to generate a Conversation-Analysis transcript with synced karaoke playback — or use Simple mode for folder batch jobs.</p></div>}

        {pid && status && status.state !== "done" && status.state !== "error" && status.state !== "cancelled" && (
          <div className="progress-wrap">
            <h2>Processing…</h2>
            <div className="bar"><div className="fill" style={{ width: pct + "%" }} /></div>
            <p className="stage">{status.stage} — {status.message} ({pct}%)</p>
            <p className="muted">Whisper on CPU runs slower than real time; larger models take longer.</p>
            <button
              type="button"
              className="btn danger"
              onClick={abortTranscription}
              title="Stop this transcription"
            >
              ■ Abort transcription
            </button>
          </div>
        )}

        {pid && status && status.state === "cancelled" && !transcript && (
          <div className="progress-wrap">
            <h2>Transcription aborted</h2>
            <p className="muted">Nothing was saved for this run. You can re-run with current Settings or upload again.</p>
            <div className="progress-actions">
              <button type="button" className="btn primary" onClick={updateTranscript}>↻ Update transcript</button>
            </div>
          </div>
        )}

        {pid && status && status.state === "error" && (
          <div className="progress-wrap error">
            <h2>Processing failed</h2>
            <pre>{status.error}</pre>
          </div>
        )}

        {pid && transcript && (
          <div className="workspace">
            {viewing && (
              <div className="viewing-banner">
                Viewing collection clip <b>{viewing.label}</b>
                <button className="btn tiny" onClick={backToParent}>← Full project</button>
                <button
                  className="btn tiny primary"
                  onClick={insertClipIntoParent}
                  title="Replace the parent transcript in this clip's time range with the corrected clip text"
                >
                  ↑ Insert into original
                </button>
                <a className="chip" href={api.elementDownloadUrl(pid, viewing.cid, viewing.eid, "mp3")} download>↓ MP3</a>
                <a className="chip" href={api.elementDownloadUrl(pid, viewing.cid, viewing.eid, "wav")} download>↓ WAV</a>
              </div>
            )}

            {showPlayer && (
              <CollapsiblePanel
                id="player"
                title="Waveform"
                className="waveform-dock"
                storageKey="ca-panel-open-player"
                headerExtra={
                  <button type="button" className="panel-hide" title="Hide waveform" onClick={() => setShowPlayer(false)}>✕</button>
                }
              >
                <Player
                  ref={playerRef}
                  url={
                    viewing
                      ? api.elementAudioUrl(pid, viewing.cid, viewing.eid)
                      : audioUrl(pid)
                  }
                  onTime={setCurrentTime}
                  onRegionChange={setRegion}
                />
                {!viewing && (
                  <div className="wave-quick-add">
                    <button
                      type="button"
                      className="btn primary"
                      disabled={quickAddBusy || !region || region.end <= region.start}
                      onClick={addSelectionToCollection}
                      title={
                        currentCollection
                          ? `Add selection to “${currentCollection.label}”`
                          : "Add selection to the last-used collection (creates “Clips” if none)"
                      }
                    >
                      {quickAddBusy
                        ? "Adding…"
                        : `+ Add to ${currentCollection?.label || "collection"}`}
                    </button>
                    <span className="wave-quick-meta muted">
                      {region && region.end > region.start
                        ? `Will name: “${clipLabelFromSelection(transcript, region.start, region.end)}”`
                        : "Select a range on the waveform first"}
                    </span>
                  </div>
                )}
                {viewing && (
                  <ClipRerunBar
                    pid={pid}
                    viewing={viewing}
                    settings={settings}
                    onToast={flash}
                    onUpdated={(res) => {
                      if (res?.transcript) {
                        setTranscript(res.transcript);
                        setDirty(false);
                        setSelectedId(null);
                      }
                      if (res?.meta?.label) {
                        setViewing((v) => (v ? { ...v, label: res.meta.label } : v));
                      }
                      setCollectionsTick((n) => n + 1);
                    }}
                  />
                )}
              </CollapsiblePanel>
            )}

            {showPitch && (
              <CollapsiblePanel
                id="pitch"
                title="Pitch / intensity"
                storageKey="ca-panel-open-pitch"
                defaultOpen={true}
                headerExtra={
                  <button type="button" className="panel-hide" title="Hide pitch" onClick={() => setShowPitch(false)}>✕</button>
                }
              >
                <PitchView
                  transcript={transcript}
                  currentTime={currentTime}
                  pid={pid}
                  selectedId={selectedId}
                  onSelectToken={setSelectedId}
                  onSeek={(s) => playerRef.current && playerRef.current.seek(s)}
                  onSelectRange={selectTurnRange}
                  onPlayRange={(a, b) => {
                    if (!playerRef.current) return;
                    playerRef.current.setRegion(a, b);
                    playerRef.current.playRegion();
                  }}
                />
              </CollapsiblePanel>
            )}

            {!viewing && showEditBar && (
              <CollapsiblePanel
                id="editbar"
                title="Edit tools"
                storageKey="ca-panel-open-editbar"
                headerExtra={
                  <button type="button" className="panel-hide" title="Hide edit tools" onClick={() => setShowEditBar(false)}>✕</button>
                }
              >
                <EditBar
                  region={region}
                  speakers={transcript.speakers}
                  settings={settings}
                  busy={rangeBusy}
                  selectedToken={selectedToken()}
                  onAddPhrase={addPhraseFromWave}
                  onApplyTimingToSelected={applyTimingToSelected}
                  onRerunRange={rerunSelectedRange}
                  onAbortRerun={abortRangeRerun}
                  onPlayRegion={() => playerRef.current && playerRef.current.playRegion()}
                />
              </CollapsiblePanel>
            )}

            <div className="toolbar">
              <button className="btn" onClick={save} disabled={!dirty}>
                {dirty
                  ? (viewing ? "● Save clip" : "● Save edits")
                  : (viewing ? "Clip saved" : "Saved")}
              </button>
              {viewing && (
                <button
                  className="btn primary"
                  onClick={insertClipIntoParent}
                  title="Write this corrected clip back into the original project transcript at its timestamps"
                >
                  ↑ Insert into original
                </button>
              )}
              {!viewing && (
                <button
                  className="btn primary"
                  onClick={updateTranscript}
                  title="Save settings and re-transcribe with current options"
                >
                  ↻ Update transcript
                </button>
              )}
              {transcript.layout === "japanese_four_line" && (
                <button
                  className="btn"
                  disabled={japaneseBusy}
                  onClick={generateJapanese}
                  title="Refresh romanization, direct gloss and natural translation"
                >
                  {japaneseBusy ? "Generating…" : "文 Generate 4 lines"}
                </button>
              )}
              {settings?.enable_openai && !viewing && <button className="btn" onClick={refine}>OpenAI refine</button>}
              <span className="speaker-rename">
                Speakers:
                {transcript.speakers.map((s) => (
                  <span key={s.id} className="spk-edit">
                    <input
                      defaultValue={s.label}
                      onBlur={(e) => renameSpeaker(s.id, e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && e.target.blur()}
                    />
                  </span>
                ))}
              </span>
              <span className="spacer" />
              {!viewing && (
                <span className="exports">
                  Export:
                  {["txt", "json", "midi", "textgrid", "eaf"].map((f) => (
                    <a key={f} className="chip" href={exportUrl(pid, f)} download>{f}</a>
                  ))}
                  {transcript.layout === "japanese_four_line" && (
                    <a
                      className="chip primary"
                      href={exportUrl(pid, "docx")}
                      download
                      title="Four-line Japanese research transcript matching the supplied Word layout"
                    >
                      DOCX 4-line
                    </a>
                  )}
                  <a className="chip primary" href={exportUrl(pid, "vba")} download title="Word/sentence timing for PowerPoint VBA animation">VBA timing</a>
                  <a className="chip primary" href={exportUrl(pid, "slides")} download title="Transcript laid out across slides (font size 20)">Slides PPTX</a>
                  <a className="chip" href={exportUrl(pid, "mp4")} download>mp4 karaoke</a>
                  <button className="chip build" onClick={() => setShowPresent(true)} title="Generate full presentations (pptx/pptm/odp/pdf/srt/vtt/txt/json) with options">🎬 Generate presentation…</button>
                </span>
              )}
            </div>

            <div
              className={"main-split" + (showInspector ? "" : " no-inspector")}
              style={showInspector ? {
                gridTemplateColumns: `minmax(0, 1fr) 6px ${inspectorW}px`,
                minHeight: `${splitH}vh`,
              } : {
                minHeight: `${splitH}vh`,
              }}
            >
              <div className="split-left">
                <div className="panel-chrome in-split">
                  <span className="panel-title">Transcript</span>
                </div>
                <TranscriptView
                  transcript={transcript}
                  currentTime={currentTime}
                  onSeek={(s) => playerRef.current && playerRef.current.seek(s)}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  onUpdateToken={updateToken}
                  onUpdateJapanese={updateJapanese}
                  onSelectTurnRange={selectTurnRange}
                />
              </div>
              {showInspector && (
                <>
                  <ResizeHandle axis="x" onDrag={onInspectorDrag} />
                  <div className="split-right" style={{ width: inspectorW }}>
                    <div className="panel-chrome in-split">
                      <span className="panel-title">Inspector</span>
                      <button type="button" className="panel-hide" title="Hide inspector" onClick={() => setShowInspector(false)}>✕</button>
                    </div>
                    <Inspector
                      token={selectedToken()}
                      speakers={transcript.speakers}
                      onChange={updateToken}
                      onInsertBefore={(id) => insertWord(id, "before")}
                      onInsertAfter={(id) => insertWord(id, "after")}
                      onDelete={deleteToken}
                      onSeek={(s) => playerRef.current && playerRef.current.seek(s)}
                      playerRef={playerRef}
                      region={region}
                      onApplyRegionTiming={applyTimingToSelected}
                      onSetRegionFromWord={(tok) => selectTurnRange(tok.start, tok.end)}
                    />
                  </div>
                </>
              )}
            </div>
            <ResizeHandle axis="y" onDrag={onSplitHeightDrag} />

            {showJefferson && (
              <CollapsiblePanel
                id="jefferson"
                title="Jefferson transcript"
                storageKey="ca-panel-open-jefferson"
                defaultOpen={true}
                headerExtra={
                  <button type="button" className="panel-hide" title="Hide Jefferson" onClick={() => setShowJefferson(false)}>✕</button>
                }
              >
                <pre className="jefferson-pre">{transcript.jefferson}</pre>
              </CollapsiblePanel>
            )}

            {transcript.meta?.warnings?.length > 0 && (
              <div className="warnings">
                {transcript.meta.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
              </div>
            )}
          </div>
        )}
      </main>

      {showPresent && pid && transcript && (
        <PresentationModal
          pid={pid}
          defaultTitle={
            (projects.find((p) => p.project_id === pid) || {}).filename ||
            transcript.meta?.filename ||
            "Transcript"
          }
          onClose={() => setShowPresent(false)}
          onToast={flash}
        />
      )}

    </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
