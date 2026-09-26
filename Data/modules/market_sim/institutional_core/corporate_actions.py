"""W59 — Corporate actions: economic adjustments + point-in-time application.

Complements event_intel / pit_fabric — does not invent unobserved CAs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


CA_TYPES: tuple[str, ...] = (
    "SPLIT",
    "DIVIDEND_CASH",
    "DIVIDEND_STOCK",
    "MERGER",
    "SPINOFF",
    "SYMBOL_CHANGE",
    "DELISTING",
)


@dataclass(frozen=True)
class CorporateAction:
    ca_id: str
    instrument_id: str
    ca_type: str
    effective_time: str
    observed_at: str
    ratio: float | None = None  # split/stock dividend ratio
    cash_amount: float | None = None
    new_instrument_id: str | None = None
    status: str = MeasurementState.OBSERVED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "caId": self.ca_id,
            "instrumentId": self.instrument_id,
            "caType": self.ca_type,
            "effectiveTime": self.effective_time,
            "observedAt": self.observed_at,
            "ratio": self.ratio,
            "cashAmount": self.cash_amount,
            "newInstrumentId": self.new_instrument_id,
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "unobserved_ca_is_not_invented": True,
            },
        }


@dataclass
class PositionAdjustment:
    instrument_id: str
    qty_before: float
    qty_after: float
    cost_basis_before: float
    cost_basis_after: float
    cash_delta: float
    ca_id: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "qtyBefore": self.qty_before,
            "qtyAfter": self.qty_after,
            "costBasisBefore": self.cost_basis_before,
            "costBasisAfter": self.cost_basis_after,
            "cashDelta": self.cash_delta,
            "caId": self.ca_id,
        }


def apply_corporate_action(
    ca: CorporateAction | Mapping[str, Any],
    *,
    qty: float,
    cost_basis: float,
    as_of: str,
) -> dict[str, Any]:
    """Apply CA economically if as_of >= effective_time; else no-op with PIT honesty."""
    if isinstance(ca, Mapping):
        ca = CorporateAction(
            ca_id=str(ca.get("ca_id") or ca.get("caId") or ""),
            instrument_id=str(ca.get("instrument_id") or ca.get("instrumentId") or ""),
            ca_type=str(ca.get("ca_type") or ca.get("caType") or "").upper(),
            effective_time=str(ca.get("effective_time") or ca.get("effectiveTime") or ""),
            observed_at=str(ca.get("observed_at") or ca.get("observedAt") or ""),
            ratio=(None if ca.get("ratio") is None else float(ca.get("ratio"))),
            cash_amount=(
                None
                if ca.get("cash_amount", ca.get("cashAmount")) is None
                else float(ca.get("cash_amount") or ca.get("cashAmount"))
            ),
            new_instrument_id=(
                None
                if ca.get("new_instrument_id", ca.get("newInstrumentId")) is None
                else str(ca.get("new_instrument_id") or ca.get("newInstrumentId"))
            ),
            status=str(ca.get("status") or MeasurementState.OBSERVED.value),
        )

    if as_of < ca.effective_time:
        return {
            "applied": False,
            "reason": "before_effective_time",
            "status": MeasurementState.OBSERVED.value,
            "adjustment": None,
            "truth": {"point_in_time_respected": True},
        }

    if ca.ca_type not in CA_TYPES:
        return {
            "applied": False,
            "reason": "ca_type_NOT_IMPLEMENTED",
            "status": MeasurementState.NOT_IMPLEMENTED.value,
            "adjustment": None,
        }

    qty_after = qty
    cost_after = cost_basis
    cash_delta = 0.0

    if ca.ca_type == "SPLIT":
        if ca.ratio is None or ca.ratio <= 0:
            return {
                "applied": False,
                "reason": "split_ratio_missing",
                "status": MeasurementState.UNAVAILABLE.value,
                "adjustment": None,
            }
        qty_after = qty * ca.ratio
        cost_after = cost_basis / ca.ratio if ca.ratio else cost_basis
    elif ca.ca_type == "DIVIDEND_CASH":
        if ca.cash_amount is None:
            return {
                "applied": False,
                "reason": "cash_amount_missing",
                "status": MeasurementState.UNAVAILABLE.value,
                "adjustment": None,
            }
        cash_delta = qty * ca.cash_amount
    elif ca.ca_type == "DIVIDEND_STOCK":
        if ca.ratio is None:
            return {
                "applied": False,
                "reason": "stock_dividend_ratio_missing",
                "status": MeasurementState.UNAVAILABLE.value,
                "adjustment": None,
            }
        qty_after = qty * (1.0 + ca.ratio)
        cost_after = (qty * cost_basis) / qty_after if qty_after else cost_basis
    elif ca.ca_type == "SYMBOL_CHANGE":
        # Quantity/cost unchanged; instrument id change is caller responsibility.
        pass
    elif ca.ca_type in {"MERGER", "SPINOFF", "DELISTING"}:
        return {
            "applied": False,
            "reason": f"{ca.ca_type}_requires_terms_NOT_IMPLEMENTED",
            "status": MeasurementState.NOT_IMPLEMENTED.value,
            "adjustment": None,
        }

    adj = PositionAdjustment(
        instrument_id=ca.new_instrument_id or ca.instrument_id,
        qty_before=qty,
        qty_after=qty_after,
        cost_basis_before=cost_basis,
        cost_basis_after=cost_after,
        cash_delta=cash_delta,
        ca_id=ca.ca_id,
    )
    return {
        "applied": True,
        "reason": "ok",
        "status": ca.status,
        "adjustment": adj.public_dict(),
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "point_in_time_respected": True,
            "late_observation_still_uses_effective_time": ca.observed_at > ca.effective_time,
        },
    }


def apply_ca_series(
    actions: Sequence[CorporateAction | Mapping[str, Any]],
    *,
    qty: float,
    cost_basis: float,
    as_of: str,
) -> dict[str, Any]:
    """Apply CAs in effective_time order for PIT reconstruction."""
    normalized: list[CorporateAction] = []
    for raw in actions:
        result_probe = apply_corporate_action(raw, qty=0, cost_basis=0, as_of="9999-12-31")
        # Re-parse properly:
        if isinstance(raw, CorporateAction):
            normalized.append(raw)
        else:
            normalized.append(
                CorporateAction(
                    ca_id=str(raw.get("ca_id") or raw.get("caId") or ""),
                    instrument_id=str(raw.get("instrument_id") or raw.get("instrumentId") or ""),
                    ca_type=str(raw.get("ca_type") or raw.get("caType") or "").upper(),
                    effective_time=str(raw.get("effective_time") or raw.get("effectiveTime") or ""),
                    observed_at=str(raw.get("observed_at") or raw.get("observedAt") or ""),
                    ratio=(None if raw.get("ratio") is None else float(raw.get("ratio"))),
                    cash_amount=(
                        None
                        if raw.get("cash_amount", raw.get("cashAmount")) is None
                        else float(raw.get("cash_amount") or raw.get("cashAmount"))
                    ),
                    new_instrument_id=(
                        None
                        if raw.get("new_instrument_id", raw.get("newInstrumentId")) is None
                        else str(raw.get("new_instrument_id") or raw.get("newInstrumentId"))
                    ),
                    status=str(raw.get("status") or MeasurementState.OBSERVED.value),
                )
            )
        _ = result_probe

    normalized.sort(key=lambda c: (c.effective_time, c.ca_id))
    q, c = float(qty), float(cost_basis)
    cash = 0.0
    steps: list[dict[str, Any]] = []
    for ca in normalized:
        step = apply_corporate_action(ca, qty=q, cost_basis=c, as_of=as_of)
        steps.append(step)
        if step.get("applied") and step.get("adjustment"):
            adj = step["adjustment"]
            q = float(adj["qtyAfter"])
            c = float(adj["costBasisAfter"])
            cash += float(adj["cashDelta"])
    return {
        "qty": q,
        "costBasis": c,
        "cashDelta": cash,
        "steps": steps,
        "truth": DEFAULT_TRUTH.public_dict(),
    }
