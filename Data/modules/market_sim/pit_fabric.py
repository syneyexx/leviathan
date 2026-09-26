"""Point-in-time market data fabric (institutional W06).

Binds sealed/revision identity, adjustment-mode labeling, and survivorship
honesty to market observations. Does not invent quotes or fundamentals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .dataset_pipeline import DatasetQualityReport, analyze_bars, analyze_quote_snapshot
from .epistemic import compare_ts, is_available
from .types import Bar
from .universe import DatasetRevisionIdentity, PointInTimeUniverse


ALLOWED_ADJUSTMENT_MODES = frozenset(
    {
        "as_traded",
        "split_adjusted",
        "dividend_adjusted",
        "total_return",
        "unadjusted",
        "unknown",
    }
)

ALLOWED_SURVIVORSHIP_MODES = frozenset(
    {
        "point_in_time",
        "survivors_only",
        "labelled_today_universe",
        "UNMEASURED",
    }
)


@dataclass(frozen=True)
class PitObservation:
    """Single market observation with causal availability."""

    symbol: str
    event_ts: str
    available_at: str
    data_level: str  # ohlcv | quotes | orderbook | fundamentals
    adjustment_mode: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "eventTs": self.event_ts,
            "availableAt": self.available_at,
            "dataLevel": self.data_level,
            "adjustmentMode": self.adjustment_mode,
            "payload": dict(self.payload),
            "truth": {
                "available_at_is_primary_boundary": True,
                "ohlcv_is_not_orderbook": self.data_level == "ohlcv",
            },
        }


def normalize_adjustment_mode(mode: str | None) -> str:
    raw = (mode or "unknown").strip().lower() or "unknown"
    if raw not in ALLOWED_ADJUSTMENT_MODES:
        return "unknown"
    return raw


def normalize_survivorship_mode(mode: str | None) -> str:
    raw = (mode or "UNMEASURED").strip() or "UNMEASURED"
    if raw not in ALLOWED_SURVIVORSHIP_MODES:
        return "UNMEASURED"
    return raw


def build_revision_identity(
    *,
    revision_id: str,
    content_hash: str,
    published_at: str,
    available_at: str,
    observed_at: str | None = None,
    parent_revision_id: str | None = None,
    survivorship_mode: str = "point_in_time",
) -> DatasetRevisionIdentity:
    return DatasetRevisionIdentity(
        revision_id=revision_id,
        published_at=published_at,
        available_at=available_at,
        observed_at=observed_at or published_at,
        content_hash=content_hash,
        parent_revision_id=parent_revision_id,
        survivorship_mode=normalize_survivorship_mode(survivorship_mode),
    )


def bars_to_pit_observations(
    bars: Sequence[Bar],
    *,
    symbol: str,
    adjustment_mode: str = "as_traded",
    available_at_override: str | None = None,
) -> list[PitObservation]:
    """OHLCV bars become PIT observations; available_at defaults to event_ts.

    Callers may pass ``available_at_override`` only when a real vendor publication
    lag is known — never invent lag from OHLCV alone.
    """
    mode = normalize_adjustment_mode(adjustment_mode)
    out: list[PitObservation] = []
    for bar in bars:
        out.append(
            PitObservation(
                symbol=symbol,
                event_ts=bar.ts,
                available_at=available_at_override or bar.ts,
                data_level="ohlcv",
                adjustment_mode=mode,
                payload=bar.public_dict(),
            )
        )
    return out


def filter_observations_as_of(
    observations: Sequence[PitObservation],
    *,
    as_of: str,
) -> list[PitObservation]:
    """Fail-closed: drop observations without available_at or with available_at > as_of."""
    kept: list[PitObservation] = []
    for obs in observations:
        if not obs.available_at:
            continue
        if is_available(available_at=obs.available_at, as_of=as_of):
            kept.append(obs)
    return kept


def filter_bars_as_of(bars: Sequence[Bar], *, as_of: str) -> list[Bar]:
    """Causal bar slice: keep bars whose event timestamp is <= as_of."""
    kept: list[Bar] = []
    for bar in bars:
        if not bar.ts:
            continue
        if compare_ts(bar.ts, as_of) <= 0:
            kept.append(bar)
    return kept


def quality_with_pit_labels(
    report: DatasetQualityReport,
    *,
    adjustment_mode: str | None = None,
    survivorship_mode: str = "UNMEASURED",
    revision: DatasetRevisionIdentity | None = None,
) -> dict[str, Any]:
    """Attach PIT / adjustment / survivorship honesty fields to a quality public dict."""
    payload = report.public_dict()
    adj = normalize_adjustment_mode(adjustment_mode or report.adjustment_mode)
    surv = normalize_survivorship_mode(
        survivorship_mode
        if survivorship_mode != "UNMEASURED"
        else report.survivorship_bias_risk
    )
    payload["adjustmentMode"] = adj
    payload["survivorshipBiasRisk"] = surv
    payload["survivorshipMode"] = surv
    if revision is not None:
        payload["revision"] = revision.public_dict()
    truth = dict(payload.get("truth") or {})
    truth["adjusted_vs_unadjusted_must_be_labeled"] = True
    truth["survivorship_bias_must_be_labelled"] = True
    truth["today_universe_is_not_historical_by_default"] = surv != "labelled_today_universe"
    truth["parsed_csv_is_not_quality_pass"] = True
    payload["truth"] = truth
    return payload


def analyze_market_file_quality(
    bars: Sequence[Bar],
    *,
    timeframe: str = "1h",
    content_hash: str = "",
    byte_size: int = 0,
    adjustment_mode: str = "as_traded",
    survivorship_mode: str = "UNMEASURED",
) -> dict[str, Any]:
    """Operator-facing quality + PIT labels for an OHLCV series."""
    report = analyze_bars(
        bars,
        timeframe=timeframe,
        content_hash=content_hash,
        byte_size=byte_size,
        adjustment_mode=normalize_adjustment_mode(adjustment_mode),
        survivorship_bias_risk=normalize_survivorship_mode(survivorship_mode),
    )
    return quality_with_pit_labels(
        report,
        adjustment_mode=adjustment_mode,
        survivorship_mode=survivorship_mode,
    )


def analyze_quotes_quality(quotes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return analyze_quote_snapshot(quotes)


def survivorship_membership_as_of(
    universe: PointInTimeUniverse,
    *,
    as_of: str,
) -> dict[str, Any]:
    members = sorted(universe.as_of_membership(as_of))
    return {
        "asOf": as_of,
        "symbols": members,
        "count": len(members),
        "survivorshipMode": universe.survivorship_mode,
        "truth": {
            "point_in_time_default": universe.survivorship_mode == "point_in_time",
            "delisted_do_not_silently_vanish_from_history": True,
        },
    }
