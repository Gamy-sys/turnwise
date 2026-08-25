"""Japanese four-line CA annotation.

The timed Japanese source remains in ``Turn.tokens``.  This module adds three
turn-level companion rows:

1. Hepburn-style transliteration
2. Morpheme-level direct English gloss
3. Natural English translation

Romanization is always available locally.  The two English rows use the
configured OpenAI model because ordinary machine translation cannot reliably
produce the CA-oriented literal gloss used in the supplied research example.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable

from ..models import JapaneseLayers, Transcript
from .ca import render_turn_body


_SPEAKER_COLORS = {
    "CM": "#0070C0",   # blue in the reference document
    "DCW": "#FF0000",  # red
    "EL": "#00B050",   # green
}
_FALLBACK_COLORS = ("#0070C0", "#FF0000", "#00B050", "#000000")
_CA_MARKER_RE = re.compile(
    r"\(\d+(?:\.\d+)?\)|\(\.\)|\.hh|::+|->|=>|➡|[=\[\]↑↓°><|]"
)

_SYSTEM = """You are a Japanese Conversation Analysis transcription linguist.
For each supplied Japanese Jefferson-notation turn, produce exactly three rows:

1. transliteration: lowercase Hepburn-like romanization. Match the reference
   convention where practical (e.g. soo, moo, riyoo), retain fillers and
   repairs, and preserve every CA marker in its corresponding position.
2. direct_translation: a morpheme-by-morpheme English gloss, preserving spacing
   where useful for alignment. Use these abbreviations consistently:
   SP=subject particle, O=object particle, L=linking/genitive particle,
   P=particle, CP=copula/politeness, FP=final particle, QT=quotative,
   ITJ=interjection, Q=question.
3. natural_translation: idiomatic English but still verbatim: preserve
   hesitation, repetition, repair, fillers, overlap and all CA markers.

