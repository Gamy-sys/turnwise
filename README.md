# Turnwise

Formerly CA Studio. A local, offline-capable app for **Conversation-Analysis (CA)
transcription** — with a **Simple** batch mode for folder-to-folder jobs and an
**Advanced** editor for Jefferson notation, karaoke playback, collections, and exports.

Drop in an MP3 (or WAV/M4A/FLAC/OGG) and it produces a **word-perfect, Jefferson-notation
draft transcript** you can play back with a **karaoke-style word highlight**, inspect
against the measured evidence, hand-correct, and export.

It is **local-first**: all core features run on your machine with no network. OpenAI is
optional and off by default. Speaker diarization is optional and needs a free Hugging Face
token (see below).

### Modes

| Mode | Use when |
|---|---|
| **Simple** | Many files in a row — pick an input folder, an output folder, a few settings, Start batch |
| **Advanced** | One recording at a time — waveform, Praat-style pitch, collections, PPT, Japanese 4-line, hand edits |

---

## What it does

**Pipeline (each stage cached per project):**

1. **Ingest** – ffmpeg decodes to 16 kHz mono WAV (original kept for playback).
2. **Diarization + overlap** *(optional)* – `pyannote.audio` labels speakers and finds
   overlapping talk. Skipped gracefully if unavailable.
3. **ASR** – `faster-whisper` (CTranslate2) verbatim transcription **with word timestamps**,
   CPU-friendly via `int8`. Keeps fillers (uh/um), repeats, and false starts.
4. **Prosody** – Praat (`parselmouth`) continuous **pitch (F0)** + **intensity**. This is the
   "voice as music" layer, done on continuous pitch rather than lossy MIDI so the CA symbols
   are accurate.
5. **CA derivation** – converts measurements into Jefferson symbols; every cue stores the
   numbers that produced it.
6. **Render + edit + export.**

**Jefferson / CA notation produced (all tunable, all editable):**

| Feature | Symbol | Source |
|---|---|---|
| Timed pause / micropause | `(0.6)` / `(.)` | gaps between words |
| Latching | `=` | ~0-gap turn transitions |
| Overlap | `[ ]` | diarization overlap (optional) |
| Sound stretch | `so::::` | word/vowel duration vs expected |
| Intonation (terminal) | `. , ? ↑ ↓` | F0 trend over the unit's final region |
| Emphasis | underline | intensity prominence |
| Volume | `CAPS` / `°quiet°` | intensity vs speaker median |
| Tempo | `>fast<` / `<slow>` | syllable rate vs speaker median |
| Cut-off | `wor-` | short low-confidence fragment *(candidate)* |
| Breath / laughter | `.hh` `hh` `£` | non-speech energy + text cues *(candidate)* |

**UI:** waveform + transport (wavesurfer), synced karaoke highlight (click a word to seek),
pitch/intensity "musical" view with **MIDI export**, a right-hand **Inspector** to hand-correct
any word and toggle/edit its cues (auto cues show their measured evidence), and a canonical
plain-text Jefferson pane.

**Exports:** Jefferson `.txt`, project `.json`, pitch `.mid`, Praat `.TextGrid`, ELAN `.eaf`,
**VBA timing** `.txt` (word/sentence start+end for PowerPoint animation).

---

## Requirements

- Linux, **Python 3.10+**, **Node 18+**, and **ffmpeg** (`sudo apt install ffmpeg`).
- CPU is fine (default). An NVIDIA GPU is auto-used if available and speeds things up.

## Quick start

```bash
cd ca-studio
./run.sh                 # builds the UI if needed, serves on http://127.0.0.1:8000
# or during development (hot-reload UI on :5173):
./run.sh --dev
```

Manual setup (equivalent to the script):

