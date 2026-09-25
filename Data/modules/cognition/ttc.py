"""Test-time compute (TTC) — multi-candidate generate / select.

Used when provider-native reasoning is unsupported. Does not invent provider
knobs. Selection is deterministic public-channel scoring (majority / length);
critic/verifier LLM meshes land in later phases.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence


_WS_RE = re.compile(r"\s+")


def normalize_answer_key(text: str) -> str:
    """Normalize public answer text for majority self-consistency."""
    cleaned = _WS_RE.sub(" ", (text or "").strip().lower())
    # Strip trivial trailing punctuation for grouping only.
    return cleaned.rstrip(" .,;:!?")


def candidate_temperatures(
    count: int,
    *,
    diversity_temperature: float = 0.0,
    base_temperature: float = 0.2,
) -> list[float]:
    """Spread temperatures across candidates for diversity (bounded)."""
    n = max(1, int(count))
    base = float(base_temperature)
    diversity = max(0.0, float(diversity_temperature))
    if n == 1 or diversity <= 0.0:
        return [max(0.0, min(1.5, base))] * n
    return [
        max(0.0, min(1.5, base + diversity * (i / (n - 1))))
        for i in range(n)
    ]


@dataclass(frozen=True)
class TTCCandidate:
    index: int
    text: str
    temperature: float
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    usage_source: str = "unavailable"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.text.strip()) and self.error is None

    def public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text_preview": (self.text or "")[:160],
            "text_chars": len(self.text or ""),
            "temperature": self.temperature,
            "finish_reason": self.finish_reason,
            "usage_source": self.usage_source,
            "ok": self.ok,
            "error": self.error,
            "truth": {"private_cot_not_in_candidate": True},
        }


@dataclass(frozen=True)
class TTCSelection:
    method: str
    chosen_index: int
    chosen_text: str
    candidate_count: int
    valid_count: int
    agreement_ratio: float | None
    notes: tuple[str, ...] = ()
    scores: tuple[dict[str, Any], ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "chosen_index": self.chosen_index,
            "chosen_text_preview": (self.chosen_text or "")[:200],
            "candidate_count": self.candidate_count,
            "valid_count": self.valid_count,
            "agreement_ratio": self.agreement_ratio,
            "notes": list(self.notes),
            "scores": list(self.scores),
            "truth": {
                "selection_uses_public_text_only": True,
                "no_private_cot_in_selection": True,
                "no_fabricated_answer": True,
            },
        }


def select_ttc_candidate(
    candidates: Sequence[TTCCandidate],
    *,
    prefer_majority: bool = True,
) -> TTCSelection:
    """Pick a public answer among candidates. Never invents text."""
    items = list(candidates)
    valid = [c for c in items if c.ok]
    notes: list[str] = []
    if not items:
        return TTCSelection(
            method="empty",
            chosen_index=-1,
            chosen_text="",
            candidate_count=0,
            valid_count=0,
            agreement_ratio=None,
            notes=("no_candidates",),
        )
    if not valid:
        # Prefer first error-bearing slot for diagnostics; text stays empty.
        first = items[0]
        return TTCSelection(
            method="none_valid",
            chosen_index=first.index,
            chosen_text="",
            candidate_count=len(items),
            valid_count=0,
            agreement_ratio=0.0,
            notes=("all_candidates_empty_or_failed",),
        )

    scores: list[dict[str, Any]] = []
    keys = [normalize_answer_key(c.text) for c in valid]
    counts = Counter(keys)
    top_key, top_count = counts.most_common(1)[0]
    agreement = top_count / max(1, len(valid))

    if prefer_majority and top_count >= 2:
        majority_pool = [c for c, k in zip(valid, keys) if k == top_key]
        # Among majority, prefer longest public answer (more complete, still public).
        chosen = max(majority_pool, key=lambda c: (len(c.text.strip()), -c.index))
        method = "majority_normalized"
        notes.append(f"majority_key_votes={top_count}/{len(valid)}")
    else:
        # All unique (or single): prefer longest non-empty public text.
        chosen = max(valid, key=lambda c: (len(c.text.strip()), -c.index))
        method = "longest_valid" if len(valid) > 1 else "single_valid"
        if len(valid) > 1:
            notes.append("no_majority — longest_valid_public_text")

    for c, k in zip(valid, keys):
        scores.append(
            {
                "index": c.index,
                "normalized_key_preview": k[:80],
                "chars": len(c.text.strip()),
                "majority_bucket": k == top_key,
                "selected": c.index == chosen.index,
            }
        )

    return TTCSelection(
        method=method,
        chosen_index=chosen.index,
        chosen_text=chosen.text.strip(),
        candidate_count=len(items),
        valid_count=len(valid),
        agreement_ratio=round(agreement, 4),
        notes=tuple(notes),
        scores=tuple(scores),
    )


CompleteFn = Callable[..., Awaitable[Mapping[str, Any]]]


@dataclass
class TTCRunResult:
    selection: TTCSelection
    candidates: tuple[TTCCandidate, ...]
    model_calls_consumed: int
    temperatures: tuple[float, ...]
    path: str = "ttc"

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "model_calls_consumed": self.model_calls_consumed,
            "temperatures": list(self.temperatures),
            "selection": self.selection.public_dict(),
            "candidates": [c.public_dict() for c in self.candidates],
            "truth": {
                "ttc_not_a_second_runtime": True,
                "no_unknown_provider_knobs": True,
            },
        }


class TTCExecutor:
    """Fan-out completions for a TTC plan and select a public winner."""

    async def run(
        self,
        *,
        candidate_count: int,
        max_parallel: int = 1,
        diversity_temperature: float = 0.0,
        base_temperature: float = 0.2,
        complete: CompleteFn,
        complete_kwargs: Mapping[str, Any] | None = None,
    ) -> TTCRunResult:
        n = max(1, int(candidate_count))
        parallel = max(1, int(max_parallel))
        temps = candidate_temperatures(
            n,
            diversity_temperature=diversity_temperature,
            base_temperature=base_temperature,
        )
        kwargs = dict(complete_kwargs or {})
        # Never smuggle native reasoning knobs through TTC.
        kwargs.pop("provider_hints", None)

        sem = asyncio.Semaphore(parallel)

        async def _one(index: int, temperature: float) -> TTCCandidate:
            async with sem:
                try:
                    raw = await complete(temperature=temperature, **kwargs)
                    if not isinstance(raw, Mapping):
                        return TTCCandidate(
                            index=index,
                            text="",
                            temperature=temperature,
                            error="non_mapping_result",
                        )
                    text = str(raw.get("text") or raw.get("content") or "").strip()
                    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
                    return TTCCandidate(
                        index=index,
                        text=text,
                        temperature=temperature,
                        finish_reason=(
                            str(raw.get("finish_reason"))
                            if raw.get("finish_reason")
                            else None
                        ),
                        usage=dict(usage),
                        usage_source=str(raw.get("usage_source") or "unavailable"),
                        error=None if text else "empty_response",
                    )
                except Exception as exc:  # noqa: BLE001 — surface as failed candidate
                    return TTCCandidate(
                        index=index,
                        text="",
                        temperature=temperature,
                        error=f"{type(exc).__name__}: {exc}",
                    )

        results = await asyncio.gather(
            *[_one(i, temps[i]) for i in range(n)]
        )
        candidates = tuple(results)
        selection = select_ttc_candidate(candidates)
        return TTCRunResult(
            selection=selection,
            candidates=candidates,
            model_calls_consumed=n,
            temperatures=tuple(temps),
        )
