"""Voice-to-task: local STT transcript → structured HADES task proposal.

Does not claim speech recognition itself; accepts text from a local STT plugin
or pasted transcript and produces a reviewable task draft.
"""

from __future__ import annotations

import re
from typing import Any


PRIORITY_HINTS = {
    "high": ("urgent", "asap", "hoog", "kritiek", "critical", "nu"),
    "low": ("later", "laag", "whenever", "ooit"),
}


def transcript_to_task(transcript: str, *, default_agent: str = "auto") -> dict[str, Any]:
    text = (transcript or "").strip()
    if not text:
        raise ValueError("Lege transcriptie.")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0][:120] if lines else "Spraaktaak"
    if title.lower().startswith(("maak ", "create ", "start ", "doe ")):
        title = title.split(" ", 1)[-1][:120].strip().capitalize() or title

    lower = text.lower()
    priority = "normal"
    for level, hints in PRIORITY_HINTS.items():
        if any(hint in lower for hint in hints):
            priority = level
            break

    acceptance: list[str] = []
    for match in re.finditer(r"(?:accepteer|acceptance|done when|klaar als)[:\s]+(.+)", text, re.I):
        acceptance.append(match.group(1).strip()[:300])
    if not acceptance:
        acceptance = ["Het gevraagde resultaat is lokaal geleverd of eerlijk als incompleet gemeld."]

    agent = default_agent
    for hint, mapped in (
        ("code", "builder"),
        ("bouw", "builder"),
        ("onderzoek", "research_worker"),
        ("research", "research_worker"),
        ("review", "critic"),
        ("verifieer", "critic"),
    ):
        if hint in lower:
            agent = mapped
            break

    return {
        "title": title,
        "prompt": text,
        "agent": agent,
        "priority": priority,
        "acceptance_criteria": acceptance,
        "source": "voice_transcript",
        "auto_start_recommended": False,
        "note": (
            "Concept uit transcriptie — controleer vóór starten. "
            "Dit voice-to-task-pad doet zelf geen ASR: plak tekst of gebruik local-stt-paste. "
            "Ingebouwde lokale ASR/TTS zit in de Spraak-modus (backend/voice). Geen cloud-STT."
        ),
    }
