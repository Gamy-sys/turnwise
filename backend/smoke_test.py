"""Offline smoke test: exercises everything except the Whisper download.

Generates a short synthetic WAV, runs prosody extraction, feeds a fake ASR
result into the CA builder, renders Jefferson, and writes every export format.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import main  # noqa: F401  (import-time check for the whole app)
from app.config import Settings
from app.pipeline import prosody as pros_mod
from app.pipeline import ca
from app.pipeline.asr import ASRResult, ASRWord
from app.pipeline.diarization import DiarResult
from app.pipeline.midi_export import export_midi
from app.exports import export_txt, export_textgrid, export_eaf


def make_wav(path: Path):
    # A short tone that glides in pitch, so parselmouth finds real F0.
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "sine=frequency=180:duration=3", "-ar", "16000", "-ac", "1", str(path)],
        capture_output=True, check=True,
    )


def main_test():
    tmp = Path(tempfile.mkdtemp())
    wav = tmp / "audio.wav"
    make_wav(wav)
    print("[1] wav generated:", wav)

    pros = pros_mod.extract(str(wav))
    print(f"[2] prosody: {len(pros.f0)} f0 frames, median_f0={pros.median_f0:.1f}Hz, "
          f"median_int={pros.median_intensity:.1f}dB")

    # Fake verbatim ASR with fillers, a long word, a repeat -> exercise cues.
    words = [
        ASRWord("uh", 0.10, 0.30, 0.9),
        ASRWord("so", 0.35, 0.95, 0.9),          # long -> elongation candidate
        ASRWord("I", 1.00, 1.10, 0.9),
        ASRWord("I", 1.12, 1.20, 0.4),           # repeat / cutoff candidate
        ASRWord("think", 1.25, 1.55, 0.9),
        ASRWord("that's", 2.10, 2.40, 0.9),      # preceded by a ~0.55s pause
        ASRWord("right", 2.42, 2.90, 0.9),
    ]
    asr = ASRResult(language="en", words=words, model_name="fake")
    diar = DiarResult(available=False, error="disabled for test")

    tr = ca.build_transcript("testproj", "sample.mp3", 3.0, asr, pros, diar, Settings())
    print("[3] transcript built:", len(tr.turns), "turns,",
          sum(len(t.tokens) for t in tr.turns), "tokens")
    print("---- Jefferson ----")
    print(tr.jefferson)
    print("-------------------")

    d = tmp
    export_txt(tr, d / "t.txt")
    export_textgrid(tr, d / "t.TextGrid")
    export_eaf(tr, d / "t.eaf")
    export_midi(tr, d / "t.mid")
    for f in ["t.txt", "t.TextGrid", "t.eaf", "t.mid"]:
        p = d / f
        assert p.exists() and p.stat().st_size > 0, f"export failed: {f}"
    print("[4] exports OK:", [f for f in ["t.txt", "t.TextGrid", "t.eaf", "t.mid"]])

    # round-trip transcript model validation
    from app.models import Transcript
    Transcript.model_validate(tr.model_dump())
    print("[5] transcript model round-trip OK")
    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main_test()
