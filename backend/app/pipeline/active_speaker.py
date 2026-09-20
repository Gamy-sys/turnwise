"""Lip / mouth-motion active-speaker cues from video (optional).

General-purpose: any clip with visible faces. No corpus-specific IDs.

Pipeline:
  1. Sample frames from the source video
  2. Detect face landmarks (MediaPipe Face Mesh)
  3. Track faces across time (centroid + IoU)
  4. Score mouth opening motion per track
  5. Fuse with pyannote segments so overlap / mis-attribution follows lips

Fails soft: if OpenCV/MediaPipe missing or no faces, returns unavailable and
the audio-only path continues unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .diarization import DiarResult, _detect_overlaps


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg"}

# MediaPipe Face Mesh lip landmarks (outer / inner mouth)
_LIP_TOP = 13
_LIP_BOT = 14
_LIP_LEFT = 78
_LIP_RIGHT = 308


@dataclass
class FaceTrack:
    track_id: int
    # (t_sec, mouth_open, motion) samples
    samples: list[tuple[float, float, float]] = field(default_factory=list)
    # last bbox (x1,y1,x2,y2) normalized 0-1
    last_bbox: tuple[float, float, float, float] | None = None


@dataclass
class ActiveSpeakerResult:
    available: bool = False
    error: str | None = None
    source: str = "mediapipe-facemesh"
    n_faces: int = 0
    # (start, end, face_id) where lips look active
    visual_segments: list[tuple[float, float, str]] = field(default_factory=list)
    # face_id -> audio speaker label after fusion mapping
    face_to_speaker: dict[str, str] = field(default_factory=dict)
    # refined audio-style segments (same shape as diarization)
    fused_segments: list[tuple[float, float, str]] = field(default_factory=list)


def is_video_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def analyze_active_speaker(
    video_path: str | Path,
    settings,
    progress=None,
) -> ActiveSpeakerResult:
    """Return lip-activity tracks + coarse visual speaking segments."""
    if not getattr(settings, "enable_active_speaker", True):
        return ActiveSpeakerResult(available=False, error="active speaker disabled")
    video_path = Path(video_path)
    if not video_path.is_file() or not is_video_path(video_path):
        return ActiveSpeakerResult(available=False, error="not a video file")

    try:
        import cv2  # noqa: F401
        import mediapipe as mp  # noqa: F401
    except Exception as e:
        return ActiveSpeakerResult(
            available=False,
            error=f"vision deps missing (pip install -r requirements-vision.txt): {e}",
        )

    if progress:
        progress(0.05, "Scanning faces / lip motion")

    try:
        tracks, fps_used, duration = _extract_tracks(video_path, settings, progress)
    except Exception as e:
        return ActiveSpeakerResult(available=False, error=f"face scan failed: {e}")

    if not tracks:
        return ActiveSpeakerResult(available=False, error="no faces detected in video")

    max_faces = int(getattr(settings, "num_speakers", None) or 4)
    tracks = _keep_top_tracks(tracks, max_faces)
    visual_segs = _tracks_to_segments(tracks, settings)
    return ActiveSpeakerResult(
        available=True,
        n_faces=len(tracks),
        visual_segments=visual_segs,
        source=f"mediapipe-facemesh@{fps_used:.1f}fps",
    )


def fuse_with_diarization(
    diar: DiarResult,
    visual: ActiveSpeakerResult,
    settings=None,
) -> DiarResult:
    """Refine audio diarization with lip-activity priors.

    - Learns a face↔audio-speaker mapping from co-occurrence
    - In overlap (or short disputed spans), prefers the visually active face
    - Adds brief visual-only spans when lips move but audio diar missed them
    """
    if not diar.available or not diar.segments:
        return diar
    if not visual.available or not visual.visual_segments:
        return diar

    audio_labels = sorted({lbl for _, _, lbl in diar.segments})
    face_ids = sorted({lbl for _, _, lbl in visual.visual_segments})
    if not audio_labels or not face_ids:
        return diar

    mapping = _map_faces_to_speakers(diar.segments, visual.visual_segments, audio_labels, face_ids)
    visual.face_to_speaker = mapping

    hop = float(getattr(getattr(settings, "thresholds", None), "active_speaker_hop", 0.1) or 0.1)
    duration = max(
        max((e for _, e, _ in diar.segments), default=0.0),
        max((e for _, e, _ in visual.visual_segments), default=0.0),
    )
    refined = _refine_segments(diar.segments, visual.visual_segments, mapping, duration, hop)
    # Optional: attach short visual-only regions mapped onto audio labels
    refined = _add_visual_only(refined, visual.visual_segments, mapping, min_dur=0.18)

    refined.sort(key=lambda s: (s[0], s[1], s[2]))
    refined = _merge_adjacent(refined, gap=0.05)
    visual.fused_segments = refined

    out = DiarResult(
        segments=refined,
        overlaps=_detect_overlaps(refined),
        available=True,
        error=None,
        source=f"{diar.source}+lips",
    )
    return out


def _extract_tracks(video_path: Path, settings, progress=None):
    import cv2
    import mediapipe as mp

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = (n_frames / fps) if fps > 0 and n_frames > 0 else 0.0

    target_fps = float(getattr(settings, "active_speaker_fps", 5.0) or 5.0)
    target_fps = max(2.0, min(target_fps, 12.0))
    step = max(1, int(round(fps / target_fps))) if fps > 0 else 5

    # static_image_mode=True re-detects every sampled frame — more reliable when
    # people turn away briefly; still cheap at 5–8 fps.
    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=int(getattr(settings, "num_speakers", None) or 4),
        refine_landmarks=True,
        min_detection_confidence=0.25,
        min_tracking_confidence=0.25,
    )

    tracks: list[FaceTrack] = []
    next_id = 0
    frame_i = 0
    prev_open: dict[int, float] = {}

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_i % step != 0:
                frame_i += 1
                continue
            t = frame_i / fps if fps > 0 else frame_i / target_fps
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = mesh.process(rgb)
            detections: list[tuple[tuple[float, float, float, float], float]] = []
            if res.multi_face_landmarks:
                for fl in res.multi_face_landmarks:
                    xs = [p.x for p in fl.landmark]
                    ys = [p.y for p in fl.landmark]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    open_amt = _mouth_open(fl.landmark)
                    detections.append((bbox, open_amt))

            assigned = _assign_detections(tracks, detections, next_id)
            next_id = max(next_id, max((tr.track_id for tr in tracks), default=-1) + 1)
            for tr, open_amt in assigned:
                prev = prev_open.get(tr.track_id, open_amt)
                motion = abs(open_amt - prev)
                prev_open[tr.track_id] = open_amt
                tr.samples.append((t, open_amt, motion))

            if progress and n_frames > 0 and frame_i % (step * 10) == 0:
                progress(min(0.05 + 0.85 * (frame_i / max(n_frames, 1)), 0.9), "Lip activity")
            frame_i += 1
    finally:
        cap.release()
        mesh.close()

    return tracks, (fps / step if step else fps), duration


def _mouth_open(landmarks) -> float:
    """Normalized vertical lip gap / mouth width."""
    top = landmarks[_LIP_TOP]
    bot = landmarks[_LIP_BOT]
    left = landmarks[_LIP_LEFT]
    right = landmarks[_LIP_RIGHT]
    vert = abs(top.y - bot.y)
    horiz = max(abs(right.x - left.x), 1e-6)
    return float(vert / horiz)


def _bbox_iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(area_a + area_b - inter, 1e-9)


def _bbox_center(b):
    return ((b[0] + b[2]) * 0.5, (b[1] + b[3]) * 0.5)


def _assign_detections(tracks: list[FaceTrack], detections, next_id: int):
    """Greedy IoU / distance match of face detections to existing tracks."""
    result: list[tuple[FaceTrack, float]] = []
    unused = set(range(len(detections)))
    # score matrix
    pairs: list[tuple[float, int, int]] = []
    for ti, tr in enumerate(tracks):
        if tr.last_bbox is None:
            continue
        for di in unused:
            bbox, _ = detections[di]
            iou = _bbox_iou(tr.last_bbox, bbox)
            cx, cy = _bbox_center(tr.last_bbox)
            dx, dy = _bbox_center(bbox)
            dist = ((cx - dx) ** 2 + (cy - dy) ** 2) ** 0.5
            score = iou * 2.0 - dist
            pairs.append((score, ti, di))
    pairs.sort(reverse=True)
    used_t, used_d = set(), set()
    for score, ti, di in pairs:
        if score < -0.15:
            break
        if ti in used_t or di in used_d:
            continue
        used_t.add(ti)
        used_d.add(di)
        unused.discard(di)
        bbox, open_amt = detections[di]
        tracks[ti].last_bbox = bbox
        result.append((tracks[ti], open_amt))

    for di in list(unused):
        bbox, open_amt = detections[di]
        tr = FaceTrack(track_id=next_id, last_bbox=bbox)
        next_id += 1
        tracks.append(tr)
        result.append((tr, open_amt))
    return result


def _keep_top_tracks(tracks: list[FaceTrack], k: int) -> list[FaceTrack]:
    scored = sorted(
        tracks,
        key=lambda tr: (len(tr.samples), sum(m for _, _, m in tr.samples)),
        reverse=True,
    )
    return scored[: max(1, k)]


def _tracks_to_segments(tracks: list[FaceTrack], settings) -> list[tuple[float, float, str]]:
    """Threshold mouth motion into contiguous visual-active spans per face.

    Uses each face's own resting baseline (low percentile of mouth opening) so
    quiet talkers still register; absolute thresholds alone fail on distant faces.
    """
    open_margin = float(getattr(settings, "active_speaker_open_thr", 0.02) or 0.02)
    motion_thr = float(getattr(settings, "active_speaker_motion_thr", 0.008) or 0.008)
    min_dur = float(getattr(settings, "active_speaker_min_dur", 0.12) or 0.12)
    segs: list[tuple[float, float, str]] = []

    for tr in tracks:
        if len(tr.samples) < 3:
            continue
        face = f"F{tr.track_id}"
        opens = [op for _, op, _ in tr.samples]
        baseline = float(np.percentile(opens, 25))
        active_times = [
            t for t, op, mo in tr.samples
            if (op >= baseline + open_margin) or (mo >= motion_thr) or (op >= baseline * 1.35 + 0.01)
        ]
        if not active_times:
            continue
        active_times.sort()
        gaps = np.diff(active_times)
        med_gap = float(np.median(gaps)) if len(gaps) else 0.2
        join = max(0.22, med_gap * 2.5)
        start = active_times[0]
        prev = active_times[0]
        for t in active_times[1:]:
            if t - prev > join:
                if prev - start >= min_dur:
                    segs.append((start, prev + med_gap * 0.5, face))
                start = t
            prev = t
        if prev - start >= min_dur:
            segs.append((start, prev + med_gap * 0.5, face))
    segs.sort(key=lambda s: s[0])
    return segs


def _map_faces_to_speakers(audio_segs, visual_segs, audio_labels, face_ids) -> dict[str, str]:
    """Maximize co-occurrence overlap between face activity and audio labels."""
    co = {f: {a: 0.0 for a in audio_labels} for f in face_ids}
    for vs, ve, face in visual_segs:
        for as_, ae, spk in audio_segs:
            ov = min(ve, ae) - max(vs, as_)
            if ov > 0:
                co[face][spk] += ov

    mapping: dict[str, str] = {}
    used_spk: set[str] = set()
    # Greedy: largest co-occurrence first
    pairs = []
    for f in face_ids:
        for a in audio_labels:
            pairs.append((co[f][a], f, a))
    pairs.sort(reverse=True)
    for score, f, a in pairs:
        if f in mapping or a in used_spk:
            continue
        if score <= 0.05:
            continue
        mapping[f] = a
        used_spk.add(a)
    # Leftover faces → leftover speakers
    leftover_f = [f for f in face_ids if f not in mapping]
    leftover_a = [a for a in audio_labels if a not in used_spk]
    for f, a in zip(leftover_f, leftover_a):
        mapping[f] = a
    return mapping


def _speakers_at(segments, t: float) -> list[str]:
    return [lbl for s, e, lbl in segments if s <= t < e]


def _refine_segments(audio_segs, visual_segs, mapping, duration, hop):
    """Per time-hop: if audio overlap or conflict, trust mapped visual face."""
    if duration <= 0:
        return list(audio_segs)

    # Build visual label timeline in audio-speaker space
    vis_audio = [(s, e, mapping[f]) for s, e, f in visual_segs if f in mapping]

    out_events: list[tuple[float, float, str]] = []
    t = 0.0
    while t < duration:
        t2 = min(duration, t + hop)
        mid = (t + t2) * 0.5
        audio_here = _speakers_at(audio_segs, mid)
        vis_here = _speakers_at(vis_audio, mid)
        if len(audio_here) >= 2 and vis_here:
            # Overlap: keep visually supported speakers; if one visual, prefer it
            chosen = [v for v in vis_here if v in audio_here] or vis_here[:1]
            for spk in chosen:
                out_events.append((t, t2, spk))
        elif len(audio_here) == 1 and vis_here and audio_here[0] not in vis_here:
            # Brief disagreement: if visual is strong singleton, switch
            out_events.append((t, t2, vis_here[0]))
        elif audio_here:
            for spk in audio_here:
                out_events.append((t, t2, spk))
        elif vis_here:
            out_events.append((t, t2, vis_here[0]))
        t = t2

    return _events_to_segments(out_events)


def _events_to_segments(events: list[tuple[float, float, str]]):
    if not events:
        return []
    events = sorted(events, key=lambda e: (e[2], e[0], e[1]))
    segs: list[tuple[float, float, str]] = []
    for s, e, lbl in events:
        if segs and segs[-1][2] == lbl and abs(segs[-1][1] - s) < 1e-6:
            segs[-1] = (segs[-1][0], e, lbl)
        else:
            segs.append((s, e, lbl))
    # merge near-adjacent same label
    return _merge_adjacent(segs, gap=0.08)


def _merge_adjacent(segs, gap=0.05):
    if not segs:
        return []
    segs = sorted(segs, key=lambda s: (s[2], s[0], s[1]))
    out = [segs[0]]
    for s, e, lbl in segs[1:]:
        ps, pe, pl = out[-1]
        if pl == lbl and s <= pe + gap:
            out[-1] = (ps, max(pe, e), pl)
        else:
            out.append((s, e, lbl))
    out.sort(key=lambda s: (s[0], s[1], s[2]))
    return out


def _add_visual_only(audio_segs, visual_segs, mapping, min_dur=0.18):
    """If lips move with no audio label, add a short span for the mapped speaker."""
    out = list(audio_segs)
    for vs, ve, face in visual_segs:
        if ve - vs < min_dur:
            continue
        spk = mapping.get(face)
        if not spk:
            continue
        # coverage by any audio
        covered = 0.0
        for as_, ae, _ in audio_segs:
            ov = min(ve, ae) - max(vs, as_)
            if ov > 0:
                covered += ov
        if covered / max(ve - vs, 1e-6) >= 0.5:
            continue
        out.append((vs, ve, spk))
    return out


def dump_debug(visual: ActiveSpeakerResult, path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "available": visual.available,
                "error": visual.error,
                "source": visual.source,
                "n_faces": visual.n_faces,
                "face_to_speaker": visual.face_to_speaker,
                "visual_segments": [
                    {"start": s, "end": e, "face": f} for s, e, f in visual.visual_segments
                ],
                "fused_segments": [
                    {"start": s, "end": e, "speaker": sp} for s, e, sp in visual.fused_segments
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
