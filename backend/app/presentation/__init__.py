"""Presentation generation subsystem (a sub-app of the transcription app).

Clean-architecture layering — each concern lives on its own and depends only on
the layer below it:

    transcription  ->  builder  ->  PresentationProject  ->  exporters

* ``project``   : the one universal project model every exporter reads.
* ``builder``   : turns a Transcript (+ audio + word timings) into a project.
* ``exporters/``: pluggable format writers behind a single ``Exporter`` interface
                  and a registry, so new targets (Google Slides, Reveal.js, OBS…)
                  are added without touching transcription/builder code.
* ``service``   : orchestrates "build project -> run selected exporters -> bundle".

Nothing here imports the ASR/CA pipeline, so transcription and presentation stay
independently maintainable.
"""
from __future__ import annotations

from . import exporters  # noqa: F401  (registers all built-in exporters)
from .builder import build_project
from .project import (
    AnimationSpec,
    AudioRef,
    ExportOptions,
    PresentationProject,
    Slide,
    SlideLine,
    SpeakerInfo,
    ThemeSpec,
    WordTiming,
)
from .service import available_formats, generate

__all__ = [
    "build_project",
    "generate",
    "available_formats",
    "PresentationProject",
    "Slide",
    "SlideLine",
    "WordTiming",
    "SpeakerInfo",
    "ThemeSpec",
    "AudioRef",
    "AnimationSpec",
    "ExportOptions",
]
