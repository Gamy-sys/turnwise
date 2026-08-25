"""Validate channel-based speaker separation on a short clip of a real file."""
import sys
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings
from app.pipeline import ingest, asr as asr_mod, prosody as pros_mod, ca
from app.pipeline.asr import ASRResult
from app.pipeline.diarization import DiarResult
from app.jobs import _channel_overlaps

SRC = "/home/majestic1/Documents/4708.mp3"
CLIP_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 90
MODEL = sys.argv[2] if len(sys.argv) > 2 else "base"

tmp = Path(tempfile.mkdtemp())
clip = tmp / "clip.mp3"
subprocess.run(["ffmpeg", "-y", "-t", str(CLIP_SECONDS), "-i", SRC, "-c", "copy", str(clip)],
               capture_output=True, check=True)

prep = ingest.prepare(clip, tmp, sample_rate=16000)
print(f"mode={prep.mode}  channels={prep.n_channels}  corr={prep.corr}  "
      f"active_channels={len(prep.channels)}")

settings = Settings()
settings.whisper_model = MODEL

all_words = []
if prep.mode == "multichannel":
    for label, chan_wav in prep.channels:
        res = asr_mod.transcribe(str(chan_wav), settings)
        for w in res.words:
            w.speaker = label
        all_words.extend(res.words)
        print(f"  channel {label}: {len(res.words)} words")
    all_words.sort(key=lambda w: (w.start, w.end))
    diar = DiarResult(available=True, source="channels",
                      segments=[(w.start, w.end, w.speaker) for w in all_words],
                      overlaps=_channel_overlaps(all_words))
    asr_res = ASRResult(language="en", words=all_words, model_name=MODEL)
else:
    res = asr_mod.transcribe(str(prep.mono_wav), settings)
    asr_res = res
    diar = DiarResult(available=False, error="mono")

print(f"overlaps detected: {len(diar.overlaps)}")

pros = pros_mod.extract(str(prep.mono_wav))
tr = ca.build_transcript("clip", "4708.mp3", prep.duration, asr_res, pros, diar, settings)
print("speakers:", [s['label'] if isinstance(s, dict) else s.label for s in tr.speakers])
print("=== TRANSCRIPT (first ~", CLIP_SECONDS, "s) ===")
print(tr.jefferson)