```bash
# backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# frontend (one-time build)
cd ../frontend
npm install && npm run build

# run (from ca-studio/)
cd ../backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open **http://127.0.0.1:8000**. Use the top **Simple / Advanced** switch:
- **Simple** — input folder, output folder, basic settings, Start batch
- **Advanced** — full CA editor (the original studio UI)

> **CPU note:** the first run downloads the chosen Whisper model to `data/models/`. Processing
> runs in the background with a live progress bar.

### Install on Mac

Build an installable `.app` / `.dmg` **on a Mac** (Apple Silicon or Intel):

```bash
brew install ffmpeg python@3.12 node
cd ca-studio
chmod +x scripts/build-mac.sh
./scripts/build-mac.sh
```

Installers land in `desktop/dist/` (e.g. `Turnwise-0.2.0-arm64.dmg`). Open the DMG and
drag **Turnwise** into Applications. The first launch creates a Python environment under
`~/Library/Application Support/Turnwise` and installs backend packages — allow several minutes.

To run the desktop shell without packaging (also works during development):

```bash
cd ca-studio/frontend && npm run build
cd ../desktop && npm install && npm start
```

### Japanese four-line transcripts

In **Settings → Transcript layout**, choose **Japanese · romanization · direct · natural**.
This forces `language=ja`, selects multilingual `large-v3`, keeps Jefferson markers, and
renders each spoken unit as:

1. timed Japanese CA source
2. italic Hepburn-style romanization
3. morpheme-level direct English gloss
4. bold natural English translation

Romanization and Japanese morphological spacing are local. Direct and natural English use
the configured OpenAI model, because generic offline MT cannot reproduce the specialized
particle glosses (`SP`, `O`, `L`, `CP`, `FP`, `QT`) in the research layout. All three
companion rows are editable by double-clicking. Use **DOCX 4-line** to export A4, 10 pt
monospace Word output with speaker/focus colors.

For multi-speaker or overlapping recordings, configure diarization below. No ASR can
guarantee error-free recovery of a quiet backchannel masked by louder speech in a mixed
channel; confidence/timing remain visible for manual correction.

---

## Enabling speaker diarization (Hugging Face token)

Diarization (who spoke when + overlaps) uses `pyannote.audio`, which downloads a gated model.
It is **optional** — without it the app treats the audio as a single speaker and everything
else still works.

### 1. Install the optional dependencies

```bash
cd ca-studio/backend
. .venv/bin/activate
# CPU-only torch wheels (skip the index-url line if you have CUDA):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-diarization.txt
```

### 2. Get a Hugging Face access token (free)

1. Create a free account at **https://huggingface.co/join** (or log in).
2. Go to **https://huggingface.co/settings/tokens**.
3. Click **"Create new token"**. Choose type **Read** (or a fine-grained token with
   *"Read access to public gated repos"* enabled). Name it e.g. `ca-studio` and click
   **Create token**.
4. **Copy the token** (it looks like `hf_XXXXXXXXXXXXXXXXXXXXXXXX`). You will not be able to see
   it again — store it somewhere safe.

### 3. Accept the model's terms (one-time, required for gated models)

While logged in, open each page and click **"Agree and access repository"**:

- **https://huggingface.co/pyannote/speaker-diarization-3.1**
- **https://huggingface.co/pyannote/segmentation-3.0**

(These are free; you just have to accept the usage conditions once.)

### 4. Give CA Studio the token

Either paste it into the **Settings → Hugging Face token** field before uploading, **or** set
it as an environment variable before starting the server:

```bash
export HUGGINGFACE_TOKEN=hf_XXXXXXXXXXXXXXXXXXXXXXXX
./run.sh
```

Make sure **"Diarization + overlap"** is checked in Settings. If the token is missing or the
model terms haven't been accepted, the app logs a warning and simply proceeds without
diarization.

---

## Enabling OpenAI (optional)

Off by default; nothing leaves your machine unless you turn this on.

```bash
pip install "openai>=1.30"
export OPENAI_API_KEY=sk-...        # or paste it in Settings
```

Tick **Settings → Enable OpenAI refinement**. The **OpenAI refine** button then asks a model to
fix obvious ASR word errors (while preserving verbatim fillers) and improve CA symbol placement;
the result is shown in the Jefferson pane for you to accept or ignore.

---

## Tuning the CA output

The auto transcript is a **draft** meant to be hand-finished. To keep that draft close to a clean
CA transcript, the noisy prosodic cue families are **off by default** and switched on in
**Settings → CA cues (auto)**:

| Cue family | Default | Notes |
|---|---|---|
| Elongation `so::` | on | conservative (needs a clear stretch) |
| Overlap `[ ]`, latching `=`, pauses `(.) (0.4)`, cut-offs `th-` | on | structural, low false-alarm |
| Laughter `hhh hhh` (+ its overlaps) | on | detected from channel audio in word gaps |
| Breath `.hhh` | **off** | noisier; enable if you need it |
| Terminal intonation `. , ? ↑` | **off** | per-word; enable if you want it |
| Volume `CAPS / °quiet° / stress` | **off** | very sensitive on phone audio |
| Tempo `>fast< / <slow>` | **off** | only spans runs of ≥2 words |

**Laughter / breath detection** looks for energy bursts on each channel that fall in the *gaps*
between that speaker's words (so they aren't already transcribed). Pulsed bursts become `hhh hhh`
(laughter), single blobs become `.hhh` (breath). Because they land on the timeline as tokens, a
laughter during the other speaker's talk is bracketed as an overlap automatically. It's tuned to be
conservative; adjust *Laughter energy* in Advanced thresholds, and add/remove any in the editor.

Other tunables (pause length, elongation ratio, overlap minimum duration, cross-talk rejection,
loud/quiet dB, tempo ratios) live under **Settings → Advanced: CA thresholds** and are **relative
to each speaker**, so they're best tuned per recording. A **vocabulary hint** field lets you bias
the recogniser toward names/jargon likely in the audio.

### Matching a reference transcript

Work on a short slice first (the pipeline is fast on a 10–15 s clip): upload it, pick a bigger
Whisper model (`medium`/`large-v3`) for word accuracy, and tune thresholds until overlaps, pauses
and elongation line up. Then apply the same settings to the full file. Exact word-for-word and
laughter/`hhh`-level matching is **not achievable by ASR alone** on 8 kHz phone audio — that final
polish is what the editor is for.

### Keeping fillers / disfluencies ("uh", "uhh", stutters)

Standard Whisper *normalises* speech and drops fillers, repetitions and false starts — no setting
changes that. If verbatim disfluencies matter (they do for CA), use a verbatim-focused recogniser:

- **CrisperWhisper** — a Whisper variant fine-tuned specifically for verbatim transcription (keeps
  "um/uh", stutters, false starts, with crisp word timestamps). A CTranslate2 build,
  `nyrahealth/faster_CrisperWhisper`, runs in the same faster-whisper engine, so it's selectable
  directly in the **Whisper model** dropdown (first run downloads ~1.5 GB). This is the recommended
  option for CA-grade fillers.
- **wav2vec2 / CTC models** (e.g. `facebook/wav2vec2-large-960h`) transcribe very literally but
  without punctuation/casing.
- **Cloud APIs with explicit filler modes**: Deepgram (`filler_words=true`), AssemblyAI
  (`disfluencies=true`), Speechmatics (verbatim mode). These need an API key and send audio off-box.

For higher-precision word/phoneme timing than faster-whisper's built-in timestamps, you can swap
the ASR stage for WhisperX or the Montreal Forced Aligner behind the same interface in
`backend/app/pipeline/asr.py`.

## Editing (the Inspector)

Click any word to open the Inspector. You can:

- **edit the word text** and toggle/add/remove any CA cue on it;
- **edit timing** — `start`/`end` in seconds (type, or nudge ±0.05 s). Timing **drives the karaoke
  highlight**, so this is how you fix when a word lights up. `▶ preview` plays just that word;
- **add words** before/after the selected one, or **delete** a word;
- **reassign the speaker** of a word (chips at the bottom);
- **rename speakers** (`A` → `S1`, etc.) from the toolbar.

On **Save**, turns, latching (`=`) and pauses are recomputed from the edited words + timings, so
the structure stays consistent no matter how much you rearrange.

## PowerPoint karaoke export

Two buttons in the export bar produce a karaoke that keeps the moving highlight inside PowerPoint:

- **▶ PPTX karaoke** — a `.pptx` with a full-slide video already embedded. Open it, and in
  slideshow click the video (or set *Playback → Start: Automatically* once) to play the transcript
  with the words highlighting in time with the audio.
- **mp4** — the raw karaoke video, in case you'd rather drop it onto an existing slide (Insert →
  Video → This Device).

The video is rendered with `ffmpeg` (ASS `\k` karaoke subtitles over a dark background + your
audio), so it plays on any machine with no fonts or plugins. It's cached per project and only
re-rendered after you change the transcript. Long recordings take a little while to encode.

## VBA timing export (roll your own PowerPoint animation)

If you'd rather drive PowerPoint animations from VBA instead of embedding a video, use the
**VBA timing** export. It's a plain `.txt` with four fixed sections and no markdown/numbering:

```
==================================
TRANSCRIPT
==================================

