"""Synthetic data generation with immutable generator provenance (U310–U315)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from Data.modules.datasets.quality import semantic_dedupe
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
    generator_revision: str | None = None
    prompt_template_revision: str | None = None
    sampling_config: dict[str, Any] = field(default_factory=dict)
    generation_timestamp: str = field(default_factory=_utc_now)
    generation_run_id: str = field(default_factory=lambda: f"synrun_{uuid.uuid4().hex[:12]}")
    verifier: str = "deterministic_validator"
    filtering_result: dict[str, Any] = field(default_factory=dict)
    mode: str = "fixture"  # fixture | teacher_inference

    def public_dict(self) -> dict[str, Any]:
        return {
            "generator_model": self.generator_model,
            "generator_revision": self.generator_revision,
            "prompt_template": self.prompt_template,
            "prompt_template_revision": self.prompt_template_revision,
            "seed": self.seed,
            "sampling_config": dict(self.sampling_config),
            "generation_timestamp": self.generation_timestamp,
            "generation_run_id": self.generation_run_id,
            "filter_chain": list(self.filter_chain),
            "teacher_ensemble": list(self.teacher_ensemble),
            "verifier": self.verifier,
            "filtering_result": dict(self.filtering_result),
            "mode": self.mode,
            "truth": {
                "immutable_generator_provenance": True,
                "fixture_is_not_teacher_inference": self.mode == "fixture",
            },
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
                "dedupe_before_run_metadata": True,
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


TeacherInferFn = Callable[[str, dict[str, Any]], str]


class SyntheticDataService:
    """Synthetic generator — fixture by default; real teacher inference when configured."""

    def generate(
        self,
        *,
        prompts: list[str],
        generator_model: str = "fixture-synth-v1",
        prompt_template: str = "answer:{prompt}",
        seed: int = 42,
        teacher_ensemble: list[str] | None = None,
        extra_validators: list[Callable[[CanonicalRecord], bool]] | None = None,
        teacher_infer: TeacherInferFn | None = None,
        generator_revision: str | None = None,
        prompt_template_revision: str | None = None,
        sampling_config: dict[str, Any] | None = None,
        prefer_verifiable: bool = True,
    ) -> SyntheticBatch:
        mode = "teacher_inference" if teacher_infer is not None else "fixture"
        if mode == "fixture" and generator_model == "fixture-synth-v1":
            pass
        elif mode == "teacher_inference" and generator_model == "fixture-synth-v1":
            generator_model = "teacher-configured"
        sampling = dict(sampling_config or {"temperature": 0.0, "seed": seed})
        run_id = f"synrun_{uuid.uuid4().hex[:12]}"
        timestamp = _utc_now()
        # Stage 1: generate canonical semantic content WITHOUT run-specific metadata.
        draft_records: list[CanonicalRecord] = []
        for idx, prompt in enumerate(prompts):
            if teacher_infer is not None:
                try:
                    body = teacher_infer(
                        prompt,
                        {
                            "seed": seed,
                            "index": idx,
                            "template": prompt_template,
                            "sampling": sampling,
                            "revision": generator_revision,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    body = f"[teacher_failed:{type(exc).__name__}] {prompt_template.replace('{prompt}', prompt.strip())}"
            else:
                body = prompt_template.replace("{prompt}", prompt.strip())
                body = f"[fixture seed={seed} i={idx}] {body}"
                if teacher_ensemble:
                    body = f"{body} | teachers={','.join(teacher_ensemble)}"
            draft_records.append(
                CanonicalRecord(
                    id=f"syn_draft_{idx}",
                    text=str(body),
                    metadata={"synthetic": True, "prompt": prompt},
                    labels={"verifiable": bool(prefer_verifiable)},
                )
            )

        # Stage 2: semantic dedupe BEFORE attaching run-specific metadata.
        deduped, dedupe_stats = semantic_dedupe(draft_records)
        seen: set[str] = set()
        kept: list[CanonicalRecord] = []
        filtered = 0
        for rec in deduped:
            ok = deterministic_validator(rec) and diversity_check(rec, seen)
            if ok and extra_validators:
                ok = all(fn(rec) for fn in extra_validators)
            if not ok:
                filtered += 1
                continue
            # Stage 3: attach run provenance metadata only after dedupe.
            kept.append(
                CanonicalRecord(
                    id=f"syn_{uuid.uuid4().hex[:10]}",
                    text=rec.text,
                    metadata={
                        **dict(rec.metadata or {}),
                        "generator_model": generator_model,
                        "generator_revision": generator_revision,
                        "prompt_template_revision": prompt_template_revision,
                        "seed": seed,
                        "generation_run_id": run_id,
                        "generation_timestamp": timestamp,
                        "mode": mode,
                        "sampling_config": sampling,
                    },
                    labels=dict(rec.labels or {}),
                )
            )
        filtered += int(dedupe_stats.get("removedCount") or 0)
        filtering_result = {
            "kept": len(kept),
            "filtered": filtered,
            "dedupe": dedupe_stats,
            "verifier": "deterministic_validator",
        }
        provenance = GeneratorProvenance(
            generator_model=generator_model,
            prompt_template=prompt_template,
            seed=seed,
            filter_chain=["semantic_dedupe", "deterministic_validator", "diversity_check"],
            teacher_ensemble=list(teacher_ensemble or []),
            generator_revision=generator_revision,
            prompt_template_revision=prompt_template_revision,
            sampling_config=sampling,
            generation_timestamp=timestamp,
            generation_run_id=run_id,
            verifier="deterministic_validator",
            filtering_result=filtering_result,
            mode=mode,
        )
        diversity = {
            "lexical_type_token_ratio": _lexical_diversity([r.text for r in kept]),
            "unique_records": len(kept),
            "method": "lexical_fixture" if mode == "fixture" else "teacher_inference",
        }
        return SyntheticBatch(
            batch_id=f"synb_{uuid.uuid4().hex[:12]}",
            records=kept,
            provenance=provenance,
            diversity=diversity,
            filtered_out=filtered,
        )
