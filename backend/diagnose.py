"""Diagnose per-channel ASR, cross-talk drops, and overlaps on a clip.

Usage: python diagnose.py [start] [dur] [model] [crosstalk_db]
"""
import sys, tempfile, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings
from app.pipeline import ingest, asr as asr_mod, prosody as pros_mod, ca
from app.pipeline.asr import ASRResult
from app.pipeline.diarization import DiarResult
from app.jobs import _channel_overlaps, _suppress_crosstalk

SRC = "/home/majestic1/Documents/4708.mp3"
START = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 22.0
MODEL = sys.argv[3] if len(sys.argv) > 3 else "medium"
XTALK = float(sys.argv[4]) if len(sys.argv) > 4 else 8.0

tmp = Path(tempfile.mkdtemp())
clip = tmp / "clip.wav"
subprocess.run(["ffmpeg", "-y", "-ss", str(START), "-t", str(DUR), "-i", SRC,
                "-c:a", "pcm_s16le", str(clip)], capture_output=True, check=True)
prep = ingest.prepare(clip, tmp, sample_rate=16000)
s = Settings(); s.whisper_model = MODEL; s.thresholds.crosstalk_db = XTALK

per_chan = {}
all_words = []
cw = {}
for label, w in prep.channels:
    cw[label] = w
    r = asr_mod.transcribe(str(w), s)
    for x in r.words:
        x.speaker = label
    per_chan[label] = list(r.words)
    all_words += r.words

print(f"=== MODEL={MODEL}  START={START}  DUR={DUR}  crosstalk_db={XTALK} ===\n")
for label in per_chan:
    print(f"--- channel {label} raw ({len(per_chan[label])} words) ---")
    print("  " + " ".join(f"{x.text}[{x.start:.1f}]" for x in per_chan[label]))
    print()

kept = _suppress_crosstalk(all_words, cw, XTALK, s.thresholds.crosstalk_max_dur)
kept_ids = {id(x) for x in kept}
dropped = [x for x in all_words if id(x) not in kept_ids]
print(f"--- CROSS-TALK DROPPED {len(dropped)} words ---")
print("  " + " ".join(f"{x.speaker}:{x.text}[{x.start:.1f}]" for x in dropped))
print()

from app.pipeline import nonspeech
ns = nonspeech.detect(cw, kept, s.thresholds)
print(f"--- NON-SPEECH detected {len(ns)} ---")
for x in ns:
    print(f"  {x.speaker}:{x.kind} '{x.text}' [{x.start:.2f}-{x.end:.2f}]")
kept = kept + ns
print()

kept.sort(key=lambda x: (x.start, x.end))
ov = _channel_overlaps(kept, s.thresholds.min_overlap_dur)
print(f"--- OVERLAP regions ({len(ov)}) ---")
for a, b in ov:
    print(f"  {a:.2f}-{b:.2f}  ({b-a:.2f}s)")
print()

diar = DiarResult(available=True, source="channels",
                  segments=[(x.start, x.end, x.speaker) for x in kept], overlaps=ov)
asr = ASRResult(language="en", words=kept, model_name=MODEL)
pros = pros_mod.extract(str(prep.mono_wav))
tr = ca.build_transcript("clip", "4708.mp3", prep.duration, asr, pros, diar, s)
print("--- JEFFERSON ---")
print(tr.jefferson)
