#!/usr/bin/env python3
"""Generic clip accuracy probe (not tied to any one corpus).

Example (any video + optional ELAN gold for the same window):

  cd backend
  .venv/bin/python ../scripts/probe_active_speaker.py \\
      --video /path/to/clip.mp4 \\
      --speakers 4

Optional: compare fused diarization to an EAF orthography tier window:

  .venv/bin/python ../scripts/probe_active_speaker.py \\
      --video clip.mp4 --eaf gold.eaf --eaf-start 461 --eaf-end 476 --speakers 4

Writes JSON summary to stdout. Use this to tune thresholds on held-out clips.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--speakers", type=int, default=4)
    ap.add_argument("--eaf", type=Path, default=None)
    ap.add_argument("--eaf-start", type=float, default=None, help="Gold window start (sec, absolute in EAF)")
    ap.add_argument("--eaf-end", type=float, default=None, help="Gold window end (sec)")
    args = ap.parse_args()

    from app.config import Settings, load_secrets
    from app.pipeline import active_speaker, diarization, ingest

    settings = Settings.from_dict({
        "num_speakers": args.speakers,
        "enable_diarization": True,
        "enable_active_speaker": True,
        "hf_token": load_secrets().get("hf_token"),
    })

    work = ROOT / "data" / "probe_work"
    work.mkdir(parents=True, exist_ok=True)
    prep = ingest.prepare(args.video, work, sample_rate=16000)
    diar = diarization.diarize(str(prep.mono_wav), settings)
    visual = active_speaker.analyze_active_speaker(args.video, settings)
    fused = diar
    if diar.available and visual.available:
        fused = active_speaker.fuse_with_diarization(diar, visual, settings)

    summary = {
        "video": str(args.video),
        "duration": prep.duration,
        "audio_diar": {
            "available": diar.available,
            "source": diar.source,
            "error": diar.error,
            "speakers": sorted({s for _, _, s in diar.segments}),
            "n_segments": len(diar.segments),
        },
        "visual": {
            "available": visual.available,
            "source": visual.source,
            "error": visual.error,
            "n_faces": visual.n_faces,
            "face_to_speaker": visual.face_to_speaker,
            "n_visual_segments": len(visual.visual_segments),
        },
        "fused": {
            "source": fused.source,
            "speakers": sorted({s for _, _, s in fused.segments}),
            "n_segments": len(fused.segments),
            "segments": [
                {"start": round(s, 3), "end": round(e, 3), "speaker": sp}
                for s, e, sp in fused.segments
            ],
        },
    }

    if args.eaf and args.eaf_start is not None and args.eaf_end is not None:
        summary["eaf_window"] = _eaf_speaker_spans(
            args.eaf, args.eaf_start, args.eaf_end
        )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if (diar.available or visual.available) else 1


def _eaf_speaker_spans(eaf_path: Path, start_s: float, end_s: float) -> dict:
    import xml.etree.ElementTree as ET

    root = ET.parse(eaf_path).getroot()
    slots = {
        ts.get("TIME_SLOT_ID"): int(ts.get("TIME_VALUE"))
        for ts in root.findall(".//TIME_SLOT")
        if ts.get("TIME_VALUE")
    }
    lo, hi = int(start_s * 1000), int(end_s * 1000)
    by: dict[str, list] = {}
    for tier in root.findall(".//TIER"):
        tid = tier.get("TIER_ID") or ""
        # Orthography parent tiers only (no ort@ / xtrn@)
        if "@" in tid:
            continue
        if tier.get("LINGUISTIC_TYPE_REF") not in (None, "orthography"):
            # still allow if it's a main participant tier without @
            pass
        part = tier.get("PARTICIPANT") or tid
        for ann in tier.findall("ANNOTATION"):
            align = ann.find("ALIGNABLE_ANNOTATION")
            if align is None:
                continue
            s = slots.get(align.get("TIME_SLOT_REF1"))
            e = slots.get(align.get("TIME_SLOT_REF2"))
            if s is None or e is None or e <= lo or s >= hi:
                continue
            val = (align.findtext("ANNOTATION_VALUE") or "").strip()
            by.setdefault(part, []).append({
                "start": round(max(0.0, (s - lo) / 1000), 3),
                "end": round(min(end_s - start_s, (e - lo) / 1000), 3),
                "text": val[:120],
                "tier": tid,
            })
    return {"speakers": sorted(by.keys()), "tiers": by}


if __name__ == "__main__":
    raise SystemExit(main())
