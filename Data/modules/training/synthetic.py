"""Synthetic data generation with immutable generator provenance (U310–U315)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from Data.modules.datasets.types import CanonicalRecord


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class GeneratorProvenance:
    generator_model: str
    prompt_template: str
    seed: int
    filter_chain: list[str] = field(default_factory=list)
    teacher_ensemble: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "generator_model": self.generator_model,
            "prompt_template": self.prompt_template,
            "seed": self.seed,
            "filter_chain": list(self.filter_chain),
            "teacher_ensemble": list(self.teacher_ensemble),
            "truth": {"immutable_generator_provenance": True},
        }


@dataclass
class SyntheticBatch:
    batch_id: str
    records: list[CanonicalRecord]
    provenance: GeneratorProvenance
    diversity: dict[str, Any]
    filtered_out: int
    created_at: str = field(default_factory=_utc_now)

    def public_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "record_count": len(self.records),
            "records": [r.to_dict() for r in self.records],
            "provenance": self.provenance.public_dict(),
            "diversity": dict(self.diversity),
            "filtered_out": self.filtered_out,
            "created_at": self.created_at,
            "truth": {
                "synthetic_is_not_unlabeled_truth": True,
                "filter_cascade_before_expensive_judges": True,
            },
        }


def _lexical_diversity(texts: list[str]) -> float:
    tokens: set[str] = set()
    total = 0
    for t in texts:
        parts = t.lower().split()
        total += len(parts)
        tokens.update(parts)
    if total == 0:
        return 0.0
    return round(len(tokens) / float(total), 4)


def deterministic_validator(rec: CanonicalRecord) -> bool:
    text = (rec.text or "").strip()
    if len(text) < 8:
        return False
    lowered = text.lower()
    if lowered.startswith("todo:") or "todo:" in lowered:
        return False
    return True


def diversity_check(rec: CanonicalRecord, seen: set[str]) -> bool:
    key = hashlib.sha256((rec.text or "").strip().lower().encode("utf-8")).hexdigest()
    if key in seen:
        return False
    seen.add(key)
    return True


class SyntheticDataService:
    """Fixture synthetic generator — uses shared record schema, not a private store."""

    def generate(
        self,
        *,
        prompts: list[str],
        generator_model: str = "fixture-synth-v1",
        prompt_template: str = "answer:{prompt}",
        seed: int = 42,
        teacher_ensemble: list[str] | None = None,
        extra_validators: list[Callable[[CanonicalRecord], bool]] | None = None,
    ) -> SyntheticBatch:
        provenance = GeneratorProvenance(
            generator_model=generator_model,
            prompt_template=prompt_template,
            seed=seed,
            filter_chain=["deterministic_validator", "diversity_check"],
            teacher_ensemble=list(teacher_ensemble or []),
        )
        seen: set[str] = set()
        kept: list[CanonicalRecord] = []
        filtered = 0
        for idx, prompt in enumerate(prompts):
            # Deterministic fixture generation (not a claim of model quality).
            body = prompt_template.replace("{prompt}", prompt.strip())
            text = f"[fixture seed={seed} i={idx}] {body}"
            if teacher_ensemble:
                text = f"{text} | teachers={','.join(teacher_ensemble)}"
            rec = CanonicalRecord(
                id=f"syn_{uuid.uuid4().hex[:10]}",
                text=text,
                metadata={
                    "synthetic": True,
                    "prompt": prompt,
                    "generator_model": generator_model,
                    "seed": seed,
                },
            )
            ok = deterministic_validator(rec) and diversity_check(rec, seen)
            if ok and extra_validators:
                ok = all(fn(rec) for fn in extra_validators)
            if not ok:
                filtered += 1
                continue
            kept.append(rec)
        diversity = {
            "lexical_type_token_ratio": _lexical_diversity([r.text for r in kept]),
            "unique_records": len(kept),
            "method": "lexical_fixture",
        }
        return SyntheticBatch(
            batch_id=f"synb_{uuid.uuid4().hex[:12]}",
            records=kept,
            provenance=provenance,
            diversity=diversity,
            filtered_out=filtered,
        )
