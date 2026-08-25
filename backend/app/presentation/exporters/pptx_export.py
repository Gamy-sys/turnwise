"""PPTX exporter — standards-compliant Office Open XML via python-pptx.

No COM automation: python-pptx writes the OOXML package directly. Each slide
carries title, transcript, speaker-coloured text, speaker notes and metadata.

Karaoke Strategy A (native PowerPoint animation timeline) is injected as a
``<p:timing>`` tree whose per-word colour emphases target **character ranges**
(``charRg``) on the transcript text box — i.e. it highlights by character
position, never by searching. The timing tree is structurally valid OOXML; if a
build ever fails it is skipped, leaving clean static slides (never a corrupt file).
"""
from __future__ import annotations

from pathlib import Path

from ..project import PresentationProject, Slide, ThemeSpec
from .base import Exporter, register

_EMU_IN = 914400
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _hex(c: str) -> str:
    return c.lstrip("#").upper()[:6].ljust(6, "0")


@register
class PptxExporter(Exporter):
    format_id = "pptx"
    extension = "pptx"
    media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    label = "PowerPoint (.pptx)"
    supports_karaoke = True
    karaoke_strategy = "timeline"

    def export(self, project: PresentationProject, dst: Path) -> Path:
        from pptx import Presentation
        from pptx.util import Inches

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        self._core_props(prs, project)

        if project.options.include_title_slide:
            self._title_slide(prs, project)

        want_karaoke = project.animations.strategy in ("timeline", "auto")
        for slide in project.slides:
            self._content_slide(prs, project, slide, karaoke=want_karaoke)

        prs.save(str(dst))
        return dst

    # -- pieces --------------------------------------------------------------
    def _core_props(self, prs, project: PresentationProject):
        cp = prs.core_properties
        cp.title = project.title
        cp.author = "CA Studio"
        cp.subject = "Conversation-analysis transcript"
        cp.keywords = "transcript,karaoke,conversation-analysis"
        cp.comments = (f"{project.meta.get('slide_count', 0)} slides, "
                       f"{project.meta.get('word_count', 0)} words, "
                       f"{project.meta.get('duration', 0):.1f}s audio")

    def _bg(self, slide, theme: ThemeSpec):
        from pptx.dml.color import RGBColor
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(_hex(theme.bg))

    def _title_slide(self, prs, project: PresentationProject):
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
        from pptx.util import Inches, Pt

        theme = project.theme
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        self._bg(slide, theme)
        tb = slide.shapes.add_textbox(Inches(0.8), Inches(2.6), Inches(11.7), Inches(2.3))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = project.title
        r.font.size = Pt(theme.title_size + 8)
        r.font.bold = True
        r.font.name = theme.title_font
        r.font.color.rgb = RGBColor.from_string(_hex(theme.accent))
        if project.subtitle:
            p2 = tf.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            r2 = p2.add_run()
            r2.text = project.subtitle
            r2.font.size = Pt(theme.font_size)
            r2.font.name = theme.title_font
            r2.font.color.rgb = RGBColor.from_string(_hex(theme.muted))
        if project.options.include_audio and project.audio and project.audio.path:
            self._embed_audio(slide, project)

    def _content_slide(self, prs, project: PresentationProject, slide_m: Slide, karaoke: bool):
        from pptx.dml.color import RGBColor
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Inches, Pt

        theme = project.theme
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        self._bg(slide, theme)

        # title (timecode)
        tt = slide.shapes.add_textbox(Inches(0.5), Inches(0.25), Inches(12.3), Inches(0.6))
        tp = tt.text_frame.paragraphs[0]
        rr = tp.add_run()
        rr.text = slide_m.title
        rr.font.size = Pt(theme.font_size + 2)
        rr.font.bold = True
        rr.font.name = theme.title_font
        rr.font.color.rgb = RGBColor.from_string(_hex(theme.accent))

        # transcript body — one paragraph per line; runs coloured by role
        body = slide.shapes.add_textbox(Inches(0.5), Inches(1.0), Inches(12.3), Inches(6.2))
        tf = body.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.TOP
        first = True
        for ln in slide_m.lines:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.space_after = Pt(max(4, theme.font_size // 3))
            if ln.num_prefix:
                rn = p.add_run()
                rn.text = ln.num_prefix
                rn.font.size = Pt(theme.font_size)
                rn.font.name = theme.body_font
                rn.font.color.rgb = RGBColor.from_string(_hex(theme.muted))
            # CA layout: name + 2 spaces + colon + 4 spaces (empty name on pauses)
            spfx = f"{ln.speaker or ''}  :    "
            if ln.is_pause:
                rs = p.add_run()
                rs.text = spfx
                rs.font.size = Pt(theme.font_size)
                rs.font.name = theme.body_font
                rs.font.color.rgb = RGBColor.from_string(_hex(theme.muted))
                r = p.add_run()
                r.text = ln.text
                r.font.italic = True
                r.font.size = Pt(theme.font_size)
                r.font.name = theme.body_font
                r.font.color.rgb = RGBColor.from_string(_hex(theme.muted))
                continue
            r1 = p.add_run()
            r1.text = spfx
            r1.font.bold = True
            r1.font.size = Pt(theme.font_size)
            r1.font.name = theme.body_font
            spk_col = theme.speaker_colors.get(ln.speaker, theme.accent)
            r1.font.color.rgb = RGBColor.from_string(_hex(spk_col))
            r2 = p.add_run()
            r2.text = ln.text
            r2.font.size = Pt(theme.font_size)
            r2.font.name = theme.body_font
            r2.font.color.rgb = RGBColor.from_string(_hex(theme.fg))

        if project.options.include_notes and slide_m.notes:
            slide.notes_slide.notes_text_frame.text = slide_m.notes

        if karaoke and slide_m.words:
            try:
                self._inject_karaoke(slide, body, slide_m, theme)
            except Exception as e:  # never corrupt the deck over an animation
                print("pptx karaoke timeline skipped:", e)

    def _embed_audio(self, slide, project: PresentationProject):
        from pptx.util import Inches
        try:
            slide.shapes.add_movie(
                project.audio.path, Inches(12.4), Inches(6.6), Inches(0.6), Inches(0.6),
                mime_type=project.audio.mime,
            )
        except Exception as e:
            print("pptx audio embed skipped:", e)

    # -- Strategy A: native animation timeline (charRg colour emphasis) ------
    def _inject_karaoke(self, slide, body_shape, slide_m: Slide, theme: ThemeSpec):
        from lxml import etree

        spid = body_shape.shape_id
        hi = _hex(theme.highlight_bg)
        base = slide_m.start
        words = sorted(slide_m.words, key=lambda w: w.start)

        effects = []
        _id = [10]

        def nid():
            _id[0] += 1
            return _id[0]

        prev = base
        for i, w in enumerate(words):
            delay = int(round(max(0.0, (w.start - prev)) * 1000))
            prev = w.start
            node_type = "clickEffect" if i == 0 else "withEffect"
            cs = w.char_start
            ce = w.char_start + w.char_length
            effects.append(
                f'<p:par><p:cTn id="{nid()}" presetID="2" presetClass="emph" '
                f'presetSubtype="0" fill="hold" grpId="0" nodeType="{node_type}">'
                f'<p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>'
                f'<p:animClr clrSpc="rgb"><p:cBhvr><p:cTn id="{nid()}" dur="1" fill="hold"/>'
                f'<p:tgtEl><p:spTgt spid="{spid}"><p:txEl>'
                f'<p:charRg st="{cs}" end="{ce}"/></p:txEl></p:spTgt></p:tgtEl>'
                f'<p:attrNameLst><p:attrName>style.color</p:attrName></p:attrNameLst>'
                f'</p:cBhvr><p:to><a:srgbClr val="{hi}"/></p:to></p:animClr>'
                f'</p:childTnLst></p:cTn></p:par>'
            )

        timing = (
            f'<p:timing xmlns:p="{_P}" xmlns:a="{_A}"><p:tnLst>'
            f'<p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">'
            f'<p:childTnLst><p:seq concurrent="1" nextAc="seek">'
            f'<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
            f'<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
            f'</p:stCondLst><p:childTnLst>'
            f'<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            f'<p:childTnLst>{"".join(effects)}</p:childTnLst></p:cTn></p:par>'
            f'</p:childTnLst></p:cTn></p:par>'
            f'</p:childTnLst></p:cTn></p:seq>'
            f'<p:cond evt="onBegin" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond>'
            f'</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>'
        )
        slide._element.append(etree.fromstring(timing))
