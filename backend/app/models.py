"""Pydantic models: the single source of truth for a transcript.

The auto pipeline fills `tokens`/`turns` with cues that carry their *evidence*
(the measured numbers). User edits are stored non-destructively in `overrides`
so any stage can be re-run without losing manual corrections.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


CueType = Literal[
    "pause", "micropause", "latch", "overlap", "elongation",
    "intonation", "stress", "loud", "quiet", "fast", "slow",
    "cutoff", "in_breath", "out_breath", "laughter",
]


class Cue(BaseModel):
    type: CueType
    symbol: str                       # the rendered Jefferson symbol
    value: Optional[float] = None     # primary measurement (e.g. gap seconds)
    evidence: dict[str, Any] = Field(default_factory=dict)
    source: Literal["auto", "user"] = "auto"
    confidence: float = 1.0


class Phoneme(BaseModel):
    text: str
    start: float
    end: float


class Token(BaseModel):
    id: str
    text: str
    start: float
    end: float
    speaker: Optional[str] = None
    phonemes: list[Phoneme] = Field(default_factory=list)
    cues: list[Cue] = Field(default_factory=list)
    # pause that occurs *before* this token (rendered on its own or inline)
    pre_pause: Optional[Cue] = None


class JapaneseLayers(BaseModel):
    """Three companion rows beneath a Japanese CA source line.

    The Japanese row itself remains token-backed so karaoke timing and CA cues
    stay editable. These rows are turn-level because literal/natural
    translations do not have reliable word-level timing.
    """

    transliteration: str = ""
    direct_translation: str = ""
    natural_translation: str = ""
    natural_color: str = "#000000"
    generated_by: str = "local"


class Turn(BaseModel):
    id: str
    speaker: str
    start: float
    end: float
    tokens: list[Token] = Field(default_factory=list)
    latched_to_prev: bool = False
    japanese: Optional[JapaneseLayers] = None


class Speaker(BaseModel):
    id: str
    label: str


class PitchPoint(BaseModel):
    t: float
    f0: float          # Hz, 0 when unvoiced


class DocumentMeta(BaseModel):
    project_id: str
    filename: str
    duration: float = 0.0
    sample_rate: int = 16000
    created_at: str = ""
    models: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Transcript(BaseModel):
    meta: DocumentMeta
    speakers: list[Speaker] = Field(default_factory=list)
    turns: list[Turn] = Field(default_factory=list)
    pitch: list[PitchPoint] = Field(default_factory=list)
    intensity: list[PitchPoint] = Field(default_factory=list)  # reuse shape: t + value(f0 field)
    # Non-destructive user edits keyed by token id.
    overrides: dict[str, Any] = Field(default_factory=dict)
    jefferson: str = ""   # rendered plain-text CA transcript
    layout: Literal["standard", "japanese_four_line"] = "standard"


class JobStatus(BaseModel):
    project_id: str
    state: Literal["queued", "running", "done", "error", "cancelled"] = "queued"
    stage: str = ""
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
