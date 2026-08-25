"""Collections + elements: labeled groups of cut clips under a parent project.

Layout on disk::

    data/projects/{pid}/collections/
      index.json
      {cid}/
        meta.json
        elements/
          {eid}/
            meta.json
            audio.wav      # clipped PCM (playback)
            audio.mp3      # downloadable
            transcript.json

Each element is a self-contained mini-transcript with times remapped so the
clip starts at 0.0 s.
"""
from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import jobs
from .models import DocumentMeta, Speaker, Token, Transcript, Turn
from .pipeline.ca import regroup_turns, render_jefferson
from .config import DEFAULT_SETTINGS, Settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collections_root(pid: str) -> Path:
    d = jobs.project_dir(pid) / "collections"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(pid: str) -> Path:
    return collections_root(pid) / "index.json"


def _load_index(pid: str) -> list[dict]:
    p = _index_path(pid)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_index(pid: str, items: list[dict]) -> None:
    _index_path(pid).write_text(json.dumps(items, indent=2), encoding="utf-8")


def _coll_dir(pid: str, cid: str) -> Path:
    return collections_root(pid) / cid


def _elem_dir(pid: str, cid: str, eid: str) -> Path:
    return _coll_dir(pid, cid) / "elements" / eid


def list_collections(pid: str) -> list[dict]:
    items = _load_index(pid)
    out = []
    for it in items:
        cid = it["id"]
        meta = load_collection(pid, cid) or it
        els = meta.get("elements") or []
        out.append({
            "id": cid,
            "label": meta.get("label") or it.get("label") or cid,
            "created_at": meta.get("created_at") or it.get("created_at", ""),
            "element_count": len(els),
        })
    return out