<full text, one sentence per turn, punctuation only here>

==================================
WORD_TIMESTAMPS
==================================

start|end|Word          # seconds, 3 decimals, no punctuation on the word

==================================
SENTENCE_TIMESTAMPS
==================================

start|end|Sentence text.

==================================
VBA_IMPORT
==================================

WordCount=<n>

start|Word              # start time only, for triggering each animation step
```

Words are listed strictly in chronological order across both speakers, capitalization is
preserved, and punctuation is attached only to the transcript/sentence text (never to the word
list). All edits you make in the Inspector (text + timing) are reflected in the export.

## Transcript slides (.pptx)

The **Slides PPTX** button lays the whole Jefferson transcript out across 16:9 slides at
**font size 20** in a monospace font, on the same dark background as the app. Speaker labels are
bold/amber and every CA symbol is preserved verbatim — pauses `(0.4)`, micro-pauses `(.)`,
overlap brackets `[ ]`, elongation `::`, latching `=`, laughter, etc. Turns are packed to fill
each slide and long turns wrap and roll onto the next slide automatically. Append `?size=24`
to the export URL for a different font size.

---

## Presentation generator (sub-app)

The **🎬 Generate presentation…** button (in the export bar) opens an options dialog and builds
complete decks from one universal project (audio + transcript + word timings). Pick a title,
theme (dark/light), font size, slide chunking (fit-to-slide or fixed time window), whether to
include a title slide / speaker notes / audio, karaoke mode, and any mix of output formats.
Everything is packaged into a `.zip` you can download in one click.

**Outputs:** `.pptx`, `.pptm`, `.odp`, `.pdf`, `.srt`, `.vtt`, `.txt`, `.json`. Each slide carries
a title (timecode), the transcript, speaker-coloured text, speaker notes, per-word timing and
bookmarks, theme, and document metadata.

**Karaoke (one word highlights while narration plays)** — the generator picks the best strategy
per format:

- **Strategy A — PowerPoint animation timeline** (`.pptx`): native per-word colour emphases that
  target **character ranges**, editable in PowerPoint.
- **Strategy B — VBA runtime** (`.pptm`): a macro reads `timing.txt` + audio from the same folder
  and highlights by character position, advancing slides / pause / resume / replay. Shipped as
  importable `Karaoke.bas` (enable macros to run; signing needs your own certificate).
- **Strategy C — LibreOffice runtime** (`.odp`): a Basic/UNO macro (`karaoke_libreoffice.bas`) does
  the same in Impress.

**Timing contract:** every word stores `start`, `end`, `charStart`, `charLength`, `speaker`.
Highlighting always uses character positions — never a text search.

**Architecture (`app/presentation/`)** is deliberately layered so it stays maintainable and new
targets (Google Slides, Keynote, Reveal.js, HTML5, OBS/DaVinci/Premiere/CapCut/After Effects) can
be added by dropping in one exporter module — no changes to transcription, the builder or the
project model:

```
transcription → builder → PresentationProject → exporters (registry)
```

- `project.py`   — the universal `PresentationProject` model every exporter reads.
- `builder.py`   — the only place that reads the transcript; produces the project.
- `exporters/`   — one module per format behind a single `Exporter` interface + registry.
- `service.py`   — build → run selected exporters → bundle `.zip`.

Direct OOXML/OpenDocument is written (no COM automation). `.pptx`/`.pptm` are valid Office Open
XML packages; `.odp` is a valid OpenDocument package. `.pdf` renders with reportlab (no Office
needed).

---

## Project layout

```
ca-studio/
├── run.sh                     # one-command launcher
├── backend/
│   ├── requirements.txt       # core deps (CPU, no torch)
│   ├── requirements-diarization.txt   # optional pyannote + torch
│   └── app/
│       ├── main.py            # FastAPI routes + serves the built UI
│       ├── config.py          # settings + tunable CA thresholds
│       ├── models.py          # transcript data model
│       ├── jobs.py            # background pipeline runner + progress
│       ├── exports.py         # txt / TextGrid / ELAN / VBA timing / slides pptx
│       ├── presentation/      # presentation sub-app: project, builder, exporters, service
│       └── pipeline/          # ingest, asr, prosody, diarization, ca, midi, karaoke, openai
└── frontend/                  # Vite + React SPA (built into frontend/dist)
```

## Notes & limitations

- Cut-offs, breaths, and laughter are the hardest cues to detect automatically and are emitted
  as low-confidence **candidates** for you to confirm. Laughter that isn't spoken as words (e.g.
  `hhh` over another speaker) won't auto-create an overlap — add it in the editor.
- For **stereo phone calls**, each speaker is on their own channel: CA Studio transcribes the
  channels separately for near-perfect speaker attribution, and suppresses cross-channel bleed.
  For true mono, it falls back to `pyannote` diarization (needs the HF token).
- Overlap `[ ]` requires a real simultaneous stretch (`min_overlap_dur`, default 0.2 s); brief
  boundary bleed is treated as latching instead.
- Data (uploads, WAVs, transcripts, models, karaoke video/pptx) lives under `ca-studio/data/`.
