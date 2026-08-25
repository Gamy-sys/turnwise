"""Plain-data exporters: universal project JSON, transcript TXT, SRT and VTT."""
from __future__ import annotations

import json
from pathlib import Path

from ..project import PresentationProject
from ._util import caption_segments, srt_time, vtt_time
from .base import Exporter, register


@register
class JsonExporter(Exporter):
    format_id = "json"
    extension = "json"
    media_type = "application/json"
    label = "Universal project (JSON)"

    def export(self, project: PresentationProject, dst: Path) -> Path:
        data = project.model_dump(by_alias=True, exclude_none=True)
        dst.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return dst


@register
class TxtExporter(Exporter):
    format_id = "txt"
    extension = "txt"
    media_type = "text/plain"
    label = "Transcript (TXT)"

    def export(self, project: PresentationProject, dst: Path) -> Path:
        dst.write_text(project.transcript_text + "\n", encoding="utf-8")
        return dst


@register
class SrtExporter(Exporter):
    format_id = "srt"
    extension = "srt"
    media_type = "application/x-subrip"
    label = "Subtitles (SRT)"

    def export(self, project: PresentationProject, dst: Path) -> Path:
        out = []
        for i, (start, end, text) in enumerate(caption_segments(project), start=1):
            out.append(str(i))
            out.append(f"{srt_time(start)} --> {srt_time(max(end, start + 0.2))}")
            out.append(text)
            out.append("")
        dst.write_text("\n".join(out) + "\n", encoding="utf-8")
        return dst


@register
class VttExporter(Exporter):
    format_id = "vtt"
    extension = "vtt"
    media_type = "text/vtt"
    label = "Subtitles (WebVTT)"

    def export(self, project: PresentationProject, dst: Path) -> Path:
        out = ["WEBVTT", ""]
        for start, end, text in caption_segments(project):
            out.append(f"{vtt_time(start)} --> {vtt_time(max(end, start + 0.2))}")
            out.append(text)
            out.append("")
        dst.write_text("\n".join(out) + "\n", encoding="utf-8")
        return dst
