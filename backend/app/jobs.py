"""Background job manager: runs the full pipeline per project and tracks progress.

Uses a thread pool (jobs are I/O + native-code heavy, releasing the GIL), keeps
per-stage artifacts on disk so re-runs are cheap, and exposes a progress snapshot
that the API streams to the browser.
"""
from __future__ import annotations

import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import PROJECTS_DIR, Settings
from .models import JobStatus, Transcript

_executor = ThreadPoolExecutor(max_workers=1)  # CPU-bound ML: serialize by default
_jobs: dict[str, JobStatus] = {}
_lock = threading.Lock()
# Per-project cancel flags (full pipeline and in-request range / element jobs).
_cancel_flags: dict[str, threading.Event] = {}


class JobCancelled(Exception):
    """User aborted a running transcription job."""


# Stage weights for a smooth overall progress bar.
_STAGES = [
    ("ingest", 0.05),
    ("diarize", 0.20),
    ("asr", 0.45),
    ("prosody", 0.15),
    ("ca", 0.10),
    ("render", 0.05),
]


def project_dir(project_id: str) -> Path:
    d = PROJECTS_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_status(project_id: str) -> JobStatus | None:
    with _lock:
        return _jobs.get(project_id)


def _set(project_id: str, **kw):
    with _lock:
        st = _jobs.setdefault(project_id, JobStatus(project_id=project_id))
        for k, v in kw.items():
            setattr(st, k, v)


def _cancel_event(project_id: str) -> threading.Event:
    with _lock:
        ev = _cancel_flags.get(project_id)
        if ev is None:
            ev = threading.Event()
            _cancel_flags[project_id] = ev
        return ev


def clear_cancel(project_id: str) -> None:
    """Reset the cancel flag before starting a new job."""
    with _lock:
        ev = _cancel_flags.get(project_id)
        if ev is None:
            _cancel_flags[project_id] = threading.Event()
        else:
            ev.clear()


def request_cancel(project_id: str) -> dict:
    """Ask a running full-pipeline or range job for this project to stop."""
    with _lock:
        st = _jobs.get(project_id)
        state = st.state if st else None
        ev = _cancel_flags.get(project_id)
        if ev is None:
            ev = threading.Event()
            _cancel_flags[project_id] = ev
        ev.set()
        if st and st.state in ("queued", "running"):
            st.state = "cancelled"
            st.message = "Aborting…"
            st.stage = "cancelled"
    return {"ok": True, "project_id": project_id, "was_state": state}


def is_cancelled(project_id: str) -> bool:
    with _lock:
        ev = _cancel_flags.get(project_id)
        return bool(ev and ev.is_set())


def check_cancel(project_id: str) -> None:
    if is_cancelled(project_id):
        raise JobCancelled("Transcription aborted by user")


def load_transcript(project_id: str) -> Transcript | None:
    p = project_dir(project_id) / "transcript.json"
    if p.exists():
        return Transcript.model_validate_json(p.read_text(encoding="utf-8"))
    return None


def save_transcript(project_id: str, tr: Transcript):
    p = project_dir(project_id) / "transcript.json"
    p.write_text(tr.model_dump_json(indent=2), encoding="utf-8")


def enqueue(project_id: str, source_path: Path, settings: Settings):
    clear_cancel(project_id)
    _set(project_id, state="queued", stage="", progress=0.0, message="Queued", error=None)
    _executor.submit(_run, project_id, source_path, settings)


def _channel_overlaps(words, min_dur: float = 0.2) -> list[tuple[float, float]]:
    """Time regions where two different speakers (channels) talk at once.

    Only regions lasting >= `min_dur` count as real overlap; shorter ones are
    just word-boundary bleed and are ignored (they become latching instead).
    """
    from collections import Counter

    events: list[tuple[float, int, str]] = []
    for w in words:
        events.append((w.start, 1, w.speaker))
        events.append((w.end, -1, w.speaker))
    events.sort(key=lambda e: (e[0], e[1]))  # closes (-1) before opens (+1) at same t
    active: Counter = Counter()
    overlaps: list[tuple[float, float]] = []
    ov_start = None
    for t, d, spk in events:
        active[spk] += d
        n_distinct = sum(1 for v in active.values() if v > 0)
        if n_distinct >= 2 and ov_start is None:
            ov_start = t
        elif n_distinct < 2 and ov_start is not None:
            if t - ov_start >= min_dur:
                overlaps.append((ov_start, t))
            ov_start = None
    return overlaps


