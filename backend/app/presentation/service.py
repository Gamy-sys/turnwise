"""Orchestration: run the selected exporters over one project and bundle output.

Depends only on the exporter registry and the project model — it has no idea how
any single format is produced, so adding formats never touches this file.
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from .exporters.base import available, get_exporter
from .exporters.karaoke_scripts import basic_module, timing_feed, vba_module
from .project import PresentationProject


def available_formats() -> list[dict]:
    return available()


def generate(project: PresentationProject, out_dir: Path) -> list[Path]:
    """Write every requested format (+ karaoke sidecars) into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []

    formats = project.options.formats or ["pptx"]
    exporters = {f: get_exporter(f) for f in formats}

    for f, exp in exporters.items():
        dst = out_dir / f"presentation.{exp.extension}"
        exp.export(project, dst)
        produced.append(dst)

    karaoke_on = project.options.karaoke != "none"
    strategies = {e.karaoke_strategy for e in exporters.values()}

    # audio travels with the bundle so runtime scripts + players can find it
    if project.options.include_audio and project.audio and project.audio.path \
            and Path(project.audio.path).exists():
        audio_dst = out_dir / project.audio.filename
        if Path(project.audio.path).resolve() != audio_dst.resolve():
            shutil.copyfile(project.audio.path, audio_dst)
        produced.append(audio_dst)

    if karaoke_on and strategies & {"vba", "uno"}:
        feed = out_dir / "timing.txt"
        feed.write_text(timing_feed(project), encoding="utf-8")
        produced.append(feed)

    if karaoke_on and "vba" in strategies:
        bas = out_dir / "Karaoke.bas"
        bas.write_text(vba_module(project), encoding="utf-8")
        produced.append(bas)

    if karaoke_on and "uno" in strategies:
        bas = out_dir / "karaoke_libreoffice.bas"
        bas.write_text(basic_module(project), encoding="utf-8")
        produced.append(bas)

    return produced


def bundle(paths: list[Path], zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            if p.exists() and p.resolve() != zip_path.resolve():
                z.write(p, p.name)
    return zip_path
