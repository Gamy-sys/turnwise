"""Importing this package registers every built-in exporter.

Add a new format by dropping a module here that defines an ``Exporter`` subclass
decorated with ``@register`` and importing it below — nothing else changes.
"""
from __future__ import annotations

from . import (  # noqa: F401  (import side effect: registration)
    odp_export,
    pdf_export,
    pptm_export,
    pptx_export,
    text_exports,
)
from .base import available, get_exporter, register

__all__ = ["available", "get_exporter", "register"]
