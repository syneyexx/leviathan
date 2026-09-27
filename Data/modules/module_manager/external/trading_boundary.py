"""Trading boundary for external finance capabilities.

External packages may research/analyze. They must not bypass MarketSim
qualification, RiskGuard, or paper-accounting authority, and must not claim
real-money authority. This is an engineering gate — not a moral-policy layer.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from Data.modules.execution.types import CapabilityResult, CapabilityStatus


# Operations that imply LEVIATHAN trading-state mutation or live money.
_MUTATION_OPS = re.compile(
    r"(^|[._:-])("
    r"place_order|submit_order|create_order|cancel_order|execute_trade|"
    r"buy|sell|short|cover|market_order|limit_order|"
    r"paper_order|live_trade|live_order|broker_order|"
    r"open_position|close_position|flatten|liquidate|"
    r"marketsim\.(order|trade|portfolio\.mutate|broker)"
    r")($|[._:-])",
    re.IGNORECASE,
)

_MUTATION_ARG_KEYS = frozenset(
    {
        "order",
        "orders",
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_order",
        "live_trade",
        "paper_order",
        "quantity_side",  # rare composite
    }
)


def module_trading_flags(managed_or_config: Any) -> dict[str, bool]:
    """Extract marketsim_bypass_forbidden / real_money_blocked from module metadata."""
    meta: dict[str, Any] = {}
    external: dict[str, Any] = {}
    if managed_or_config is None:
        return {"marketsim_bypass_forbidden": False, "real_money_blocked": False}
    # CapabilityDefinition.metadata
    if hasattr(managed_or_config, "metadata") and isinstance(managed_or_config.metadata, Mapping):
        meta = dict(managed_or_config.metadata)
        external = dict(meta.get("external_metadata") or meta)
    # Managed module / ExternalConfig
    manifest = getattr(managed_or_config, "manifest", None)
    if manifest is not None:
        raw = (getattr(manifest, "metadata", None) or {}).get("external") or {}
        if isinstance(raw, Mapping):
            external = dict(raw.get("metadata") or {})
            # Also honor top-level flags if present.
            for key in ("marketsim_bypass_forbidden", "real_money_blocked"):
                if key in raw and key not in external:
                    external[key] = raw[key]
    if hasattr(managed_or_config, "metadata") and isinstance(getattr(managed_or_config, "metadata", None), Mapping):
        # ExternalConfig.metadata
        cfg_meta = dict(managed_or_config.metadata)
        for key in ("marketsim_bypass_forbidden", "real_money_blocked"):
            if key in cfg_meta:
                external[key] = cfg_meta[key]
    if isinstance(managed_or_config, Mapping):
        external = {**external, **dict(managed_or_config)}
    return {
        "marketsim_bypass_forbidden": bool(external.get("marketsim_bypass_forbidden")),
        "real_money_blocked": bool(external.get("real_money_blocked") or external.get("marketsim_bypass_forbidden")),
    }


def looks_like_trading_mutation(operation: str, arguments: Mapping[str, Any] | None = None) -> bool:
    op = (operation or "").strip()
    if op and _MUTATION_OPS.search(op):
        return True
    args = arguments or {}
    for key in args:
        if str(key).lower() in _MUTATION_ARG_KEYS:
            return True
        if _MUTATION_OPS.search(str(key)):
            return True
    # Explicit live-money / Marketsim mutation intent flags.
    for flag in ("live_trading", "real_money", "bypass_marketsim", "marketsim_order"):
        if args.get(flag) is True:
            return True
    side = str(args.get("side") or "").upper()
    if side in {"BUY", "SELL", "SHORT", "COVER"} and (
        args.get("quantity") is not None or args.get("qty") is not None or args.get("order_type")
    ):
        return True
    return False


def enforce_trading_boundary(
    *,
    flags: Mapping[str, bool],
    capability_id: str,
    operation: str,
    arguments: Mapping[str, Any] | None,
    request_id: str = "",
    provider_kind: str = "module",
    provider_ref: str = "",
) -> CapabilityResult | None:
    """Return a REJECTED CapabilityResult when mutation would bypass MarketSim; else None."""
    if not flags.get("marketsim_bypass_forbidden") and not flags.get("real_money_blocked"):
        return None
    if not looks_like_trading_mutation(operation, arguments) and not looks_like_trading_mutation(
        capability_id, arguments
    ):
        return None
    return CapabilityResult(
        request_id=request_id or "",
        capability_id=capability_id,
        status=CapabilityStatus.REJECTED,
        error=(
            "TRADING_BOUNDARY: external finance capabilities cannot mutate LEVIATHAN "
            "trading state or claim real-money authority. Route hypotheses through MarketSim "
            "(TRAIN→VAL→ROBUSTNESS→SEALED→SHADOW→PAPER)."
        ),
        output={
            "summary": "Trading boundary rejected mutation",
            "parts": [
                {
                    "kind": "ERROR",
                    "code": "TRADING_BOUNDARY",
                    "message": "MarketSim remains trading authority; real-money remains BLOCKED.",
                }
            ],
            "metadata": {
                "marketsim_authority": False,
                "real_money_blocked": True,
                "marketsim_bypass_forbidden": True,
                "operation": operation,
            },
        },
        provider_kind=provider_kind,
        provider_ref=provider_ref,
        telemetry={"trading_boundary": "rejected"},
    )


def annotate_research_only(output: dict[str, Any] | None, flags: Mapping[str, bool]) -> dict[str, Any]:
    """Stamp research-only provenance on successful external finance results."""
    out = dict(output or {})
    if not flags.get("marketsim_bypass_forbidden") and not flags.get("real_money_blocked"):
        return out
    meta = dict(out.get("metadata") or {})
    meta.update(
        {
            "marketsim_authority": False,
            "real_money_blocked": True,
            "marketsim_bypass_forbidden": bool(flags.get("marketsim_bypass_forbidden")),
            "qualification_required": "MarketSim TRAIN→VAL→ROBUSTNESS→SEALED→SHADOW→PAPER",
            "external_result_is_not_fact": True,
        }
    )
    out["metadata"] = meta
    return out
