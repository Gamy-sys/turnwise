"""Iterate transcription params on a short clip and compare to the reference.

Usage: python iterate.py [start] [dur] [model] [prompt]
"""
import sys
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings
from app.pipeline import ingest, asr as asr_mod, prosody as pros_mod, ca
from app.pipeline.asr import ASRResult
from app.pipeline.diarization import DiarResult
from app.jobs import _channel_overlaps, _suppress_crosstalk

SRC = "/home/majestic1/Documents/4708.mp3"
START = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 13.0
MODEL = sys.argv[3] if len(sys.argv) > 3 else "medium"
PROMPT = sys.argv[4] if len(sys.argv) > 4 else None

TARGET = """\
S1: you there Dick
S2: yeah
S1: ok
S2: what's going on [hhh hhh
S1: [no, it's, uh funny thing, I got this uhh my mother in law called me
S2: yeah"""


def run():
    tmp = Path(tempfile.mkdtemp())
    clip = tmp / "clip.wav"
    subprocess.run(["ffmpeg", "-y", "-ss", str(START), "-t", str(DUR), "-i", SRC,
                    "-c:a", "pcm_s16le", str(clip)], capture_output=True, check=True)

    prep = ingest.prepare(clip, tmp, sample_rate=16000)
    settings = Settings()
    settings.whisper_model = MODEL
    settings.initial_prompt = PROMPT

    all_words = []
    chan_wavs = {}
    for label, chan_wav in prep.channels:
        chan_wavs[label] = chan_wav
        res = asr_mod.transcribe(str(chan_wav), settings)
        for w in res.words:
            w.speaker = label
        all_words.extend(res.words)
    all_words = _suppress_crosstalk(all_words, chan_wavs, settings.thresholds.crosstalk_db)
    all_words.sort(key=lambda w: (w.start, w.end))
    diar = DiarResult(available=True, source="channels",
                      segments=[(w.start, w.end, w.speaker) for w in all_words],
                      overlaps=_channel_overlaps(all_words, settings.thresholds.min_overlap_dur))
    asr_res = ASRResult(language="en", words=all_words, model_name=MODEL)
    pros = pros_mod.extract(str(prep.mono_wav))
    tr = ca.build_transcript("clip", "4708.mp3", prep.duration, asr_res, pros, diar, settings)

    print(f"=== MODEL={MODEL} START={START} DUR={DUR} PROMPT={'yes' if PROMPT else 'no'} ===")
    print("--- TARGET (reference) ---")
    print(TARGET)
    print("--- OUTPUT ---")
    print(tr.jefferson)


if __name__ == "__main__":
    run()
