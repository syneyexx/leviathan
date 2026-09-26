"""W70 — Private / illiquid asset extensibility hooks.

Honest NOT_IMPLEMENTED defaults — no fake marks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, StatusedValue, DEFAULT_TRUTH


ILLIQUID_FAMILIES: tuple[str, ...] = (
    "private_equity",
    "private_credit",
    "real_estate",
    "infrastructure",
    "fund_interest",
    "other_illiquid",
)


@dataclass
class IlliquidInstrument:
    instrument_id: str
    family: str
    name: str
    currency: str = "USD"
    valuation_method: str = "NOT_IMPLEMENTED"
    attributes: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "family": self.family,
            "name": self.name,
            "currency": self.currency,
            "valuationMethod": self.valuation_method,
            "attributes": dict(self.attributes),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "illiquid_marks_default_UNMEASURED": True,
            },
        }


@dataclass
class IlliquidValuation:
    instrument_id: str
    as_of: str
    nav: StatusedValue
    source: str = "UNMEASURED"

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "asOf": self.as_of,
            "nav": self.nav.public_dict(),
            "source": self.source,
            "truth": DEFAULT_TRUTH.public_dict(),
        }


class IlliquidRegistry:
    def __init__(self) -> None:
        self._instruments: dict[str, IlliquidInstrument] = {}
        self._valuations: list[IlliquidValuation] = []

    def register(self, instrument: IlliquidInstrument) -> IlliquidInstrument:
        if instrument.family not in ILLIQUID_FAMILIES:
            raise ValueError(f"unsupported illiquid family: {instrument.family}")
        self._instruments[instrument.instrument_id] = instrument
        return instrument

    def record_valuation(
        self,
        *,
        instrument_id: str,
        as_of: str,
        nav: float | None,
        state: str = MeasurementState.UNMEASURED.value,
        source: str = "UNMEASURED",
        methodology: str = "external_nav_ASSUMED",
    ) -> IlliquidValuation:
        if instrument_id not in self._instruments:
            raise KeyError(instrument_id)
        if nav is None:
            state = MeasurementState.UNMEASURED.value
        val = IlliquidValuation(
            instrument_id=instrument_id,
            as_of=as_of,
            nav=StatusedValue(
                nav,
                MeasurementState(state) if state in MeasurementState.__members__ else MeasurementState.UNMEASURED,
                unit="currency",
                methodology=methodology,
                notes=["no_fabricated_mark"] if nav is None else [],
            ),
            source=source,
        )
        self._valuations.append(val)
        return val

    def latest_valuation(self, instrument_id: str) -> IlliquidValuation | None:
        items = [v for v in self._valuations if v.instrument_id == instrument_id]
        if not items:
            return None
        items.sort(key=lambda v: v.as_of)
        return items[-1]

    def capability_matrix(self) -> dict[str, Any]:
        return {
            "families": [
                {
                    "family": fam,
                    "trading": MeasurementState.NOT_IMPLEMENTED.value,
                    "valuation": MeasurementState.NOT_IMPLEMENTED.value,
                    "liquidity": MeasurementState.UNMEASURED.value,
                }
                for fam in ILLIQUID_FAMILIES
            ],
            "registeredCount": len(self._instruments),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extensibility_hooks_only": True,
                "not_full_private_markets_platform": True,
            },
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "instruments": [i.public_dict() for i in self._instruments.values()],
            "valuations": [v.public_dict() for v in self._valuations],
            "capabilities": self.capability_matrix(),
            "truth": DEFAULT_TRUTH.public_dict(),
        }
