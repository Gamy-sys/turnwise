"""FastAPI app: upload, run pipeline, stream progress, edit + export transcripts,
and serve the built frontend. Local-first; no network needed for core features.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import jobs
from .config import (
    DEFAULT_SETTINGS,
    FRONTEND_DIST,
    MODEL_CACHE_DIR,
    PROJECTS_DIR,
    Settings,
    load_global_settings_dict,
    merged_defaults,
    save_global_settings_dict,
)
from .exports import (
    build_transcript_pptx,
    export_eaf,
    export_japanese_docx,
    export_textgrid,
    export_txt,
    export_vba,
)
from .models import Speaker, Transcript
from .presentation import available_formats, build_project, generate
from .presentation.project import ExportOptions
from .presentation.service import bundle
from .pipeline.ca import regroup_turns, render_jefferson
from .pipeline.midi_export import export_midi
from .pipeline.openai_pass import refine_transcript

app = FastAPI(title="Turnwise", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _source_file(project_id: str) -> Path | None:
    d = jobs.project_dir(project_id)
    for f in d.glob("source.*"):
        return f
    return None


def _display_name(d: Path, meta: dict) -> str:
    name_file = d / "original_name.txt"
    if name_file.exists():
        n = name_file.read_text(encoding="utf-8").strip()
        if n:
            return n
    n = meta.get("filename", "")
    if n and not n.startswith("source."):
        return n
    return ""


def _dir_size(d: Path) -> int:
    total = 0
    for f in d.rglob("*"):
        # skip symlinks so HuggingFace cache blobs aren't counted twice
        # (real files live in blobs/, snapshots/ are symlinks to them)
        if f.is_file() and not f.is_symlink():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def _project_summary(pid: str) -> dict:
    d = jobs.project_dir(pid)
    meta = {}
    tp = d / "transcript.json"
    if tp.exists():
        try:
            data = json.loads(tp.read_text(encoding="utf-8"))
            meta = data.get("meta", {})
        except Exception:
            pass
    st = jobs.get_status(pid)
    return {
        "project_id": pid,
        "filename": _display_name(d, meta) or f"({pid[:6]})",
        "duration": meta.get("duration", 0),
        "created_at": meta.get("created_at", ""),
        "size_mb": round(_dir_size(d) / 1_000_000, 1),
        "state": st.state if st else ("done" if tp.exists() else "unknown"),
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _project_settings_file(pid: str) -> Path:
    return jobs.project_dir(pid) / "settings.json"


def _merge_settings(override: dict | None = None) -> Settings:
    """Global defaults + request overrides; secrets always from server store."""
    base = load_global_settings_dict()
    override = dict(override or {})
    merged = {**base, **override}
    if isinstance(base.get("thresholds"), dict) and isinstance(override.get("thresholds"), dict):
        merged["thresholds"] = {**base["thresholds"], **override["thresholds"]}
    try:
        return Settings.from_dict(merged)
    except Exception:
        return merged_defaults()


def _project_settings(pid: str, override: dict | None = None) -> Settings:
    """Project-saved settings merged with request overrides.

    Each project keeps its own settings.json; API keys always come from the
    server-side secrets store so they are never erased by the UI.
    """
    saved: dict = {}
    f = _project_settings_file(pid)
    if f.exists():
        try:
            saved = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
    override = dict(override or {})
    merged = {**saved, **override}
    if isinstance(saved.get("thresholds"), dict) and isinstance(override.get("thresholds"), dict):
        merged["thresholds"] = {**saved["thresholds"], **override["thresholds"]}
    try:
        return Settings.from_dict(merged)
    except Exception:
        return merged_defaults()


def _save_project_settings(pid: str, settings_obj: Settings) -> dict:
    masked = settings_obj.to_dict()
    _project_settings_file(pid).write_text(json.dumps(masked, indent=2), encoding="utf-8")
    return masked


@app.get("/api/settings/defaults")
def settings_defaults():
    return merged_defaults().to_dict()


@app.put("/api/settings/defaults")
def put_settings_defaults(body: dict = {}):
    """Save global defaults used by Simple batch mode and new uploads."""
    try:
        settings_obj = Settings.from_dict((body or {}).get("settings", {}))
    except Exception:
        settings_obj = Settings()
    masked = settings_obj.to_dict()
    save_global_settings_dict(masked)
    return masked


# ---------------------------------------------------------------------------
# In-app update from git
# ---------------------------------------------------------------------------
@app.get("/api/update/status")
def update_status(fetch: bool = False):
    """Report current commit and whether origin has newer commits."""
    from . import updater
    return updater.get_status(fetch=bool(fetch))


@app.put("/api/update/config")
def update_config(body: dict = {}):
    """Save the git remote URL / branch used by Update from Git."""
    from . import updater
    body = body or {}
    cfg = updater.save_update_config(
        remote_url=body.get("remote_url"),
        branch=body.get("branch"),
    )
    return {"ok": True, **cfg, "status": updater.get_status(fetch=False)}


@app.post("/api/update/connect")
def update_connect(body: dict = {}):
    """Init/attach a remote so zip installs can start receiving git updates."""
    from . import updater
    body = body or {}
    result = updater.connect_remote(
        remote_url=body.get("remote_url") or "",
        branch=body.get("branch") or "main",
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("message") or "connect failed")
    return result


@app.post("/api/update")
def update_apply():
    """Pull latest from origin, rebuild the UI, refresh Python deps."""
    from . import updater
    result = updater.apply_update()
    if not result.get("ok"):
        raise HTTPException(400, result.get("message") or "update failed")
    return result


@app.post("/api/batch/preview")
def batch_preview(body: dict = {}):
    """List audio files in an input folder without starting a job."""
    from . import batch as batch_mod
    try:
        return batch_mod.preview_input(
            (body or {}).get("input_dir", ""),
            recursive=bool((body or {}).get("recursive", False)),
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/batch")
def start_batch(body: dict = {}):
    """Queue a Simple-mode folder → folder batch transcription."""
    from . import batch as batch_mod
    body = body or {}
    try:
        settings_obj = Settings.from_dict(body.get("settings") or {})
    except Exception:
        settings_obj = Settings()
    try:
        job = batch_mod.start_batch(
            input_dir=body.get("input_dir") or "",
            output_dir=body.get("output_dir") or "",
            settings=settings_obj,
            formats=body.get("formats") or ["txt"],
            recursive=bool(body.get("recursive", False)),
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"batch start failed: {e}")
    return job.to_dict()


@app.get("/api/batch/{batch_id}")
def get_batch(batch_id: str):
    from . import batch as batch_mod
    job = batch_mod.get_batch(batch_id)
    if not job:
        raise HTTPException(404, "batch not found")
    return job.to_dict()


@app.post("/api/batch/{batch_id}/cancel")
def cancel_batch(batch_id: str):
    from . import batch as batch_mod
    job = batch_mod.cancel_batch(batch_id)
    if not job:
        raise HTTPException(404, "batch not found")
    return job.to_dict()


@app.get("/api/projects/{pid}/settings")
def get_project_settings(pid: str):
    if not (PROJECTS_DIR / pid).exists():
        raise HTTPException(404, "project not found")
    return _project_settings(pid).to_dict()


@app.put("/api/projects/{pid}/settings")
def put_project_settings(pid: str, body: dict = {}):
    if not (PROJECTS_DIR / pid).exists():
        raise HTTPException(404, "project not found")
    settings_obj = _project_settings(pid, (body or {}).get("settings", {}))
    return _save_project_settings(pid, settings_obj)


@app.get("/api/projects")
def list_projects():
    items = []
    for d in sorted(PROJECTS_DIR.iterdir(), reverse=True) if PROJECTS_DIR.exists() else []:
        if d.is_dir():
            items.append(_project_summary(d.name))
    return items


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...), settings: str = Form("{}")):
    pid = uuid.uuid4().hex[:12]
    pdir = jobs.project_dir(pid)
    orig_name = file.filename or "audio.mp3"
    suffix = Path(orig_name).suffix or ".mp3"
    src = pdir / f"source{suffix}"
    with src.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    (pdir / "original_name.txt").write_text(orig_name, encoding="utf-8")

    try:
        settings_obj = _merge_settings(json.loads(settings or "{}"))
    except Exception:
        settings_obj = merged_defaults()

    jobs.enqueue(pid, src, settings_obj)
    return {"project_id": pid, "filename": file.filename}


@app.get("/api/projects/{pid}/status")
def project_status(pid: str):
    st = jobs.get_status(pid)
    if st is None:
        if (jobs.project_dir(pid) / "transcript.json").exists():
            return {"project_id": pid, "state": "done", "progress": 1.0, "stage": "done"}
        raise HTTPException(404, "unknown project")
    return st.model_dump()


@app.get("/api/projects/{pid}/events")
async def project_events(pid: str):
    async def gen():
        last = None
        for _ in range(3600):  # ~30 min ceiling
            st = jobs.get_status(pid)
            payload = st.model_dump() if st else {"state": "unknown"}
            s = json.dumps(payload)
            if s != last:
                yield f"data: {s}\n\n"
                last = s
            if payload.get("state") in ("done", "error", "cancelled"):
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/projects/{pid}/abort")
def abort_project(pid: str):
    """Stop an in-progress full transcription or range re-ASR for this project."""
    # Don't use jobs.project_dir() here: it mkdirs, creating ghost projects.
    if not (PROJECTS_DIR / pid).is_dir():
        raise HTTPException(404, "unknown project")
    return jobs.request_cancel(pid)


@app.get("/api/projects/{pid}/transcript")
def get_transcript(pid: str):
    tr = jobs.load_transcript(pid)
    if tr is None:
        raise HTTPException(404, "transcript not ready")
    # Upgrade legacy "A:\\t..." Jefferson blobs to the CA spacing layout.
    jeff = tr.jefferson or ""
    if jeff and (":\t" in jeff or not re.match(r"^\s*\d+ {3}", jeff)):
        tr.jefferson = render_jefferson(tr)
        try:
            jobs.save_transcript(pid, tr)
        except Exception:
            pass
    return tr.model_dump()


@app.put("/api/projects/{pid}/transcript")
def put_transcript(pid: str, body: dict):
    """Save an edited transcript.

    Rebuilds turns/latching/pauses from the (possibly edited) tokens so that
    adding/deleting words and changing timing or speaker stays consistent, then
    re-renders the Jefferson text. Returns the regrouped transcript.
    """
    try:
        tr = Transcript.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"invalid transcript: {e}")
    old_turns = tr.turns
    content = [tok for turn in old_turns if turn.speaker for tok in turn.tokens]
    tr.turns = regroup_turns(content, DEFAULT_SETTINGS.thresholds)
    if tr.layout == "japanese_four_line":
        from .pipeline.japanese import reattach_japanese_layers

        reattach_japanese_layers(old_turns, tr.turns)
    # keep speaker list in sync with whatever labels remain
    labels = sorted({t.speaker for t in tr.turns if t.speaker})
    existing = {s.id: s for s in tr.speakers}
    tr.speakers = [existing.get(l) or Speaker(id=l, label=l) for l in labels]
    tr.jefferson = render_jefferson(tr)
    jobs.save_transcript(pid, tr)
    return {"ok": True, "transcript": tr.model_dump()}


@app.post("/api/projects/{pid}/japanese-layers")
def generate_japanese_layers(pid: str, body: dict = {}):
    """Generate/refresh romanization, direct gloss and natural translation."""
    from .pipeline.japanese import populate_japanese_layers

    tr = jobs.load_transcript(pid)
    if tr is None:
        raise HTTPException(404, "transcript not ready")
    settings_obj = _project_settings(pid, (body or {}).get("settings", {}))
    settings_obj.transcript_layout = "japanese_four_line"
    settings_obj.japanese_auto_translate = True
    populate_japanese_layers(tr, settings_obj)
    jobs.save_transcript(pid, tr)
    return {"ok": True, "transcript": tr.model_dump()}


@app.post("/api/projects/{pid}/reprocess")
def reprocess(pid: str, body: dict = {}):
    """Re-run the whole pipeline on the already-uploaded audio with new settings.

    Lets the user change the model / VAD / thresholds and regenerate without
    re-uploading. Any manual edits are overwritten by the fresh transcript.
    """
    src = _source_file(pid)
    if not src or not src.exists():
        raise HTTPException(404, "source audio not found")
    settings_obj = _project_settings(pid, (body or {}).get("settings", {}))
    jobs.enqueue(pid, src, settings_obj)
    return {"project_id": pid, "reprocessing": True}


@app.post("/api/projects/{pid}/reprocess-range")
def reprocess_range(pid: str, body: dict = {}):
    """Re-ASR only ``[start, end]`` and splice the result into the transcript.

    Tokens outside the window are preserved (manual edits survive). Overlapping
    tokens inside the window are replaced. Optional body fields:
    ``start``, ``end``, ``settings``, ``speaker`` (force label).
    """
    from .pipeline.asr import ASRCancelled
    from .pipeline.partial import reprocess_range as _reprocess_range

    tr = jobs.load_transcript(pid)
    if tr is None:
        raise HTTPException(404, "transcript not ready")
    d = jobs.project_dir(pid)
    audio = d / "audio.wav"
    if not audio.exists():
        raise HTTPException(400, "normalized audio missing; re-run the full job once")
    try:
        start = float((body or {}).get("start", 0))
        end = float((body or {}).get("end", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "start/end must be numbers")
    if end - start < 0.05:
        raise HTTPException(400, "select at least 50 ms on the waveform")
    if end - start > 120:
        raise HTTPException(400, "selection too long (max 120 s); re-run full file instead")
    settings_obj = _project_settings(pid, (body or {}).get("settings", {}))
    speaker = (body or {}).get("speaker")
    jobs.clear_cancel(pid)
    try:
        result = _reprocess_range(
            pid, audio, tr, start, end, settings_obj,
            speaker=speaker if isinstance(speaker, str) else None,
            cancel_check=lambda: jobs.is_cancelled(pid),
        )
    except (ASRCancelled, jobs.JobCancelled):
        raise HTTPException(status_code=409, detail="Transcription aborted")
    except Exception as e:
        if jobs.is_cancelled(pid):
            raise HTTPException(status_code=409, detail="Transcription aborted")
        raise HTTPException(500, f"range reprocess failed: {e}")
    jobs.save_transcript(pid, result["transcript"])
    return {
        "ok": True,
        "start": result["start"],
        "end": result["end"],
        "removed": result["removed"],
        "added": result["added"],
        "speaker": result["speaker"],
        "transcript": result["transcript"].model_dump(),
    }


@app.post("/api/projects/{pid}/openai-refine")
def openai_refine(pid: str, body: dict = {}):
    tr = jobs.load_transcript(pid)
    if tr is None:
        raise HTTPException(404, "transcript not ready")
    settings = _project_settings(pid, (body or {}).get("settings", {}))
    result = refine_transcript(tr.jefferson, settings)
    return result


@app.get("/api/projects/{pid}/audio")
def get_audio(pid: str):
    src = _source_file(pid)
    if not src or not src.exists():
        raise HTTPException(404, "audio not found")
    return FileResponse(str(src))


# ---------------------------------------------------------------------------
# Collections: labeled groups of cut clips (elements) under a project
# ---------------------------------------------------------------------------
@app.get("/api/projects/{pid}/collections")
def api_list_collections(pid: str):
    if not jobs.project_dir(pid).exists():
        raise HTTPException(404, "project not found")
    from . import collections as coll
    return {"collections": coll.list_collections(pid)}


@app.post("/api/projects/{pid}/collections")
def api_create_collection(pid: str, body: dict = {}):
    if not jobs.project_dir(pid).exists():
        raise HTTPException(404, "project not found")
    from . import collections as coll
    return coll.create_collection(pid, (body or {}).get("label", ""))


@app.get("/api/projects/{pid}/collections/{cid}")
def api_get_collection(pid: str, cid: str):
    from . import collections as coll
    meta = coll.load_collection(pid, cid)
    if not meta:
        raise HTTPException(404, "collection not found")
    return meta


@app.patch("/api/projects/{pid}/collections/{cid}")
def api_rename_collection(pid: str, cid: str, body: dict = {}):
    from . import collections as coll
    try:
        return coll.rename_collection(pid, cid, (body or {}).get("label", ""))
    except FileNotFoundError:
        raise HTTPException(404, "collection not found")


@app.delete("/api/projects/{pid}/collections/{cid}")
def api_delete_collection(pid: str, cid: str):
    from . import collections as coll
    coll.delete_collection(pid, cid)
    return {"ok": True}


@app.post("/api/projects/{pid}/collections/{cid}/elements")
def api_add_element(pid: str, cid: str, body: dict = {}):
    """Cut the waveform selection into a new collection element."""
    from . import collections as coll
    try:
        start = float((body or {}).get("start", 0))
        end = float((body or {}).get("end", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "start/end must be numbers")
    label = (body or {}).get("label")
    try:
        return coll.add_element(pid, cid, start, end, label=label)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"add element failed: {e}")


@app.get("/api/projects/{pid}/collections/{cid}/elements/{eid}")
def api_get_element(pid: str, cid: str, eid: str):
    from . import collections as coll
    meta = coll.load_element(pid, cid, eid)
    if not meta:
        raise HTTPException(404, "element not found")
    tr = coll.load_element_transcript(pid, cid, eid)
    return {
        "meta": meta,
        "transcript": tr.model_dump() if tr else None,
    }


@app.get("/api/projects/{pid}/collections/{cid}/elements/{eid}/audio")
def api_element_audio(pid: str, cid: str, eid: str):
    from . import collections as coll
    p = coll.element_audio_path(pid, cid, eid, "wav")
    if not p:
        raise HTTPException(404, "element audio not found")
    return FileResponse(str(p), filename=f"{eid}.wav", media_type="audio/wav")


@app.get("/api/projects/{pid}/collections/{cid}/elements/{eid}/download")
def api_element_download(pid: str, cid: str, eid: str, fmt: str = "mp3"):
    from . import collections as coll
    fmt = (fmt or "mp3").lower()
    if fmt not in ("mp3", "wav"):
        raise HTTPException(400, "fmt must be mp3 or wav")
    p = coll.element_audio_path(pid, cid, eid, fmt)
    if not p:
        raise HTTPException(404, "download file not found")
    media = "audio/mpeg" if fmt == "mp3" else "audio/wav"
    label = (coll.load_element(pid, cid, eid) or {}).get("label") or eid
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in label)[:60].strip() or eid
    return FileResponse(str(p), filename=f"{safe}.{fmt}", media_type=media)


@app.delete("/api/projects/{pid}/collections/{cid}/elements/{eid}")
def api_delete_element(pid: str, cid: str, eid: str):
    from . import collections as coll
    coll.delete_element(pid, cid, eid)
    return {"ok": True}


@app.post("/api/projects/{pid}/collections/{cid}/elements/{eid}/reprocess")
def api_reprocess_element(pid: str, cid: str, eid: str, body: dict = {}):
    """Re-ASR a collection element from its own cut audio (does not change parent)."""
    from . import collections as coll
    settings_obj = _project_settings(pid, (body or {}).get("settings", {}))
    speaker = (body or {}).get("speaker")
    try:
        result = coll.reprocess_element(
            pid, cid, eid, settings_obj,
            speaker=speaker if isinstance(speaker, str) else None,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"element reprocess failed: {e}")
    return {
        "ok": True,
        "meta": result["meta"],
        "added": result["added"],
        "transcript": result["transcript"].model_dump(),
    }


@app.post("/api/projects/{pid}/collections/{cid}/reprocess-all")
def api_reprocess_collection(pid: str, cid: str, body: dict = {}):
    """Re-ASR every element in a collection."""
    from . import collections as coll
    settings_obj = _project_settings(pid, (body or {}).get("settings", {}))
    speaker = (body or {}).get("speaker")
    try:
        return coll.reprocess_collection_elements(
            pid, cid, settings_obj,
            speaker=speaker if isinstance(speaker, str) else None,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"collection reprocess failed: {e}")


@app.post("/api/projects/{pid}/collections/{cid}/presentation")
def api_collection_presentation(pid: str, cid: str, body: dict = {}):
    """Export all collection clips, in order, as one PowerPoint deck."""
    from .presentation.collection_builder import build_collection_project

    try:
        opts = ExportOptions(**(body or {})).model_copy(update={"formats": ["pptx"]})
    except Exception as e:
        raise HTTPException(400, f"bad options: {e}")

    out = jobs.project_dir(pid) / "collection_presentations" / cid
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    try:
        project = build_collection_project(pid, cid, out, opts)
        paths = generate(project, out)
        pptx = next((p for p in paths if p.suffix.lower() == ".pptx"), None)
        if pptx is None:
            raise RuntimeError("PowerPoint exporter produced no file")
        final = out / "collection.pptx"
        if pptx != final:
            pptx.replace(final)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"collection presentation failed: {e}")

    return {
        "ok": True,
        "filename": final.name,
        "slides": len(project.slides),
        "clips": project.meta.get("clip_count", 0),
        "url": f"/api/projects/{pid}/collections/{cid}/presentation/{final.name}",
    }


@app.get("/api/projects/{pid}/collections/{cid}/presentation/{filename}")
def api_collection_presentation_file(pid: str, cid: str, filename: str):
    out = (jobs.project_dir(pid) / "collection_presentations" / cid).resolve()
    path = (out / filename).resolve()
    if path.parent != out or not path.exists() or path.suffix.lower() != ".pptx":
        raise HTTPException(404, "collection presentation not found")
    return FileResponse(
        str(path),
        filename="collection.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.put("/api/projects/{pid}/collections/{cid}/elements/{eid}/transcript")
def api_save_element_transcript(pid: str, cid: str, eid: str, body: dict = {}):
    """Save manual edits to an element's transcript (clip only)."""
    from . import collections as coll
    from .models import Transcript
    try:
        tr = Transcript.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"invalid transcript: {e}")
    try:
        saved = coll.save_element_transcript(pid, cid, eid, tr)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"save element failed: {e}")
    return {"ok": True, "transcript": saved.model_dump()}


