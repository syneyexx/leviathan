from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RecipeRunStatus(str, Enum):
    REGISTERED = "REGISTERED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TrainingRecipe:
    """Declarative training recipe — registration ≠ trained."""

    recipe_id: str
    name: str
    objective: str
    loss: str
    formulation: str
    data_sources: tuple[str, ...] = ()
    requires_verification: bool = True
    freezes_base_model: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "name": self.name,
            "objective": self.objective,
            "loss": self.loss,
            "formulation": self.formulation,
            "data_sources": list(self.data_sources),
            "requires_verification": self.requires_verification,
            "freezes_base_model": self.freezes_base_model,
            "metadata": self.metadata,
            "truth": {
                "recipe_registered_is_not_trained": True,
                "no_fabricated_metrics": True,
            },
        }


NEURO_RECIPES: tuple[TrainingRecipe, ...] = (
    TrainingRecipe(
        recipe_id="proc_supervision_v1",
        name="Process supervision on reasoning traces",
        objective="process_supervision",
        loss="NLL",
        formulation="L_proc = -sum_t log p_theta(s_{t+1} | s_<=t, c_t) over critic-approved steps",
        data_sources=("ModelData/reasoning", "verification_reports"),
        requires_verification=True,
        freezes_base_model=True,
        metadata={
            "operational": False,
            "truth": {"not_operational_until_objective_trainer_exists": True},
        },
    ),
    TrainingRecipe(
        recipe_id="pref_dpo_v1",
        name="Preference optimization on multi-step trajectories",
        objective="preference_optimization",
        loss="DPO",
        formulation="L_pref = -log sigma(beta (r_w - r_l)); rewards from Verification + human preference",
        data_sources=("verification_reports", "human_preferences"),
        requires_verification=True,
        freezes_base_model=True,
        metadata={
            "reference_model_required": True,
            "method": "dpo",
            "operational_objective": "dpo_micro",
            "hf_production_dpo": False,
            "truth": {
                "registered_is_not_trained": True,
                "micro_dpo_is_not_hf_production_dpo": True,
            },
        },
    ),
    TrainingRecipe(
        recipe_id="reward_model_v1",
        name="Reward model on preference pairs",
        objective="reward_modeling",
        loss="BradleyTerry",
        formulation="L_rm = -log sigma(r_theta(y_w) - r_theta(y_l)); calibrate on held-out prefs",
        data_sources=("human_preferences", "preference_records"),
        requires_verification=False,
        freezes_base_model=True,
        metadata={
            "held_out_calibration_required": True,
            "method": "reward",
            "operational": False,
            "truth": {"not_operational_until_objective_trainer_exists": True},
        },
    ),
    TrainingRecipe(
        recipe_id="contrastive_memory_v1",
        name="Contrastive objectives for memory retrieval heads",
        objective="contrastive_retrieval",
        loss="InfoNCE",
        formulation="L_nce = -log exp(sim(q,k+)/tau) / sum_i exp(sim(q,k_i)/tau)",
        data_sources=("knowledge_chunks", "evidence_links"),
        requires_verification=False,
        freezes_base_model=True,
    ),
    TrainingRecipe(
        recipe_id="synthetic_reasoning_v1",
        name="Synthetic reasoning from ModelData",
        objective="synthetic_reasoning",
        loss="NLL+grounding",
        formulation="Generate (question, grounded steps, citations); discard samples failing Verification",
        data_sources=("D:/ModelData", "knowledge_v2"),
        requires_verification=True,
        freezes_base_model=True,
    ),
    TrainingRecipe(
        recipe_id="joint_cortex_memory_v1",
        name="Joint cortex blocks + memory interfaces",
        objective="joint_cortex_memory",
        loss="multi_task",
        formulation="Train cortex adapters + memory interfaces; base frozen or LoRA",
        data_sources=("proc_supervision_v1", "contrastive_memory_v1"),
        requires_verification=True,
        freezes_base_model=True,
        metadata={"lora_rank_default": 16},
    ),
)


@dataclass(frozen=True)
class RecipeRun:
    run_id: str
    recipe_id: str
    status: RecipeRunStatus
    created_at: str
    updated_at: str
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    trainer_backend: str | None = None
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "recipe_id": self.recipe_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metrics": self.metrics,
            "error": self.error,
            "trainer_backend": self.trainer_backend,
            "detail": self.detail,
            "truth": {
                "registered_is_not_trained": True,
                "no_fabricated_metrics": True,
                "completed_requires_real_trainer_metrics": True,
            },
        }


