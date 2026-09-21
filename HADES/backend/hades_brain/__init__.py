"""HADES One Brain: shared cognition contracts over existing subsystems."""

from .agent_protocol import from_agent_contract, justify_additional_agent
from .contracts import CanonicalAgent, CanonicalCapability, ContentRef, VerificationOutcome
from .cost import get_ledger, reset_ledger
from .domain_runtime import MIGRATION_MATRIX, migration_matrix
from .evidence import evaluate_verification, should_stop_reasoning
from .mission import compile_role_view, compose_domain_steps, cross_domain_handoff
from .service import HadesBrain, get_brain, reset_brain
from .substrate import substrate_overview
from .tool_context import bound_tools_for_model

__all__ = [
    "CanonicalAgent",
    "CanonicalCapability",
    "ContentRef",
    "HadesBrain",
    "MIGRATION_MATRIX",
    "VerificationOutcome",
    "bound_tools_for_model",
    "compile_role_view",
    "compose_domain_steps",
    "cross_domain_handoff",
    "evaluate_verification",
    "from_agent_contract",
    "get_brain",
    "get_ledger",
    "justify_additional_agent",
    "migration_matrix",
    "reset_brain",
    "reset_ledger",
    "should_stop_reasoning",
    "substrate_overview",
]
