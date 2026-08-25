"""Build a :class:`PresentationProject` from a transcript + audio + word timings.

This is the *only* place that knows about the transcript data model. Exporters
depend on the resulting project, not on the transcript, so transcription can
evolve without touching any exporter.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from ..models import Transcript
from .project import (
    AudioRef,
    ExportOptions,
    PresentationProject,
    Slide,
    SlideLine,
    SpeakerInfo,
    ThemeSpec,
    WordTiming,
)

_NONSPEECH = {"laughter", "in_breath", "out_breath"}

_PALETTE = ["#f0c674", "#79c0ff", "#7ee787", "#ff7b72", "#d2a8ff", "#ffa657"]

_THEMES = {
    "dark": dict(bg="#0d1117", fg="#e6edf3", accent="#f0c674", muted="#8b949e",
                 highlight_bg="#f0c674", highlight_fg="#0d1117"),
    "light": dict(bg="#ffffff", fg="#1b1f24", accent="#b26a00", muted="#6a737d",
                  highlight_bg="#ffe08a", highlight_fg="#1b1f24"),
}


def _mmss(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60):d}:{int(t % 60):02d}"


class _Row:
    """A pre-slice unit: either a speaker turn (with word tokens) or a pause."""

    __slots__ = ("speaker", "label", "tokens", "is_pause", "pause_text", "start", "end")

    def __init__(self, speaker, label, tokens, is_pause, pause_text, start, end):
        self.speaker = speaker
        self.label = label
        self.tokens = tokens
        self.is_pause = is_pause
        self.pause_text = pause_text
        self.start = start
        self.end = end


def _rows(tr: Transcript, labels: dict[str, str]) -> list[_Row]:
    rows: list[_Row] = []
    for turn in tr.turns:
        if not turn.speaker:  # standalone pause line
            sym = turn.tokens[0].cues[0].symbol if turn.tokens and turn.tokens[0].cues else "(.)"
            rows.append(_Row(None, None, [], True, sym, turn.start, turn.end))
            continue
        toks = [t for t in turn.tokens
                if t.text.strip() and not any(c.type in _NONSPEECH for c in t.cues)]
        if not toks:
            continue
        rows.append(_Row(turn.speaker, labels.get(turn.speaker, turn.speaker),
                         toks, False, "", toks[0].start, toks[-1].end))
    return rows


# Non-breaking space: keeps the number gutter aligned and, unlike ASCII spaces,
# is never collapsed by OpenDocument and counts as one character everywhere
# (Python len, OOXML charRg, VBA/Basic goRight) so karaoke offsets stay valid.
_NBSP = "\u00a0"


def _num_prefix(n: int, width: int) -> str:
    """``{number}{3 nbsp}`` — first half of the CA line layout."""
    return f"{n}".rjust(width, _NBSP) + (_NBSP * 3)


def _spk_prefix(label: str | None) -> str:
    """``{name}{2 nbsp}:{4 nbsp}`` — second half of the CA line layout."""
    name = (label or "").strip()
    return f"{name}{_NBSP * 2}:{_NBSP * 4}"


def _render(rows: list[_Row], start_no: int = 0,
            width: int = 0) -> tuple[str, list[WordTiming], list[SlideLine], int]:
    """Render rows into body text + char-addressable word timings + lines.

    Each line uses the CA spacing contract
    ``number + 3 spaces + name + 2 spaces + colon + 4 spaces + talk``
    (nbsp so ODF/OOXML never collapse the gutter). Returns the next line
    number to continue from.
    """
    numbering = start_no > 0
    n = start_no
    parts: list[str] = []
    words: list[WordTiming] = []
    lines: list[SlideLine] = []
    cur = 0
    for row in rows:
        line_cs = cur
        npfx = _num_prefix(n, width) if numbering else ""
        if npfx:
            parts.append(npfx)
            cur += len(npfx)
        if row.is_pause:
            spfx = _spk_prefix("")
            parts.append(spfx)
            cur += len(spfx)
            parts.append(row.pause_text)
            cur += len(row.pause_text)
            lines.append(SlideLine(speaker=None, text=row.pause_text, no=n,
                                    num_prefix=npfx, is_pause=True,
                                    char_start=line_cs, char_length=cur - line_cs,
                                    start=row.start, end=row.end))
            parts.append("\n")
            cur += 1
            n += 1
            continue
        prefix = _spk_prefix(row.label)
        parts.append(prefix)
        cur += len(prefix)
        widx: list[int] = []
        for i, tok in enumerate(row.tokens):
            if i:
                parts.append(" ")
                cur += 1
            cs = cur
            parts.append(tok.text)
            cur += len(tok.text)
            widx.append(len(words))
            words.append(WordTiming(word=tok.text, start=tok.start, end=tok.end,
                                    char_start=cs, char_length=len(tok.text),
                                    speaker=row.label))
        lines.append(SlideLine(
            speaker=row.label,
            text=" ".join(t.text for t in row.tokens),
            no=n, num_prefix=npfx,
            is_pause=False, char_start=line_cs, char_length=cur - line_cs,
            start=row.tokens[0].start, end=row.tokens[-1].end, word_indices=widx))
        parts.append("\n")
        cur += 1
        n += 1
    return "".join(parts).rstrip("\n"), words, lines, n


def _fit_lines_per_slide(font_size: int) -> tuple[int, int]:
    """(chars_per_line, lines_per_slide) estimate for a 16:9 monospace slide."""
    char_w = 0.55 * font_size / 72.0
    line_h = 1.22 * font_size / 72.0
    cpl = max(24, int((13.333 - 1.0) / char_w))
    lps = max(4, int((7.5 - 0.9 - 0.7) / (line_h * 1.12)))  # leave room for a title
    return cpl, lps


def _chunk(rows: list[_Row], opts: ExportOptions) -> list[list[_Row]]:
    if not rows:
        return []
    if opts.chunk_mode == "time":
        span = max(2.0, float(opts.seconds_per_slide))
        pages: list[list[_Row]] = []
        cur: list[_Row] = []
        base: Optional[float] = None
        for r in rows:
            if base is None:
                base = r.start
            if cur and r.start - base > span:
                pages.append(cur)
                cur, base = [], r.start
            cur.append(r)
        if cur:
            pages.append(cur)
        return pages

    # "auto"/"turn": greedy pack by estimated wrapped-line count
    cpl, lps = _fit_lines_per_slide(opts.font_size)
    if opts.max_lines_per_slide:
        lps = opts.max_lines_per_slide
    pages, cur, used = [], [], 0
    for r in rows:
        length = len(r.pause_text) if r.is_pause else len(f"{r.label}: ") + sum(
            len(t.text) + 1 for t in r.tokens)
        wl = max(1, math.ceil(length / cpl))
        if used + wl > lps and cur:
            pages.append(cur)
            cur, used = [], 0
        cur.append(r)
        used += wl
    if cur:
        pages.append(cur)
    return pages


def build_project(tr: Transcript, audio_path: Optional[str],
                  opts: Optional[ExportOptions] = None) -> PresentationProject:
    opts = opts or ExportOptions()

    labels = {s.id: s.label for s in tr.speakers}
    speakers = [SpeakerInfo(id=s.id, label=s.label,
                            color=_PALETTE[i % len(_PALETTE)])
                for i, s in enumerate(tr.speakers)]
    spk_colors = {s.label: s.color for s in speakers}

    tp = _THEMES.get(opts.theme, _THEMES["dark"])
    theme = ThemeSpec(name=opts.theme, font_size=opts.font_size,
                      title_size=max(opts.font_size + 8, 24),
                      speaker_colors=spk_colors, **tp)

    rows = _rows(tr, labels)
    global_text, global_words, _, _ = _render(rows)

    width = len(str(max(1, len(rows))))
    line_no = 1 if opts.line_numbers else 0

    slides: list[Slide] = []
    for idx, page in enumerate(_chunk(rows, opts)):
        body, words, lines, line_no = _render(page, start_no=line_no, width=width)
        start = page[0].start
        end = page[-1].end
        bookmarks = [
            {"name": f"w{idx}_{wi}", "time": round(w.start, 3),
             "char_start": w.char_start, "char_length": w.char_length, "word": w.word}
            for wi, w in enumerate(words)
        ]
        spk_here = sorted({ln.speaker for ln in lines if ln.speaker})
        notes = (f"Slide {idx + 1} · {_mmss(start)}–{_mmss(end)} · "
                 f"speakers: {', '.join(spk_here) or '—'} · {len(words)} words\n\n"
                 + "\n".join(ln.text for ln in lines))
        slides.append(Slide(index=idx, title=f"{_mmss(start)}–{_mmss(end)}",
                             body_text=body, lines=lines, words=words, notes=notes,
                             start=start, end=end, bookmarks=bookmarks))

    audio = None
    if audio_path and Path(audio_path).exists():
        ext = Path(audio_path).suffix.lstrip(".").lower() or "mp3"
        mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
                "ogg": "audio/ogg", "flac": "audio/flac"}.get(ext, "audio/mpeg")
        audio = AudioRef(filename=f"audio.{ext}", mime=mime,
                         duration=tr.meta.duration, sample_rate=tr.meta.sample_rate,
                         path=str(audio_path))

    return PresentationProject(
        project_id=tr.meta.project_id,
        title=opts.title or (tr.meta.filename or "Transcript"),
        subtitle=opts.subtitle,
        transcript_text=global_text,
        audio=audio,
        speakers=speakers,
        slides=slides,
        word_timings=global_words,
        theme=theme,
        fonts=[theme.body_font, theme.title_font],
        animations=_resolve_animation(opts),
        options=opts,
        meta={
            "duration": tr.meta.duration,
            "created_at": tr.meta.created_at,
            "source": tr.meta.filename,
            "models": tr.meta.models,
            "slide_count": len(slides),
            "word_count": len(global_words),
        },
    )


def _resolve_animation(opts: ExportOptions):
    from .project import AnimationSpec
    return AnimationSpec(strategy=opts.karaoke if opts.karaoke != "auto" else "auto")
