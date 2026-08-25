"""Folder-to-folder batch transcription for the Simple mode."""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from . import jobs
from .config import Settings, DATA_DIR
from .exports import export_japanese_docx, export_txt

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".mp4", ".mkv"}

_BATCHES: dict[str, "BatchJob"] = {}
_lock = threading.Lock()
# Share the same single-worker pool as transcription so batches queue behind jobs
# (jobs._executor is private; we keep a dedicated sequential batch pool).
_batch_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="turnwise-batch")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BatchItem:
    filename: str
    path: str
    state: str = "queued"  # queued | running | done | error | cancelled | skipped
    message: str = ""
    project_id: str | None = None
    outputs: list[str] = field(default_factory=list)


@dataclass
class BatchJob:
    batch_id: str
    input_dir: str
    output_dir: str
    state: str = "queued"  # queued | running | done | error | cancelled
    message: str = ""
    created_at: str = ""
    formats: list[str] = field(default_factory=lambda: ["txt"])
    items: list[BatchItem] = field(default_factory=list)
    current: int = 0
    cancel: bool = False

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "state": self.state,
            "message": self.message,
            "created_at": self.created_at,
            "formats": list(self.formats),
            "current": self.current,
            "total": len(self.items),
            "done": sum(1 for i in self.items if i.state == "done"),
            "failed": sum(1 for i in self.items if i.state == "error"),
            "items": [asdict(i) for i in self.items],
        }


def list_audio_files(input_dir: Path, recursive: bool = False) -> list[Path]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input folder not found: {input_dir}")
    files: list[Path] = []
    iterator = input_dir.rglob("*") if recursive else input_dir.iterdir()
    for p in iterator:
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            files.append(p)
    return sorted(files, key=lambda p: str(p).lower())


def get_batch(batch_id: str) -> BatchJob | None:
    with _lock:
        return _BATCHES.get(batch_id)


def cancel_batch(batch_id: str) -> BatchJob | None:
    with _lock:
        job = _BATCHES.get(batch_id)
        if not job:
            return None
        job.cancel = True
        if job.state in ("queued", "running"):
            job.state = "cancelled"
            job.message = "Cancelling…"
        if job.current < len(job.items):
            item = job.items[job.current]
            if item.project_id:
                jobs.request_cancel(item.project_id)
        return job


def start_batch(
    input_dir: str,
    output_dir: str,
    settings: Settings,
    formats: list[str] | None = None,
    recursive: bool = False,
) -> BatchJob:
    inp = Path(input_dir).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    if not inp.is_dir():
        raise FileNotFoundError(f"input folder not found: {inp}")
    out.mkdir(parents=True, exist_ok=True)
    files = list_audio_files(inp, recursive=recursive)
    if not files:
        raise ValueError(f"no audio files found in {inp}")

    fmts = [f for f in (formats or ["txt"]) if f in ("txt", "json", "docx")]
    if not fmts:
        fmts = ["txt"]

    batch_id = uuid.uuid4().hex[:12]
    job = BatchJob(
        batch_id=batch_id,
        input_dir=str(inp),
        output_dir=str(out),
        state="queued",
        message=f"Queued {len(files)} file(s)",
        created_at=_now(),
        formats=fmts,
        items=[BatchItem(filename=f.name, path=str(f)) for f in files],
    )
    with _lock:
        _BATCHES[batch_id] = job
    _batch_pool.submit(_run_batch, batch_id, settings)
    return job


def _run_batch(batch_id: str, settings: Settings) -> None:
    job = get_batch(batch_id)
    if not job:
        return
    job.state = "running"
    job.message = "Starting"
    out_root = Path(job.output_dir)

    for idx, item in enumerate(job.items):
        job.current = idx
        if job.cancel:
            item.state = "cancelled"
            item.message = "Cancelled"
            for rest in job.items[idx + 1 :]:
                rest.state = "cancelled"
                rest.message = "Cancelled"
            break

        item.state = "running"
        item.message = "Transcribing…"
        job.message = f"Transcribing {item.filename} ({idx + 1}/{len(job.items)})"

        try:
            pid = uuid.uuid4().hex[:12]
            item.project_id = pid
            pdir = jobs.project_dir(pid)
            src_name = Path(item.path).name
            suffix = Path(src_name).suffix or ".wav"
            dst = pdir / f"source{suffix}"
            shutil.copy2(item.path, dst)
            (pdir / "original_name.txt").write_text(src_name, encoding="utf-8")

            # Run the same pipeline used by interactive uploads, synchronously.
            jobs.clear_cancel(pid)
            jobs._run(pid, dst, settings)

            if job.cancel or jobs.is_cancelled(pid):
                item.state = "cancelled"
                item.message = "Cancelled"
                break

            tr = jobs.load_transcript(pid)
            if tr is None:
                raise RuntimeError("transcript missing after run")

            stem = Path(item.filename).stem
            written: list[str] = []
            if "txt" in job.formats:
                p = export_txt(tr, out_root / f"{stem}.txt")
                written.append(p.name)
            if "json" in job.formats:
                jp = out_root / f"{stem}.json"
                jp.write_text(tr.model_dump_json(indent=2), encoding="utf-8")
                written.append(jp.name)
            if "docx" in job.formats:
                if tr.layout == "japanese_four_line":
                    p = export_japanese_docx(tr, out_root / f"{stem}.docx")
                    written.append(p.name)
                else:
                    # Fall back to plain text export named .txt if not Japanese
                    if "txt" not in job.formats:
                        p = export_txt(tr, out_root / f"{stem}.txt")
                        written.append(p.name)

            # Also drop a small manifest next to the outputs
            meta = {
                "source": item.path,
                "project_id": pid,
                "outputs": written,
                "finished_at": _now(),
            }
            (out_root / f"{stem}.meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )

            item.outputs = written
            item.state = "done"
            item.message = "Done · " + ", ".join(written)
        except jobs.JobCancelled:
            item.state = "cancelled"
            item.message = "Cancelled"
            break
        except Exception as e:
            item.state = "error"
            item.message = str(e)[:400]
            # continue with remaining files

    if job.cancel or any(i.state == "cancelled" for i in job.items):
        job.state = "cancelled"
        job.message = "Batch cancelled"
    elif any(i.state == "error" for i in job.items) and not any(i.state == "done" for i in job.items):
        job.state = "error"
        job.message = "All files failed"
    elif any(i.state == "error" for i in job.items):
        job.state = "done"
        job.message = (
            f"Finished with errors · "
            f"{sum(1 for i in job.items if i.state == 'done')} ok, "
            f"{sum(1 for i in job.items if i.state == 'error')} failed"
        )
    else:
        job.state = "done"
        job.message = f"Finished {sum(1 for i in job.items if i.state == 'done')} file(s)"


def preview_input(input_dir: str, recursive: bool = False) -> dict:
    inp = Path(input_dir).expanduser().resolve()
    files = list_audio_files(inp, recursive=recursive)
    return {
        "input_dir": str(inp),
        "count": len(files),
        "files": [f.name for f in files[:200]],
        "truncated": len(files) > 200,
    }


# Ensure batch state directory exists (for future persistence if needed)
(DATA_DIR / "batches").mkdir(parents=True, exist_ok=True)
