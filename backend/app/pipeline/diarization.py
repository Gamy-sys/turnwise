"""Stage 5 - speaker diarization + overlap detection (OPTIONAL).

Uses pyannote.audio when available and a Hugging Face token is provided. This is
the only torch-heavy piece, so it is fully optional: if unavailable, the caller
falls back to a single speaker and the app still works end-to-end.

Returns a list of (start, end, speaker_label) segments and a list of overlap
(start, end) regions.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiarResult:
    segments: list[tuple[float, float, str]] = field(default_factory=list)
    overlaps: list[tuple[float, float]] = field(default_factory=list)
    available: bool = True
    error: str | None = None
    source: str = "pyannote-3.1"


def diarize(wav_path: str, settings, progress=None) -> DiarResult:
    if not settings.enable_diarization:
        return DiarResult(available=False, error="diarization disabled")
    if not settings.hf_token:
        return DiarResult(available=False,
                          error="no Hugging Face token (see README to enable diarization)")
    try:
        from pyannote.audio import Pipeline
        import torch
    except Exception as e:  # pragma: no cover - optional dep
        return DiarResult(available=False, error=f"pyannote not installed: {e}")

    try:
        if progress:
            progress(0.1, "Loading diarization model")

        # Try the configured model first, then fall back to the other known
        # pipelines so an upgraded/cached environment "just works".
        configured = getattr(settings, "diarization_model", None) \
            or "pyannote/speaker-diarization-community-1"
        candidates: list[str] = []
        for m in (configured,
                  "pyannote/speaker-diarization-community-1",
                  "pyannote/speaker-diarization-3.1"):
            if m and m not in candidates:
                candidates.append(m)

        pipeline = None
        model_id = None
        load_errors: list[str] = []
        for cand in candidates:
            try:
                # pyannote 4.x uses token=, 3.x uses use_auth_token=; support both.
                try:
                    pipeline = Pipeline.from_pretrained(cand, token=settings.hf_token)
                except TypeError:
                    pipeline = Pipeline.from_pretrained(cand, use_auth_token=settings.hf_token)
            except Exception as e:  # not accessible / terms not accepted / offline
                load_errors.append(f"{cand}: {e}")
                pipeline = None
                continue
            if pipeline is not None:
                model_id = cand
                break

        if pipeline is None:
            detail = " | ".join(load_errors) or "unknown error"
            return DiarResult(available=False,
                              error="no diarization model accessible - accept terms at "
                                    "hf.co/pyannote/speaker-diarization-community-1 (or -3.1) "
                                    f"and check your HF token. Details: {detail}")
        device = "cuda" if (settings.device != "cpu" and torch.cuda.is_available()) else "cpu"
        pipeline.to(torch.device(device))

        kwargs = {}
        if settings.num_speakers:
            n = int(settings.num_speakers)
            kwargs["num_speakers"] = n
            # pyannote 3.x/4.x: also pin min/max so Japanese mono mixes don't collapse
            kwargs["min_speakers"] = n
            kwargs["max_speakers"] = n
        if progress:
            progress(0.3, "Diarizing speakers")
        # Feed a pre-decoded waveform instead of a path so pyannote never
        # reaches for torchcodec/ffmpeg to read the file (recent pyannote
        # raises "torchcodec is not available" otherwise). We already have a
        # 16 kHz mono PCM WAV, which soundfile reads with no codec deps.
        diar_input = _load_waveform(wav_path)
        if diar_input is None:
            diar_input = wav_path  # last-ditch fallback to the old path-based call
        try:
            diarization = pipeline(diar_input, **kwargs)
        except TypeError:
            kwargs.pop("min_speakers", None)
            kwargs.pop("max_speakers", None)
            diarization = pipeline(diar_input, **kwargs)

        # pyannote 3.x returns an Annotation directly; pyannote 4.x (community-1)
        # returns a DiarizeOutput wrapping the Annotation in .speaker_diarization.
        annotation = getattr(diarization, "speaker_diarization", diarization)

        segments: list[tuple[float, float, str]] = []
        labels = sorted({lbl for _, _, lbl in annotation.itertracks(yield_label=True)})
        label_map = {lbl: chr(ord("A") + i) for i, lbl in enumerate(labels)}
        for turn, _, lbl in annotation.itertracks(yield_label=True):
            segments.append((float(turn.start), float(turn.end), label_map[lbl]))
        segments.sort(key=lambda s: s[0])

        overlaps = _detect_overlaps(segments)
        segments = absorb_short_speaker_islands(segments)
        overlaps = _detect_overlaps(segments)
        return DiarResult(segments=segments, overlaps=overlaps, available=True,
                          source=model_id or "pyannote")
    except Exception as e:  # pragma: no cover
        return DiarResult(available=False, error=f"diarization failed: {e}")


def _load_waveform(wav_path: str):
    """Decode `wav_path` into pyannote's in-memory input dict.

    Returns ``{"waveform": (channel, time) float32 tensor, "sample_rate": int}``
    or ``None`` if decoding is not possible (caller then falls back to the path).
    """
    try:
        import numpy as np
        import soundfile as sf
        import torch
    except Exception:
        return None
    try:
        data, sr = sf.read(wav_path, dtype="float32", always_2d=True)  # (time, channel)
        waveform = torch.from_numpy(np.ascontiguousarray(data.T))       # (channel, time)
        return {"waveform": waveform, "sample_rate": int(sr)}
    except Exception:
        return None


def _detect_overlaps(segments: list[tuple[float, float, str]]) -> list[tuple[float, float]]:
    """Naive overlap detection: regions covered by 2+ distinct speakers."""
    events: list[tuple[float, int]] = []
    for s, e, _ in segments:
        events.append((s, 1))
        events.append((e, -1))
    events.sort()
    overlaps: list[tuple[float, float]] = []
    depth = 0
    ov_start = None
    for t, d in events:
        prev = depth
        depth += d
        if prev < 2 <= depth:
            ov_start = t
        elif prev >= 2 > depth and ov_start is not None:
            overlaps.append((ov_start, t))
            ov_start = None
    return overlaps


def absorb_short_speaker_islands(
    segments: list[tuple[float, float, str]],
    min_dur: float = 0.35,
    max_gap: float = 0.12,
) -> list[tuple[float, float, str]]:
    """Relabel brief speaker islands flanked by the same other speaker.

    Pyannote (and vision fusion) often split one continuous talker into A then
    B for a few hundred ms, then back to A — especially near clip ends. Those
    short interior labels become false turn changes downstream. Real
    backchannels usually sit in a larger gap and are left alone.
    """
    if not segments:
        return []

    # Work on a mutable copy; keep overlaps of different speakers intact by
    # only rewriting segments that are short and *non-overlapping* with their
    # flanking same-label neighbors' interior pattern in time order.
    segs = sorted(segments, key=lambda s: (s[0], s[1], s[2]))
    # Build a non-overlap timeline view: for each segment, find nearest other
    # segments that end before it starts / start after it ends.
    changed = True
    guard = 0
    while changed and guard < 8:
        guard += 1
        changed = False
        out: list[tuple[float, float, str]] = []
        for i, (s, e, lbl) in enumerate(segs):
            dur = e - s
            if dur >= min_dur:
                out.append((s, e, lbl))
                continue
            # Nearest finished segment before this one starts
            left = None
            right = None
            for j, (s2, e2, lbl2) in enumerate(segs):
                if j == i:
                    continue
                if e2 <= s + 1e-6 and s - e2 <= max_gap:
                    if left is None or e2 > left[1]:
                        left = (s2, e2, lbl2)
                if s2 >= e - 1e-6 and s2 - e <= max_gap:
                    if right is None or s2 < right[0]:
                        right = (s2, e2, lbl2)
            if (
                left
                and right
                and left[2] == right[2]
                and left[2] != lbl
            ):
                out.append((s, e, left[2]))
                changed = True
            else:
                out.append((s, e, lbl))
        segs = out

    # Merge same-label neighbors that now touch after relabel.
    segs = sorted(segs, key=lambda s: (s[2], s[0], s[1]))
    merged: list[tuple[float, float, str]] = []
    for s, e, lbl in segs:
        if merged and merged[-1][2] == lbl and s <= merged[-1][1] + max_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e), lbl)
        else:
            merged.append((s, e, lbl))
    merged.sort(key=lambda s: (s[0], s[1], s[2]))
    return merged


def speaker_at(segments: list[tuple[float, float, str]], t: float, default: str = "A") -> str:
    """Return the speaker label whose segment best contains time `t`."""
    return speaker_for_interval(segments, t, t, default=default)


def speaker_for_interval(
    segments: list[tuple[float, float, str]],
    start: float,
    end: float,
    default: str = "A",
) -> str:
    """Map a timed word span to the diarization label with the most overlap."""
    if end < start:
        start, end = end, start
    mid = (start + end) / 2.0
    best = default
    best_ov = 0.0
    for s, e, lbl in segments:
        ov = min(e, end) - max(s, start)
        if ov > best_ov:
            best_ov = ov
            best = lbl
    if best_ov > 0:
        return best
    # Point fallback: nearest segment centre (handles gaps between diar segments).
    nearest = None
    nearest_dist = 1e9
    for s, e, lbl in segments:
        centre = (s + e) / 2.0
        d = abs(centre - mid)
        if d < nearest_dist:
            nearest_dist = d
            nearest = lbl
    return nearest or default
