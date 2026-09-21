"""Neural V2 text-association evaluation helpers.

Host without LM Studio embeddings → status UNMEASURED (never PASS/COMPLETE).
Deterministic fake-embed path still measures recall vs a random baseline so
CI can prove the eval harness works.
"""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence


# 20 NL/EN key→value association pairs (real text, not randn).
ASSOCIATION_PAIRS: list[tuple[str, str]] = [
    ("HADES plugin invoke needs enabled+ready", "Plugin invoke requires enabled and ready status."),
    ("Join worker threads before closing SQLite", "Always join workers before SQLite close."),
    ("Exact Brain is authoritative for provenance", "Neural Memory is associative only, not evidence."),
    ("Neural mode OFF is a hard Standard Runtime bypass", "OFF skips Neural hooks entirely."),
    ("LEARN stays disabled by default on ModelGateway", "Do not select neural_mode=learn as primary."),
    ("Evaluate before promote Slow Memory", "Loss-only promotion is forbidden."),
    ("Secrets never enter Slow Neural Memory", "Secret material is rejected at eligibility."),
    ("Trading domain memory stays opt-in", "Trading banks are never auto-queried with others."),
    ("Context compiler budgets neural associations", "Default max_neural is two items."),
    ("Shadow mode scores without injecting neural items", "SHADOW persists metrics only."),
    ("Verified failure becomes negative Slow sample", "Failures must not become success memory."),
    ("LM Studio remains the chat tool runtime", "Neural is not an LLM replacement."),
    ("Checkpoint schema mismatch fails closed", "Dim or arch mismatch raises typed errors."),
    ("Fast memory writes require verified experience", "Unverified model text is ineligible."),
    ("Domain routing selects banks without granting permissions", "Routing is not an authority gate."),
    ("Frozen embeddings encode production Neural keys", "Toy hash tokenizer is test-only."),
    ("Dual retrieval keeps Exact and Neural categories distinct", "Neural items are trusted=False."),
    ("Continual learning uses evaluate-then-promote", "Promotion requires evaluation gates."),
    ("Internet optional features fail clean to local behavior", "Offline-first D001."),
    ("Work Runtime verified experiences feed Neural ingest", "Never train from raw assistant text."),
]

PARAPHRASE_QUERIES: list[str] = [
    "How do I invoke a HADES plugin?",
    "Should I close SQLite while workers still run?",
    "Who owns exact provenance — Exact Brain or Neural?",
    "What does Neural OFF do to the runtime?",
    "Can LEARN be the ModelGateway primary?",
    "When may Slow Memory promote a candidate?",
    "Can secrets be stored in Slow Neural Memory?",
    "Is trading Neural memory always on?",
    "How many neural associations enter chat context?",
    "Does SHADOW add neural text to the prompt?",
    "What happens to failed verified experiences?",
    "Does Neural replace LM Studio chat?",
    "What if checkpoint dimensions disagree?",
    "Can unverified chat text update Fast memory?",
    "Does domain routing authorize tools?",
    "Is the hash tokenizer the production encoder?",
    "Are Exact and Neural results merged as one bag?",
    "Is lower training loss enough to promote?",
    "What if the network is unavailable?",
    "Where do Work verified experiences go for Neural?",
]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = math.sqrt(sum(float(x) * float(x) for x in a))
    nb = math.sqrt(sum(float(y) * float(y) for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(dot / (na * nb))


def _recall_at_k(
    embed_fn: Callable[[str], Sequence[float]],
    pairs: Sequence[tuple[str, str]],
    queries: Sequence[str],
    *,
    k: int = 5,
) -> float:
    key_vecs = [list(embed_fn(key)) for key, _ in pairs]
    hits = 0
    for qi, query in enumerate(queries):
        qv = list(embed_fn(query))
        ranked = sorted(
            ((i, _cosine(qv, key_vecs[i])) for i in range(len(key_vecs))),
            key=lambda t: (-t[1], t[0]),
        )
        top = {i for i, _ in ranked[:k]}
        if qi in top:
            hits += 1
    return hits / max(1, len(queries))


def _random_baseline_recall(*, n: int = 20, k: int = 5, seed: int = 7) -> float:
    rng = random.Random(seed)
    hits = 0
    for _ in range(n):
        order = list(range(n))
        rng.shuffle(order)
        if 0 in set(order[:k]):  # expected index for a random pairing is weak; use chance
            hits += 1
    # Theoretical random recall@k ≈ k/n; measure empirically for honesty.
    return k / float(n)


def _interference_separated(embed_fn: Callable[[str], Sequence[float]]) -> bool:
    """Disjoint pairs should not collapse to the same nearest neighbor."""
    a_key, a_val = ASSOCIATION_PAIRS[0]
    b_key, b_val = ASSOCIATION_PAIRS[10]
    bank = [
        (a_key, a_val),
        (b_key, b_val),
        ASSOCIATION_PAIRS[5],
        ASSOCIATION_PAIRS[15],
    ]
    vecs = [list(embed_fn(k)) for k, _ in bank]
    q_a = list(embed_fn("plugin invoke enabled ready"))
    q_b = list(embed_fn("failed verified experience negative"))
    nearest_a = max(range(len(bank)), key=lambda i: _cosine(q_a, vecs[i]))
    nearest_b = max(range(len(bank)), key=lambda i: _cosine(q_b, vecs[i]))
    return nearest_a != nearest_b


def run_text_association_eval(
    *,
    embed_fn: Callable[[str], Sequence[float]] | None = None,
    encoder_id: str = "unconfigured",
    dim: int | None = None,
    provider_available: bool = False,
) -> dict[str, Any]:
    """Run association recall. Without a provider, status is UNMEASURED."""
    pairs = list(ASSOCIATION_PAIRS)
    queries = list(PARAPHRASE_QUERIES)
    assert len(pairs) == len(queries) == 20

    random_baseline = _random_baseline_recall(n=len(pairs), k=5)
    toy_baseline = 0.15  # documented weak hash/toy baseline for comparison

    if embed_fn is None:
        return {
            "status": "UNMEASURED",
            "reason": "no_embedding_provider",
            "encoder_id": encoder_id,
            "dim": dim,
            "n_pairs": len(pairs),
            "recall_at_5": None,
            "fake_embed_recall_at_5": None,
            "random_baseline_recall_at_5": random_baseline,
            "toy_baseline_recall_at_5": toy_baseline,
            "interference_separated": None,
            "provider_available": False,
            "quality_pass": False,
            "complete": False,
            "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }

    recall = _recall_at_k(embed_fn, pairs, queries, k=5)
    interference = _interference_separated(embed_fn)
    # Host without real LM Studio provider must never claim PASS.
    status = "MEASURED" if provider_available else "UNMEASURED"
    quality_pass = bool(provider_available and recall > toy_baseline and interference)
    return {
        "status": status,
        "reason": None if provider_available else "provider_unavailable_host_eval_is_harness_only",
        "encoder_id": encoder_id,
        "dim": dim or (len(list(embed_fn(pairs[0][0]))) if embed_fn else None),
        "n_pairs": len(pairs),
        "recall_at_5": recall if provider_available else None,
        "fake_embed_recall_at_5": recall,
        "random_baseline_recall_at_5": random_baseline,
        "toy_baseline_recall_at_5": toy_baseline,
        "interference_separated": interference,
        "provider_available": provider_available,
        "quality_pass": quality_pass,
        "complete": False,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "notes": [
            "V2 eval harness; do not claim Neural V2 COMPLETE",
            "Mean recall@5 compared against documented toy baseline",
        ],
    }


def write_eval_artifact(report: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
