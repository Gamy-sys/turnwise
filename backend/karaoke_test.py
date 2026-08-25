"""Build a transcript from a short clip and render karaoke MP4 + PPTX."""
import sys, tempfile, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings
from app.pipeline import ingest, asr as asr_mod, prosody as pros_mod, ca
from app.pipeline.asr import ASRResult
from app.pipeline.diarization import DiarResult
from app.jobs import _channel_overlaps, _suppress_crosstalk
from app.pipeline.karaoke import render_karaoke_mp4, build_pptx

SRC = "/home/majestic1/Documents/4708.mp3"
tmp = Path(tempfile.mkdtemp())
clip = tmp / "clip.wav"
subprocess.run(["ffmpeg", "-y", "-t", "13", "-i", SRC, "-c:a", "pcm_s16le", str(clip)],
               capture_output=True, check=True)

prep = ingest.prepare(clip, tmp, sample_rate=16000)
s = Settings(); s.whisper_model = "base"
words = []
cw = {}
for label, w in prep.channels:
    cw[label] = w
    r = asr_mod.transcribe(str(w), s)
    for x in r.words: x.speaker = label
    words += r.words
words = _suppress_crosstalk(words, cw, s.thresholds.crosstalk_db)
words.sort(key=lambda x: (x.start, x.end))
diar = DiarResult(available=True, source="channels",
                  segments=[(x.start, x.end, x.speaker) for x in words],
                  overlaps=_channel_overlaps(words, s.thresholds.min_overlap_dur))
asr = ASRResult(language="en", words=words, model_name="base")
pros = pros_mod.extract(str(prep.mono_wav))
tr = ca.build_transcript("clip", "4708.mp3", prep.duration, asr, pros, diar, s)

mp4 = tmp / "karaoke.mp4"
render_karaoke_mp4(tr, prep.mono_wav, mp4, fps=15)
print("MP4:", mp4, mp4.stat().st_size, "bytes")

pptx = tmp / "karaoke.pptx"
build_pptx(mp4, pptx)
print("PPTX:", pptx, pptx.stat().st_size, "bytes")

# validate outputs
from pptx import Presentation
p = Presentation(str(pptx))
print("pptx slides:", len(p.slides.__iter__.__self__._sldIdLst))
dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                      "-of","default=noprint_wrappers=1:nokey=1", str(mp4)],
                     capture_output=True, text=True).stdout.strip()
print("mp4 duration:", dur)
print("ASS head:")
print("\n".join((tmp/'karaoke.ass').read_text().splitlines()[:14]) if (tmp/'karaoke.ass').exists() else "no ass at expected path")
print("KARAOKE TEST OK")
