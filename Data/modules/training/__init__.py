"""Training registry stub — registered ≠ trained."""

from .preferences import PreferenceBridge
from .recipes import NEURO_RECIPES, TrainingRecipe, TrainingRecipeRegistry
from .registry import TrainingRegistry
from .types import TrainingJob, TrainingJobStatus

__all__ = [
    "NEURO_RECIPES",
    "PreferenceBridge",
    "TrainingJob",
    "TrainingJobStatus",
    "TrainingRecipe",
    "TrainingRecipeRegistry",
    "TrainingRegistry",
]
