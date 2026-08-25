"""Small shared helpers for exporters (kept here so nothing is duplicated)."""
from __future__ import annotations

from ..project import PresentationProject


def srt_time(t: float) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def vtt_time(t: float) -> str:
    return srt_time(t).replace(",", ".")


def caption_segments(project: PresentationProject) -> list[tuple[float, float, str]]:
    """One caption per spoken line, in time order: (start, end, text).

    When the project uses line numbers, each caption is prefixed with its CA
    line number so subtitles line up with the slides/transcript.
    """
    segs: list[tuple[float, float, str]] = []
    for slide in project.slides:
        for ln in slide.lines:
            if ln.is_pause or not ln.text.strip():
                continue
            # CA layout: N   Name  :    talk
            talk = f"{ln.speaker}  :    {ln.text.strip()}" if ln.speaker else ln.text.strip()
            text = f"{ln.no}   {talk}" if ln.no else talk
            segs.append((ln.start, ln.end, text))
    segs.sort(key=lambda s: s[0])
    return segs