def create_collection(pid: str, label: str) -> dict:
    label = (label or "").strip() or "Untitled collection"
    cid = uuid.uuid4().hex[:10]
    d = _coll_dir(pid, cid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "elements").mkdir(exist_ok=True)
    meta = {
        "id": cid,
        "label": label,
        "created_at": _now(),
        "elements": [],
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    idx = _load_index(pid)
    idx.insert(0, {"id": cid, "label": label, "created_at": meta["created_at"]})
    _save_index(pid, idx)
    return meta


def load_collection(pid: str, cid: str) -> dict | None:
    p = _coll_dir(pid, cid) / "meta.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_collection(pid: str, cid: str, meta: dict) -> None:
    d = _coll_dir(pid, cid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # keep index label in sync
    idx = _load_index(pid)
    for it in idx:
        if it["id"] == cid:
            it["label"] = meta.get("label", it.get("label"))
            break
    _save_index(pid, idx)


def rename_collection(pid: str, cid: str, label: str) -> dict:
    meta = load_collection(pid, cid)
    if not meta:
        raise FileNotFoundError("collection not found")
    meta["label"] = (label or "").strip() or meta["label"]
    save_collection(pid, cid, meta)
    return meta


def delete_collection(pid: str, cid: str) -> None:
    import shutil
    d = _coll_dir(pid, cid)
    if d.exists():
        shutil.rmtree(d)
    idx = [it for it in _load_index(pid) if it["id"] != cid]
    _save_index(pid, idx)


def _clip_audio(src: Path, dst_wav: Path, start: float, end: float,
                dst_mp3: Path | None = None) -> float:
    dur = max(0.05, end - start)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
         "-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst_wav)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg clip failed:\n{proc.stderr[-2000:]}")
    if dst_mp3 is not None:
        proc2 = subprocess.run(
            ["ffmpeg", "-y", "-i", str(dst_wav), "-codec:a", "libmp3lame", "-qscale:a", "2",
             str(dst_mp3)],
            capture_output=True, text=True,
        )
        if proc2.returncode != 0:
            proc3 = subprocess.run(
                ["ffmpeg", "-y", "-i", str(dst_wav), str(dst_mp3)],
                capture_output=True, text=True,
            )
            if proc3.returncode != 0:
                # WAV-only is fine; download can fall back to wav
                try:
                    dst_mp3.unlink(missing_ok=True)
                except Exception:
                    pass
    return dur


def _slice_transcript(tr: Transcript, start: float, end: float,
                      element_id: str, label: str) -> Transcript:
    """Keep tokens overlapping [start, end], remap times so clip starts at 0."""
    kept: list[Token] = []
    for turn in tr.turns:
        if not turn.speaker:
            continue
        for tok in turn.tokens:
            mid = (tok.start + tok.end) / 2
            if mid < start or mid > end:
                # also keep if substantially overlapping
                if tok.end <= start or tok.start >= end:
                    continue
            ns = max(0.0, tok.start - start)
            ne = max(ns + 0.02, min(end - start, tok.end - start))
            kept.append(Token(
                id=tok.id if tok.id else f"e{uuid.uuid4().hex[:8]}",
                text=tok.text,
                start=round(ns, 3),
                end=round(ne, 3),
                speaker=tok.speaker,
                phonemes=[],
                cues=list(tok.cues or []),
                pre_pause=None,
            ))

    duration = round(max(0.05, end - start), 3)
    th = DEFAULT_SETTINGS.thresholds
    if kept:
        turns = regroup_turns(kept, th)
    else:
        turns = []
    labels = sorted({t.speaker for t in turns if t.speaker})
    existing = {s.id: s for s in tr.speakers}
    speakers = [existing.get(l) or Speaker(id=l, label=l) for l in labels]

    # Remap pitch/intensity into the window (copy — don't mutate parent)
    from .models import PitchPoint
    pitch = [
        PitchPoint(t=round(p.t - start, 3), f0=p.f0)
        for p in (tr.pitch or []) if start <= p.t <= end
    ]
    intensity = [
        PitchPoint(t=round(p.t - start, 3), f0=p.f0)
        for p in (tr.intensity or []) if start <= p.t <= end
    ]

    out = Transcript(
        meta=DocumentMeta(
            project_id=element_id,
            filename=label,
            duration=duration,
            sample_rate=tr.meta.sample_rate if tr.meta else 16000,
            created_at=_now(),
            models=dict(tr.meta.models) if tr.meta else {},
            warnings=[f"Sliced from parent [{start:.3f}, {end:.3f}]"],
        ),
        speakers=speakers,
        turns=turns,
        pitch=pitch,
        intensity=intensity,
        overrides={},
        jefferson="",
        layout=tr.layout,
    )
    if out.layout == "japanese_four_line":
        from .pipeline.japanese import reattach_japanese_layers

        reattach_japanese_layers(tr.turns, out.turns)
    out.jefferson = render_jefferson(out) if turns else ""
    return out


def add_element(
    pid: str,
    cid: str,
    start: float,
    end: float,
    label: str | None = None,
    audio_src: Path | None = None,
) -> dict:
    meta = load_collection(pid, cid)
    if not meta:
        raise FileNotFoundError("collection not found")
    if end - start < 0.05:
        raise ValueError("selection too short (min 50 ms)")

    tr = jobs.load_transcript(pid)
    if tr is None:
        raise FileNotFoundError("parent transcript not ready")

    pdir = jobs.project_dir(pid)
    src = audio_src or (pdir / "audio.wav")
    if not src.exists():
        # fall back to original upload
        matches = list(pdir.glob("source.*"))
        if not matches:
            raise FileNotFoundError("no audio to clip")
        src = matches[0]

    eid = uuid.uuid4().hex[:10]
    label = (label or "").strip() or f"Clip {start:.2f}–{end:.2f}s"
    ed = _elem_dir(pid, cid, eid)
    ed.mkdir(parents=True, exist_ok=True)

    wav = ed / "audio.wav"
    mp3 = ed / "audio.mp3"
    duration = _clip_audio(src, wav, start, end, dst_mp3=mp3)

    sliced = _slice_transcript(tr, start, end, eid, label)
    (ed / "transcript.json").write_text(
        sliced.model_dump_json(indent=2), encoding="utf-8")

    elem_meta = {
        "id": eid,
        "label": label,
        "start": round(float(start), 3),
        "end": round(float(end), 3),
        "duration": round(duration, 3),
        "created_at": _now(),
        "parent_project_id": pid,
        "collection_id": cid,
        "has_mp3": mp3.exists(),
        "word_count": sum(len(t.tokens) for t in sliced.turns if t.speaker),
    }
    (ed / "meta.json").write_text(json.dumps(elem_meta, indent=2), encoding="utf-8")

    meta.setdefault("elements", []).append({
        "id": eid,
        "label": label,
        "start": elem_meta["start"],
        "end": elem_meta["end"],
        "duration": elem_meta["duration"],
        "created_at": elem_meta["created_at"],
        "word_count": elem_meta["word_count"],
    })
    save_collection(pid, cid, meta)
    return elem_meta


def load_element(pid: str, cid: str, eid: str) -> dict | None:
    p = _elem_dir(pid, cid, eid) / "meta.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_element_transcript(pid: str, cid: str, eid: str) -> Transcript | None:
    p = _elem_dir(pid, cid, eid) / "transcript.json"
    if not p.exists():
        return None
    return Transcript.model_validate_json(p.read_text(encoding="utf-8"))


def _update_element_word_count(pid: str, cid: str, eid: str, word_count: int) -> dict:
    meta = load_element(pid, cid, eid)
    if not meta:
        raise FileNotFoundError("element not found")
    meta["word_count"] = word_count
    meta["reprocessed_at"] = _now()
    ed = _elem_dir(pid, cid, eid)
    (ed / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    coll = load_collection(pid, cid)
    if coll:
        for e in coll.get("elements") or []:
            if e.get("id") == eid:
                e["word_count"] = word_count
                e["reprocessed_at"] = meta["reprocessed_at"]
                break
        save_collection(pid, cid, coll)
    return meta


def reprocess_element(
    pid: str,
    cid: str,
    eid: str,
    settings: Settings,
    speaker: str | None = None,
) -> dict:
    """Re-ASR this element's own WAV and replace its transcript.

    Does not touch the parent project transcript. Uses a light CA pass (no
    prosody) so short clips don't get bogus elongations from duration alone.
    """
    from .pipeline.asr import transcribe

    meta = load_element(pid, cid, eid)
    if not meta:
        raise FileNotFoundError("element not found")
    wav = element_audio_path(pid, cid, eid, "wav")
    if not wav or not wav.exists():
        raise FileNotFoundError("element audio missing")

    old = load_element_transcript(pid, cid, eid)
    if (
        (old and old.layout == "japanese_four_line")
        or getattr(settings, "transcript_layout", "standard") == "japanese_four_line"
    ):
        settings.language = "ja"
        settings.transcript_layout = "japanese_four_line"
        if (
            settings.whisper_model == "nyrahealth/faster_CrisperWhisper"
            or "kotoba-whisper" in settings.whisper_model.lower()
        ):
            settings.whisper_model = "large-v3"
        settings.thresholds.enable_elongation = False

    # Prefer a clean model for short clips; caller can still override.
    asr = transcribe(str(wav), settings)

    # Speaker: explicit > existing transcript majority > A
    if speaker and str(speaker).strip():
        spk = str(speaker).strip()
    elif old and old.speakers:
        spk = old.speakers[0].id
    else:
        spk = "A"

    tokens: list[Token] = []
    for w in asr.words:
        txt = (w.text or "").strip()
        if not txt:
            continue
        # Strip ASR edge punctuation; CA owns terminals.
        clean = txt.strip(".,!?;:\"'“”‘’")
        if not clean:
            clean = txt
        tokens.append(Token(
            id=f"e{uuid.uuid4().hex[:8]}",
            text=clean,
            start=round(float(w.start), 3),
            end=round(max(float(w.start) + 0.04, float(w.end)), 3),
            speaker=spk,
            phonemes=[],
            cues=[],
            pre_pause=None,
        ))

    th = settings.thresholds
    turns = regroup_turns(tokens, th) if tokens else []
    duration = float(meta.get("duration") or (tokens[-1].end if tokens else 0.0))
    label = meta.get("label") or eid

    tr = Transcript(
        meta=DocumentMeta(
            project_id=eid,
            filename=label,
            duration=duration,
            sample_rate=16000,
            created_at=_now(),
            models={
                "asr": asr.model_name,
                "language": asr.language,
                "reprocessed": True,
            },
            warnings=["Re-ASR'd from element audio (not sliced from parent)"],
        ),
        speakers=[Speaker(id=spk, label=spk)],
        turns=turns,
        pitch=[],
        intensity=[],
        overrides={},
        jefferson="",
        layout=(
            "japanese_four_line"
            if getattr(settings, "transcript_layout", "standard") == "japanese_four_line"
            else "standard"
        ),
    )
    tr.jefferson = render_jefferson(tr) if turns else ""
    if tr.layout == "japanese_four_line":
        from .pipeline.japanese import populate_japanese_layers

        populate_japanese_layers(tr, settings)

    ed = _elem_dir(pid, cid, eid)
    (ed / "transcript.json").write_text(tr.model_dump_json(indent=2), encoding="utf-8")
    word_count = sum(len(t.tokens) for t in turns if t.speaker)
    meta = _update_element_word_count(pid, cid, eid, word_count)

    return {
        "ok": True,
        "meta": meta,
        "added": word_count,
        "transcript": tr,
    }


def reprocess_collection_elements(
    pid: str,
    cid: str,
    settings: Settings,
    speaker: str | None = None,
) -> dict:
    """Re-ASR every element in a collection. Returns per-element results."""
    coll = load_collection(pid, cid)
    if not coll:
        raise FileNotFoundError("collection not found")
    results = []
    for e in coll.get("elements") or []:
        eid = e["id"]
        try:
            r = reprocess_element(pid, cid, eid, settings, speaker=speaker)
            results.append({
                "id": eid,
                "ok": True,
                "added": r["added"],
                "label": r["meta"].get("label"),
            })
        except Exception as ex:
            results.append({"id": eid, "ok": False, "error": str(ex)})
    return {"ok": True, "results": results}


def save_element_transcript(pid: str, cid: str, eid: str, tr: Transcript) -> Transcript:
    """Persist edits to an element's own transcript (does not touch parent)."""
    meta = load_element(pid, cid, eid)
    if not meta:
        raise FileNotFoundError("element not found")
    # Flatten + regroup so pauses stay consistent after edits
    old_turns = tr.turns
    flat = [tok for turn in old_turns if turn.speaker for tok in turn.tokens]
    tr.turns = regroup_turns(flat, DEFAULT_SETTINGS.thresholds)
    if tr.layout == "japanese_four_line":
        from .pipeline.japanese import reattach_japanese_layers

        reattach_japanese_layers(old_turns, tr.turns)
    labels = sorted({t.speaker for t in tr.turns if t.speaker})
    existing = {s.id: s for s in tr.speakers}
    tr.speakers = [existing.get(l) or Speaker(id=l, label=l) for l in labels]
    tr.jefferson = render_jefferson(tr)
    ed = _elem_dir(pid, cid, eid)
    (ed / "transcript.json").write_text(tr.model_dump_json(indent=2), encoding="utf-8")
    word_count = sum(len(t.tokens) for t in tr.turns if t.speaker)
    _update_element_word_count(pid, cid, eid, word_count)
    return tr


def insert_element_into_parent(pid: str, cid: str, eid: str) -> dict:
    """Replace parent tokens in the element's time window with the element's tokens.

    Element times are 0-based on the clip; they are shifted by ``meta.start``
    before splicing into the parent transcript.
    """
    meta = load_element(pid, cid, eid)
    if not meta:
        raise FileNotFoundError("element not found")
    elem_tr = load_element_transcript(pid, cid, eid)
    if elem_tr is None:
        raise FileNotFoundError("element transcript missing")
    parent = jobs.load_transcript(pid)
    if parent is None:
        raise FileNotFoundError("parent transcript not ready")

    start = float(meta["start"])
    end = float(meta["end"])
    if end <= start:
        raise ValueError("element has invalid start/end")

    # Tokens from the element, shifted into parent time
    incoming: list[Token] = []
    for turn in elem_tr.turns:
        if not turn.speaker:
            continue
        for tok in turn.tokens:
            ns = round(start + float(tok.start), 3)
            ne = round(start + float(tok.end), 3)
            # Clamp into the element's declared window
            ns = max(start, min(end - 0.02, ns))
            ne = max(ns + 0.02, min(end, ne))
            incoming.append(Token(
                id=f"i{uuid.uuid4().hex[:8]}",
                text=tok.text,
                start=ns,
                end=ne,
                speaker=tok.speaker or "A",
                phonemes=[],
                cues=list(tok.cues or []),
                pre_pause=None,
            ))

    # Keep parent tokens outside the window
    kept: list[Token] = []
    removed = 0
    for turn in parent.turns:
        if not turn.speaker:
            continue
        for tok in turn.tokens:
            if tok.end <= start or tok.start >= end:
                kept.append(tok)
            else:
                removed += 1

    old_parent_turns = parent.turns
    merged = kept + incoming
    parent.turns = regroup_turns(merged, DEFAULT_SETTINGS.thresholds)
    if parent.layout == "japanese_four_line":
        from .pipeline.japanese import reattach_japanese_layers

        reattach_japanese_layers(old_parent_turns, parent.turns)
    labels = sorted({t.speaker for t in parent.turns if t.speaker})
    existing = {s.id: s for s in parent.speakers}
    parent.speakers = [existing.get(l) or Speaker(id=l, label=l) for l in labels]
    parent.jefferson = render_jefferson(parent)
    jobs.save_transcript(pid, parent)

    return {
        "ok": True,
        "start": start,
        "end": end,
        "removed": removed,
        "inserted": len(incoming),
        "transcript": parent,
    }


def element_audio_path(pid: str, cid: str, eid: str, fmt: str = "wav") -> Path | None:
    ed = _elem_dir(pid, cid, eid)
    if fmt == "mp3":
        p = ed / "audio.mp3"
        if p.exists():
            return p
        # fall back to wav if mp3 encode wasn't available
        p = ed / "audio.wav"
        return p if p.exists() else None
    p = ed / "audio.wav"
    return p if p.exists() else None


def delete_element(pid: str, cid: str, eid: str) -> None:
    import shutil
    ed = _elem_dir(pid, cid, eid)
    if ed.exists():
        shutil.rmtree(ed)
    meta = load_collection(pid, cid)
    if meta:
        meta["elements"] = [e for e in meta.get("elements", []) if e.get("id") != eid]
        save_collection(pid, cid, meta)


def export_clip(pid: str, start: float, end: float, fmt: str = "mp3") -> Path:
    """One-off clip export into the project's exports folder; returns the path."""
    pdir = jobs.project_dir(pid)
    src = pdir / "audio.wav"
    if not src.exists():
        matches = list(pdir.glob("source.*"))
        if not matches:
            raise FileNotFoundError("no audio")
        src = matches[0]
    out_dir = pdir / "clips"
    out_dir.mkdir(exist_ok=True)
    stamp = f"{start:.3f}_{end:.3f}".replace(".", "p")
    wav = out_dir / f"clip_{stamp}.wav"
    mp3 = out_dir / f"clip_{stamp}.mp3"
    _clip_audio(src, wav, start, end, dst_mp3=mp3 if fmt == "mp3" else None)
    if fmt == "mp3" and mp3.exists():
        return mp3
    return wav
