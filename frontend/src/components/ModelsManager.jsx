import React, { useEffect, useState } from "react";
import * as api from "../api.js";

// Shows cached ASR/diarization models on disk and lets you delete them to
// reclaim space. A deleted model simply re-downloads the next time it's used.
export default function ModelsManager({ onToast }) {
  const [models, setModels] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);

  const refresh = () => {
    setLoading(true);
    api.listModels()
      .then((d) => {
        setModels(d.models || []);
        setTotal(d.total_mb || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const remove = async (m) => {
    if (!confirm(`Delete cached model "${m.name}" (${m.size_mb} MB)? It will re-download automatically if you use it again.`)) return;
    setBusy(m.id);
    try {
      await api.deleteModel(m.id);
      onToast && onToast(`Deleted ${m.name}`);
      refresh();
    } catch (e) {
      onToast && onToast("Delete failed: " + e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="models-mgr">
      <div className="proj-head">
        <h3>Manage models</h3>
        <button className="btn tiny" onClick={refresh} disabled={loading}>↻ Refresh</button>
      </div>
      <p className="hint">
        Cached models on disk{total ? ` · ${total} MB total` : ""}. Deleting one frees space; it
        re-downloads automatically when next selected.
      </p>
      {loading && models.length === 0 && <p className="muted">Loading…</p>}
      {!loading && models.length === 0 && <p className="muted">No cached models.</p>}
      <ul className="proj-list">
        {models.map((m) => (
          <li key={m.id} className="model-row">
            <span className="pname" title={m.name}>{m.name}</span>
            <span className="psize">{m.size_mb} MB</span>
            <button
              className="pdel"
              title="Delete cached model"
              disabled={busy === m.id}
              onClick={() => remove(m)}
            >🗑</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