def _suppress_crosstalk(words, chan_wavs, crosstalk_db: float = 18.0,
                        max_dur: float = 0.6):
    """Drop words that are clearly just bleed/echo from the other channel.

    Deliberately conservative so real quiet backchannels ("yeah", "mm hm") are
    NEVER removed. A word is dropped only when ALL hold:
      * it is short (<= max_dur) -- long words are real speech, not bleed;
      * its own channel is >= crosstalk_db quieter than the other channel during
        the word, i.e. its own channel is nearly silent there; AND
      * the other channel is genuinely loud there (not both quiet).
    Set crosstalk_db very high to disable entirely.
    """
    import numpy as np
    import soundfile as sf

    sigs: dict[str, tuple] = {}
    for label, path in chan_wavs.items():
        data, sr = sf.read(str(path))
        if getattr(data, "ndim", 1) > 1:
            data = data[:, 0]
        sigs[label] = (data, sr)

    # per-channel median dB over voiced-ish frames, to know what "loud" means
    def frame_db(data, sr):
        fr = max(1, int(sr * 0.05))
        vals = []
        for i in range(0, len(data) - fr, fr):
            seg = data[i:i + fr].astype(np.float64)
            vals.append(20.0 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12))
        return float(np.median([v for v in vals if v > -70] or [-70]))
    med = {l: frame_db(d, sr) for l, (d, sr) in sigs.items()}

    def rms_db(label: str, a: float, b: float) -> float:
        data, sr = sigs[label]
        i0, i1 = max(0, int(a * sr)), min(len(data), int(b * sr))
        if i1 <= i0:
            return -120.0
        seg = data[i0:i1].astype(np.float64)
        return 20.0 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12)

    kept = []
    for w in words:
        if (w.end - w.start) <= max_dur:
            own = rms_db(w.speaker, w.start, w.end)
            others = {l: rms_db(l, w.start, w.end) for l in sigs if l != w.speaker}
            if others:
                loudest = max(others, key=others.get)
                other_db = others[loudest]
                # own channel nearly silent, other channel clearly above its median
                if own < other_db - crosstalk_db and other_db > med.get(loudest, -60) - 3:
                    continue
        kept.append(w)
    return kept


