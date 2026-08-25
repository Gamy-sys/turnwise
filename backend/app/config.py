"""Application configuration and tunable CA-notation thresholds.

Everything here is overridable per-job from the UI Settings panel. The values
below are sensible defaults grounded in Conversation-Analysis (Jefferson)
conventions. Thresholds live in one place so the whole pipeline stays honest
about *why* a symbol was produced.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = Path(os.environ.get("CA_DATA_DIR", PROJECT_DIR / "data"))
PROJECTS_DIR = DATA_DIR / "projects"
MODEL_CACHE_DIR = Path(os.environ.get("CA_MODEL_CACHE", DATA_DIR / "models"))
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"

for _p in (DATA_DIR, PROJECTS_DIR, MODEL_CACHE_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Secrets store — API keys are saved once here and reused for every project,
# so leaving a key field blank in the UI never erases a previously saved key.
# ---------------------------------------------------------------------------
SECRETS_FILE = DATA_DIR / "secrets.json"
GLOBAL_SETTINGS_FILE = DATA_DIR / "global_settings.json"
_SECRET_KEYS = ("hf_token", "openai_api_key")


def load_secrets() -> dict:
    try:
        return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_secrets(updates: dict) -> None:
    secrets = load_secrets()
    changed = False
    for k in _SECRET_KEYS:
        v = updates.get(k)
        if isinstance(v, str) and v.strip() and secrets.get(k) != v.strip():
            secrets[k] = v.strip()
            changed = True
    if changed:
        SECRETS_FILE.write_text(json.dumps(secrets, indent=2), encoding="utf-8")
        try:
            SECRETS_FILE.chmod(0o600)
        except OSError:
            pass


@dataclass
class CAThresholds:
    """Tunable thresholds used when converting measurements into CA symbols."""

    # --- Pauses (seconds) ---
    micropause_min: float = 0.1          # (.) starts here
    timed_pause_min: float = 0.2         # (0.2) and above are timed to 0.1s
    latch_max_gap: float = 0.05          # <= this between turns => latching (=)
    min_overlap_dur: float = 0.2         # real simultaneous talk must last this long
    # Cross-talk (bleed) rejection. Only drops a word when it is BOTH much quieter
    # on its own channel than the other channel AND the other channel clearly has
    # its own louder word at that moment. Conservative so real quiet backchannels
    # ("yeah", "mm hm") are never removed. Set crosstalk_db very high to disable.
    crosstalk_db: float = 18.0
    crosstalk_max_dur: float = 0.6       # only ever drop short words as bleed

    # --- Elongation ---
    # A vowel/word region counts as stretched when its measured duration exceeds
    # the expected duration by this ratio. Extra colons scale with the excess.
    # Which cue families the AUTO pass emits. The noisy prosodic ones default
    # OFF to match a clean CA transcript; enable them in Settings if wanted.
    # (All cues remain fully editable per-word regardless of these flags.)
    enable_elongation: bool = True
    enable_intonation: bool = False
    enable_volume: bool = False          # CAPS / °quiet° / underlined stress
    enable_tempo: bool = False           # >fast< / <slow>

    elongation_ratio: float = 2.3
    elongation_colon_step: float = 0.16  # seconds of excess per extra colon
    elongation_min_dur: float = 0.30     # absolute floor before marking a stretch
    elongation_max_colons: int = 4
    expected_char_dur: float = 0.075     # rough seconds-per-character baseline

    # --- Intonation (semitones of F0 movement over the unit's final region) ---
    intonation_final_frac: float = 0.35  # analyse last 35% of the unit
    rise_strong_st: float = 3.0          # >= => sharp rise (?) or up-arrow
    rise_weak_st: float = 0.8            # >= => continuing (,)
    fall_st: float = -1.2                # <= => falling (.)
    arrow_st: float = 5.0                # >= abs => marked shift (up/down arrow)

    # --- Volume (dB relative to the speaker's running median intensity) ---
    # NOTE: prosodic thresholds are relative to each speaker's median and are
    # best tuned per-recording in the Settings panel. These are safe defaults.
    loud_db: float = 6.0                 # >= => CAPS
    quiet_db: float = -6.0               # <= => wraps in degree signs
    stress_db: float = 4.0               # mean dB over median for underlined emphasis
    stress_min_dur: float = 0.15         # ignore stress on very short tokens

    # --- Tempo (speaking rate relative to speaker median, ratio) ---
    fast_ratio: float = 1.7              # >= => >compressed<
    slow_ratio: float = 0.5              # <= => <stretched>
    tempo_min_chars: int = 3             # short function words are unreliable

    # --- Breath / laughter (detected from channel audio in word gaps) ---
    breath_min_dur: float = 0.12         # minimum non-speech energy blip
    laughter_min_db: float = 8.0         # laughter energy over the channel floor
    breath_min_db: float = 6.0           # breath energy over the channel floor
    enable_laughter: bool = True         # emit `hhh hhh` for pulsed bursts
    enable_breath: bool = False          # emit `.hhh` for single breaths (noisier)

    # --- Cut-offs ---
    enable_cutoff: bool = True


@dataclass
class Settings:
    """Global, per-job configurable settings."""

    # ASR
    whisper_model: str = os.environ.get("CA_WHISPER_MODEL", "medium")  # tiny/base/small/medium/large-v3
    compute_type: str = os.environ.get("CA_COMPUTE_TYPE", "int8")     # CPU-friendly
    device: str = os.environ.get("CA_DEVICE", "auto")                 # auto/cpu/cuda
    language: str | None = None                                       # None => autodetect
    verbatim: bool = True                                             # keep fillers/false starts
    beam_size: int = 5
    initial_prompt: str | None = None                                 # bias vocab / proper nouns
    vad_filter: bool = False   # OFF preserves quiet/short words (better for CA)
    transcript_layout: str = "standard"  # standard | japanese_four_line
    japanese_auto_translate: bool = True

    # Diarization (optional, needs Hugging Face token)
    enable_diarization: bool = True
    hf_token: str | None = os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN")
    num_speakers: int | None = None                                   # None => auto
    # pyannote pipeline to use. community-1 is the pyannote 4.x native model;
    # 3.1 is kept as an automatic fallback for older setups.
    diarization_model: str = os.environ.get(
        "CA_DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1")

    # OpenAI (optional, never required)
    enable_openai: bool = False
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    openai_model: str = "gpt-4o-mini"
    openai_use_for_asr: bool = False   # use gpt-4o-transcribe instead of local

    thresholds: CAThresholds = field(default_factory=CAThresholds)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Never leak secrets to the client.
        d["hf_token"] = bool(self.hf_token)
        d["openai_api_key"] = bool(self.openai_api_key)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        data = dict(data or {})
        th = data.pop("thresholds", None)
        s = cls()
        for k, v in data.items():
            if hasattr(s, k) and k not in ("hf_token", "openai_api_key"):
                setattr(s, k, v)
        # Only overwrite secrets when a real string is supplied; newly supplied
        # keys are persisted so they are never lost between sessions.
        if isinstance(data.get("hf_token"), str) and data["hf_token"].strip():
            s.hf_token = data["hf_token"].strip()
        if isinstance(data.get("openai_api_key"), str) and data["openai_api_key"].strip():
            s.openai_api_key = data["openai_api_key"].strip()
        save_secrets(data)
        stored = load_secrets()
        if not s.hf_token and stored.get("hf_token"):
            s.hf_token = stored["hf_token"]
        if not s.openai_api_key and stored.get("openai_api_key"):
            s.openai_api_key = stored["openai_api_key"]
        if isinstance(th, dict):
            base = CAThresholds()
            for k, v in th.items():
                if hasattr(base, k):
                    setattr(base, k, v)
            s.thresholds = base
        return s


# Set model cache env vars so every library downloads to the same local folder.
os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR / "huggingface"))
os.environ.setdefault("TORCH_HOME", str(MODEL_CACHE_DIR / "torch"))
os.environ.setdefault("XDG_CACHE_HOME", str(MODEL_CACHE_DIR / "cache"))

def load_global_settings_dict() -> dict:
    try:
        return json.loads(GLOBAL_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_global_settings_dict(data: dict) -> None:
    GLOBAL_SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def merged_defaults() -> Settings:
    """Server-wide defaults (Simple mode + new uploads), including saved secrets."""
    return Settings.from_dict(load_global_settings_dict())


DEFAULT_SETTINGS = merged_defaults()
