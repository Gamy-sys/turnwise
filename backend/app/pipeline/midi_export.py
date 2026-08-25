"""Export the F0 contour as a MIDI file.

This is the fun "voice as music" artifact from the original idea. It is a
VISUALIZATION/export only - the CA analysis itself runs on continuous pitch,
not on this quantized MIDI, so nothing accuracy-critical depends on it.
"""
from __future__ import annotations

import math
from pathlib import Path

from ..models import Transcript


def _hz_to_midi(hz: float) -> int:
    return int(round(69 + 12 * math.log2(hz / 440.0)))


def export_midi(tr: Transcript, dst: Path, tempo_bpm: int = 120) -> Path:
    import mido

    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    ticks = mid.ticks_per_beat
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo_bpm)))

    def sec_to_ticks(s: float) -> int:
        return int(s * (tempo_bpm / 60.0) * ticks)

    # Build note segments by merging consecutive voiced pitch points.
    pts = [(p.t, p.f0) for p in tr.pitch if p.f0 and p.f0 > 0]
    if not pts:
        mid.save(str(dst))
        return dst

    notes: list[tuple[float, float, int]] = []
    seg_start = pts[0][0]
    seg_note = _hz_to_midi(pts[0][1])
    last_t = pts[0][0]
    for t, hz in pts[1:]:
        note = _hz_to_midi(hz)
        if note != seg_note or (t - last_t) > 0.25:
            notes.append((seg_start, last_t, seg_note))
            seg_start = t
            seg_note = note
        last_t = t
    notes.append((seg_start, last_t, seg_note))

    cursor = 0
    for start, end, note in notes:
        note = max(0, min(127, note))
        dur = max(end - start, 0.05)
        on_delta = max(sec_to_ticks(start) - cursor, 0)
        track.append(mido.Message("note_on", note=note, velocity=80, time=on_delta))
        track.append(mido.Message("note_off", note=note, velocity=0, time=sec_to_ticks(dur)))
        cursor = sec_to_ticks(start) + sec_to_ticks(dur)

    dst.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(dst))
    return dst
