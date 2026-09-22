"""Leviathan Studio OmniRoute Editor Gateway.

Editor-facing capability router between Studio, AI providers, and future MCP.
Does not mutate document content — generation returns preview/results only.
"""

from .gateway import OmniRouteEditorGateway, get_gateway
from .protocol import CONTEXT_PROTOCOL, RESULT_PROTOCOL

__all__ = [
    "CONTEXT_PROTOCOL",
    "RESULT_PROTOCOL",
    "OmniRouteEditorGateway",
    "get_gateway",
]
