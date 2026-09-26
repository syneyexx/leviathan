"""W38 — Canonical instrument identity resolution, aliases, temporal validity.

Extends market_sim.instruments — does not replace InstrumentFamily.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass(frozen=True)
class TemporalWindow:
    valid_from: str  # ISO-8601 inclusive
    valid_to: str | None = None  # None = open-ended

    def contains(self, as_of: str) -> bool:
        if as_of < self.valid_from:
            return False
        if self.valid_to is not None and as_of >= self.valid_to:
            return False
        return True

    def public_dict(self) -> dict[str, Any]:
        return {"validFrom": self.valid_from, "validTo": self.valid_to}


@dataclass
class InstrumentAlias:
    alias: str
    alias_type: str  # ticker | isin | cusip | figi | exchange_code | internal
    instrument_id: str
    window: TemporalWindow
    source: str = "UNMEASURED"

    def public_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "aliasType": self.alias_type,
            "instrumentId": self.instrument_id,
            "window": self.window.public_dict(),
            "source": self.source,
        }


@dataclass
class CanonicalInstrument:
    instrument_id: str
    family: str
    primary_symbol: str
    currency: str = "USD"
    exchange: str | None = None
    multiplier: float = 1.0
    window: TemporalWindow = field(
        default_factory=lambda: TemporalWindow(valid_from="1970-01-01T00:00:00+00:00")
    )
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = MeasurementState.OBSERVED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "family": self.family,
            "primarySymbol": self.primary_symbol,
            "currency": self.currency,
            "exchange": self.exchange,
            "multiplier": self.multiplier,
            "window": self.window.public_dict(),
            "attributes": dict(self.attributes),
            "status": self.status,
            "truth": DEFAULT_TRUTH.public_dict(),
        }


@dataclass
class ResolutionResult:
    query: str
    instrument_id: str | None
    matched_alias: str | None
    status: str
    candidates: list[str] = field(default_factory=list)
    as_of: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "instrumentId": self.instrument_id,
            "matchedAlias": self.matched_alias,
            "status": self.status,
            "candidates": list(self.candidates),
            "asOf": self.as_of,
            "truth": {
                "unresolved_is_not_silent_equity": True,
                **DEFAULT_TRUTH.public_dict(),
            },
        }


class InstrumentMaster:
    """In-process canonical identity registry with temporal alias resolution."""

    def __init__(self) -> None:
        self._instruments: dict[str, CanonicalInstrument] = {}
        self._aliases: list[InstrumentAlias] = []

    def register(self, instrument: CanonicalInstrument) -> CanonicalInstrument:
        self._instruments[instrument.instrument_id] = instrument
        # Primary symbol always registered as alias for the instrument window.
        self._aliases.append(
            InstrumentAlias(
                alias=instrument.primary_symbol.upper(),
                alias_type="ticker",
                instrument_id=instrument.instrument_id,
                window=instrument.window,
                source="primary",
            )
        )
        return instrument

    def add_alias(self, alias: InstrumentAlias) -> None:
        self._aliases.append(
            InstrumentAlias(
                alias=alias.alias.upper() if alias.alias_type == "ticker" else alias.alias,
                alias_type=alias.alias_type,
                instrument_id=alias.instrument_id,
                window=alias.window,
                source=alias.source,
            )
        )

    def get(self, instrument_id: str) -> CanonicalInstrument | None:
        return self._instruments.get(instrument_id)

    def resolve(self, query: str, *, as_of: str) -> ResolutionResult:
        q = str(query or "").strip()
        if not q:
            return ResolutionResult(
                query=q,
                instrument_id=None,
                matched_alias=None,
                status=MeasurementState.EMPTY.value,
                as_of=as_of,
            )
        # Direct id hit
        if q in self._instruments and self._instruments[q].window.contains(as_of):
            return ResolutionResult(
                query=q,
                instrument_id=q,
                matched_alias=None,
                status=MeasurementState.OBSERVED.value,
                as_of=as_of,
            )
        needle = q.upper()
        matches: list[InstrumentAlias] = []
        for alias in self._aliases:
            key = alias.alias.upper() if alias.alias_type == "ticker" else alias.alias
            if key == needle or key == q:
                if alias.window.contains(as_of):
                    matches.append(alias)
        if not matches:
            return ResolutionResult(
                query=q,
                instrument_id=None,
                matched_alias=None,
                status=MeasurementState.UNAVAILABLE.value,
                as_of=as_of,
            )
        # Prefer primary ticker source; detect conflicts across instruments.
        instrument_ids = sorted({m.instrument_id for m in matches})
        if len(instrument_ids) > 1:
            return ResolutionResult(
                query=q,
                instrument_id=None,
                matched_alias=needle,
                status=MeasurementState.FAIL.value,
                candidates=instrument_ids,
                as_of=as_of,
            )
        chosen = sorted(matches, key=lambda a: 0 if a.source == "primary" else 1)[0]
        return ResolutionResult(
            query=q,
            instrument_id=chosen.instrument_id,
            matched_alias=chosen.alias,
            status=MeasurementState.OBSERVED.value,
            as_of=as_of,
        )

    def list_instruments(self, *, as_of: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for inst in self._instruments.values():
            if as_of is not None and not inst.window.contains(as_of):
                continue
            out.append(inst.public_dict())
        return out

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentCount": len(self._instruments),
            "aliasCount": len(self._aliases),
            "instruments": [i.public_dict() for i in self._instruments.values()],
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_instruments_module": True,
            },
        }


def instrument_from_mapping(raw: Mapping[str, Any]) -> CanonicalInstrument:
    window_raw = raw.get("window") or {}
    return CanonicalInstrument(
        instrument_id=str(raw.get("instrument_id") or raw.get("instrumentId") or ""),
        family=str(raw.get("family") or "other"),
        primary_symbol=str(raw.get("primary_symbol") or raw.get("primarySymbol") or "").upper(),
        currency=str(raw.get("currency") or "USD"),
        exchange=(None if raw.get("exchange") is None else str(raw.get("exchange"))),
        multiplier=float(raw.get("multiplier") or 1.0),
        window=TemporalWindow(
            valid_from=str(window_raw.get("valid_from") or window_raw.get("validFrom") or "1970-01-01T00:00:00+00:00"),
            valid_to=(
                None
                if (window_raw.get("valid_to") if "valid_to" in window_raw else window_raw.get("validTo")) is None
                else str(window_raw.get("valid_to") or window_raw.get("validTo"))
            ),
        ),
        attributes=dict(raw.get("attributes") or {}),
        status=str(raw.get("status") or MeasurementState.OBSERVED.value),
    )


def resolve_many(
    master: InstrumentMaster,
    queries: Sequence[str],
    *,
    as_of: str,
) -> list[dict[str, Any]]:
    return [master.resolve(q, as_of=as_of).public_dict() for q in queries]
