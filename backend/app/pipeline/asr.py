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


def _load_mono_wav(wav_path: str):
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    return np.ascontiguousarray(mono), int(sr)


def _mask_speaker_audio(audio, sr: int, segments, speaker: str):
    """Keep only regions labeled `speaker`; silence everything else.

    Preserves the original timeline so word timestamps stay aligned with the
    source video. Critical for overlapping multi-party conversation: a single
    mixed-track ASR pass drops or mishears concurrent speech.
    """
    import numpy as np

    out = np.zeros_like(audio)
    kept = 0.0
    for start, end, label in segments:
        if label != speaker:
            continue
        a = max(0, int(float(start) * sr))
        b = min(len(audio), int(float(end) * sr))
        if b > a:
            out[a:b] = audio[a:b]
            kept += (b - a) / sr
    return out, kept


def _word_on_speaker(word: ASRWord, segments, speaker: str, min_overlap: float = 0.04) -> bool:
    """Drop Whisper hallucinations that fall in silence for this speaker."""
    for start, end, label in segments:
        if label != speaker:
            continue
        ov = min(end, word.end) - max(start, word.start)
        if ov >= min_overlap:
            return True
    # Very short backchannels near a segment edge
    mid = (word.start + word.end) / 2.0
    for start, end, label in segments:
        if label != speaker:
            continue
        if start - 0.08 <= mid <= end + 0.08:
            return True
    return False


def _norm_ja(text: str) -> str:
    import re
    t = (text or "").strip().lower()
    t = re.sub(r"[\s、。,.，．!?！？:：;；「」『』\-—~〜・]+", "", t)
    return t


def _filter_crosstalk_bleed(words: list[ASRWord], segments) -> list[ASRWord]:
    """When two speakers get the same hypothesis in an overlap, keep one.

    Masked mono ASR often reprints the louder talker's words onto the quieter
    speaker's track. Prefer the speaker with more exclusive (non-overlapped)
    diarization coverage under the word.
    """
    if len(words) < 2:
        return words

    def exclusive_coverage(w: ASRWord, speaker: str) -> float:
        total = 0.0
        for s, e, lbl in segments:
            if lbl != speaker:
                continue
            ov = min(e, w.end) - max(s, w.start)
            if ov <= 0:
                continue
            claimed = ov
            for s2, e2, lbl2 in segments:
                if lbl2 == speaker:
                    continue
                other = min(e2, w.end, e) - max(s2, w.start, s)
                if other > 0:
                    claimed -= other
            total += max(0.0, claimed)
        return total

    drop: set[int] = set()
    for i, a in enumerate(words):
        if i in drop or not a.speaker:
            continue
        na = _norm_ja(a.text)
        if len(na) < 2:
            continue
        a_mid = (a.start + a.end) / 2.0
        for j in range(i + 1, len(words)):
            if j in drop:
                continue
            b = words[j]
            if not b.speaker or b.speaker == a.speaker:
                continue
            b_mid = (b.start + b.end) / 2.0
            if abs(a_mid - b_mid) > 0.65:
                continue
            nb = _norm_ja(b.text)
            if not nb:
                continue
            similar = na == nb or (len(na) >= 2 and (na in nb or nb in na))
            if not similar:
                continue
            ca = exclusive_coverage(a, a.speaker)
            cb = exclusive_coverage(b, b.speaker)
            if ca >= cb:
                drop.add(j)
            else:
                drop.add(i)
                break
    return [w for i, w in enumerate(words) if i not in drop]


def repair_speaker_label_flicker(
    words: list[ASRWord],
    max_run_dur: float = 0.75,
    max_run_words: int = 6,
    interrupt_dur: float = 0.45,
    interrupt_words: int = 3,
    bridge_gap: float = 0.25,
) -> list[ASRWord]:
    """Reassign short mid-utterance speaker flips to the flanking talker.

    Diarization often splits one continuous person into A then B (or inserts a
    brief wrong label inside a longer span). When a short run of Y sits between
    two runs of X — skipping only brief interruptions — and X's speech bridges
    across Y (overlap or tiny gap), Y almost always belongs to X. Real
    backchannels sit in a larger gap and are preserved.
    """
    if len(words) < 3:
        return words

    ordered = sorted(words, key=lambda w: (w.start, w.end, w.speaker or ""))
    runs: list[tuple[int, int, str, float, float]] = []
    i = 0
    n = len(ordered)
    while i < n:
        spk = ordered[i].speaker or ""
        j = i + 1
        while j < n and (ordered[j].speaker or "") == spk:
            j += 1
        runs.append((i, j, spk, ordered[i].start, ordered[j - 1].end))
        i = j

    def run_stats(run: tuple[int, int, str, float, float]):
        i0, j0, spk, t0, t1 = run
        return spk, (t1 - t0), (j0 - i0)

    def is_interrupt(run: tuple[int, int, str, float, float]) -> bool:
        """Tiny mid-span glitches skipped when searching for flanking talkers."""
        spk, dur, nw = run_stats(run)
        if not spk:
            return True
        return dur <= interrupt_dur and nw <= interrupt_words

    def is_repairable(run: tuple[int, int, str, float, float]) -> bool:
        spk, dur, nw = run_stats(run)
        if not spk:
            return False
        return dur <= max_run_dur and nw <= max_run_words

    reassign: dict[int, str] = {}
    for k, run in enumerate(runs):
        i0, j0, spk, t0, t1 = run
        if not is_repairable(run):
            continue
        left = None
        for L in range(k - 1, -1, -1):
            if is_interrupt(runs[L]):
                continue
            left = runs[L]
            break
        right = None
        for R in range(k + 1, len(runs)):
            if is_interrupt(runs[R]):
                continue
            right = runs[R]
            break
        if not left or not right:
            continue
        if left[2] != right[2] or left[2] == spk:
            continue
        # Bridged: flanking X speech overlaps / nearly touches this run, or the
        # gap between the two X runs is tiny (identity flicker with no pause).
        bridged = (
            left[4] >= t0 - 0.08
            or right[3] <= t1 + 0.08
            or (right[3] - left[4]) <= bridge_gap
        )
        if not bridged:
            continue
        for idx in range(i0, j0):
            reassign[idx] = left[2]

    if not reassign:
        return ordered
    out = []
    for idx, w in enumerate(ordered):
        if idx in reassign:
            w.speaker = reassign[idx]
        out.append(w)
    out.sort(key=lambda w: (w.start, w.end, w.speaker or ""))
    return out


