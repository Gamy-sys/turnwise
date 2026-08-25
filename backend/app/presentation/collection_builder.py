"""Build one presentation from every clip in a collection, in collection order."""
from __future__ import annotations

import wave
from pathlib import Path

from .. import collections
from .builder import build_project
from .project import AudioRef, ExportOptions, PresentationProject, Slide, SlideLine


def _join_wavs(paths: list[Path], dst: Path) -> tuple[Path | None, list[float]]:
    """Concatenate compatible PCM clip WAVs and return exact clip durations."""
    durations: list[float] = []
    params = None
    writer = None
    try:
        for path in paths:
            if not path.exists():
                return None, []
            with wave.open(str(path), "rb") as src:
                current = (
                    src.getnchannels(),
                    src.getsampwidth(),
                    src.getframerate(),
                    src.getcomptype(),
                )
                if params is None:
                    params = current
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    writer = wave.open(str(dst), "wb")
                    writer.setnchannels(current[0])
                    writer.setsampwidth(current[1])
                    writer.setframerate(current[2])
                    writer.setcomptype(current[3], src.getcompname())
                elif current != params:
                    return None, []
                frames = src.getnframes()
                durations.append(frames / float(src.getframerate()))
                writer.writeframes(src.readframes(frames))
    finally:
        if writer is not None:
            writer.close()
    return (dst, durations) if paths else (None, [])


def build_collection_project(
    pid: str,
    cid: str,
    out_dir: Path,
    opts: ExportOptions,
) -> PresentationProject:
    """Combine collection clips without allowing a slide to cross clip boundaries.

    Every content slide generated from a clip receives that clip's label as its
    title. Clip word/audio times are shifted onto one continuous timeline.
    """
    meta = collections.load_collection(pid, cid)
    if not meta:
        raise FileNotFoundError("collection not found")
    elements = meta.get("elements") or []
    if not elements:
        raise ValueError("collection has no clips")

    clip_data = []
    wav_paths: list[Path] = []
    for element in elements:
        eid = element.get("id")
        tr = collections.load_element_transcript(pid, cid, eid)
        if tr is None:
            raise FileNotFoundError(f"transcript missing for clip {element.get('label') or eid}")
        wav = collections.element_audio_path(pid, cid, eid, "wav")
        clip_data.append((element, tr, wav))
        if wav is not None:
            wav_paths.append(wav)

    joined_audio = None
    exact_durations: list[float] = []
    if opts.include_audio and len(wav_paths) == len(clip_data):
        joined_audio, exact_durations = _join_wavs(wav_paths, out_dir / "collection_audio.wav")

    clip_opts = opts.model_copy(update={"include_title_slide": False, "formats": ["pptx"]})
    projects: list[tuple[dict, PresentationProject, float]] = []
    for index, (element, tr, _wav) in enumerate(clip_data):
        duration = (
            exact_durations[index]
            if index < len(exact_durations)
            else float(element.get("duration") or tr.meta.duration or 0)
        )
        projects.append((element, build_project(tr, None, clip_opts), duration))

    project = projects[0][1]
    project.project_id = f"{pid}:{cid}"
    project.title = opts.title or meta.get("label") or "Collection"
    project.subtitle = opts.subtitle or f"{len(projects)} clips"
    project.options = opts.model_copy(update={"formats": ["pptx"]})
    project.slides = []
    project.transcript_text = ""
    project.word_timings = []
    project.speakers = []
    project.theme.speaker_colors = {}

    speaker_ids: set[str] = set()
    elapsed = 0.0
    global_char = 0
    for element, clip_project, duration in projects:
        label = (element.get("label") or element.get("id") or "Clip").strip()

        for speaker in clip_project.speakers:
            if speaker.id not in speaker_ids:
                project.speakers.append(speaker)
                speaker_ids.add(speaker.id)
        project.theme.speaker_colors.update(clip_project.theme.speaker_colors)

        heading = f"{label}\n"
        separator = "\n\n" if project.transcript_text else ""
        project.transcript_text += separator + heading + clip_project.transcript_text
        global_char += len(separator) + len(heading)
        for word in clip_project.word_timings:
            shifted = word.model_copy(deep=True)
            shifted.start += elapsed
            shifted.end += elapsed
            shifted.char_start += global_char
            project.word_timings.append(shifted)
        global_char += len(clip_project.transcript_text)

        clip_slides = clip_project.slides
        if not clip_slides:
            clip_slides = [
                Slide(
                    index=0,
                    title=label,
                    body_text="(No transcript text)",
                    lines=[SlideLine(text="(No transcript text)", is_pause=True)],
                    notes=f"{label}\n\nNo transcript text.",
                    start=0,
                    end=duration,
                )
            ]

        for clip_slide in clip_slides:
            slide = clip_slide.model_copy(deep=True)
            slide.index = len(project.slides)
            slide.title = label
            slide.start += elapsed
            slide.end += elapsed
            slide.notes = f"{label}\n\n{slide.notes}" if slide.notes else label
            for line in slide.lines:
                line.start += elapsed
                line.end += elapsed
            for word in slide.words:
                word.start += elapsed
                word.end += elapsed
            for bookmark in slide.bookmarks:
                if isinstance(bookmark.get("time"), (int, float)):
                    bookmark["time"] = round(bookmark["time"] + elapsed, 3)
            project.slides.append(slide)
        elapsed += duration

    project.audio = (
        AudioRef(
            filename="collection_audio.wav",
            mime="audio/wav",
            duration=elapsed,
            sample_rate=16000,
            path=str(joined_audio),
        )
        if joined_audio is not None
        else None
    )
    project.meta.update(
        {
            "source": meta.get("label") or cid,
            "collection_id": cid,
            "clip_count": len(projects),
            "slide_count": len(project.slides),
            "word_count": len(project.word_timings),
            "duration": elapsed,
        }
    )
    return project
