"""Visual active-speaker cues from video (optional) — sakura-like table talk.

Distant / small faces often break Face Mesh lips. This module targets the common
CA recording style instead:

  1. MediaPipe **Face Detection** (full-range) — finds small faces reliably
  2. Per-face **animation** — frame-diff in an expanded head/shoulder ROI
  3. **Gaze / head yaw** — nose vs eye midpoint (who turns / looks while talking)
  4. Fuse with pyannote so overlap follows the animated / gazing person

No corpus-specific IDs. Soft-fails without vision deps or detections.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .diarization import DiarResult, _detect_overlaps


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg"}

# FaceDetection relative keypoints
_KP_RIGHT_EYE = 0
_KP_LEFT_EYE = 1
_KP_NOSE = 2
_KP_MOUTH = 3


@dataclass
class FaceTrack:
    track_id: int
    # (t_sec, activity, motion, abs_yaw)
    samples: list[tuple[float, float, float, float]] = field(default_factory=list)
    last_bbox: tuple[float, float, float, float] | None = None
    last_gray_roi: np.ndarray | None = None


@dataclass
class ActiveSpeakerResult:
    available: bool = False
    error: str | None = None
    source: str = "mediapipe-facedet"
    n_faces: int = 0
    visual_segments: list[tuple[float, float, str]] = field(default_factory=list)
    face_to_speaker: dict[str, str] = field(default_factory=dict)
    fused_segments: list[tuple[float, float, str]] = field(default_factory=list)


def is_video_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def analyze_active_speaker(
    video_path: str | Path,
    settings,
    progress=None,
) -> ActiveSpeakerResult:
    """Return visual-activity tracks + speaking segments (motion + gaze)."""
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
        progress(0.05, "Scanning faces / motion / gaze")

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
        source=f"facedet+motion+gaze@{fps_used:.1f}fps",
    )


def fuse_with_diarization(
    diar: DiarResult,
    visual: ActiveSpeakerResult,
    settings=None,
) -> DiarResult:
    """Refine audio diarization with visual activity priors."""
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
    refined = _add_visual_only(refined, visual.visual_segments, mapping, min_dur=0.18)
    refined.sort(key=lambda s: (s[0], s[1], s[2]))
    refined = _merge_adjacent(refined, gap=0.05)
    # Collapse brief A↔B identity flickers (same talker split across labels).
    from .diarization import absorb_short_speaker_islands

    refined = absorb_short_speaker_islands(refined)
    visual.fused_segments = refined

    return DiarResult(
        segments=refined,
        overlaps=_detect_overlaps(refined),
        available=True,
        error=None,
        source=f"{diar.source}+vision",
    )


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
    max_faces = int(getattr(settings, "num_speakers", None) or 4)

    # model_selection=1 = full-range detector (small / distant faces — table talk)
    detector = mp.solutions.face_detection.FaceDetection(
        model_selection=1,
        min_detection_confidence=float(
            getattr(settings, "active_speaker_detect_thr", 0.15) or 0.15
        ),
    )

    tracks: list[FaceTrack] = []
    next_id = 0
    frame_i = 0
    prev_yaw: dict[int, float] = {}

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_i % step != 0:
                frame_i += 1
                continue
            t = frame_i / fps if fps > 0 else frame_i / target_fps
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = detector.process(rgb)

            detections: list[tuple[tuple[float, float, float, float], float, float, np.ndarray]] = []
            if res.detections:
                scored = []
                for det in res.detections:
                    conf = float(det.score[0]) if det.score else 0.0
                    bb = det.location_data.relative_bounding_box
                    bbox = (
                        float(bb.xmin),
                        float(bb.ymin),
                        float(bb.xmin + bb.width),
                        float(bb.ymin + bb.height),
                    )
                    yaw = _yaw_from_keypoints(det)
                    scored.append((conf, bbox, yaw))
                scored.sort(reverse=True)
                for conf, bbox, yaw in scored[: max(max_faces + 1, 4)]:
                    roi = _crop_motion_roi(gray, bbox, h, w)
                    detections.append((bbox, conf, yaw, roi))

            assigned = _assign_detections(tracks, detections, next_id)
            next_id = max(next_id, max((tr.track_id for tr in tracks), default=-1) + 1)

            for tr, yaw, roi in assigned:
                motion = 0.0
                if tr.last_gray_roi is not None and roi is not None and roi.size and tr.last_gray_roi.size:
                    a = tr.last_gray_roi
                    b = roi
                    if a.shape != b.shape:
                        b = cv2.resize(b, (a.shape[1], a.shape[0]))
                    motion = float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)
                tr.last_gray_roi = roi
                dyaw = abs(yaw - prev_yaw.get(tr.track_id, yaw))
                prev_yaw[tr.track_id] = yaw
                # Activity: body/face animation + head-turn (gaze shift)
                activity = motion + 0.45 * min(dyaw, 0.35)
                tr.samples.append((t, activity, motion, abs(yaw)))

            if progress and n_frames > 0 and frame_i % (step * 10) == 0:
                progress(min(0.05 + 0.85 * (frame_i / max(n_frames, 1)), 0.9), "Motion / gaze")
            frame_i += 1
    finally:
        cap.release()
        detector.close()

    return tracks, (fps / step if step else fps), duration


def _yaw_from_keypoints(detection) -> float:
    """Approximate head yaw: nose x vs eye midpoint, normalized by face width."""
    loc = detection.location_data
    kps = loc.relative_keypoints
    if not kps or len(kps) < 3:
        return 0.0
    bb = loc.relative_bounding_box
    width = max(float(bb.width), 1e-6)
    mid = 0.5 * (float(kps[_KP_RIGHT_EYE].x) + float(kps[_KP_LEFT_EYE].x))
    nose = float(kps[_KP_NOSE].x)
    return (nose - mid) / width


def _crop_motion_roi(gray, bbox, h: int, w: int):
    """Head + upper-shoulder band (speakers often animate when talking)."""
    import cv2

    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    # expand sideways and downward into shoulders/torso
    x1e = max(0.0, x1 - 0.2 * bw)
    x2e = min(1.0, x2 + 0.2 * bw)
    y1e = max(0.0, y1 - 0.15 * bh)
    y2e = min(1.0, y2 + 1.1 * bh)
    xa, xb = int(x1e * w), int(x2e * w)
    ya, yb = int(y1e * h), int(y2e * h)
    if xb - xa < 8 or yb - ya < 8:
        return None
    roi = gray[ya:yb, xa:xb]
    # normalize size for stable frame-diff across track
    return cv2.resize(roi, (48, 64))


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
    """Greedy IoU match. detections: (bbox, conf, yaw, roi)."""
    result: list[tuple[FaceTrack, float, np.ndarray | None]] = []
    unused = set(range(len(detections)))
    pairs: list[tuple[float, int, int]] = []
    for ti, tr in enumerate(tracks):
        if tr.last_bbox is None:
            continue
        for di in unused:
            bbox = detections[di][0]
            iou = _bbox_iou(tr.last_bbox, bbox)
            cx, cy = _bbox_center(tr.last_bbox)
            dx, dy = _bbox_center(bbox)
            dist = ((cx - dx) ** 2 + (cy - dy) ** 2) ** 0.5
            pairs.append((iou * 2.0 - dist, ti, di))
    pairs.sort(reverse=True)
    used_t, used_d = set(), set()
    for score, ti, di in pairs:
        if score < -0.2:
            break
        if ti in used_t or di in used_d:
            continue
        used_t.add(ti)
        used_d.add(di)
        unused.discard(di)
        bbox, _conf, yaw, roi = detections[di]
        tracks[ti].last_bbox = bbox
        result.append((tracks[ti], yaw, roi))

    for di in list(unused):
        bbox, _conf, yaw, roi = detections[di]
        tr = FaceTrack(track_id=next_id, last_bbox=bbox)
        next_id += 1
        tracks.append(tr)
        result.append((tr, yaw, roi))
    return result


def _keep_top_tracks(tracks: list[FaceTrack], k: int) -> list[FaceTrack]:
    scored = sorted(
        tracks,
        key=lambda tr: (len(tr.samples), sum(a for _, a, _, _ in tr.samples)),
        reverse=True,
    )
    return scored[: max(1, k)]


def _tracks_to_segments(tracks: list[FaceTrack], settings) -> list[tuple[float, float, str]]:
    """Threshold per-face activity (motion + gaze shift) into spans."""
    # Frame-diff motion is typically ~0.01–0.08 when someone gestures/talks
    motion_thr = float(getattr(settings, "active_speaker_motion_thr", 0.018) or 0.018)
    activity_margin = float(getattr(settings, "active_speaker_open_thr", 0.012) or 0.012)
    min_dur = float(getattr(settings, "active_speaker_min_dur", 0.12) or 0.12)
    segs: list[tuple[float, float, str]] = []

    for tr in tracks:
        if len(tr.samples) < 3:
            continue
        face = f"F{tr.track_id}"
        acts = [a for _, a, _, _ in tr.samples]
        baseline = float(np.percentile(acts, 30))
        active_times = [
            t for t, act, mo, _yaw in tr.samples
            if act >= baseline + activity_margin or mo >= motion_thr
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
    co = {f: {a: 0.0 for a in audio_labels} for f in face_ids}
    for vs, ve, face in visual_segs:
        for as_, ae, spk in audio_segs:
            ov = min(ve, ae) - max(vs, as_)
            if ov > 0:
                co[face][spk] += ov

    mapping: dict[str, str] = {}
    used_spk: set[str] = set()
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
    leftover_f = [f for f in face_ids if f not in mapping]
    leftover_a = [a for a in audio_labels if a not in used_spk]
    for f, a in zip(leftover_f, leftover_a):
        mapping[f] = a
    return mapping


def _speakers_at(segments, t: float) -> list[str]:
    return [lbl for s, e, lbl in segments if s <= t < e]


def _refine_segments(audio_segs, visual_segs, mapping, duration, hop):
    """Fuse audio diarization with visual activity.

    Vision is used to *arbitrate overlaps* and to *hold a sticky label* when
    pyannote flickers mid-utterance while the previous talker's face is still
    active. Vision never overrides a lone audio label with a different face —
    that caused systematic A/B swaps for the same person near clip ends.
    """
    if duration <= 0:
        return list(audio_segs)

    vis_audio = [(s, e, mapping[f]) for s, e, f in visual_segs if f in mapping]
    out_events: list[tuple[float, float, str]] = []
    prev_spk: str | None = None
    t = 0.0
    while t < duration:
        t2 = min(duration, t + hop)
        mid = (t + t2) * 0.5
        audio_here = _speakers_at(audio_segs, mid)
        vis_here = _speakers_at(vis_audio, mid)
        if len(audio_here) >= 2 and vis_here:
            chosen = [v for v in vis_here if v in audio_here] or vis_here[:1]
            for spk in chosen:
                out_events.append((t, t2, spk))
            prev_spk = chosen[0] if chosen else prev_spk
        elif len(audio_here) == 1:
            spk = audio_here[0]
            # Sticky continuity: hold the previous talker while their face is
            # still active. Mid-utterance pyannote A→B swaps often fire while
            # both faces move (talker + listener); do not accept the swap until
            # the previous face goes quiet.
            if prev_spk and prev_spk != spk and prev_spk in vis_here:
                spk = prev_spk
            out_events.append((t, t2, spk))
            prev_spk = spk
        elif audio_here:
            for spk in audio_here:
                out_events.append((t, t2, spk))
            prev_spk = audio_here[0]
        elif vis_here:
            # Prefer sticky face if still active; else first visual label.
            if prev_spk and prev_spk in vis_here:
                out_events.append((t, t2, prev_spk))
            else:
                out_events.append((t, t2, vis_here[0]))
                prev_spk = vis_here[0]
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
    out = list(audio_segs)
    for vs, ve, face in visual_segs:
        if ve - vs < min_dur:
            continue
        spk = mapping.get(face)
        if not spk:
            continue
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
