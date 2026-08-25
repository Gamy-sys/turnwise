"""Exporter interface + registry.

Every output format implements :class:`Exporter` and registers itself with
``@register``. New targets (Google Slides, Keynote, Reveal.js, OBS captions,
DaVinci/Premiere/CapCut/After Effects…) are added by dropping a new module in
this package — no changes to the builder, project model or transcription code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..project import PresentationProject


class Exporter(ABC):
    format_id: str = ""
    extension: str = ""
    media_type: str = "application/octet-stream"
    label: str = ""
    #: karaoke strategy this format uses when options.karaoke == "auto"
    karaoke_strategy: str = "none"
    #: whether the format understands karaoke highlighting at all
    supports_karaoke: bool = False

    @abstractmethod
    def export(self, project: PresentationProject, dst: Path) -> Path:
        """Write ``project`` to ``dst`` and return the path actually written."""


_REGISTRY: dict[str, Exporter] = {}


def register(cls: type[Exporter]) -> type[Exporter]:
    inst = cls()
    if not inst.format_id:
        raise ValueError(f"{cls.__name__} has no format_id")
    _REGISTRY[inst.format_id] = inst
    return cls


def get_exporter(fmt: str) -> Exporter:
    try:
        return _REGISTRY[fmt]
    except KeyError:
        raise KeyError(f"no exporter for format {fmt!r}; "
                       f"have {sorted(_REGISTRY)}")


def available() -> list[dict]:
    return [
        {
            "id": e.format_id,
            "extension": e.extension,
            "label": e.label or e.format_id.upper(),
            "karaoke": e.supports_karaoke,
            "strategy": e.karaoke_strategy,
        }
        for e in sorted(_REGISTRY.values(), key=lambda x: x.format_id)
    ]
