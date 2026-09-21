"""Helpers so Work/Critic test fakes emit finals aligned with step evidence."""

from __future__ import annotations

import re


_STEP_BLOCK = re.compile(
    r"=== \d+\. .*? ===\n(.*?)(?=\n=== |\nTOOLSTATUS:|\nCONCEPTANTWOORD|\nTOEGESTANE EVIDENCE|\nACCEPTANCE|\Z)",
    re.DOTALL,
)


def aligned_verification_final(prompt: str, *, fallback: str) -> str:
    """Return a critic ``final`` that quote-aligns with the first step observation.

    F-053 requires Work coverage to assess the candidate answer that will be
    returned. Test doubles must therefore not invent unrelated finals when the
    verification prompt already contains real step evidence.
    """
    match = _STEP_BLOCK.search(prompt or "")
    if not match:
        return fallback
    body = " ".join(match.group(1).split()).strip()
    if len(body) < 12:
        return fallback
    # Prefer a literal prefix of the step output so coverage finds source_passage.
    return body[:320].strip()
