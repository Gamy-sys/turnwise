"""Partial re-ASR of a time range, splicing new words into an existing transcript.

Keeps everything outside [start, end] untouched (manual edits survive). Inside
the window, overlapping tokens are replaced by a fresh Whisper pass on a
ffmpeg-clipped slice of the project's normalized WAV.
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from ..config import Settings
from ..models import Token, Transcript
from .asr import transcribe
from .ca import regroup_turns, render_jefferson


def _clip_wav(src: Path, dst: Path, start: float, end: float, sr: int = 16000) -> None:
    dur = max(0.05, end - start)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
         "-i", str(src), "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg clip failed:\n{proc.stderr[-2000:]}")


def _flat_tokens(tr: Transcript) -> list[Token]:
    out: list[Token] = []
    for turn in tr.turns:
        if not turn.speaker:
            continue
        out.extend(turn.tokens)
    return out


def _majority_speaker(tokens: list[Token], default: str = "A") -> str:
    counts: dict[str, int] = {}
    for t in tokens:
        if t.speaker:
            counts[t.speaker] = counts.get(t.speaker, 0) + 1
    if not counts:
        return default
    return max(counts, key=counts.get)


def reprocess_range(
    project_id: str,
    audio_wav: Path,
    tr: Transcript,
    start: float,
    end: float,
    settings: Settings,
    speaker: str | None = None,
    pad: float = 0.12,
    cancel_check=None,
) -> dict:
    """Re-ASR ``[start, end]`` and splice into ``tr``. Returns a result dict."""
    from .asr import ASRCancelled

    if end <= start:
        raise ValueError("end must be greater than start")
    if not audio_wav.exists():
        raise FileNotFoundError(f"normalized audio missing: {audio_wav}")

    start = max(0.0, float(start))
    end = float(end)
    clip_start = max(0.0, start - pad)
    clip_end = end + pad

    work = audio_wav.parent / f"_clip_{uuid.uuid4().hex[:8]}.wav"
    try:
        _clip_wav(audio_wav, work, clip_start, clip_end)
        if cancel_check and cancel_check():
            raise ASRCancelled("Transcription aborted by user")
        asr = transcribe(str(work), settings, cancel_check=cancel_check)
    finally:
        try:
            work.unlink(missing_ok=True)
        except Exception:
            pass

    existing = _flat_tokens(tr)
    removed = [t for t in existing if not (t.end <= start or t.start >= end)]
    kept = [t for t in existing if t.end <= start or t.start >= end]
    spk = (speaker or "").strip() or _majority_speaker(removed, default=(
        tr.speakers[0].id if tr.speakers else "A"
    ))

    added: list[Token] = []
    for w in asr.words:
        abs_s = float(w.start) + clip_start
        abs_e = float(w.end) + clip_start
        # Keep words that land mostly inside the user window.
        mid = (abs_s + abs_e) / 2
        if mid < start or mid > end:
            continue
        txt = (w.text or "").strip()
        if not txt:
            continue
        # Clamp lightly into the window so boundaries stay tidy.
        abs_s = max(start, abs_s)
        abs_e = min(end, max(abs_s + 0.04, abs_e))
        added.append(Token(
            id=f"r{uuid.uuid4().hex[:8]}",
            text=txt,
            start=round(abs_s, 3),
            end=round(abs_e, 3),
            speaker=spk,
            phonemes=[],
            cues=[],
            pre_pause=None,
        ))

    old_turns = tr.turns
    merged = kept + added
    th = settings.thresholds
    tr.turns = regroup_turns(merged, th)
    if tr.layout == "japanese_four_line":
        from .japanese import reattach_japanese_layers

        reattach_japanese_layers(old_turns, tr.turns)
    labels = sorted({t.speaker for t in tr.turns if t.speaker})
    existing_spk = {s.id: s for s in tr.speakers}
    from ..models import Speaker
    tr.speakers = [existing_spk.get(l) or Speaker(id=l, label=l) for l in labels]
    tr.jefferson = render_jefferson(tr)

    return {
        "ok": True,
        "start": start,
        "end": end,
        "removed": len(removed),
        "added": len(added),
        "speaker": spk,
        "transcript": tr,
    }