def transcribe_per_speaker(
    wav_path: str,
    segments: list,
    settings,
    progress=None,
    cancel_check=None,
) -> ASRResult:
    """ASR each diarized speaker on a masked copy of the mono mix.

    Overlapping talk (common in Japanese CA recordings) is recovered because
    each speaker is transcribed without the other voices in the mix.
    """
    import os
    import tempfile
    import soundfile as sf

    if not segments:
        return transcribe(wav_path, settings, progress=progress, cancel_check=cancel_check)

    labels = sorted({lbl for _, _, lbl in segments})
    if len(labels) < 2:
        res = transcribe(wav_path, settings, progress=progress, cancel_check=cancel_check)
        for w in res.words:
            w.speaker = labels[0] if labels else "A"
        return res

    audio, sr = _load_mono_wav(wav_path)
    all_words: list[ASRWord] = []
    lang = None
    n = len(labels)

    for idx, label in enumerate(labels):
        if cancel_check and cancel_check():
            raise ASRCancelled("Transcription aborted by user")
        masked, kept = _mask_speaker_audio(audio, sr, segments, label)
        if kept < 0.08:
            if progress:
                progress((idx + 1) / n, f"Skip quiet speaker {label}")
            continue

        def speaker_cb(frac, msg="", _i=idx, _l=label):
            if progress:
                progress((_i + max(0.0, min(frac, 1.0))) / n, msg or f"Transcribing speaker {_l}")

        fd, tmp = tempfile.mkstemp(suffix=f"_{label}.wav")
        os.close(fd)
        try:
            sf.write(tmp, masked, sr)
            res = transcribe(tmp, settings, progress=speaker_cb, cancel_check=cancel_check)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

        lang = lang or res.language
        for w in res.words:
            if not w.text or not w.text.strip():
                continue
            if not _word_on_speaker(w, segments, label):
                continue
            w.speaker = label
            all_words.append(w)

    all_words.sort(key=lambda w: (w.start, w.end, w.speaker or ""))
    all_words = _filter_crosstalk_bleed(all_words, segments)
    all_words = repair_speaker_label_flicker(all_words)
    all_words = repair_speaker_label_flicker(all_words)  # nested brief flips
    return ASRResult(
        language=lang or (settings.language or "en"),
        words=all_words,
        model_name=settings.whisper_model,
    )


def merge_mix_gap_words(
    per_speaker: ASRResult,
    mix: ASRResult,
    segments: list,
    min_gap: float = 0.12,
) -> ASRResult:
    """Add full-mix words that are not already covered by per-speaker ASR.

    Quiet or briefly diarized talk sometimes appears only in the mixed track.
    Speaker labels come from diarization overlap. Same-time words with
    *different* text are kept (true overlap); near-duplicate reprints are not.
    """
    from .diarization import speaker_for_interval

    kept = list(per_speaker.words)
    for w in mix.words:
        if not w.text or not w.text.strip():
            continue
        nw = _norm_ja(w.text)
        collide = False
        for e in kept:
            ov = min(e.end, w.end) - max(e.start, w.start)
            if ov < min(min_gap, max(0.05, (w.end - w.start) * 0.4)):
                continue
            ne = _norm_ja(e.text)
            # Duplicate hypothesis in the same span — skip.
            if nw and ne and (nw == ne or nw in ne or ne in nw):
                collide = True
                break
            # Same speaker already covering this instant — skip unless novel.
            if e.speaker and ov > 0.08 and nw and ne and nw == ne:
                collide = True
                break
        if collide:
            continue
        # Also skip if an existing word already contains this mix token nearby
        covered = False
        for e in kept:
            if abs(((e.start + e.end) / 2) - ((w.start + w.end) / 2)) > 0.55:
                continue
            ne = _norm_ja(e.text)
            if nw and ne and (nw == ne or (len(nw) >= 2 and nw in ne)):
                covered = True
                break
        if covered:
            continue
        label = speaker_for_interval(segments, w.start, w.end, default="A")
        w.speaker = label
        kept.append(w)
    kept.sort(key=lambda x: (x.start, x.end, x.speaker or ""))
    kept = _filter_crosstalk_bleed(kept, segments)
    kept = repair_speaker_label_flicker(kept)
    kept = repair_speaker_label_flicker(kept)
    return ASRResult(
        language=per_speaker.language or mix.language,
        words=kept,
        model_name=per_speaker.model_name,
    )
