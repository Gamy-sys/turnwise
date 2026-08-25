"""Stage 6 - prosody extraction with Praat (via parselmouth).

This is the "treat the voice like music" layer, but done on *continuous* pitch
(F0) + intensity instead of lossy MIDI, so downstream CA symbols are accurate.
CPU-only, no torch. Returns time series plus helpers to query a time window.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass
class Prosody:
    times: np.ndarray        # F0 time grid (s)
    f0: np.ndarray           # Hz, 0 => unvoiced
    itimes: np.ndarray       # intensity time grid (s)
    intensity: np.ndarray    # dB
    median_f0: float
    median_intensity: float

    # ----- window queries -------------------------------------------------
    def _slice(self, times, values, a, b):
        m = (times >= a) & (times <= b)
        return values[m]

    def f0_in(self, a: float, b: float) -> np.ndarray:
        v = self._slice(self.times, self.f0, a, b)
        return v[v > 0]

    def intensity_in(self, a: float, b: float) -> np.ndarray:
        return self._slice(self.itimes, self.intensity, a, b)

    def semitone_trend(self, a: float, b: float) -> float:
        """Linear F0 trend across [a,b] expressed in semitones (end - start)."""
        m = (self.times >= a) & (self.times <= b)
        t = self.times[m]
        f = self.f0[m]
        voiced = f > 0
        t, f = t[voiced], f[voiced]
        if len(f) < 3:
            return 0.0
        # least-squares line, evaluate endpoints, convert Hz->semitones
        coeffs = np.polyfit(t, f, 1)
        f_start = np.polyval(coeffs, t[0])
        f_end = np.polyval(coeffs, t[-1])
        if f_start <= 0 or f_end <= 0:
            return 0.0
        return float(12.0 * np.log2(f_end / f_start))


def extract(wav_path: str, f0_min: float = 75.0, f0_max: float = 500.0) -> Prosody:
    import parselmouth

    snd = parselmouth.Sound(wav_path)
    pitch = snd.to_pitch(pitch_floor=f0_min, pitch_ceiling=f0_max)
    f0 = pitch.selected_array["frequency"]           # 0 where unvoiced
    ptimes = pitch.xs()

    intensity_obj = snd.to_intensity(minimum_pitch=f0_min)
    intensity = intensity_obj.values.T.flatten()
    itimes = intensity_obj.xs()

    voiced = f0[f0 > 0]
    median_f0 = float(np.median(voiced)) if len(voiced) else 0.0
    valid_i = intensity[np.isfinite(intensity)]
    median_intensity = float(np.median(valid_i)) if len(valid_i) else 0.0

    return Prosody(
        times=np.asarray(ptimes), f0=np.asarray(f0),
        itimes=np.asarray(itimes), intensity=np.asarray(intensity),
        median_f0=median_f0, median_intensity=median_intensity,
    )
