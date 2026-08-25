const JSON_HEADERS = { "Content-Type": "application/json" };

export async function getDefaults() {
  const r = await fetch("/api/settings/defaults");
  return r.json();
}

export async function previewBatch(input_dir, recursive = false) {
  const r = await fetch("/api/batch/preview", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ input_dir, recursive }),
  });
  if (!r.ok) {
    let msg = "preview failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function startBatch({ input_dir, output_dir, settings, formats, recursive }) {
  const r = await fetch("/api/batch", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ input_dir, output_dir, settings, formats, recursive }),
  });
  if (!r.ok) {
    let msg = "batch start failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function getBatch(batchId) {
  const r = await fetch(`/api/batch/${batchId}`);
  if (!r.ok) throw new Error("batch status failed");
  return r.json();
}

export async function cancelBatch(batchId) {
  const r = await fetch(`/api/batch/${batchId}/cancel`, { method: "POST" });
  if (!r.ok) throw new Error("batch cancel failed");
  return r.json();
}

export async function getProjectSettings(pid) {
  const r = await fetch(`/api/projects/${pid}/settings`);
  if (!r.ok) throw new Error("settings load failed");
  return r.json();
}

export async function saveDefaults(settings) {
  const r = await fetch("/api/settings/defaults", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ settings }),
  });
  if (!r.ok) throw new Error("defaults save failed");
  return r.json();
}

export async function getUpdateStatus(fetchRemote = false) {
  const q = fetchRemote ? "?fetch=true" : "";
  const r = await fetch(`/api/update/status${q}`);
  if (!r.ok) throw new Error("update status failed");
  return r.json();
}

export async function saveUpdateConfig({ remote_url, branch }) {
  const r = await fetch("/api/update/config", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ remote_url, branch }),
  });
  if (!r.ok) {
    let msg = "could not save update config";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function connectUpdate({ remote_url, branch }) {
  const r = await fetch("/api/update/connect", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ remote_url, branch }),
  });
  if (!r.ok) {
    let msg = "connect failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function applyUpdate() {
  const r = await fetch("/api/update", { method: "POST" });
  if (!r.ok) {
    let msg = "update failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function saveProjectSettings(pid, settings) {
  const r = await fetch(`/api/projects/${pid}/settings`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ settings }),
  });
  if (!r.ok) throw new Error("settings save failed");
  return r.json();
}

export async function listProjects() {
  const r = await fetch("/api/projects");
  return r.json();
}

export async function uploadAudio(file, settings) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("settings", JSON.stringify(settings || {}));
  const r = await fetch("/api/projects", { method: "POST", body: fd });
  if (!r.ok) throw new Error("upload failed");
  return r.json();
}

export async function getStatus(pid) {
  const r = await fetch(`/api/projects/${pid}/status`);
  if (!r.ok) throw new Error("status failed");
  return r.json();
}

export async function getTranscript(pid) {
  const r = await fetch(`/api/projects/${pid}/transcript`);
  if (!r.ok) throw new Error("transcript not ready");
  return r.json();
}

export async function saveTranscript(pid, transcript) {
  const r = await fetch(`/api/projects/${pid}/transcript`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(transcript),
  });
  if (!r.ok) throw new Error("save failed");
  return r.json(); // { ok, transcript }
}

export async function reprocess(pid, settings) {
  const r = await fetch(`/api/projects/${pid}/reprocess`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ settings }),
  });
  if (!r.ok) throw new Error("reprocess failed");
  return r.json();
}

export async function generateJapaneseLayers(pid, settings) {
  const r = await fetch(`/api/projects/${pid}/japanese-layers`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ settings }),
  });
  if (!r.ok) {
    let msg = "Japanese translation failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function abortProject(pid) {
  const r = await fetch(`/api/projects/${pid}/abort`, { method: "POST" });
  if (!r.ok) {
    let msg = "abort failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function reprocessRange(pid, { start, end, settings, speaker, signal }) {
  const r = await fetch(`/api/projects/${pid}/reprocess-range`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ start, end, settings, speaker }),
    signal,
  });
  if (!r.ok) {
    let msg = "range reprocess failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function refineOpenAI(pid, settings) {
  const r = await fetch(`/api/projects/${pid}/openai-refine`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ settings }),
  });
  return r.json();
}

