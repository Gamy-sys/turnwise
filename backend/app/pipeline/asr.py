"""Stage 3 - verbatim ASR + word-level timestamps with faster-whisper.

faster-whisper (CTranslate2) runs well on CPU with int8 and provides word-level
timestamps directly, so we get accurate-enough word timing for the karaoke
highlight and pause measurement WITHOUT pulling in torch just for alignment.

For higher-precision timing you can swap in WhisperX or Montreal Forced Aligner
behind this same interface (see README). The rest of the pipeline only cares
about the returned word list shape.
"""
from __future__ import annotations

from dataclasses import dataclass


class ASRCancelled(Exception):
    """Raised when a cancel_check callback signals abort mid-transcription."""


@dataclass
class ASRWord:
    text: str
    start: float
    end: float
    probability: float = 1.0
    speaker: str | None = None
    kind: str = "word"  # word | laughter | breath (non-speech vocalisations)


@dataclass
class ASRResult:
    language: str
    words: list[ASRWord]
    model_name: str


def _segment_japanese_words(words: list[ASRWord]) -> list[ASRWord]:
    """Merge Whisper's Japanese character pieces into timed morphemes.

    Whisper word timestamps commonly return one kanji/kana per "word". Sudachi
    supplies lexical boundaries; timing is inherited from all character pieces
    overlapping each morpheme.
    """
    if not words:
        return words
    try:
        from sudachipy import dictionary, tokenizer
    except Exception:
        return words

    raw = "".join(w.text for w in words if w.text)
    if not raw:
        return words

    spans: list[tuple[int, int, ASRWord]] = []
    pos = 0
    for word in words:
        text = word.text or ""
        spans.append((pos, pos + len(text), word))
        pos += len(text)

    try:
        morphemes = dictionary.Dictionary().create().tokenize(
            raw, tokenizer.Tokenizer.SplitMode.C
        )
    except Exception:
        return words

    out: list[ASRWord] = []
    cursor = 0
    punctuation = set("、。,.，．!?！？:：;；」』】）)]}")
    for morph in morphemes:
        surface = morph.surface()
        if not surface:
            continue
        start_i = cursor
        end_i = cursor + len(surface)
        cursor = end_i
        touched = [
            word for a, b, word in spans
            if a < end_i and b > start_i
        ]
        if not touched:
            continue
        if all(ch in punctuation for ch in surface) and out:
            out[-1].text += surface
            out[-1].end = max(out[-1].end, max(w.end for w in touched))
            continue
        if (
            out
            and out[-1].text in ("お", "ご")
            and min(w.start for w in touched) - out[-1].end <= 0.08
        ):
            out[-1].text += surface
            out[-1].end = max(w.end for w in touched)
            out[-1].probability = (
                out[-1].probability
                + sum(w.probability for w in touched) / len(touched)
            ) / 2
            continue
        out.append(ASRWord(
            text=surface,
            start=min(w.start for w in touched),
            end=max(w.end for w in touched),
            probability=sum(w.probability for w in touched) / len(touched),
            speaker=touched[0].speaker,
        ))
    return out or words


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import ctranslate2  # noqa
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _local_model_snapshot(model_name: str, cache_root) -> str | None:
    """Use a complete cached Hugging Face snapshot without a network probe."""
    aliases = {
        "tiny": "Systran/faster-whisper-tiny",
        "base": "Systran/faster-whisper-base",
        "small": "Systran/faster-whisper-small",
        "medium": "Systran/faster-whisper-medium",
        "large-v3": "Systran/faster-whisper-large-v3",
    }
    repo_id = aliases.get(model_name, model_name)
    if "/" not in repo_id:
        return None
    model_dir = cache_root / ("models--" + repo_id.replace("/", "--"))
    refs_main = model_dir / "refs" / "main"
    try:
        revision = refs_main.read_text(encoding="utf-8").strip()
        snapshot = model_dir / "snapshots" / revision
        if (
            snapshot.is_dir()
            and (snapshot / "model.bin").exists()
            and (snapshot / "tokenizer.json").exists()
        ):
            return str(snapshot)
    except Exception:
        pass
    return None


def transcribe(wav_path: str, settings, progress=None, cancel_check=None) -> ASRResult:
    """Run faster-whisper. `progress(frac, msg)` is an optional callback.

    ``cancel_check`` is an optional zero-arg callable; if it returns True,
    transcription stops between segments.
    """
    from faster_whisper import WhisperModel
    from ..config import MODEL_CACHE_DIR

    def _check():
        if cancel_check and cancel_check():
            raise ASRCancelled("Transcription aborted by user")

    device = _resolve_device(settings.device)
    compute_type = settings.compute_type
    if device == "cpu" and compute_type in ("float16", "fp16"):
        compute_type = "int8"  # float16 is not supported on CPU

    _check()
    if progress:
        progress(0.02, f"Loading Whisper '{settings.whisper_model}' ({device}/{compute_type})")

    model_source = _local_model_snapshot(
        str(settings.whisper_model), MODEL_CACHE_DIR / "whisper"
    ) or settings.whisper_model
    model = WhisperModel(
        model_source,
        device=device,
        compute_type=compute_type,
        download_root=str(MODEL_CACHE_DIR / "whisper"),
    )

    _check()
    # Verbatim: no condition_on_previous_text cleanup, keep fillers.
    model_name = str(settings.whisper_model)
    japanese_specialist = "kotoba-whisper" in model_name.lower()
    transcribe_kwargs = dict(
        language=settings.language,
        word_timestamps=True,
        vad_filter=getattr(settings, "vad_filter", False),
        condition_on_previous_text=not settings.verbatim,
        beam_size=getattr(settings, "beam_size", 5),
        initial_prompt=getattr(settings, "initial_prompt", None),
    )
    if japanese_specialist:
        transcribe_kwargs["chunk_length"] = 15
        transcribe_kwargs["hotwords"] = getattr(settings, "initial_prompt", None)
    segments, info = model.transcribe(wav_path, **transcribe_kwargs)

    words: list[ASRWord] = []
    total = max(info.duration, 0.001)
    for seg in segments:
        _check()
        if seg.words:
            for w in seg.words:
                txt = w.word.strip()
                if not txt:
                    continue
                words.append(ASRWord(text=txt, start=float(w.start),
                                     end=float(w.end), probability=float(w.probability or 1.0)))
        else:
            words.append(ASRWord(text=seg.text.strip(), start=float(seg.start), end=float(seg.end)))
        if progress:
            progress(min(0.02 + 0.9 * (seg.end / total), 0.95), "Transcribing")

    if (info.language or settings.language or "").lower().startswith("ja"):
        words = _segment_japanese_words(words)
    return ASRResult(language=info.language, words=words, model_name=settings.whisper_model)
