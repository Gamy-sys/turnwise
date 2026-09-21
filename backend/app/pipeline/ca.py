"""Stage 7/8 - turn measurements into CA (Jefferson) cues and render text.

Every cue keeps the numbers that produced it (`evidence`) so the transcript is
auditable and the user can trust or override each symbol. This is a *draft*
generator; the UI editor is where a human finalizes the transcript.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from ..config import Settings
from ..models import (Cue, DocumentMeta, PitchPoint, Speaker, Token, Transcript, Turn)
from .asr import ASRResult
from .prosody import Prosody
from .diarization import DiarResult, speaker_for_interval

_VOWELS = "aeiouyAEIOUY"
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_LAUGH_RE = re.compile(r"^(ha|he|heh|hah|hee|haha|hehe|lol|ahah)+$", re.I)
_PUNCT_EDGE = re.compile(r"^[\"'“”‘’(\[]+|[.,!?;:\"'“”‘’)\]]+$")


def _clean(text: str) -> str:
    """Strip standard punctuation edges; CA uses its own intonation symbols."""
    t = text.strip()
    t = re.sub(r'^[."“”‘’\'(\[「『（【]+', "", t)
    t = re.sub(r'[.,!?;:"“”‘’)\]。、，！？：；」』）】]+$', "", t)
    return t or text.strip()


@lru_cache(maxsize=4096)
def _japanese_mora_count(text: str) -> int:
    try:
        from pykakasi import kakasi

        reading = "".join(
            x.get("hira", x.get("orig", "")) for x in kakasi().convert(text)
        )
        kana = [ch for ch in reading if re.match(r"[\u3040-\u30ffー]", ch)]
        small = set("ゃゅょぁぃぅぇぉャュョァィゥェォ")
        return max(1, sum(ch not in small for ch in kana))
    except Exception:
        return max(1, len(text))


def _fmt_pause(seconds: float, th) -> Cue | None:
    if seconds < th.micropause_min:
        return None
    if seconds < th.timed_pause_min:
        return Cue(type="micropause", symbol="(.)", value=round(seconds, 3),
                   evidence={"gap_s": round(seconds, 3)})
    return Cue(type="pause", symbol=f"({seconds:.1f})", value=round(seconds, 3),
               evidence={"gap_s": round(seconds, 3)})


def _elongation(token_text: str, dur: float, th) -> Cue | None:
    clean = _clean(token_text)
    if dur < getattr(th, "elongation_min_dur", 0.22):
        return None
    units = len(clean)
    ratio = th.elongation_ratio
    if _JAPANESE_RE.search(clean):
        # Kanji character count badly underestimates spoken morae (e.g.
        # お友達=5 morae but 3 written units). Use the kana reading and a more
        # conservative threshold to avoid blanket false elongations.
        units = _japanese_mora_count(clean)
        ratio *= 2.0
    expected = max(units * th.expected_char_dur, th.expected_char_dur)
    if dur <= expected * ratio:
        return None
    excess = dur - expected * ratio
    n_colons = 1 + int(excess / max(th.elongation_colon_step, 0.01))
    n_colons = min(n_colons, getattr(th, "elongation_max_colons", 4))
    return Cue(type="elongation", symbol=":" * n_colons, value=round(dur, 3),
               evidence={"dur_s": round(dur, 3), "expected_s": round(expected, 3),
                         "colons": n_colons})


def _intonation(prosody: Prosody, start: float, end: float, th) -> Cue | None:
    span = end - start
    if span <= 0:
        return None
    a = end - span * th.intonation_final_frac
    trend = prosody.semitone_trend(a, end)
    if trend >= th.arrow_st:
        return Cue(type="intonation", symbol="↑", value=round(trend, 2),
                   evidence={"semitones": round(trend, 2), "kind": "sharp_rise"})
    if trend <= -th.arrow_st:
        return Cue(type="intonation", symbol="↓", value=round(trend, 2),
                   evidence={"semitones": round(trend, 2), "kind": "sharp_fall"})
    if trend >= th.rise_strong_st:
        return Cue(type="intonation", symbol="?", value=round(trend, 2),
                   evidence={"semitones": round(trend, 2), "kind": "rise"})
    if trend >= th.rise_weak_st:
        return Cue(type="intonation", symbol=",", value=round(trend, 2),
                   evidence={"semitones": round(trend, 2), "kind": "continuing"})
    if trend <= th.fall_st:
        return Cue(type="intonation", symbol=".", value=round(trend, 2),
                   evidence={"semitones": round(trend, 2), "kind": "falling"})
    return None


def _volume(prosody: Prosody, start: float, end: float, speaker_median: float, th):
    vals = prosody.intensity_in(start, end)
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return None, None
    mean_i = float(np.mean(vals))
    delta = mean_i - speaker_median
    vol_cue = None
    if delta >= th.loud_db:
        vol_cue = Cue(type="loud", symbol="CAPS", value=round(delta, 2),
                      evidence={"db_over_median": round(delta, 2)})
    elif delta <= th.quiet_db:
        vol_cue = Cue(type="quiet", symbol="°", value=round(delta, 2),
                      evidence={"db_over_median": round(delta, 2)})
    # Emphasis = clearly-above-median loudness that isn't a full "shout".
    stress_cue = None
    dur = end - start
    if (vol_cue is None and th.stress_db <= delta < th.loud_db
            and dur >= getattr(th, "stress_min_dur", 0.15)):
        stress_cue = Cue(type="stress", symbol="_", value=round(delta, 2),
                         evidence={"db_over_median": round(delta, 2)}, confidence=0.6)
    return vol_cue, stress_cue


def _tempo(clean_text: str, dur: float, speaker_rate: float, th) -> Cue | None:
    if dur <= 0 or speaker_rate <= 0 or len(clean_text) < getattr(th, "tempo_min_chars", 3):
        return None
    rate = len(clean_text) / dur              # chars per second
    ratio = rate / speaker_rate
    if ratio >= th.fast_ratio:
        return Cue(type="fast", symbol="><", value=round(ratio, 2),
                   evidence={"rate_ratio": round(ratio, 2)}, confidence=0.7)
    if ratio <= th.slow_ratio:
        return Cue(type="slow", symbol="<>", value=round(ratio, 2),
                   evidence={"rate_ratio": round(ratio, 2)}, confidence=0.7)
    return None


def build_transcript(project_id: str, filename: str, duration: float,
                     asr: ASRResult, prosody: Prosody, diar: DiarResult,
                     settings: Settings) -> Transcript:
    th = settings.thresholds
    words = [w for w in asr.words if _clean(w.text)]

    # ---- assign speakers -------------------------------------------------
    # Channel-split ASR pre-assigns a speaker per word; honor that first.
    preassigned = len(words) > 0 and all(getattr(w, "speaker", None) for w in words)
    if preassigned:
        labels = sorted({w.speaker for w in words})  # type: ignore[attr-defined]
    elif diar.available and diar.segments:
        for w in words:
            w.speaker = speaker_for_interval(  # type: ignore[attr-defined]
                diar.segments, w.start, w.end,
            )
        labels = sorted({w.speaker for w in words})  # type: ignore[attr-defined]
    else:
        for w in words:
            w.speaker = "A"  # type: ignore[attr-defined]
        labels = ["A"]

    # Collapse brief mid-utterance speaker flips (same talker labeled A then B).
    try:
        from .asr import repair_speaker_label_flicker

        words = repair_speaker_label_flicker(words)
        words = repair_speaker_label_flicker(words)
    except Exception:
        pass
    labels = sorted({w.speaker for w in words if getattr(w, "speaker", None)}) or ["A"]
    speakers = [Speaker(id=l, label=l) for l in labels]

    # ---- per-speaker baselines for volume + tempo ------------------------
    spk_intensity: dict[str, list[float]] = {l: [] for l in labels}
    spk_rate: dict[str, list[float]] = {l: [] for l in labels}
    for w in words:
        if getattr(w, "kind", "word") != "word":
            continue  # non-speech (laughter/breath) doesn't set speech baselines
        vals = prosody.intensity_in(w.start, w.end)
        vals = vals[np.isfinite(vals)]
        if len(vals):
            spk_intensity[w.speaker].append(float(np.mean(vals)))  # type: ignore[attr-defined]
        dur = w.end - w.start
        c = _clean(w.text)
        if dur > 0 and c:
            spk_rate[w.speaker].append(len(c) / dur)  # type: ignore[attr-defined]
    spk_med_i = {l: (float(np.median(v)) if v else prosody.median_intensity)
                 for l, v in spk_intensity.items()}
    spk_med_r = {l: (float(np.median(v)) if v else 12.0) for l, v in spk_rate.items()}

    # ---- group into turns + attach cues ----------------------------------
    turns: list[Turn] = []
    cur: Turn | None = None
    prev_word_end = 0.0
    tok_idx = 0
    for i, w in enumerate(words):
        spk = w.speaker  # type: ignore[attr-defined]
        kind = getattr(w, "kind", "word")
        is_ns = kind in ("laughter", "breath")
        dur = w.end - w.start
        clean = w.text if is_ns else _clean(w.text)

        new_turn = cur is None or cur.speaker != spk
        if new_turn:
            _gap = w.start - prev_word_end
            # Latch only on a genuine ~zero POSITIVE gap. Negative gaps mean the
            # speakers overlap -> that is handled by overlap brackets, not '='.
            latched = cur is not None and 0.0 <= _gap <= th.latch_max_gap
            cur = Turn(id=f"turn{len(turns)}", speaker=spk, start=w.start, end=w.end,
                       latched_to_prev=latched)
            turns.append(cur)

        tok = Token(id=f"t{tok_idx}", text=clean, start=w.start, end=w.end, speaker=spk)
        tok_idx += 1

        # pause before this token
        gap = w.start - prev_word_end if i > 0 else 0.0
        if not new_turn:
            p = _fmt_pause(gap, th)
            if p:
                tok.pre_pause = p
        else:
            # inter-turn pause becomes a standalone pause turn (rendered on its own line)
            if i > 0 and not cur.latched_to_prev:
                p = _fmt_pause(gap, th)
                if p:
                    turns.insert(len(turns) - 1, Turn(id=f"pause{i}", speaker="", start=prev_word_end,
                                                      end=w.start, tokens=[
                                                          Token(id=f"tp{i}", text=p.symbol,
                                                                start=prev_word_end, end=w.start,
                                                                cues=[p])]))

        if is_ns:
            # detected laughter / breath: no prosodic cues, just tag it
            if kind == "laughter":
                ctype = "laughter"
            else:
                ctype = "in_breath" if w.text.strip().startswith(".") else "out_breath"
            tok.cues.append(Cue(type=ctype, symbol="", confidence=0.5,
                                evidence={"kind": kind, "dur_s": round(dur, 3)}))
        else:
            # elongation
            if getattr(th, "enable_elongation", True):
                el = _elongation(clean, dur, th)
                if el:
                    tok.cues.append(el)
            # volume + stress
            if getattr(th, "enable_volume", False):
                vol, stress = _volume(prosody, w.start, w.end, spk_med_i[spk], th)
                if vol:
                    tok.cues.append(vol)
                if stress:
                    tok.cues.append(stress)
            # tempo
            if getattr(th, "enable_tempo", False):
                tp = _tempo(clean, dur, spk_med_r[spk], th)
                if tp:
                    tok.cues.append(tp)
            # cutoff (candidate)
            if th.enable_cutoff and dur < 0.18 and w.probability < 0.5 and i + 1 < len(words):
                nxt = _clean(words[i + 1].text)
                if nxt and clean and nxt[0].lower() == clean[0].lower():
                    tok.cues.append(Cue(type="cutoff", symbol="-", confidence=0.4,
                                        evidence={"dur_s": round(dur, 3), "prob": round(w.probability, 2)}))
            # laughter (from text)
            if th.enable_laughter and _LAUGH_RE.match(clean.replace(" ", "")):
                tok.cues.append(Cue(type="laughter", symbol="£", confidence=0.6,
                                    evidence={"token": clean}))

        cur.tokens.append(tok)
        cur.end = w.end
        prev_word_end = w.end

    # ---- terminal intonation on the last token of each turn --------------
    if getattr(th, "enable_intonation", False):
        for t in turns:
            if not t.tokens or t.speaker == "":
                continue
            last = t.tokens[-1]
            ic = _intonation(prosody, last.start, last.end, th)
            if ic:
                last.cues.append(ic)

    # ---- overlap markers -------------------------------------------------
    if diar.available and diar.overlaps:
        for t in turns:
            for tok in t.tokens:
                for (os_, oe) in diar.overlaps:
                    if tok.start < oe and tok.end > os_:
                        tok.cues.append(Cue(type="overlap", symbol="[]", confidence=0.6,
                                            evidence={"region": [round(os_, 2), round(oe, 2)]}))
                        break

    # ---- pitch + intensity time series (downsampled for the UI) ----------
    pitch_pts = _downsample(prosody.times, prosody.f0, 1500)
    int_pts = _downsample(prosody.itimes, prosody.intensity, 1500)

    meta = DocumentMeta(
        project_id=project_id, filename=filename, duration=duration,
        created_at=datetime.now(timezone.utc).isoformat(),
        models={"asr": asr.model_name, "language": asr.language,
                "diarization": diar.source if diar.available else None},
        warnings=(
            ([] if diar.available else [diar.error or "diarization unavailable"])
            + (
                ["Only one speaker detected — set Number of speakers in Settings (e.g. 2) and Update transcript"]
                if diar.available and len(labels) < 2 and settings.enable_diarization
                else []
            )
        ),
    )
    tr = Transcript(meta=meta, speakers=speakers, turns=turns,
                    pitch=[PitchPoint(t=round(t, 3), f0=round(f, 1)) for t, f in pitch_pts],
                    intensity=[PitchPoint(t=round(t, 3), f0=round(f, 1)) for t, f in int_pts])
    tr.jefferson = render_jefferson(tr)
    return tr


def _downsample(times, values, max_points):
    n = len(times)
    if n == 0:
        return []
    if n <= max_points:
        return list(zip(times.tolist(), np.nan_to_num(values).tolist()))
    idx = np.linspace(0, n - 1, max_points).astype(int)
    return list(zip(times[idx].tolist(), np.nan_to_num(values[idx]).tolist()))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def regroup_turns(tokens: list[Token], th) -> list[Turn]:
    """Rebuild turn structure from a flat, edited token list.

    Used after manual edits (add/delete word, change timing or speaker) so that
    turns, latching (=) and pauses stay consistent with the words + timings.
    """
    toks = sorted(tokens, key=lambda t: (t.start, t.end))
    turns: list[Turn] = []
    cur: Turn | None = None
    prev_end: float | None = None
    for i, tok in enumerate(toks):
        new_turn = cur is None or cur.speaker != (tok.speaker or "A")
        if new_turn:
            gap = (tok.start - prev_end) if prev_end is not None else 0.0
            latched = cur is not None and 0.0 <= gap <= th.latch_max_gap
            if cur is not None and not latched:
                p = _fmt_pause(gap, th)
                if p:
                    turns.append(Turn(id=f"pause_{i}", speaker="", start=prev_end or 0.0,
                                      end=tok.start,
                                      tokens=[Token(id=f"tp_{i}", text=p.symbol,
                                                    start=prev_end or 0.0, end=tok.start, cues=[p])]))
            cur = Turn(id=f"turn{len([t for t in turns if t.speaker])}",
                       speaker=tok.speaker or "A", start=tok.start, end=tok.end,
                       latched_to_prev=latched)
            turns.append(cur)
            tok.pre_pause = None
        else:
            gap = tok.start - (prev_end if prev_end is not None else tok.start)
            tok.pre_pause = _fmt_pause(gap, th)
        cur.tokens.append(tok)
        cur.end = tok.end
        prev_end = tok.end
    return turns


def _render_token(tok: Token) -> str:
    text = tok.text
    types = {c.type for c in tok.cues}
    # elongation colons inserted after the last vowel
    el = next((c for c in tok.cues if c.type == "elongation"), None)
    if el:
        if _JAPANESE_RE.search(text):
            # Moraic ん follows the prolonged vowel: う::ん, not うん::.
            pos = len(text) - 2 if len(text) > 1 and text[-1] in "んン" else len(text) - 1
        else:
            pos = max((i for i, ch in enumerate(text) if ch in _VOWELS), default=len(text) - 1)
        text = text[: pos + 1] + el.symbol + text[pos + 1:]
    if "cutoff" in types and not text.endswith("-"):
        text = text + "-"
    if "loud" in types:
        text = text.upper()
    if "stress" in types:
        text = f"_{text}_"
    if "quiet" in types:
        text = f"°{text}°"
    # intonation terminal symbol appended
    ic = next((c for c in tok.cues if c.type == "intonation"), None)
    prefix = ""
    if tok.pre_pause:
        prefix = tok.pre_pause.symbol + " "
    rendered = prefix + text
    if ic:
        rendered = rendered + ic.symbol
    return rendered


# CA line layout (Jefferson plain-text export + on-screen monospace):
#   {line_number}{3 spaces}{speaker}{2 spaces}:{4 spaces}{talk}
# Example:  "1   A  :    Hello"
# Pause lines use an empty speaker so the colon column still lines up:
#           "2     :    (0.4)"
_CA_AFTER_NUM = "   "      # 3 spaces after the line number
_CA_AFTER_NAME = "  "      # 2 spaces after the speaker code
_CA_AFTER_COLON = "    "   # 4 spaces after the colon
_CA_LINE_RE = re.compile(
    r"^\s*(\d+)"           # line number
    r" {3}"                # exactly 3 spaces
    r"(.*?)"               # speaker name (may be empty)
    r" {2}:"               # exactly 2 spaces + colon
    r" {4}"                # exactly 4 spaces
    r"(.*)$"               # talk / pause body
)


def format_ca_line(no: int, speaker: str | None, body: str,
                   *, num_width: int = 0) -> str:
    """Render one CA transcript line with the fixed spacing contract.

    ``number + 3 spaces + name + 2 spaces + colon + 4 spaces + talk``
    """
    n = f"{no:>{num_width}}" if num_width > 0 else str(no)
    name = (speaker or "").strip()
    return f"{n}{_CA_AFTER_NUM}{name}{_CA_AFTER_NAME}:{_CA_AFTER_COLON}{body}"


def parse_ca_line(raw: str) -> tuple[str, str]:
    """Split a CA line into (speaker, body). Empty speaker => pause/comment line."""
    s = raw.rstrip("\n")
    if not s.strip():
        return ("", "")
    m = _CA_LINE_RE.match(s)
    if m:
        return (m.group(2).strip(), m.group(3))
    # Legacy fallbacks: "A:\tbody", "A: body", tab-only pause, "N  A: body"
    if s.startswith("\t"):
        return ("", s.strip())
    if ":\t" in s:
        spk, body = s.split(":\t", 1)
        spk = spk.strip()
        if " " in spk:
            maybe_no, maybe_name = spk.split(None, 1)
            if maybe_no.isdigit():
                spk = maybe_name
        return (spk.strip(), body)
    if ":" in s:
        spk, body = s.split(":", 1)
        spk = spk.strip()
        if " " in spk:
            maybe_no, maybe_name = spk.split(None, 1)
            if maybe_no.isdigit():
                spk = maybe_name
        return (spk.strip(), body.lstrip("\t "))
    return ("", s.strip())


def render_turn_body(t: Turn) -> str:
    """Render one spoken turn body without its line number/speaker gutter."""
    if not t.speaker:
        return t.tokens[0].cues[0].symbol if t.tokens and t.tokens[0].cues else "(.)"

    parts: list[str] = []
    # tempo run wrapping
    i = 0
    toks = t.tokens
    while i < len(toks):
        tk = toks[i]
        ttypes = {c.type for c in tk.cues}
        if "fast" in ttypes or "slow" in ttypes:
            kind = "fast" if "fast" in ttypes else "slow"
            run_toks = []
            while i < len(toks) and any(c.type == kind for c in toks[i].cues):
                run_toks.append(toks[i])
                i += 1
            rendered = [_render_token(x) for x in run_toks]
            # Tempo brackets should span a stretch of talk, not one word.
            if len(run_toks) >= 2:
                inner = " ".join(rendered)
                parts.append(f">{inner}<" if kind == "fast" else f"<{inner}>")
            else:
                parts.extend(rendered)
        else:
            parts.append(_render_token(tk))
            i += 1
    body = " ".join(parts)
    # overlap brackets (approximate: wrap contiguous overlapped tokens)
    if any(c.type == "overlap" for tk in t.tokens for c in tk.cues):
        body = _wrap_overlap(t)
    latch = "= " if t.latched_to_prev else ""
    return latch + body


def render_jefferson(tr: Transcript) -> str:
    """Render the full Jefferson transcript with CA line layout + numbers."""
    n_turns = max(1, len(tr.turns))
    width = len(str(n_turns))
    return "\n".join(
        format_ca_line(no, t.speaker, render_turn_body(t), num_width=width)
        for no, t in enumerate(tr.turns, start=1)
    )


def _wrap_overlap(t: Turn) -> str:
    out = []
    in_ov = False
    for tk in t.tokens:
        is_ov = any(c.type == "overlap" for c in tk.cues)
        piece = _render_token(tk)
        if is_ov and not in_ov:
            piece = "[" + piece
            in_ov = True
        if not is_ov and in_ov:
            out[-1] = out[-1] + "]"
            in_ov = False
        out.append(piece)
    if in_ov:
        out[-1] = out[-1] + "]"
    return " ".join(out)
