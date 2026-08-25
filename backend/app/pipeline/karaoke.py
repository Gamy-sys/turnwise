"""Karaoke export: render the transcript as a video whose words highlight in
sync with the audio, then embed that video in a ready-to-use .pptx.

Pipeline:
  transcript -> ASS subtitle file (per-word \\k karaoke timing)
             -> ffmpeg burns ASS over a background + audio -> MP4
             -> python-pptx embeds the MP4 full-slide -> PPTX

Dropping the MP4 (or the PPTX's slide) into PowerPoint preserves the karaoke
highlight during playback, on any machine, with no fonts/plugins needed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..models import Transcript

# Bottom-center, white text that turns amber as it's "sung".
_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Def,Arial,40,&H0000E5FF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginV, Effect, Text
"""


def _ass_time(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def build_ass(tr: Transcript, dst: Path) -> Path:
    content = [t for t in tr.turns if t.speaker and t.tokens]
    starts = [t.tokens[0].start for t in content]
    lines = [_ASS_HEADER]
    # Give each speaker a vertical lane so overlaps don't collide.
    spk_ids = [s.id for s in tr.speakers] or ["A"]
    lane = {sid: 60 + i * 70 for i, sid in enumerate(spk_ids)}

    for idx, turn in enumerate(content):
        line_start = turn.tokens[0].start
        # keep the line up until the next turn begins (min 0.8s), so nothing flickers
        nxt = starts[idx + 1] if idx + 1 < len(starts) else None
        line_end = nxt if (nxt and nxt > line_start) else turn.tokens[-1].end + 0.8

        chunks = [f"{{\\k0}}{_esc(turn.speaker)}: "]
        cursor = line_start
        for tok in turn.tokens:
            gap = tok.start - cursor
            if gap > 0.02:
                chunks.append(f"{{\\k{int(round(gap * 100))}}} ")
            dur = max(tok.end - tok.start, 0.05)
            chunks.append(f"{{\\k{int(round(dur * 100))}}}{_esc(tok.text)} ")
            cursor = tok.end
        text = "".join(chunks)
        mv = lane.get(turn.speaker, 60)
        lines.append(
            f"Dialogue: 0,{_ass_time(line_start)},{_ass_time(line_end)},Def,,{mv},,{text}"
        )

    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dst


def render_karaoke_mp4(tr: Transcript, audio_wav: Path, out_mp4: Path,
                       fps: int = 15, bg: str = "0x0d1117") -> Path:
    ass = build_ass(tr, out_mp4.with_suffix(".ass"))
    duration = max(tr.meta.duration, 0.5)
    # ass filter path: escape for the filtergraph (':' and '\\').
    ass_path = str(ass).replace("\\", "\\\\").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={bg}:s=1280x720:r={fps}:d={duration:.2f}",
        "-i", str(audio_wav),
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg karaoke render failed:\n{proc.stderr[-2500:]}")
    return out_mp4


def build_pptx(mp4: Path, out_pptx: Path, poster: Path | None = None) -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    slide.shapes.add_movie(
        str(mp4), Inches(0), Inches(0), Inches(13.333), Inches(7.5),
        poster_frame_image=str(poster) if poster else None,
        mime_type="video/mp4",
    )
    _try_autoplay(slide)
    prs.save(str(out_pptx))
    return out_pptx


def _try_autoplay(slide) -> None:
    """Best-effort: make the embedded video start automatically in slideshow.

    If anything about the XML shape differs, we silently leave it as click-to-
    play (still fully functional).
    """
    try:
        from pptx.oxml.ns import qn

        # find the movie's shape id + name
        pic = slide.shapes[-1]._element
        nv = pic.find(qn("p:nvPicPr"))
        cnv = nv.find(qn("p:cNvPr"))
        sp_id = cnv.get("id")

        timing_xml = (
            '<p:timing xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">'
            '<p:childTnLst><p:seq concurrent="1" nextAc="seek">'
            '<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
            '<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>'
            '<p:childTnLst><p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            '<p:childTnLst><p:par><p:cTn id="5" presetID="1" presetClass="mediaCall" presetSubtype="0" '
            'fill="hold" nodeType="clickEffect"><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            '<p:childTnLst><p:cmd type="call" cmd="playFrom(0.0)">'
            '<p:cBhvr><p:cTn id="6" dur="1" fill="hold"/><p:tgtEl>'
            f'<p:spTgt spid="{sp_id}"/></p:tgtEl></p:cBhvr></p:cmd></p:childTnLst></p:cTn></p:par>'
            '</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
            '</p:childTnLst></p:seq>'
            f'<p:audio><p:cMediaNode vol="80"><p:cTn id="7" fill="hold" display="0"><p:stCondLst>'
            '<p:cond delay="0"/></p:stCondLst></p:cTn><p:tgtEl>'
            f'<p:spTgt spid="{sp_id}"/></p:tgtEl></p:cMediaNode></p:audio>'
            '</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>'
        )
        from lxml import etree
        timing = etree.fromstring(timing_xml)
        slide._element.append(timing)
    except Exception:
        pass