class RecipeTrainerBackend(Protocol):
    """Optional trainer backend. Must return real metrics or raise — never fabricate."""

    backend_id: str

    def available(self) -> bool: ...

    def execute(
        self,
        recipe: TrainingRecipe,
        *,
        samples: Sequence[Mapping[str, Any]],
        config: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Return metrics dict from a real training step. Raise on failure."""
        ...


@dataclass
class FixtureRecipeTrainer:
    """Dev/test trainer that runs a deterministic local step without ML deps.

    Produces honest fixture metrics labelled as fixture — never claims GPU training.
    """

    backend_id: str = "fixture"
    fail: bool = False

    def available(self) -> bool:
        return True

    def execute(
        self,
        recipe: TrainingRecipe,
        *,
        samples: Sequence[Mapping[str, Any]],
        config: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if self.fail:
            raise RuntimeError("fixture trainer forced failure")
        # Round 4: preference/DPO must use the real DPO objective — never fabricate DPO metrics.
        if recipe.objective == "preference_optimization" or str(recipe.loss).upper() == "DPO":
            from .dpo import DpoRecipeTrainer

            return DpoRecipeTrainer().execute(recipe, samples=samples, config=config)
        # Process-supervision / InfoNCE / synthetic honesty gates.
        approved = [s for s in samples if s.get("critic_approved") or s.get("verification_passed")]
        if recipe.requires_verification and not approved and samples:
            raise RuntimeError("recipe requires verification-approved samples; none present")
        if recipe.objective == "synthetic_reasoning":
            kept = [s for s in samples if s.get("verification_passed")]
            discarded = len(samples) - len(kept)
        else:
            kept = list(approved or samples)
            discarded = 0
        loss_proxy = max(0.01, 1.0 / max(len(kept), 1))
        return {
            "steps": len(kept),
            "samples_kept": len(kept),
            "samples_discarded": discarded,
            "loss": round(loss_proxy, 6),
            "objective": recipe.objective,
            "fixture": True,
            "operational": bool(recipe.metadata.get("operational", True)),
            "config": dict(config or {}),
            "truth": {
                "fixture_metrics_are_not_gpu_training": True,
                "no_fabricated_production_metrics": True,
                "registered_is_not_trained": recipe.metadata.get("operational") is False,
            },
        }


class TrainingRecipeRegistry:
    """Recipe catalog + honest run status machine.

    REGISTERED → QUEUED → RUNNING → COMPLETED | FAILED
    Metrics only when a real trainer backend reports them.
    """

    def __init__(
        self,
        recipes: tuple[TrainingRecipe, ...] = NEURO_RECIPES,
        *,
        trainer: RecipeTrainerBackend | None = None,
    ) -> None:
        self._recipes = {item.recipe_id: item for item in recipes}
        self._runs: dict[str, RecipeRun] = {}
        self.trainer = trainer

    def list(self) -> list[TrainingRecipe]:
        return sorted(self._recipes.values(), key=lambda item: item.recipe_id)

    def get(self, recipe_id: str) -> TrainingRecipe | None:
        return self._recipes.get(recipe_id)

    def list_runs(self) -> list[RecipeRun]:
        return sorted(self._runs.values(), key=lambda item: item.created_at, reverse=True)

    def get_run(self, run_id: str) -> RecipeRun | None:
        return self._runs.get(run_id)

    def enqueue(self, recipe_id: str) -> RecipeRun:
        recipe = self._recipes.get(recipe_id)
        if recipe is None:
            raise KeyError(f"Unknown recipe: {recipe_id}")
        now = utc_now()
        run = RecipeRun(
            run_id=str(uuid.uuid4()),
            recipe_id=recipe_id,
            status=RecipeRunStatus.QUEUED,
            created_at=now,
            updated_at=now,
            detail="queued — registered is not trained",
        )
        self._runs[run.run_id] = run
        return run

    def execute(
        self,
        recipe_id: str,
        *,
        samples: Sequence[Mapping[str, Any]] | None = None,
        config: Mapping[str, Any] | None = None,
        trainer: RecipeTrainerBackend | None = None,
    ) -> RecipeRun:
        recipe = self._recipes.get(recipe_id)
        if recipe is None:
            raise KeyError(f"Unknown recipe: {recipe_id}")
        backend = trainer if trainer is not None else self.trainer
        now = utc_now()
        run = RecipeRun(
            run_id=str(uuid.uuid4()),
            recipe_id=recipe_id,
            status=RecipeRunStatus.QUEUED,
            created_at=now,
            updated_at=now,
            trainer_backend=getattr(backend, "backend_id", None) if backend else None,
            detail="queued",
        )
        self._runs[run.run_id] = run

        if backend is None or not backend.available():
            failed = RecipeRun(
                run_id=run.run_id,
                recipe_id=recipe_id,
                status=RecipeRunStatus.FAILED,
                created_at=run.created_at,
                updated_at=utc_now(),
                metrics={},
                error="No trainer backend available — recipe remains untrained (registered ≠ trained)",
                trainer_backend=None,
                detail="FAILED without fabricated metrics",
            )
            self._runs[run.run_id] = failed
            return failed

        running = RecipeRun(
            run_id=run.run_id,
            recipe_id=recipe_id,
            status=RecipeRunStatus.RUNNING,
            created_at=run.created_at,
            updated_at=utc_now(),
            trainer_backend=backend.backend_id,
            detail="running",
        )
        self._runs[run.run_id] = running
        started = time.perf_counter()
        try:
            metrics = dict(
                backend.execute(recipe, samples=list(samples or ()), config=config)
            )
            # Refuse forged COMPLETED with empty metrics.
            if not metrics:
                raise RuntimeError("trainer returned empty metrics — refusing fabricated COMPLETED")
            duration_ms = (time.perf_counter() - started) * 1000
            metrics.setdefault("duration_ms", round(duration_ms, 3))
            completed = RecipeRun(
                run_id=run.run_id,
                recipe_id=recipe_id,
                status=RecipeRunStatus.COMPLETED,
                created_at=run.created_at,
                updated_at=utc_now(),
                metrics=metrics,
                trainer_backend=backend.backend_id,
                detail="completed with trainer-reported metrics",
            )
            self._runs[run.run_id] = completed
            return completed
        except Exception as exc:  # noqa: BLE001
            failed = RecipeRun(
                run_id=run.run_id,
                recipe_id=recipe_id,
                status=RecipeRunStatus.FAILED,
                created_at=run.created_at,
                updated_at=utc_now(),
                metrics={},
                error=str(exc),
                trainer_backend=backend.backend_id,
                detail="FAILED — no fabricated metrics",
            )
            self._runs[run.run_id] = failed
            return failed
