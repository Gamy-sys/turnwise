"""Detect non-speech vocalisations (laughter, audible breath) per channel.

CA notates these as `hhh hhh` (laughter / heavy aspiration) and `.hhh`
(in-breath). Whisper omits them, so we find energy bursts that sit in the GAPS
between a channel's ASR words (i.e. not already transcribed as speech), classify
them, and emit them as tokens tagged with `kind`. Because they become normal
tokens on the timeline, the existing overlap logic brackets them automatically
when they land during the other speaker's talk -> automatic laughter/breath
overlaps.

The detector is deliberately conservative (energy well above the channel's own
noise floor, must be the loudest channel at that moment, bounded durations) so
it does not spam. Everything it finds is editable/removable in the UI.
"""
from __future__ import annotations

import numpy as np
import soundfile as sf

from .asr import ASRWord


def _envelope(data: np.ndarray, sr: int, hop: float = 0.01, win: float = 0.03):
    n_hop = max(1, int(sr * hop))
    n_win = max(n_hop, int(sr * win))
    n = 1 + max(0, (len(data) - n_win) // n_hop)
    times = np.empty(n)
    env = np.empty(n)
    for k in range(n):
        i = k * n_hop
        seg = data[i:i + n_win].astype(np.float64)
        env[k] = 20.0 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12)
        times[k] = (i + n_win / 2) / sr
    return times, env


def _count_peaks(seg: np.ndarray, prom: float = 4.0) -> int:
    """Rough count of energy pulses (laughter is pulsed; breath is a single blob)."""
    if len(seg) < 3:
        return 1
    peaks = 0
    lo = seg[0]
    rising = False
    for x in seg[1:]:
        if x > lo + prom:
            rising = True
        if rising and x < lo - prom:
            peaks += 1
            rising = False
            lo = x
        lo = min(lo, x) if not rising else lo
        if x > lo:
            lo = max(lo, x - prom) if rising else lo
    return max(1, peaks)


def detect(chan_wavs: dict, words: list, th) -> list[ASRWord]:
    enable_laughter = getattr(th, "enable_laughter", True)
    enable_breath = getattr(th, "enable_breath", False)
    if not (enable_laughter or enable_breath):
        return []

    from collections import defaultdict
    spans = defaultdict(list)
    for w in words:
        spans[w.speaker].append((w.start, w.end))

    # load + envelope every channel once (for attribution)
    envs: dict = {}
    for label, path in chan_wavs.items():
        data, sr = sf.read(str(path))
        if getattr(data, "ndim", 1) > 1:
            data = data[:, 0]
        envs[label] = _envelope(data, sr)

    def other_env_at(exclude: str, a: float, b: float) -> float:
        best = -120.0
        for lab, (t, e) in envs.items():
            if lab == exclude:
                continue
            m = (t >= a) & (t <= b)
            if np.any(m):
                best = max(best, float(np.mean(e[m])))
        return best

    breath_min = getattr(th, "breath_min_dur", 0.12)
    laugh_over = getattr(th, "laughter_min_db", 8.0)
    breath_over = getattr(th, "breath_min_db", 6.0)
    # Only reject as bleed when the OTHER channel is much louder (true echo).
    bleed_margin = 12.0
    out: list[ASRWord] = []

    for label, (t, env) in envs.items():
        if len(env) == 0:
            continue
        voiced = env[env > -90]
        floor = float(np.percentile(voiced, 10)) if len(voiced) else -80.0
        active_thr = floor + 8.0

        mask = np.zeros(len(t), bool)
        for (a, b) in spans.get(label, []):
            lo = np.searchsorted(t, a - 0.15)
            hi = np.searchsorted(t, b + 0.15)
            mask[lo:hi] = True

        cand = (env > active_thr) & (~mask)
        i, N = 0, len(env)
        while i < N:
            if not cand[i]:
                i += 1
                continue
            j = i
            while j < N and cand[j]:
                j += 1
            a_t, b_t = float(t[i]), float(t[j - 1])
            dur = b_t - a_t
            seg = env[i:j]
            mean_over = float(np.mean(seg)) - floor
            peaks = _count_peaks(seg)
            i = j

            if dur < breath_min or dur > 3.0:
                continue
            # reject only clear bleed: the other channel is MUCH louder than this
            # segment (a faint echo). Comparable energy = genuine vocalisation.
            if other_env_at(label, a_t, b_t) - float(np.mean(seg)) > bleed_margin:
                continue

            is_laugh = enable_laughter and dur >= 0.20 and peaks >= 2 and mean_over >= laugh_over
            is_breath = enable_breath and (not is_laugh) and dur <= 0.9 and mean_over >= breath_over

            if is_laugh:
                n = int(min(max(peaks, 2), 4))
                out.append(ASRWord(text=" ".join(["hhh"] * n), start=a_t, end=b_t,
                                   probability=0.5, speaker=label, kind="laughter"))
            elif is_breath:
                out.append(ASRWord(text=".hhh", start=a_t, end=b_t,
                                   probability=0.5, speaker=label, kind="breath"))
    return out
