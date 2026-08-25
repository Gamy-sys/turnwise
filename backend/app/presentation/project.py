"""The universal presentation project model.

This is the single source of truth every exporter reads. Transcription writes it
(via ``builder``) and never needs to know which formats exist; exporters read it
and never need to know how transcription works.

Word timing follows the agreed contract: highlighting is driven by **character
positions** (``char_start`` / ``char_length``) into a known text string — never by
searching for words — so the same data drives PowerPoint, LibreOffice and web.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class WordTiming(BaseModel):
    """One spoken word, addressable by character range inside its host text.

    ``char_start``/``char_length`` are offsets into the *slide's* ``body_text``
    when attached to a :class:`Slide`, and into the project's ``transcript_text``
    when attached to the project. Serialises with the camelCase keys the spec
    uses (``charStart``/``charLength``).
    """

    model_config = ConfigDict(populate_by_name=True)

    word: str
    start: float
    end: float
    char_start: int = Field(0, alias="charStart")
    char_length: int = Field(0, alias="charLength")
    speaker: str = ""


class SpeakerInfo(BaseModel):
    id: str
    label: str
    color: str = "#f0c674"


class AudioRef(BaseModel):
    """Narration audio. ``path`` is a local absolute path used at export time; it
    is dropped from any serialised project so JSON stays portable."""

    filename: str = "audio.mp3"
    mime: str = "audio/mpeg"
    duration: float = 0.0
    sample_rate: int = 0
    path: Optional[str] = Field(default=None, exclude=True)


class ThemeSpec(BaseModel):
    name: str = "dark"
    bg: str = "#0d1117"
    fg: str = "#e6edf3"
    accent: str = "#f0c674"
    muted: str = "#8b949e"
    highlight_bg: str = "#f0c674"   # karaoke: active-word background
    highlight_fg: str = "#0d1117"   # karaoke: active-word text
    body_font: str = "Consolas"
    title_font: str = "Segoe UI"
    font_size: int = 20
    title_size: int = 30
    speaker_colors: dict[str, str] = Field(default_factory=dict)


class AnimationSpec(BaseModel):
    """Which karaoke rendering strategy the generator resolved for a format.

    * ``timeline`` — native PowerPoint animation timeline (Strategy A)
    * ``vba``      — VBA runtime highlighting in .pptm (Strategy B)
    * ``uno``      — LibreOffice Basic/UNO runtime highlighting in .odp (Strategy C)
    * ``video``    — pre-rendered highlight video (always-works fallback)
    * ``none``     — static slides, no karaoke
    """

    strategy: str = "none"
    per_word: bool = True


class SlideLine(BaseModel):
    """One rendered line of a slide's transcript body."""

    speaker: Optional[str] = None
    text: str = ""             # line content WITHOUT the line-number gutter
    no: int = 0                # sequential line number (0 = unnumbered)
    num_prefix: str = ""       # the exact gutter string prepended in body_text
    is_pause: bool = False
    char_start: int = 0        # offset of this line inside Slide.body_text
    char_length: int = 0
    start: float = 0.0
    end: float = 0.0
    word_indices: list[int] = Field(default_factory=list)  # into Slide.words


class Slide(BaseModel):
    index: int
    title: str = ""
    body_text: str = ""                 # the transcript text shown on the slide
    lines: list[SlideLine] = Field(default_factory=list)
    words: list[WordTiming] = Field(default_factory=list)  # offsets into body_text
    notes: str = ""
    start: float = 0.0
    end: float = 0.0
    bookmarks: list[dict[str, Any]] = Field(default_factory=list)


class ExportOptions(BaseModel):
    title: str = "Transcript"
    subtitle: str = ""
    theme: str = "dark"                 # dark | light
    font_size: int = 20
    chunk_mode: str = "auto"            # auto (fit) | time | turn
    max_lines_per_slide: int = 0        # 0 = derive from font size
    seconds_per_slide: float = 20.0     # for chunk_mode == "time"
    line_numbers: bool = True           # number every line (incl. pauses), CA style
    karaoke: str = "auto"               # auto | timeline | vba | uno | video | none
    include_audio: bool = True
    include_notes: bool = True
    include_title_slide: bool = True
    formats: list[str] = Field(default_factory=lambda: ["pptx"])


class PresentationProject(BaseModel):
    """One project, read by every exporter."""

    project_id: str
    title: str = "Transcript"
    subtitle: str = ""
    transcript_text: str = ""
    audio: Optional[AudioRef] = None
    speakers: list[SpeakerInfo] = Field(default_factory=list)
    slides: list[Slide] = Field(default_factory=list)
    word_timings: list[WordTiming] = Field(default_factory=list)  # global offsets
    theme: ThemeSpec = Field(default_factory=ThemeSpec)
    fonts: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    animations: AnimationSpec = Field(default_factory=AnimationSpec)
    options: ExportOptions = Field(default_factory=ExportOptions)
    meta: dict[str, Any] = Field(default_factory=dict)