export async function deleteProject(pid) {
  await fetch(`/api/projects/${pid}`, { method: "DELETE" });
}

export async function listModels() {
  const r = await fetch("/api/models");
  if (!r.ok) throw new Error("list models failed");
  return r.json();
}

export async function deleteModel(id) {
  const r = await fetch(`/api/models?id=${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok) throw new Error("delete failed");
  return r.json();
}

export function audioUrl(pid) {
  return `/api/projects/${pid}/audio`;
}

export function exportUrl(pid, fmt) {
  return `/api/projects/${pid}/export/${fmt}`;
}

export async function presentationFormats() {
  const r = await fetch("/api/presentation/formats");
  if (!r.ok) throw new Error("formats failed");
  return r.json();
}

export async function generatePresentation(pid, options) {
  const r = await fetch(`/api/projects/${pid}/presentation`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(options || {}),
  });
  if (!r.ok) {
    let msg = "generation failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}

export function presentationFileUrl(pid, filename) {
  return `/api/projects/${pid}/presentation/${encodeURIComponent(filename)}`;
}

// ---- Collections ----
export async function listCollections(pid) {
  const r = await fetch(`/api/projects/${pid}/collections`);
  if (!r.ok) throw new Error("list collections failed");
  return r.json();
}

export async function createCollection(pid, label) {
  const r = await fetch(`/api/projects/${pid}/collections`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ label }),
  });
  if (!r.ok) throw new Error("create collection failed");
  return r.json();
}

export async function getCollection(pid, cid) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}`);
  if (!r.ok) throw new Error("get collection failed");
  return r.json();
}

export async function renameCollection(pid, cid, label) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify({ label }),
  });
  if (!r.ok) throw new Error("rename failed");
  return r.json();
}

export async function deleteCollection(pid, cid) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}`, { method: "DELETE" });
  if (!r.ok) throw new Error("delete collection failed");
  return r.json();
}

export async function addCollectionElement(pid, cid, { start, end, label }) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}/elements`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ start, end, label }),
  });
  if (!r.ok) {
    let msg = "add element failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function getCollectionElement(pid, cid, eid) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}/elements/${eid}`);
  if (!r.ok) throw new Error("get element failed");
  return r.json();
}

export async function deleteCollectionElement(pid, cid, eid) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}/elements/${eid}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error("delete element failed");
  return r.json();
}

export async function reprocessCollectionElement(pid, cid, eid, { settings, speaker } = {}) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}/elements/${eid}/reprocess`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ settings, speaker }),
  });
  if (!r.ok) {
    let msg = "element reprocess failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function reprocessCollectionAll(pid, cid, { settings, speaker } = {}) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}/reprocess-all`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ settings, speaker }),
  });
  if (!r.ok) {
    let msg = "collection reprocess failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function generateCollectionPresentation(pid, cid, options = {}) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}/presentation`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(options),
  });
  if (!r.ok) {
    let msg = "collection presentation failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function saveElementTranscript(pid, cid, eid, transcript) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}/elements/${eid}/transcript`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(transcript),
  });
  if (!r.ok) {
    let msg = "save element failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export async function insertElementIntoParent(pid, cid, eid) {
  const r = await fetch(`/api/projects/${pid}/collections/${cid}/elements/${eid}/insert`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
  if (!r.ok) {
    let msg = "insert into parent failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export function elementAudioUrl(pid, cid, eid) {
  return `/api/projects/${pid}/collections/${cid}/elements/${eid}/audio`;
}

export function elementDownloadUrl(pid, cid, eid, fmt = "mp3") {
  return `/api/projects/${pid}/collections/${cid}/elements/${eid}/download?fmt=${encodeURIComponent(fmt)}`;
}

export async function exportClipBlob(pid, start, end, fmt = "mp3") {
  const r = await fetch(`/api/projects/${pid}/export-clip`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ start, end, fmt }),
  });
  if (!r.ok) {
    let msg = "export clip failed";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.blob();
}

// Subscribe to job progress via Server-Sent Events. Returns an unsubscribe fn.
export function subscribeProgress(pid, onUpdate) {
  const es = new EventSource(`/api/projects/${pid}/events`);
  es.onmessage = (e) => {
    try {
      onUpdate(JSON.parse(e.data));
    } catch (_) {}
  };
  es.onerror = () => es.close();
  return () => es.close();
}