def _run(project_id: str, source_path: Path, settings: Settings):
    from .pipeline import ingest, asr as asr_mod, prosody as pros_mod, diarization, ca
    from .pipeline.asr import ASRCancelled, ASRResult
    from .pipeline.diarization import DiarResult

    pdir = project_dir(project_id)
    # Speaker diarization is hard-on for Turnwise 0.3+ unless explicitly disabled
    # in the request. Ensure HF token is loaded from the secrets store.
    if getattr(settings, "enable_diarization", True) is not False:
        settings.enable_diarization = True
    if not getattr(settings, "hf_token", None):
        from .config import load_secrets
        tok = load_secrets().get("hf_token")
        if tok:
            settings.hf_token = tok
    if getattr(settings, "num_speakers", None) in (None, 0) and settings.enable_diarization:
        # Keep auto if user cleared the field; otherwise default was already 2.
        pass
    if getattr(settings, "transcript_layout", "standard") == "japanese_four_line":
        # Japanese mode is explicit; don't leave language detection to a short
        # backchannel-heavy excerpt. CrisperWhisper is English-focused.
        settings.language = "ja"
        settings.per_speaker_asr = True
        settings.hybrid_mix_asr = True
        model_l = (settings.whisper_model or "").lower()
        if (
            settings.whisper_model == "nyrahealth/faster_CrisperWhisper"
            or "kotoba-whisper" in model_l
            or settings.whisper_model in ("tiny", "base", "small", "medium")
        ):
            # medium+ below large-v3 miss too much casual overlapping Japanese.
            settings.whisper_model = "large-v3"
        # Bias toward conversational Japanese (fillers + CA-style lexis).
        prompt = (getattr(settings, "initial_prompt", None) or "").strip()
        if not prompt or prompt.lower() in {"alice, bob", "alice bob"}:
            settings.initial_prompt = (
                "日本語の会話。うん、えー、あの、でも、だから、じゃん、しょ、"
                "ね、さ、凡人、うざい、つまんない、面白くない。"
            )
        if getattr(settings, "beam_size", 5) < 5:
            settings.beam_size = 5
        # Whisper's Japanese "word" timings are morpheme spans, so the generic
        # seconds-per-Latin-character heuristic grossly over-marks normal words.
        # Preserve manual colons, but do not invent unreliable automatic ones.
        settings.thresholds.enable_elongation = False
        # Multi-party CA: legacy default was 2 speakers — bump so Update installs
        # actually diarize four voices without a manual Settings edit.
        if settings.num_speakers in (None, 0):
            settings.num_speakers = 4
    elif (settings.language or "").lower().startswith("ja"):
        # Same ASR upgrades when language is forced to Japanese without the
        # four-line layout (e.g. Simple batch with Language=ja).
        settings.per_speaker_asr = True
        settings.hybrid_mix_asr = True
        if settings.whisper_model in ("tiny", "base", "small", "medium"):
            settings.whisper_model = "large-v3"
        prompt = (getattr(settings, "initial_prompt", None) or "").strip()
        if not prompt or prompt.lower() in {"alice, bob", "alice bob"}:
            settings.initial_prompt = (
                "日本語の会話。うん、えー、あの、でも、だから、じゃん、しょ、"
                "ね、さ、凡人、うざい、つまんない、面白くない。"
            )
        if settings.num_speakers in (None, 0):
            settings.num_speakers = 4
    # persist settings used for this run
    (pdir / "settings.json").write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")

    done = 0.0

    def cancel_check() -> bool:
        return is_cancelled(project_id)

    def stage_progress(stage_name: str, weight: float):
        def cb(frac: float, msg: str = ""):
            check_cancel(project_id)
            _set(project_id, state="running", stage=stage_name,
                 progress=round(done + weight * max(0.0, min(frac, 1.0)), 4),
                 message=msg or stage_name)
        return cb

    try:
        check_cancel(project_id)
        _set(project_id, state="running", stage="ingest", progress=0.0, message="Decoding audio")
        cb = stage_progress("ingest", _STAGES[0][1])
        cb(0.2, "Normalizing + analyzing channels")
        prep = ingest.prepare(source_path, pdir, sample_rate=16000)
        wav = prep.mono_wav
        duration = prep.duration
        done += _STAGES[0][1]
        check_cancel(project_id)

        if prep.mode == "multichannel":
            # Speakers come straight from the channels; no diarization model needed.
            cb = stage_progress("diarize", _STAGES[1][1])
            cb(0.6, f"Split into {len(prep.channels)} per-speaker channels")
            diar = DiarResult(available=True, source="channels")
            done += _STAGES[1][1]

            cb = stage_progress("asr", _STAGES[2][1])
            all_words = []
            chan_wavs = {}
            lang = None
            nchan = len(prep.channels)
            for idx, (label, chan_wav) in enumerate(prep.channels):
                check_cancel(project_id)
                chan_wavs[label] = chan_wav
                def chan_cb(frac, msg="", _i=idx, _l=label):
                    cb((_i + max(0.0, min(frac, 1.0))) / nchan, f"Transcribing speaker {_l}")
                res = asr_mod.transcribe(
                    str(chan_wav), settings, progress=chan_cb, cancel_check=cancel_check,
                )
                lang = lang or res.language
                for w in res.words:
                    w.speaker = label
                all_words.extend(res.words)
            all_words = _suppress_crosstalk(all_words, chan_wavs,
                                            settings.thresholds.crosstalk_db,
                                            settings.thresholds.crosstalk_max_dur)
            # detect laughter / breath in the gaps and add them to the timeline
            from .pipeline import nonspeech
            try:
                ns = nonspeech.detect(chan_wavs, all_words, settings.thresholds)
                all_words.extend(ns)
            except Exception as e:
                print("nonspeech detection skipped:", e)
            all_words.sort(key=lambda w: (w.start, w.end))
            asr_res = ASRResult(language=lang or "en", words=all_words,
                                model_name=settings.whisper_model)
            diar.segments = [(w.start, w.end, w.speaker) for w in all_words]
            diar.overlaps = _channel_overlaps(all_words, settings.thresholds.min_overlap_dur)
            done += _STAGES[2][1]
        else:
            # diarization (optional, needs pyannote + HF token)
            check_cancel(project_id)
            cb = stage_progress("diarize", _STAGES[1][1])
            diar = diarization.diarize(str(wav), settings, progress=cb)
            try:
                (pdir / "diar.json").write_text(
                    json.dumps({
                        "available": diar.available,
                        "error": diar.error,
                        "source": diar.source,
                        "segments": [{"start": s, "end": e, "speaker": sp} for s, e, sp in diar.segments],
                        "overlaps": [{"start": a, "end": b} for a, b in diar.overlaps],
                    }, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
            done += _STAGES[1][1]

            check_cancel(project_id)
            cb = stage_progress("asr", _STAGES[2][1])
            # Mono multi-party (esp. overlapping Japanese CA): ASR each
            # diarized speaker on a masked track so concurrent speech is not
            # collapsed into one Whisper hypothesis.
            use_per_spk = (
                getattr(settings, "per_speaker_asr", True)
                and diar.available
                and len({lbl for _, _, lbl in diar.segments}) >= 2
            )
            if use_per_spk:
                cb(0.02, "Per-speaker ASR (overlap-aware)")
                asr_res = asr_mod.transcribe_per_speaker(
                    str(wav), diar.segments, settings,
                    progress=lambda f, m="": cb(0.05 + 0.7 * f, m),
                    cancel_check=cancel_check,
                )
                # Fill gaps: a full-mix pass can still catch quiet/overlapped
                # words the masked tracks missed (common in CA laughter + soft
                # backchannels). Keep only mix words that do not collide with
                # an existing per-speaker hypothesis.
                if getattr(settings, "hybrid_mix_asr", True):
                    cb(0.78, "Mix ASR for missed words")
                    mix = asr_mod.transcribe(
                        str(wav), settings,
                        progress=lambda f, m="": cb(0.78 + 0.2 * f, m),
                        cancel_check=cancel_check,
                    )
                    asr_res = asr_mod.merge_mix_gap_words(
                        asr_res, mix, diar.segments,
                    )
            else:
                asr_res = asr_mod.transcribe(
                    str(wav), settings, progress=cb, cancel_check=cancel_check,
                )
            done += _STAGES[2][1]

        check_cancel(project_id)
        # prosody
        cb = stage_progress("prosody", _STAGES[3][1])
        cb(0.3, "Extracting pitch + intensity")
        pros = pros_mod.extract(str(wav))
        done += _STAGES[3][1]

        check_cancel(project_id)
        # CA derivation
        cb = stage_progress("ca", _STAGES[4][1])
        cb(0.3, "Deriving CA notation")
        name_file = pdir / "original_name.txt"
        display_name = (name_file.read_text(encoding="utf-8").strip()
                        if name_file.exists() else source_path.name)
        tr = ca.build_transcript(project_id, display_name, duration,
                                 asr_res, pros, diar, settings)
        done += _STAGES[4][1]

        check_cancel(project_id)
        if getattr(settings, "transcript_layout", "standard") == "japanese_four_line":
            from .pipeline.japanese import populate_japanese_layers

            def japanese_progress(frac: float, msg: str = ""):
                check_cancel(project_id)
                _set(
                    project_id,
                    state="running",
                    stage="japanese",
                    progress=round(min(0.99, done + _STAGES[5][1] * frac), 4),
                    message=msg or "Building Japanese four-line transcript",
                )

            populate_japanese_layers(tr, settings, progress=japanese_progress)

        check_cancel(project_id)
        # render + save
        cb = stage_progress("render", _STAGES[5][1])
        cb(0.5, "Rendering transcript")
        save_transcript(project_id, tr)
        done += _STAGES[5][1]

        if is_cancelled(project_id):
            raise JobCancelled("Transcription aborted by user")
        _set(project_id, state="done", stage="done", progress=1.0, message="Complete")
    except (JobCancelled, ASRCancelled) as e:
        prog = 0.0
        st = get_status(project_id)
        if st is not None:
            prog = st.progress
        _set(project_id, state="cancelled", stage="cancelled",
             message="Aborted", error=None, progress=prog)
        (pdir / "error.log").write_text(f"cancelled: {e}\n", encoding="utf-8")
    except Exception as e:  # pragma: no cover
        if is_cancelled(project_id):
            _set(project_id, state="cancelled", stage="cancelled",
                 message="Aborted", error=None)
        else:
            _set(project_id, state="error", error=f"{e}", message="Failed",
                 stage="error")
            (pdir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
