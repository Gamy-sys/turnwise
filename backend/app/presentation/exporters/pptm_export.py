"""PPTM exporter — macro-enabled PowerPoint (Strategy B).

Builds the .pptx package (static slides) then rewrites it into a macro-enabled
.pptm: the presentation content-type becomes ``...macroEnabled.main+xml`` and, if
a prebuilt ``assets/vbaProject.bin`` template is available, it is embedded and
wired up so the highlight macro is ready to run. The macro *source* and the
timing feed are always emitted as sidecars by the service, so users can import
the module even without the binary. Signing the VBA project requires the user's
own code-signing certificate and is intentionally left to them.
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from ..project import PresentationProject
from .base import Exporter, register
from .pptx_export import PptxExporter

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_MAIN_STD = ("application/vnd.openxmlformats-officedocument."
             "presentationml.presentation.main+xml")
_MAIN_MACRO = ("application/vnd.ms-powerpoint."
               "presentation.macroEnabled.main+xml")
_VBA_REL = "http://schemas.microsoft.com/office/2006/relationships/vbaProject"


@register
class PptmExporter(Exporter):
    format_id = "pptm"
    extension = "pptm"
    media_type = "application/vnd.ms-powerpoint.presentation.macroEnabled.12"
    label = "PowerPoint macro-enabled (.pptm)"
    supports_karaoke = True
    karaoke_strategy = "vba"

    def export(self, project: PresentationProject, dst: Path) -> Path:
        # 1) build a normal pptx (no native timeline; VBA drives the karaoke)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "base.pptx"
            saved = project.animations.strategy
            project.animations.strategy = "none"
            try:
                PptxExporter().export(project, base)
            finally:
                project.animations.strategy = saved
            self._to_macro_enabled(base, dst)
        return dst

    def _to_macro_enabled(self, src_pptx: Path, dst: Path):
        vba_bin = _ASSETS / "vbaProject.bin"
        embed = vba_bin.exists()
        with zipfile.ZipFile(src_pptx, "r") as zin, \
                zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    text = data.decode("utf-8").replace(_MAIN_STD, _MAIN_MACRO)
                    if embed and 'Extension="bin"' not in text:
                        text = text.replace(
                            "</Types>",
                            '<Default Extension="bin" '
                            'ContentType="application/vnd.ms-office.vbaProject"/></Types>')
                    data = text.encode("utf-8")
                elif item.filename == "ppt/_rels/presentation.xml.rels" and embed:
                    text = data.decode("utf-8").replace(
                        "</Relationships>",
                        f'<Relationship Id="rIdVba" Type="{_VBA_REL}" '
                        'Target="vbaProject.bin"/></Relationships>')
                    data = text.encode("utf-8")
                zout.writestr(item, data)
            if embed:
                zout.write(vba_bin, "ppt/vbaProject.bin")
