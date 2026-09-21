
"""Viral/content pattern analysis from transcripts (structure, not verbatim copying)."""

from __future__ import annotations

import re
from typing import Any


_HOOK_QUESTION = re.compile(r"^\s*(what|why|how|who|when|where|is|are|did|do|can|could)\b", re.I)
_CONTRADICTION = re.compile(r"\b(but|however|actually|impossible|nobody|never|wrong)\b", re.I)
_CTA = re.compile(r"\b(subscribe|follow|comment|like|share|link in bio|watch till)\b", re.I)
_LISTICLE = re.compile(r"\b(\d+\s+(ways|things|reasons|facts|secrets)|first,|second,|third,)\b", re.I)


def analyze_transcript_pattern(text: str, *, duration_sec: float | None = None) -> dict[str, Any]:
    body = (text or "").strip()
    words = re.findall(r"[A-Za-z0-9']+", body)
    word_count = len(words)
    sentences = [s.strip() for s in re.split(r"[.!?]+", body) if s.strip()]
    first = sentences[0] if sentences else body[:120]
    wps = None
    if duration_sec and duration_sec > 0:
        wps = round(word_count / float(duration_sec), 3)

    hook_type = "statement"
    if _HOOK_QUESTION.search(first):
        hook_type = "question"
    elif _CONTRADICTION.search(first):
        hook_type = "contradiction"
    elif first.lower().startswith(("imagine", "picture", "what if")):
        hook_type = "curiosity_gap"

    structure = "story"
    if _LISTICLE.search(body):
        structure = "listicle"
    elif re.search(r"\b(problem|solution|fix)\b", body, re.I):
        structure = "problem_solution"
    elif re.search(r"\b(before|after)\b", body, re.I):
        structure = "before_after"
    elif re.search(r"\b(secret|reveal|actually)\b", body, re.I):
        structure = "mystery_reveal"
    elif re.search(r"\b(how to|tutorial|step)\b", body, re.I):
        structure = "tutorial"

    cta_hits = _CTA.findall(body)
    question_density = sum(1 for s in sentences if s.endswith("?") or _HOOK_QUESTION.search(s)) / max(1, len(sentences))

    avg_sentence_len = (sum(len(re.findall(r"[A-Za-z0-9']+", s)) for s in sentences) / max(1, len(sentences))) if sentences else 0

    return {
        "hook": {
            "hook_text": first[:240],
            "hook_type": hook_type,
            "hook_duration": None,
            "first_information_time": None,
            "curiosity_gap": hook_type in {"curiosity_gap", "contradiction", "question"},
            "open_loop": bool(re.search(r"\b(but|until|then|here's why)\b", first, re.I)),
        },
        "script": {
            "word_count": word_count,
            "words_per_second": wps,
            "sentence_length": round(avg_sentence_len, 2),
            "information_density": round(min(1.0, word_count / max(40.0, (duration_sec or 40.0))), 3),
            "question_density": round(question_density, 3),
            "emotional_language": bool(re.search(r"\b(shock|insane|crazy|amazing|terrifying|beautiful)\b", body, re.I)),
            "payoff_timing": None,
            "cta_timing": None,
        },
        "structure": {
            "pattern": structure,
            "cta_present": bool(cta_hits),
            "cta_types": sorted({c.lower() for c in cta_hits}),
        },
        "retention_architecture": {
            "hook": True,
            "setup": word_count > 20,
            "escalation": word_count > 60,
            "open_loop": bool(re.search(r"\b(but|wait|here's the twist)\b", body, re.I)),
            "re_hook": len(sentences) >= 4,
            "payoff": len(sentences) >= 3,
            "cta": bool(cta_hits),
        },
        "editing": {
            "scene_change_frequency": None,
            "average_shot_length": None,
            "motion_intensity": None,
            "caption_density": None,
            "note": "Video editing metrics require vision/FFmpeg scene analysis when available.",
        },
    }