@app.post("/api/projects/{pid}/collections/{cid}/elements/{eid}/insert")
def api_insert_element(pid: str, cid: str, eid: str):
    """Insert the element's (corrected) transcript back into the parent at its timestamps."""
    from . import collections as coll
    try:
        result = coll.insert_element_into_parent(pid, cid, eid)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"insert failed: {e}")
    return {
        "ok": True,
        "start": result["start"],
        "end": result["end"],
        "removed": result["removed"],
        "inserted": result["inserted"],
        "transcript": result["transcript"].model_dump(),
    }


@app.post("/api/projects/{pid}/export-clip")
def api_export_clip(pid: str, body: dict = {}):
    """Cut the selection and return a downloadable clip (not added to a collection)."""
    from . import collections as coll
    try:
        start = float((body or {}).get("start", 0))
        end = float((body or {}).get("end", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "start/end must be numbers")
    fmt = ((body or {}).get("fmt") or "mp3").lower()
    if end - start < 0.05:
        raise HTTPException(400, "selection too short")
    try:
        p = coll.export_clip(pid, start, end, fmt=fmt)
    except Exception as e:
        raise HTTPException(500, f"export clip failed: {e}")
    media = "audio/mpeg" if p.suffix == ".mp3" else "audio/wav"
    return FileResponse(
        str(p),
        filename=p.name,
        media_type=media,
    )


@app.get("/api/projects/{pid}/export/{fmt}")
def export(pid: str, fmt: str, size: int = 20):
    tr = jobs.load_transcript(pid)
    if tr is None:
        raise HTTPException(404, "transcript not ready")
    d = jobs.project_dir(pid)
    if fmt == "txt":
        p = export_txt(tr, d / "transcript.txt")
        return FileResponse(str(p), filename="transcript.txt", media_type="text/plain")
    if fmt == "docx":
        if tr.layout != "japanese_four_line":
            raise HTTPException(400, "DOCX four-line export requires Japanese layout")
        p = export_japanese_docx(tr, d / "transcript_japanese.docx")
        return FileResponse(
            str(p),
            filename="transcript_japanese.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    if fmt == "vba":
        p = export_vba(tr, d / "transcript_vba.txt")
        return FileResponse(str(p), filename="transcript_vba.txt", media_type="text/plain")
    if fmt == "slides":
        fs = min(60, max(8, int(size)))
        p = build_transcript_pptx(tr, d / "transcript_slides.pptx", font_size=fs)
        return FileResponse(
            str(p), filename="transcript_slides.pptx",
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    if fmt == "json":
        return FileResponse(str(d / "transcript.json"), filename="transcript.json",
                            media_type="application/json")
    if fmt == "midi":
        p = export_midi(tr, d / "pitch.mid")
        return FileResponse(str(p), filename="pitch.mid", media_type="audio/midi")
    if fmt == "textgrid":
        p = export_textgrid(tr, d / "transcript.TextGrid")
        return FileResponse(str(p), filename="transcript.TextGrid", media_type="text/plain")
    if fmt == "eaf":
        p = export_eaf(tr, d / "transcript.eaf")
        return FileResponse(str(p), filename="transcript.eaf", media_type="application/xml")
    if fmt in ("mp4", "pptx"):
        from .pipeline.karaoke import render_karaoke_mp4, build_pptx
        audio = d / "audio.wav"
        if not audio.exists():
            raise HTTPException(400, "normalized audio missing; re-run the job")
        mp4 = d / "karaoke.mp4"
        tr_json = d / "transcript.json"
        stale = (not mp4.exists()) or (mp4.stat().st_mtime < tr_json.stat().st_mtime)
        if stale:
            render_karaoke_mp4(tr, audio, mp4)
        if fmt == "mp4":
            return FileResponse(str(mp4), filename="karaoke.mp4", media_type="video/mp4")
        pptx = d / "karaoke.pptx"
        build_pptx(mp4, pptx)
        return FileResponse(
            str(pptx), filename="karaoke.pptx",
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    raise HTTPException(400, f"unknown format: {fmt}")


# ---------------------------------------------------------------------------
# Presentation generator (sub-app): audio + transcript + timings -> slide decks
# ---------------------------------------------------------------------------
@app.get("/api/presentation/formats")
def presentation_formats():
    return {"formats": available_formats()}


@app.post("/api/projects/{pid}/presentation")
def make_presentation(pid: str, body: dict = {}):
    tr = jobs.load_transcript(pid)
    if tr is None:
        raise HTTPException(404, "transcript not ready")
    try:
        opts = ExportOptions(**(body or {}))
    except Exception as e:
        raise HTTPException(400, f"bad options: {e}")
    src = _source_file(pid)
    d = jobs.project_dir(pid)
    out = d / "presentation"
    shutil.rmtree(out, ignore_errors=True)
    project = build_project(tr, str(src) if src else None, opts)
    try:
        paths = generate(project, out)
    except Exception as e:
        raise HTTPException(500, f"generation failed: {e}")
    zip_path = bundle(paths, out / "presentation_bundle.zip")
    return {
        "ok": True,
        "slides": len(project.slides),
        "words": len(project.word_timings),
        "files": [p.name for p in paths],
        "bundle": zip_path.name,
        "base_url": f"/api/projects/{pid}/presentation/",
    }


@app.get("/api/projects/{pid}/presentation/{filename}")
def get_presentation_file(pid: str, filename: str):
    d = (jobs.project_dir(pid) / "presentation").resolve()
    p = (d / filename).resolve()
    if not str(p).startswith(str(d)) or not p.exists():
        raise HTTPException(404, "presentation file not found")
    return FileResponse(str(p), filename=filename)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    d = jobs.project_dir(pid)
    if d.exists():
        shutil.rmtree(d)
    return {"ok": True}


def _pretty_model(dirname: str) -> str:
    # "models--Systran--faster-whisper-small" -> "Systran/faster-whisper-small"
    if dirname.startswith("models--"):
        return dirname[len("models--"):].replace("--", "/")
    return dirname


@app.get("/api/models")
def list_models():
    """Cached ASR/diarization model snapshots on disk (HuggingFace hub layout)."""
    out = []
    if MODEL_CACHE_DIR.exists():
        for p in MODEL_CACHE_DIR.rglob("models--*"):
            if p.is_dir() and ".locks" not in p.parts:
                out.append({
                    "id": str(p.relative_to(MODEL_CACHE_DIR)),
                    "name": _pretty_model(p.name),
                    "size_mb": round(_dir_size(p) / 1_000_000, 1),
                })
    out.sort(key=lambda m: -m["size_mb"])
    total = round(sum(m["size_mb"] for m in out), 1)
    return {"models": out, "total_mb": total}


@app.delete("/api/models")
def delete_model(id: str):
    """Delete one cached model directory (it re-downloads if used again)."""
    root = MODEL_CACHE_DIR.resolve()
    target = (MODEL_CACHE_DIR / id).resolve()
    if root not in target.parents or "models--" not in target.name:
        raise HTTPException(400, "invalid model id")
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "model not found")
    shutil.rmtree(target)
    # drop the matching lock dir too, if present
    lock = target.parent / ".locks" / target.name
    if lock.exists():
        shutil.rmtree(lock, ignore_errors=True)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time()}


# ---------------------------------------------------------------------------
# Frontend (built SPA). Mounted last so /api/* wins.
# ---------------------------------------------------------------------------
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/")
    def no_frontend():
        return JSONResponse(
            {"message": "Frontend not built yet. Run `npm install && npm run build` in frontend/, "
                        "or use the Vite dev server on :5173."},
            status_code=200,
        )
