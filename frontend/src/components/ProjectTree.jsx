import React, { useCallback, useEffect, useState } from "react";
import * as api from "../api.js";

/**
 * Projects list with nested Collections → clips tree.
 * Click a project to open it; expand to browse collections and open clips.
 */
export default function ProjectTree({
  projects,
  pid,
  viewing,
  currentCollectionId,
  refreshTick,
  onOpenProject,
  onOpenElement,
  onOpenSettings,
  onActiveCollectionChange,
  onDeleteProject,
  onDeleteAllProjects,
  onToast,
}) {
  const [expandedPid, setExpandedPid] = useState(() => new Set());
  const [expandedCid, setExpandedCid] = useState(() => new Set());
  // pid → [{id, label, element_count}] or full detail with elements
  const [byProject, setByProject] = useState({});
  const [newLabel, setNewLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [exportingCid, setExportingCid] = useState(null);

  const loadProjectCollections = useCallback(async (projectId) => {
    if (!projectId) return;
    try {
      const res = await api.listCollections(projectId);
      const list = res.collections || [];
      const detailed = await Promise.all(
        list.map(async (c) => {
          try {
            const meta = await api.getCollection(projectId, c.id);
            return {
              id: meta.id,
              label: meta.label,
              element_count: (meta.elements || []).length,
              elements: meta.elements || [],
            };
          } catch (_) {
            return { ...c, elements: [] };
          }
        })
      );
      setByProject((prev) => ({ ...prev, [projectId]: detailed }));
    } catch (e) {
      onToast && onToast("Collections: " + e.message);
    }
  }, [onToast]);

  // Auto-expand the open project and load its collections
  useEffect(() => {
    if (!pid) return;
    setExpandedPid((prev) => {
      if (prev.has(pid)) return prev;
      const next = new Set(prev);
      next.add(pid);
      return next;
    });
    loadProjectCollections(pid);
  }, [pid, loadProjectCollections]);

  // Refresh after quick-add / clip ops
  useEffect(() => {
    if (refreshTick && pid) loadProjectCollections(pid);
  }, [refreshTick, pid, loadProjectCollections]);

  // Expand the collection that owns the viewing clip / current collection
  useEffect(() => {
    const cid = viewing?.cid || currentCollectionId;
    if (!cid) return;
    setExpandedCid((prev) => {
      if (prev.has(cid)) return prev;
      const next = new Set(prev);
      next.add(cid);
      return next;
    });
  }, [viewing?.cid, currentCollectionId]);

  const toggleProject = (e, projectId) => {
    e.stopPropagation();
    setExpandedPid((prev) => {
      const next = new Set(prev);
      if (next.has(projectId)) next.delete(projectId);
      else {
        next.add(projectId);
        loadProjectCollections(projectId);
      }
      return next;
    });
  };

  const toggleCollection = (e, cid) => {
    e.stopPropagation();
    setExpandedCid((prev) => {
      const next = new Set(prev);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });
  };

  const selectCollection = (projectId, coll) => {
    if (projectId !== pid) onOpenProject(projectId);
    onActiveCollectionChange && onActiveCollectionChange({
      id: coll.id,
      label: coll.label,
    }, projectId);
    setExpandedCid((prev) => {
      const next = new Set(prev);
      next.add(coll.id);
      return next;
    });
  };

  const createCollection = async (projectId) => {
    if (projectId !== pid) {
      onToast && onToast("Open the project first to create a collection");
      return;
    }
    setBusy(true);
    try {
      const meta = await api.createCollection(projectId, newLabel || "Untitled collection");
      setNewLabel("");
      await loadProjectCollections(projectId);
      onActiveCollectionChange && onActiveCollectionChange({
        id: meta.id,
        label: meta.label,
      });
      setExpandedCid((prev) => new Set(prev).add(meta.id));
      onToast && onToast(`Collection “${meta.label}” created`);
    } catch (e) {
      onToast && onToast(e.message);
    } finally {
      setBusy(false);
    }
  };

  const renameCollection = async (e, projectId, coll) => {
    e.stopPropagation();
    const label = prompt("Rename collection", coll.label);
    if (!label) return;
    try {
      const meta = await api.renameCollection(projectId, coll.id, label);
      await loadProjectCollections(projectId);
      if (currentCollectionId === coll.id) {
        onActiveCollectionChange && onActiveCollectionChange({
          id: meta.id,
          label: meta.label,
        });
      }
    } catch (err) {
      onToast && onToast(err.message);
    }
  };

  const deleteCollection = async (e, projectId, coll) => {
    e.stopPropagation();
    if (!confirm(`Delete collection “${coll.label}” and all its clips?`)) return;
    try {
      await api.deleteCollection(projectId, coll.id);
      if (currentCollectionId === coll.id) {
        onActiveCollectionChange && onActiveCollectionChange(null);
      }
      await loadProjectCollections(projectId);
      onToast && onToast("Collection deleted");
    } catch (err) {
      onToast && onToast(err.message);
    }
  };

  const deleteElement = async (e, projectId, cid, eid) => {
    e.stopPropagation();
    if (!confirm("Delete this clip?")) return;
    try {
      await api.deleteCollectionElement(projectId, cid, eid);
      await loadProjectCollections(projectId);
    } catch (err) {
      onToast && onToast(err.message);
    }
  };

  const exportCollectionPpt = async (e, projectId, coll) => {
    e.stopPropagation();
    if (!(coll.elements || []).length) {
      onToast && onToast("Add at least one clip before exporting");
      return;
    }
    setExportingCid(coll.id);
    try {
      const result = await api.generateCollectionPresentation(projectId, coll.id, {
        title: coll.label || "Collection",
        subtitle: `${(coll.elements || []).length} clips`,
        formats: ["pptx"],
        include_audio: true,
        include_title_slide: true,
        include_notes: true,
        line_numbers: true,
        karaoke: "auto",
      });
      const a = document.createElement("a");
      a.href = result.url;
      a.download = `${coll.label || "collection"}.pptx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      onToast && onToast(
        `PowerPoint ready · ${result.clips} clips · ${result.slides} slides`
      );
    } catch (err) {
      onToast && onToast("PowerPoint export failed: " + err.message);
    } finally {
      setExportingCid(null);
    }
  };

  const fmtRange = (el) => {
    if (el.start == null || el.end == null) return "";
    return `${Number(el.start).toFixed(1)}–${Number(el.end).toFixed(1)}s`;
  };

  return (
    <div className="project-tree">
      <div className="proj-head">
        <h3>Projects</h3>
        {projects.length > 0 && (
          <button className="btn tiny danger" onClick={onDeleteAllProjects}>
            Delete all ({projects.length})
          </button>
        )}
      </div>
      {projects.length > 0 && (
        <p className="hint">
          Total {(projects.reduce((s, p) => s + (p.size_mb || 0), 0)).toFixed(1)} MB on disk
        </p>
      )}

      <ul className="tree-root">
        {projects.map((p) => {
          const open = expandedPid.has(p.project_id);
          const active = p.project_id === pid;
          const collections = byProject[p.project_id] || [];
          return (
            <li key={p.project_id} className={"tree-project" + (active ? " on" : "")}>
              <div
                className="tree-row project-row"
                onClick={() => onOpenProject(p.project_id)}
              >
                <button
                  type="button"
                  className="tree-twist"
                  onClick={(e) => toggleProject(e, p.project_id)}
                  title={open ? "Collapse" : "Expand collections"}
                >
                  {open ? "▾" : "▸"}
                </button>
                <span className="pname" title={p.filename}>{p.filename}</span>
                <button
                  type="button"
                  className="pgear"
                  title="Settings for this project"
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenSettings && onOpenSettings(p.project_id);
                  }}
                >⚙</button>
                <span className="psize">{p.size_mb != null ? `${p.size_mb} MB` : ""}</span>
                <span className={"pstate " + p.state}>{p.state}</span>
                <button
                  className="pdel"
                  title="Delete project + audio"
                  onClick={(e) => onDeleteProject(e, p.project_id)}
                >🗑</button>
              </div>

              {open && (
                <ul className="tree-branch">
                  <li className="tree-collections-label">
                    <span className="tree-branch-title">Collections</span>
                    {active && (
                      <span className="tree-create">
                        <input
                          placeholder="New collection…"
                          value={newLabel}
                          onChange={(e) => setNewLabel(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") createCollection(p.project_id);
                          }}
                        />
                        <button
                          type="button"
                          className="btn tiny primary"
                          disabled={busy}
                          onClick={(e) => {
                            e.stopPropagation();
                            createCollection(p.project_id);
                          }}
                        >+</button>
                      </span>
                    )}
                  </li>

                  {collections.map((coll) => {
                    const cOpen = expandedCid.has(coll.id);
                    const cActive = currentCollectionId === coll.id && active;
                    return (
                      <li
                        key={coll.id}
                        className={"tree-collection" + (cActive ? " current" : "")}
                      >
                        <div
                          className="tree-row collection-row"
                          onClick={() => selectCollection(p.project_id, coll)}
                        >
                          <button
                            type="button"
                            className="tree-twist"
                            onClick={(e) => toggleCollection(e, coll.id)}
                          >
                            {cOpen ? "▾" : "▸"}
                          </button>
                          <span className="cname">{coll.label}</span>
                          <span className="ccount">{coll.element_count ?? (coll.elements || []).length}</span>
                          <button
                            type="button"
                            className="chip tiny collection-ppt"
                            disabled={exportingCid === coll.id}
                            title="Combine all clips in order into one PowerPoint"
                            onClick={(e) => exportCollectionPpt(e, p.project_id, coll)}
                          >
                            {exportingCid === coll.id ? "…" : "PPT"}
                          </button>
                          {active && (
                            <>
                              <button
                                type="button"
                                className="chip tiny"
                                title="Rename"
                                onClick={(e) => renameCollection(e, p.project_id, coll)}
                              >✎</button>
                              <button
                                type="button"
                                className="chip tiny danger"
                                title="Delete collection"
                                onClick={(e) => deleteCollection(e, p.project_id, coll)}
                              >🗑</button>
                            </>
                          )}
                        </div>

                        {cOpen && (
                          <ul className="tree-clips">
                            {(coll.elements || []).map((el) => {
                              const clipOn =
                                viewing &&
                                viewing.cid === coll.id &&
                                viewing.eid === el.id;
                              return (
                                <li key={el.id} className={"tree-clip" + (clipOn ? " on" : "")}>
                                  <button
                                    type="button"
                                    className="clip-open"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onActiveCollectionChange && onActiveCollectionChange({
                                        id: coll.id,
                                        label: coll.label,
                                      }, p.project_id);
                                      onOpenElement({
                                        cid: coll.id,
                                        eid: el.id,
                                        label: el.label,
                                        projectId: p.project_id,
                                      });
                                    }}
                                    title="Open clip to edit transcript"
                                  >
                                    <span className="ename">{el.label || "clip"}</span>
                                    <span className="emeta">{fmtRange(el)}</span>
                                  </button>
                                  {active && (
                                    <button
                                      type="button"
                                      className="chip tiny danger"
                                      title="Delete clip"
                                      onClick={(e) => deleteElement(e, p.project_id, coll.id, el.id)}
                                    >🗑</button>
                                  )}
                                </li>
                              );
                            })}
                            {(coll.elements || []).length === 0 && (
                              <li className="muted tree-empty">No clips</li>
                            )}
                          </ul>
                        )}
                      </li>
                    );
                  })}

                  {collections.length === 0 && (
                    <li className="muted tree-empty">No collections yet</li>
                  )}
                </ul>
              )}
            </li>
          );
        })}
        {projects.length === 0 && <li className="muted">No projects yet</li>}
      </ul>
    </div>
  );
}
