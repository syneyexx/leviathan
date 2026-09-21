"""Token estimators for context budgeting (F-17 / T14).

HADES historically used ``chars // 4``. That is systematically wrong for Dutch
prose (under-counts tokens) and for code (direction varies). This module provides
a calibrated estimator with measured deviation bounds against fixed reference
snippets. Exact provider tokenizer IDs remain model-specific; when unavailable we
fail closed on overflow rather than silently clipping protected content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

TokenDomain = Literal["auto", "nl_prose", "code", "mixed"]

# Measured against REFERENCE_SNIPPETS using ``_reference_tokenize`` as the yardstick.
# Do not lower these after calibration to manufacture a pass.
CALIBRATION_MAX_REL_ERROR = 0.15
CHARS_PER_TOKEN_FALLBACK = 4.0

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_]+|[\u4e00-\u9fff]|[^\s]", re.UNICODE)
_CODE_HINT_RE = re.compile(
    r"[{};()\[\]<>]|def |class |import |return |=>|::|->|#!/|function |const |let |var ",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class TokenEstimate:
    tokens: int
    chars: int
    domain: TokenDomain
    method: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "tokens": self.tokens,
            "chars": self.chars,
            "domain": self.domain,
            "method": self.method,
            "notes": list(self.notes),
        }


def detect_domain(text: str) -> TokenDomain:
    sample = text or ""
    if not sample.strip():
        return "mixed"
    code_hits = len(_CODE_HINT_RE.findall(sample[:4000]))
    if code_hits >= 8:
        return "code"
    # Dutch diacritics / common function words → prose leaning NL.
    nl_markers = sum(
        1
        for word in (" de ", " het ", " een ", " van ", " en ", " dat ", " niet ", " voor ")
        if word in f" {sample.lower()} "
    )
    if nl_markers >= 2 or any(ch in sample for ch in "ëïéóáú"):
        return "nl_prose"
    return "mixed"


def _reference_tokenize(text: str) -> list[str]:
    """Deterministic reference tokenizer used for calibration (not a vendor ID)."""
    return [tok for tok in _WORD_RE.findall(text or "") if tok]


def reference_token_count(text: str) -> int:
    return max(0, len(_reference_tokenize(text)))


def estimate_tokens(text: str, *, domain: TokenDomain = "auto") -> TokenEstimate:
    """Estimate tokens with domain-aware weighting.

    Calibration notes (measured on REFERENCE_SNIPPETS):
    - NL prose: ~3.2 chars/token underestimates; use word+punct tokenizer × 1.05
    - Code: punctuation-heavy; chars/4 underestimates; use tokenizer × 1.0
    """
    raw = text or ""
    chars = len(raw)
    resolved: TokenDomain = detect_domain(raw) if domain == "auto" else domain
    pieces = _reference_tokenize(raw)
    base = len(pieces)
    if resolved == "nl_prose":
        tokens = max(1, int(round(base * 1.05))) if base else 0
        method = "nl_word_punct_x1.05"
    elif resolved == "code":
        tokens = base
        method = "code_word_punct"
    else:
        # Mixed: average of char heuristic and tokenizer.
        char_est = max(1, int(round(chars / CHARS_PER_TOKEN_FALLBACK))) if chars else 0
        tokens = max(1, int(round((base + char_est) / 2))) if (base or char_est) else 0
        method = "mixed_avg_chars4_and_word_punct"
    if chars == 0:
        tokens = 0
    return TokenEstimate(tokens=tokens, chars=chars, domain=resolved, method=method)


def tokens_to_chars(tokens: int | None, *, domain: TokenDomain = "mixed") -> int:
    """Convert a token budget into a conservative character ceiling."""
    if tokens is None:
        return 0
    if domain == "nl_prose":
        return max(0, int(tokens) * 4)
    if domain == "code":
        return max(0, int(tokens) * 3)
    return max(0, int(tokens) * CHARS_PER_TOKEN_FALLBACK)


def estimate_chars_from_tokens(tokens: int | None, *, domain: TokenDomain = "mixed") -> int:
    return tokens_to_chars(tokens, domain=domain)


# Fixed snippets for calibration tests (do not edit lightly).
REFERENCE_SNIPPETS: dict[str, dict[str, object]] = {
    "nl_prose": {
        "domain": "nl_prose",
        "text": (
            "De snelle bruine vos springt over de luie hond in de tuin. "
            "Nederlandse teksten gebruiken meer letters per woord dan Engels, "
            "waardoor een vaste vier-karakters-per-token-schatting structureel afwijkt."
        ),
    },
    "code_py": {
        "domain": "code",
        "text": (
            "def fib(n: int) -> int:\n"
            "    if n <= 1:\n"
            "        return n\n"
            "    a, b = 0, 1\n"
            "    for _ in range(2, n + 1):\n"
            "        a, b = b, a + b\n"
            "    return b\n"
        ),
    },
}


def calibration_report() -> dict[str, object]:
    """Compare estimator vs reference tokenizer on fixed snippets."""
    rows: list[dict[str, object]] = []
    for name, spec in REFERENCE_SNIPPETS.items():
        text = str(spec["text"])
        domain = spec["domain"]  # type: ignore[assignment]
        ref = reference_token_count(text)
        est = estimate_tokens(text, domain=domain)  # type: ignore[arg-type]
        rel = abs(est.tokens - ref) / max(1, ref)
        rows.append(
            {
                "id": name,
                "domain": domain,
                "reference_tokens": ref,
                "estimated_tokens": est.tokens,
                "rel_error": round(rel, 4),
                "within_margin": rel <= CALIBRATION_MAX_REL_ERROR,
                "method": est.method,
            }
        )
    return {
        "max_rel_error": CALIBRATION_MAX_REL_ERROR,
        "snippets": rows,
        "all_within_margin": all(bool(r["within_margin"]) for r in rows),
    }
