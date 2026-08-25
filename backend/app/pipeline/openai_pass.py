"""Optional OpenAI refinement pass. Never required; guarded and off by default.

Given the auto-generated Jefferson draft, ask a model to (a) fix obvious ASR
word errors while preserving verbatim fillers, and (b) suggest CA-cue tweaks.
Returns suggestions the UI presents as non-destructive edits.
"""
from __future__ import annotations


SYSTEM = (
    "You are a Conversation Analysis (CA) transcription assistant. You refine "
    "Jefferson-notation transcripts. CRITICAL RULES: keep every filler (uh, um), "
    "false start, repair and repeat verbatim - never clean up disfluencies. Do not "
    "invent words. Only correct clear speech-to-text errors and improve CA symbol "
    "placement. Return the corrected Jefferson transcript only."
)


def refine_transcript(jefferson_text: str, settings) -> dict:
    if not settings.enable_openai or not settings.openai_api_key:
        return {"ok": False, "reason": "OpenAI disabled or no API key", "text": jefferson_text}
    try:
        from openai import OpenAI
    except Exception as e:  # pragma: no cover
        return {"ok": False, "reason": f"openai package missing: {e}", "text": jefferson_text}

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": jefferson_text},
            ],
            temperature=0.0,
        )
        text = resp.choices[0].message.content or jefferson_text
        return {"ok": True, "text": text}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "reason": str(e), "text": jefferson_text}
