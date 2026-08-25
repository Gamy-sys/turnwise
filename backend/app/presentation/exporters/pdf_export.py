"""PDF exporter: renders the shared slide model with reportlab (no Office needed)."""
from __future__ import annotations

from pathlib import Path

from ..project import PresentationProject, Slide, ThemeSpec
from .base import Exporter, register

_W, _H = 960.0, 540.0     # 13.333 x 7.5 in at 72 dpi (16:9)
_MARGIN = 48.0


def _wrap(text: str, width: int) -> list[str]:
    if width < 4:
        width = 4
    rows: list[str] = []
    line = ""
    for word in text.split(" "):
        while len(word) > width:            # hard-split absurdly long tokens
            if line:
                rows.append(line)
                line = ""
            rows.append(word[:width])
            word = word[width:]
        cand = word if not line else f"{line} {word}"
        if len(cand) <= width:
            line = cand
        else:
            if line:
                rows.append(line)
            line = word
    if line:
        rows.append(line)
    return rows or [""]


@register
class PdfExporter(Exporter):
    format_id = "pdf"
    extension = "pdf"
    media_type = "application/pdf"
    label = "PDF slides"

    def export(self, project: PresentationProject, dst: Path) -> Path:
        from reportlab.lib.colors import HexColor
        from reportlab.pdfgen import canvas

        theme = project.theme
        c = canvas.Canvas(str(dst), pagesize=(_W, _H))
        if project.options.include_title_slide:
            self._title_slide(c, HexColor, project)
        for slide in project.slides:
            self._slide(c, HexColor, slide, theme)
        c.save()
        return dst

    def _bg(self, c, HexColor, theme: ThemeSpec):
        c.setFillColor(HexColor(theme.bg))
        c.rect(0, 0, _W, _H, fill=1, stroke=0)

    def _title_slide(self, c, HexColor, project: PresentationProject):
        theme = project.theme
        self._bg(c, HexColor, theme)
        c.setFillColor(HexColor(theme.accent))
        c.setFont("Helvetica-Bold", 40)
        c.drawCentredString(_W / 2, _H / 2 + 10, project.title[:80])
        if project.subtitle:
            c.setFillColor(HexColor(theme.muted))
            c.setFont("Helvetica", 20)
            c.drawCentredString(_W / 2, _H / 2 - 26, project.subtitle[:100])
        c.setFillColor(HexColor(theme.muted))
        c.setFont("Helvetica", 14)
        c.drawCentredString(_W / 2, _MARGIN,
                            f"{project.meta.get('slide_count', 0)} slides · "
                            f"{project.meta.get('word_count', 0)} words")
        c.showPage()

    def _slide(self, c, HexColor, slide: Slide, theme: ThemeSpec):
        self._bg(c, HexColor, theme)
        fs = theme.font_size
        cw = c.stringWidth("m", "Courier", fs)
        maxchars = max(10, int((_W - 2 * _MARGIN) / cw))
        line_h = fs * 1.32

        c.setFillColor(HexColor(theme.accent))
        c.setFont("Helvetica-Bold", 22)
        c.drawString(_MARGIN, _H - _MARGIN, slide.title)

        y = _H - _MARGIN - 34
        for ln in slide.lines:
            npfx = ln.num_prefix or ""
            spfx = f"{ln.speaker or ''}  :    "
            nlen = len(npfx)
            plen = len(spfx)
            if ln.is_pause:
                wrapped = _wrap(ln.text, max(4, maxchars - nlen - plen))
                for i, seg in enumerate(wrapped):
                    y = self._newpage_if_needed(c, HexColor, theme, y)
                    if i == 0:
                        if npfx:
                            c.setFillColor(HexColor(theme.muted))
                            c.setFont("Courier", fs)
                            c.drawString(_MARGIN, y, npfx)
                        c.setFillColor(HexColor(theme.muted))
                        c.setFont("Courier", fs)
                        c.drawString(_MARGIN + nlen * cw, y, spfx)
                    c.setFillColor(HexColor(theme.muted))
                    c.setFont("Courier-Oblique", fs)
                    c.drawString(_MARGIN + (nlen + plen) * cw, y, seg)
                    y -= line_h
                continue
            wrapped = _wrap(ln.text, max(4, maxchars - nlen - plen))
            for i, seg in enumerate(wrapped):
                y = self._newpage_if_needed(c, HexColor, theme, y)
                if i == 0:
                    if npfx:
                        c.setFillColor(HexColor(theme.muted))
                        c.setFont("Courier", fs)
                        c.drawString(_MARGIN, y, npfx)
                    col = theme.speaker_colors.get(ln.speaker, theme.accent)
                    c.setFillColor(HexColor(col))
                    c.setFont("Courier-Bold", fs)
                    c.drawString(_MARGIN + nlen * cw, y, spfx)
                c.setFillColor(HexColor(theme.fg))
                c.setFont("Courier", fs)
                c.drawString(_MARGIN + (nlen + plen) * cw, y, seg)
                y -= line_h
        c.showPage()

    def _newpage_if_needed(self, c, HexColor, theme, y):
        if y < _MARGIN:
            c.showPage()
            self._bg(c, HexColor, theme)
            return _H - _MARGIN
        return y
