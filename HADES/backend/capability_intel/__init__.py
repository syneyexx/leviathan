"""HADES Capability Intelligence Layer.

Normalize plugin/native/MCP/upstream packages into canonical capability
contracts and route the smallest sufficient composition. Execution still
goes through PluginManager, policy and approvals.
"""

from .broker import CapabilityBroker, get_broker, reset_broker
from .collaboration import CollaborationSession, MissionState
from .contracts import CanonicalCapability, RequirementPlan, RoutingDecision
from .ids import capability_id_for_tool, make_capability_id, parse_capability_id
from .normalize import adapt_package, normalize_legacy_plugin
from .orchestration import verification_result
from .planner import plan_requirements
from .ranking import rank_capabilities, score_capability
from .registry import CapabilityRegistry, get_registry
from .service import CapabilityIntelligence, get_service, reset_service
from .skills import retrieve_skills
from .taxonomy import CAPABILITY_KINDS, CONTRACT_VERSION, NATIVE_PROVIDER_ID

__all__ = [
    "CAPABILITY_KINDS",
    "CONTRACT_VERSION",
    "NATIVE_PROVIDER_ID",
    "CanonicalCapability",
    "CapabilityBroker",
    "CapabilityIntelligence",
    "CapabilityRegistry",
    "CollaborationSession",
    "MissionState",
    "RequirementPlan",
    "RoutingDecision",
    "adapt_package",
    "capability_id_for_tool",
    "get_broker",
    "get_registry",
    "get_service",
    "make_capability_id",
    "normalize_legacy_plugin",
    "parse_capability_id",
    "plan_requirements",
    "rank_capabilities",
    "reset_broker",
    "reset_service",
    "retrieve_skills",
    "score_capability",
    "verification_result",
]