Never remove, normalize, or invent Jefferson markers, including [, ], =, (0.3),
(.), :, ::, :::, ↑, ↓, °, >, <, -, .hh, |, ((...)), and arrows. Do not merge
turns. Return JSON only:
{"turns":[{"id":"...","transliteration":"...","direct_translation":"...",
"natural_translation":"..."}]}
"""


def _romanize(text: str) -> str:
    """Romanize locally while leaving whitespace and CA punctuation intact."""
    try:
        from pykakasi import kakasi

        converted = kakasi().convert(text)
        return "".join(piece.get("hepburn", piece.get("orig", "")) for piece in converted)
    except Exception:
        return text


def _speaker_colors(tr: Transcript) -> dict[str, str]:
    colors: dict[str, str] = {}
    for turn in tr.turns:
        if not turn.speaker or turn.speaker in colors:
            continue
        colors[turn.speaker] = _SPEAKER_COLORS.get(
            turn.speaker.upper(),
            _FALLBACK_COLORS[len(colors) % len(_FALLBACK_COLORS)],
        )
    return colors


def _add_warning(tr: Transcript, warning: str) -> None:
    if warning not in tr.meta.warnings:
        tr.meta.warnings.append(warning)


def reattach_japanese_layers(old_turns, new_turns) -> None:
    """Carry annotations across turn regrouping using token identity/overlap.

    If the Japanese source changed, romanization is refreshed and English rows
    are cleared rather than silently keeping a now-incorrect translation.
    """
    candidates = [turn for turn in old_turns if turn.speaker and turn.japanese]
    for new in new_turns:
        if not new.speaker:
            continue
        new_ids = {tok.id for tok in new.tokens}
        best = None
        best_score = -1.0
        for old in candidates:
            if old.speaker != new.speaker:
                continue
            old_ids = {tok.id for tok in old.tokens}
            shared = len(new_ids & old_ids)
            overlap = max(0.0, min(new.end, old.end) - max(new.start, old.start))
            score = shared * 1000.0 + overlap
            if score > best_score:
                best, best_score = old, score
        if not best or not best.japanese or best_score <= 0:
            continue
        old_body = render_turn_body(best)
        new_body = render_turn_body(new)
        if old_body == new_body:
            new.japanese = best.japanese.model_copy(deep=True)
        else:
            new.japanese = JapaneseLayers(
                transliteration=_romanize(new_body),
                natural_color=best.japanese.natural_color,
                generated_by="local/source-edited",
            )


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
    return s


def _preserves_markers(source: str, target: str) -> bool:
    required = Counter(_CA_MARKER_RE.findall(source or ""))
    present = Counter(_CA_MARKER_RE.findall(target or ""))
    return all(present[marker] >= count for marker, count in required.items())


def populate_japanese_layers(
    tr: Transcript,
    settings,
    progress: Callable[[float, str], None] | None = None,
) -> Transcript:
    """Populate all spoken turns, using local romanization plus optional LLM."""
    tr.layout = "japanese_four_line"
    tr.meta.warnings = [
        warning for warning in tr.meta.warnings
        if not (
            warning.startswith("Japanese translation")
            or warning.startswith("Japanese English rows")
            or "generated Japanese companion row" in warning
        )
    ]
    colors = _speaker_colors(tr)
    spoken = [turn for turn in tr.turns if turn.speaker and turn.tokens]

    for turn in spoken:
        source = render_turn_body(turn)
        old = turn.japanese
        turn.japanese = JapaneseLayers(
            transliteration=_romanize(source),
            direct_translation=old.direct_translation if old else "",
            natural_translation=old.natural_translation if old else "",
            natural_color=(old.natural_color if old else colors.get(turn.speaker, "#000000")),
            generated_by="local",
        )

    if not spoken:
        return tr

    if not getattr(settings, "japanese_auto_translate", True):
        return tr

    if not getattr(settings, "enable_openai", False) or not getattr(
        settings, "openai_api_key", None
    ):
        _add_warning(
            tr,
            "Japanese English rows not generated: enable OpenAI and provide an API key; "
            "local romanization is available and all rows remain editable.",
        )
        return tr

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
    except Exception as exc:
        _add_warning(tr, f"Japanese translation unavailable: {exc}")
        return tr

    chunk_size = 20
    total_chunks = max(1, (len(spoken) + chunk_size - 1) // chunk_size)
    translated = 0
    marker_warnings = 0
    for chunk_no, offset in enumerate(range(0, len(spoken), chunk_size), start=1):
        chunk = spoken[offset : offset + chunk_size]
        payload = {
            "turns": [
                {
                    "id": turn.id,
                    "speaker": turn.speaker,
                    "japanese": render_turn_body(turn),
                }
                for turn in chunk
            ]
        }
        if progress:
            progress(
                (chunk_no - 1) / total_chunks,
                f"Japanese gloss + translation {chunk_no}/{total_chunks}",
            )
        try:
            response = client.chat.completions.create(
                model=getattr(settings, "openai_model", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            data = json.loads(_strip_fence(response.choices[0].message.content or "{}"))
            by_id = {
                str(row.get("id")): row
                for row in data.get("turns", [])
                if isinstance(row, dict)
            }
            for turn in chunk:
                row = by_id.get(turn.id)
                if not row or not turn.japanese:
                    continue
                source = render_turn_body(turn)
                romanization = str(row.get("transliteration") or "").strip()
                if romanization and _preserves_markers(source, romanization):
                    turn.japanese.transliteration = romanization
                elif romanization:
                    marker_warnings += 1
                direct = str(
                    row.get("direct_translation") or ""
                ).strip()
                natural = str(
                    row.get("natural_translation") or ""
                ).strip()
                turn.japanese.direct_translation = direct
                turn.japanese.natural_translation = natural
                if direct and not _preserves_markers(source, direct):
                    marker_warnings += 1
                if natural and not _preserves_markers(source, natural):
                    marker_warnings += 1
                turn.japanese.generated_by = getattr(
                    settings, "openai_model", "gpt-4o-mini"
                )
                translated += 1
        except Exception as exc:
            _add_warning(
                tr,
                f"Japanese translation chunk {chunk_no} failed: {exc}",
            )

    if marker_warnings:
        _add_warning(
            tr,
            f"{marker_warnings} generated Japanese companion row(s) need CA-marker review; "
            "the source Japanese markers were not all reproduced.",
        )
    if progress:
        progress(1.0, f"Japanese four-line rows ready ({translated}/{len(spoken)})")
    return tr

