"""ODP exporter — LibreOffice Impress package written directly as OpenDocument.

Produces a valid ``.odp`` zip (mimetype, content.xml, styles.xml, meta.xml,
manifest, embedded audio + timing.json). Karaoke Strategy C (a LibreOffice
Basic/UNO macro that highlights by character position while the audio plays) is
emitted by the service as a runnable sidecar, since Impress blocks embedded
macros by default — the timing it reads is stored in the package as timing.json.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from ..project import PresentationProject, Slide
from .base import Exporter, register

_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)


def _styles_xml(theme) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-styles {_NS} office:version="1.2">'
        '<office:styles/>'
        '<office:automatic-styles>'
        '<style:page-layout style:name="PL"><style:page-layout-properties '
        'fo:page-width="33.867cm" fo:page-height="19.05cm" '
        'style:print-orientation="landscape"/></style:page-layout>'
        '<style:style style:name="dpMaster" style:family="drawing-page"/>'
        '</office:automatic-styles>'
        '<office:master-styles>'
        '<style:master-page style:name="Default" style:page-layout-name="PL" '
        'draw:style-name="dpMaster"/>'
        '</office:master-styles>'
        '</office:document-styles>'
    )


def _meta_xml(project: PresentationProject) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-meta '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" office:version="1.2"><office:meta>'
        f'<dc:title>{escape(project.title)}</dc:title>'
        '<meta:generator>CA Studio</meta:generator>'
        f'<meta:document-statistic meta:page-count="{len(project.slides)}"/>'
        '</office:meta></office:document-meta>'
    )


def _auto_styles(theme) -> str:
    fs = theme.font_size
    return (
        '<office:automatic-styles>'
        '<style:style style:name="dp1" style:family="drawing-page">'
        f'<style:drawing-page-properties draw:fill="solid" draw:fill-color="{theme.bg}" '
        'presentation:background-visible="true" presentation:background-objects-visible="true"/>'
        '</style:style>'
        '<style:style style:name="frm" style:family="graphic">'
        '<style:graphic-properties draw:fill="none" draw:stroke="none" '
        'draw:auto-grow-height="true" fo:padding="0.1cm"/></style:style>'
        '<style:style style:name="pTitle" style:family="paragraph">'
        f'<style:text-properties fo:color="{theme.accent}" fo:font-size="{fs + 2}pt" '
        f'fo:font-weight="bold" style:font-name="{escape(theme.title_font)}"/></style:style>'
        '<style:style style:name="pBody" style:family="paragraph">'
        f'<style:paragraph-properties fo:margin-bottom="0.12cm"/>'
        f'<style:text-properties fo:color="{theme.fg}" fo:font-size="{fs}pt" '
        f'style:font-name="{escape(theme.body_font)}"/></style:style>'
        '<style:style style:name="tSpk" style:family="text">'
        f'<style:text-properties fo:color="{theme.accent}" fo:font-weight="bold"/></style:style>'
        '<style:style style:name="tPause" style:family="text">'
        f'<style:text-properties fo:color="{theme.muted}" fo:font-style="italic"/></style:style>'
        '<style:style style:name="tNum" style:family="text">'
        f'<style:text-properties fo:color="{theme.muted}"/></style:style>'
        '<style:style style:name="pDeck" style:family="paragraph">'
        '<style:paragraph-properties fo:text-align="center"/>'
        f'<style:text-properties fo:color="{theme.accent}" fo:font-size="{fs * 2}pt" '
        f'fo:font-weight="bold" style:font-name="{escape(theme.title_font)}"/></style:style>'
        '<style:style style:name="pSub" style:family="paragraph">'
        '<style:paragraph-properties fo:text-align="center"/>'
        f'<style:text-properties fo:color="{theme.muted}" fo:font-size="{fs}pt" '
        f'style:font-name="{escape(theme.title_font)}"/></style:style>'
        '</office:automatic-styles>'
    )


def _title_page(project: PresentationProject) -> str:
    sub = (f'<text:p text:style-name="pSub">{escape(project.subtitle)}</text:p>'
           if project.subtitle else "")
    return (
        '<draw:page draw:name="title" draw:style-name="dp1" '
        'draw:master-page-name="Default">'
        '<draw:frame draw:style-name="frm" svg:width="28cm" svg:height="6cm" '
        'svg:x="2.9cm" svg:y="6.5cm"><draw:text-box>'
        f'<text:p text:style-name="pDeck">{escape(project.title)}</text:p>'
        f'{sub}</draw:text-box></draw:frame></draw:page>'
    )


def _page(slide: Slide, theme, include_notes: bool) -> str:
    paras = []
    for ln in slide.lines:
        num = (f'<text:span text:style-name="tNum">{escape(ln.num_prefix)}</text:span>'
               if ln.num_prefix else "")
        spfx = f"{ln.speaker or ''}  :    "
        if ln.is_pause:
            paras.append(
                f'<text:p text:style-name="pBody">{num}'
                f'<text:span text:style-name="tPause">{escape(spfx)}</text:span>'
                f'<text:span text:style-name="tPause">{escape(ln.text)}</text:span></text:p>')
            continue
        paras.append(
            f'<text:p text:style-name="pBody">{num}'
            f'<text:span text:style-name="tSpk">{escape(spfx)}</text:span>'
            f'{escape(ln.text)}</text:p>')
    body = "".join(paras) or '<text:p text:style-name="pBody"/>'

    notes = ""
    if include_notes and slide.notes:
        note_ps = "".join(f'<text:p>{escape(x)}</text:p>' for x in slide.notes.split("\n"))
        notes = ('<presentation:notes draw:style-name="dp1">'
                 '<draw:frame draw:style-name="frm" svg:width="17cm" svg:height="10cm" '
                 'svg:x="2cm" svg:y="5cm"><draw:text-box>'
                 f'{note_ps}</draw:text-box></draw:frame></presentation:notes>')

    return (
        f'<draw:page draw:name="page{slide.index + 1}" '
        'draw:style-name="dp1" draw:master-page-name="Default">'
        '<draw:frame draw:style-name="frm" svg:width="31.8cm" svg:height="1.6cm" '
        'svg:x="1cm" svg:y="0.6cm"><draw:text-box>'
        f'<text:p text:style-name="pTitle">{escape(slide.title)}</text:p>'
        '</draw:text-box></draw:frame>'
        '<draw:frame draw:style-name="frm" svg:width="31.8cm" svg:height="15.8cm" '
        'svg:x="1cm" svg:y="2.4cm"><draw:text-box>'
        f'{body}</draw:text-box></draw:frame>'
        f'{notes}</draw:page>'
    )


def _content_xml(project: PresentationProject) -> str:
    pages = _title_page(project) if project.options.include_title_slide else ""
    pages += "".join(_page(s, project.theme, project.options.include_notes)
                     for s in project.slides)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content {_NS} office:version="1.2">'
        f'{_auto_styles(project.theme)}'
        '<office:body><office:presentation>'
        f'{pages}'
        '</office:presentation></office:body></office:document-content>'
    )


def _manifest_xml(entries: list[tuple[str, str]]) -> str:
    rows = ''.join(
        f'<manifest:file-entry manifest:full-path="{escape(p)}" '
        f'manifest:media-type="{escape(m)}"/>'
        for p, m in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest:manifest '
        'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.2">'
        '<manifest:file-entry manifest:full-path="/" '
        'manifest:media-type="application/vnd.oasis.opendocument.presentation"/>'
        f'{rows}</manifest:manifest>'
    )


@register
class OdpExporter(Exporter):
    format_id = "odp"
    extension = "odp"
    media_type = "application/vnd.oasis.opendocument.presentation"
    label = "LibreOffice Impress (.odp)"
    supports_karaoke = True
    karaoke_strategy = "uno"

    def export(self, project: PresentationProject, dst: Path) -> Path:
        entries = [
            ("content.xml", "text/xml"),
            ("styles.xml", "text/xml"),
            ("meta.xml", "text/xml"),
        ]
        timing = {
            "words": [w.model_dump(by_alias=True) for w in project.word_timings],
            "slides": [
                {"index": s.index, "start": s.start, "end": s.end,
                 "words": [w.model_dump(by_alias=True) for w in s.words]}
                for s in project.slides
            ],
        }
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            # mimetype must be first and stored (uncompressed)
            zi = zipfile.ZipInfo("mimetype")
            zi.compress_type = zipfile.ZIP_STORED
            z.writestr(zi, "application/vnd.oasis.opendocument.presentation")
            z.writestr("content.xml", _content_xml(project))
            z.writestr("styles.xml", _styles_xml(project.theme))
            z.writestr("meta.xml", _meta_xml(project))
            z.writestr("timing.json", json.dumps(timing, ensure_ascii=False))
            entries.append(("timing.json", "application/json"))
            if project.options.include_audio and project.audio and project.audio.path \
                    and Path(project.audio.path).exists():
                media = f"Media/{project.audio.filename}"
                z.write(project.audio.path, media)
                entries.append((media, project.audio.mime))
            z.writestr("META-INF/manifest.xml", _manifest_xml(entries))
        return dst
