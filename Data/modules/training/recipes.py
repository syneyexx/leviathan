from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


class TrainingRecipeRegistry:
    def __init__(self, recipes: tuple[TrainingRecipe, ...] = NEURO_RECIPES) -> None:
        self._recipes = {item.recipe_id: item for item in recipes}

    def list(self) -> list[TrainingRecipe]:
        return sorted(self._recipes.values(), key=lambda item: item.recipe_id)

    def get(self, recipe_id: str) -> TrainingRecipe | None:
        return self._recipes.get(recipe_id)
