"""Stage 1 - decode input and decide how to handle speakers.

Two situations we care about:

* **Mono / stereo-duplicated** audio (a single mixed channel): normalize to one
  16 kHz mono WAV and let diarization (pyannote) find the speakers.
* **Dual-mono / split-channel** recordings (very common for phone calls, where
  each speaker is on their own channel): the channels ARE the speakers. We split
  them, transcribe each separately, and get essentially perfect speaker
  attribution + overlap detection without any diarization model.

The original file is always kept untouched for playback.
"""
from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class Prepared:
    mono_wav: Path                        # 16 kHz mono mix (prosody + fallback ASR)
    duration: float
    mode: str = "mono"                    # "mono" | "multichannel"
    channels: list[tuple[str, Path]] = field(default_factory=list)  # (speaker, wav)
    n_channels: int = 1
    corr: float | None = None


def ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _probe_channels(path: Path) -> int:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=channels",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return 1


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate() or 1)


def _to_mono(src: Path, dst: Path, sr: int) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", str(sr),
         "-c:a", "pcm_s16le", str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mono decode failed:\n{proc.stderr[-2000:]}")


def _split_channels(src: Path, out_dir: Path, sr: int, n: int) -> list[Path]:
    """Extract each channel to its own mono WAV using ffmpeg channelsplit/pan."""
    out_paths: list[Path] = []
    for ch in range(n):
        dst = out_dir / f"channel_{ch}.wav"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-filter_complex", f"pan=mono|c0=c{ch}", "-ar", str(sr),
             "-c:a", "pcm_s16le", str(dst)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg channel split failed:\n{proc.stderr[-2000:]}")
        out_paths.append(dst)
    return out_paths


def _channel_correlation(paths: list[Path]) -> float:
    """Max abs pairwise correlation across channels (low => distinct speakers)."""
    import soundfile as sf

    sigs = []
    for p in paths:
        data, _ = sf.read(str(p))
        if data.ndim > 1:
            data = data[:, 0]
        sigs.append(data)
    n = min(len(s) for s in sigs)
    sigs = [s[:n] for s in sigs]
    max_corr = 0.0
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            a, b = sigs[i], sigs[j]
            if np.std(a) < 1e-6 or np.std(b) < 1e-6:
                continue
            c = abs(float(np.corrcoef(a, b)[0, 1]))
            max_corr = max(max_corr, c)
    return max_corr


def _channel_has_speech(path: Path, floor_db: float = -45.0) -> bool:
    import soundfile as sf

    data, sr = sf.read(str(path))
    if data.ndim > 1:
        data = data[:, 0]
    if len(data) == 0:
        return False
    rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)) + 1e-12)
    return 20 * np.log10(rms) > floor_db


def prepare(src: Path, work_dir: Path, sample_rate: int = 16000,
            corr_threshold: float = 0.5) -> Prepared:
    """Decode `src`, decide mono vs per-channel, and produce the WAVs we need."""
    work_dir.mkdir(parents=True, exist_ok=True)
    mono = work_dir / "audio.wav"
    _to_mono(src, mono, sample_rate)
    duration = _wav_duration(mono)

    n_ch = _probe_channels(src)
    if n_ch < 2:
        return Prepared(mono_wav=mono, duration=duration, mode="mono", n_channels=n_ch)

    # Multi-channel: split and test whether channels are distinct speakers.
    chan_paths = _split_channels(src, work_dir, sample_rate, n_ch)
    corr = _channel_correlation(chan_paths)
    active = [p for p in chan_paths if _channel_has_speech(p)]

    if corr <= corr_threshold and len(active) >= 2:
        labels = [chr(ord("A") + i) for i in range(len(active))]
        channels = list(zip(labels, active))
        return Prepared(mono_wav=mono, duration=duration, mode="multichannel",
                        channels=channels, n_channels=n_ch, corr=corr)

    # Channels are correlated (just stereo) -> treat as mono, use diarization.
    return Prepared(mono_wav=mono, duration=duration, mode="mono",
                    n_channels=n_ch, corr=corr)


# Backwards-compatible helper used by the smoke test.
def normalize_audio(src: Path, dst_wav: Path, sample_rate: int = 16000) -> tuple[Path, float]:
    _to_mono(src, dst_wav, sample_rate)
    return dst_wav, _wav_duration(dst_wav)
