"""HADES Cognitive Runtime — ten pillars inside One Brain.

Extends existing subsystems; does not create a competing Brain.
"""

from .contracts import CONTROLLER_VERSION, AdaptiveDecision, CapabilityEntry, UncertaintyState
from .modes import CognitiveMode, PILLAR_DEFAULT_MODES
from .runtime import CognitiveRuntime, get_cognitive_runtime, reset_cognitive_runtime
from .store import CognitiveStore

__all__ = [
    "CONTROLLER_VERSION",
    "AdaptiveDecision",
    "CapabilityEntry",
    "CognitiveMode",
    "CognitiveRuntime",
    "CognitiveStore",
    "PILLAR_DEFAULT_MODES",
    "UncertaintyState",
    "get_cognitive_runtime",
    "reset_cognitive_runtime",
]
