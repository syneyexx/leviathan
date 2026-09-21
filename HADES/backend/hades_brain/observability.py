"""Structured decision reasons. Never private chain-of-thought."""

from __future__ import annotations

from typing import Any


def decision_record(
    *,
    capability: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    node: str | None = None,
    model_call_reason: str | None = None,
    context_selected: list[str] | None = None,
    cache: str | None = None,
    evidence: str | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "why_capability": capability,
        "why_provider": provider,
        "why_model": model,
        "why_agent": agent,
        "why_node": node,
        "why_model_call": model_call_reason,
        "context_selected": list(context_selected or [])[:24],
        "cache": cache,
        "evidence": evidence,
        "chain_of_thought": None,
        **(extras or {}),
    }
