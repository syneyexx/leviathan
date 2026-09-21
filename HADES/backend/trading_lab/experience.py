"""Trading experience construction.

An experience is a derived, structured fact:

    given this market context, strategy, parameters and decision, this later outcome occurred.

It is not a belief and it is not a prompt. Construction is deterministic and idempotent:
one resolved decision produces at most one experience, identified by a hash of the
decision id. Retries and restarts therefore cannot silently duplicate learning.

Raw evidence (the decision row and its later_outcome JSON) stays untouched. This module
only *reads* it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from trading_lab.contracts import DecisionRecord, stable_hash
from trading_lab.regimes import RegimeSnapshot, classify_closes

MIN_HOLDING_FOR_CLASS = 1


def experience_id_for(decision_id: str) -> str:
    return "lex_" + stable_hash({"decision_id": decision_id})[:24]


def classify_outcome(signal: str, action: str, price_change: float | None) -> str:
    """Label the later price move relative to the decision. Not a skill judgement."""
    if price_change is None:
        return "unresolved"
    direction = _signal_direction(signal, action)
    if direction == 0:
        return "flat_or_wait"
    if price_change == 0:
        return "unchanged"
    aligned = price_change * direction
    if aligned > 0:
        return "favorable"
    return "adverse"


def _signal_direction(signal: str, action: str) -> int:
    text = f"{signal} {action}".lower()
    if any(token in text for token in ("short", "sell")):
        return -1
    if any(token in text for token in ("long", "buy", "execute")):
        return 1
    return 0


def build_experience(
    decision: dict[str, Any],
    *,
    run: dict[str, Any] | None = None,
    experiment: dict[str, Any] | None = None,
    strategy: dict[str, Any] | None = None,
    closes_at_decision: Sequence[float] | None = None,
    volumes_at_decision: Sequence[float] | None = None,
    path_prices: Sequence[float] | None = None,
    engine_version: str = "",
) -> dict[str, Any]:
    """Build one experience dict from a persisted decision plus optional context.

    Missing simulator fields stay null and are listed in ``unavailable``. Nothing is
    fabricated: MAE/MFE appear only when ``path_prices`` covers the holding window.
    """
    payload = dict(decision.get("decision") or decision)
    later = decision.get("later_outcome") or payload.get("later_outcome") or {}
    if not later:
        raise ValueError("experience_requires_later_outcome")
    decision_id = str(decision.get("decision_id") or payload.get("decision_id") or "")
    if not decision_id:
        raise ValueError("experience_requires_decision_id")

    reference = _float(later.get("reference_price"))
    later_price = _float(later.get("later_price"))
    price_change = _float(later.get("price_change"))
    if price_change is None and reference and later_price is not None and reference != 0:
        price_change = (later_price / reference) - 1.0

    signal = str(decision.get("signal") or payload.get("signal") or "flat")
    action = str(decision.get("action") or payload.get("action") or "wait")
    direction = _signal_direction(signal, action)
    signed = None if price_change is None else price_change * (direction or 0)

    regime = (
        classify_closes(closes_at_decision, volumes=volumes_at_decision)
        if closes_at_decision
        else RegimeSnapshot(
            trend=None,
            volatility=None,
            stress=None,
            trend_strength=None,
            realized_vol=None,
            vol_percentile=None,
            volume_state=None,
            drawdown_from_peak=None,
            available=False,
            unavailable_reason="closes_not_supplied",
        )
    )

    mae = mfe = None
    if path_prices and reference:
        mae, mfe = _excursions(path_prices, reference, direction)

    unavailable: dict[str, str] = {}
    if mae is None:
        unavailable["mae"] = "path_prices_not_supplied"
    if mfe is None:
        unavailable["mfe"] = "path_prices_not_supplied"

    run = run or {}
    experiment = experiment or {}
    strategy = strategy or {}
    observed = payload.get("observed") or {}
    observations = (observed.get("observations") or {}).get(decision.get("instrument_id") or payload.get("instrument_id"), {})
    split = (
        decision.get("split")
        or observations.get("split")
        or run.get("split")
        or experiment.get("split")
        or "development"
    )
    dataset_ids = run.get("dataset_ids") or experiment.get("dataset_ids") or []
    if isinstance(dataset_ids, str):
        dataset_ids = [dataset_ids]

    fees = _float((run.get("result") or {}).get("costs", {}).get("fees_paid") if isinstance(run.get("result"), dict) else None)
    if fees is None:
        unavailable["fees"] = "not_on_decision_record"
    spread = slippage = None
    unavailable["spread"] = "not_separable_from_cost_model"
    unavailable["slippage"] = "not_separable_from_cost_model"

    spec = {}
    if strategy.get("versions"):
        spec = (strategy["versions"][0] or {}).get("spec") or {}
    elif strategy.get("spec"):
        spec = strategy["spec"]
    params = spec.get("params") or (run.get("config") or {}).get("strategy", {}).get("params") or {}
    family = strategy.get("family") or spec.get("family") or experiment.get("strategy_family") or ""
    version = decision.get("strategy_version") or payload.get("strategy_version") or strategy.get("current_version") or spec.get("version")
    timeframe = spec.get("timeframe") or (run.get("config") or {}).get("strategy", {}).get("timeframe") or observations.get("timeframe")
    strategy_hash = spec.get("content_hash") or run.get("strategy_hash") or ""
    if not strategy_hash and spec:
        from trading_lab.contracts import StrategySpec

        try:
            strategy_hash = StrategySpec.model_validate({**spec, "instruments": spec.get("instruments") or ["unknown"]}).content_hash()
        except Exception:
            strategy_hash = stable_hash(params)

    holding = None
    event_time = str(decision.get("event_time") or payload.get("event_time") or "")
    evaluation_time = str(later.get("resolved_at") or decision.get("deferred_evaluation_at") or "")
    if event_time and evaluation_time:
        holding = later.get("holding_horizon")

    benchmark = price_change
    excess = signed if direction else None
    outcome = classify_outcome(signal, action, price_change)
    evidence_refs = [
        f"decision:{decision_id}",
        f"run:{decision.get('run_id') or payload.get('run_id')}",
    ]
    if later.get("resolved_at"):
        evidence_refs.append(f"later_outcome:{decision_id}@{later.get('resolved_at')}")
    if experiment.get("experiment_id"):
        evidence_refs.append(f"experiment:{experiment['experiment_id']}")

    return {
        "experience_id": experience_id_for(decision_id),
        "decision_id": decision_id,
        "run_id": str(decision.get("run_id") or payload.get("run_id") or ""),
        "experiment_id": experiment.get("experiment_id") or run.get("experiment_id"),
        "trial_id": run.get("trial_id"),
        "strategy_id": decision.get("strategy_id") or payload.get("strategy_id") or strategy.get("strategy_id") or run.get("strategy_id"),
        "strategy_version": int(version) if version is not None else None,
        "instrument_id": str(decision.get("instrument_id") or payload.get("instrument_id") or ""),
        "timeframe": timeframe,
        "event_time": event_time,
        "evaluation_time": evaluation_time or None,
        "mode": run.get("mode") or "historical_simulation",
        "split": split,
        "strategy_family": family,
        "strategy_params": params,
        "signal": signal,
        "action": action,
        "confidence": payload.get("signal_uncertainty") or None,
        "regime": regime.as_json(),
        "regime_key": regime.key,
        "position_state": {"equity": observed.get("equity")},
        "portfolio": {"equity": observed.get("equity")},
        "entry_price": reference,
        "later_price": later_price,
        "price_change": price_change,
        "gross_pnl": signed,
        "net_pnl": signed if fees is None else (None if signed is None else signed),
        "fees": fees,
        "spread": spread,
        "slippage": slippage,
        "mae": mae,
        "mfe": mfe,
        "drawdown_contribution": mae,
        "benchmark_return": benchmark,
        "excess_return": excess,
        "holding_horizon": holding,
        "outcome_class": outcome,
        "evidence_refs": evidence_refs,
        "dataset_ids": list(dataset_ids),
        "dataset_checksum": run.get("dataset_hash") or experiment.get("dataset_hash") or "",
        "strategy_hash": strategy_hash,
        "engine_version": engine_version or run.get("engine_version") or "",
        "unavailable": unavailable,
        "is_synthetic": int(bool(run.get("is_synthetic") or experiment.get("is_synthetic"))),
    }


def _excursions(path: Sequence[float], reference: float, direction: int) -> tuple[float | None, float | None]:
    if not path or not reference:
        return None, None
    signed = [((price / reference) - 1.0) * (direction or 1) for price in path]
    adverse = min(signed)
    favorable = max(signed)
    return adverse, favorable


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


class DecisionCaptureSink:
    """Persists decisions and later outcomes without writing the rest of a run.

    Experiment trials historically used ``NullSink``, which dropped the very evidence the
    learning loop needs. This sink is additive: orders, fills and the ledger stay as they
    were (unpersisted for search trials) while decisions become durable raw evidence.
    """

    def __init__(self, store: Any, run_id: str) -> None:
        self.store = store
        self.run_id = run_id

    def on_order(self, record: dict[str, Any]) -> None:
        return

    def on_order_event(self, event: Any) -> None:
        return

    def on_fill(self, fill: Any) -> None:
        return

    def on_ledger(self, rows: Sequence[dict[str, Any]]) -> None:
        return

    def on_snapshot(self, snapshot: Any) -> None:
        return

    def on_checkpoint(self, event_time: str, checkpoint: dict[str, Any]) -> None:
        return

    def on_decision(self, record: DecisionRecord) -> None:
        self.store.save_decision(record)

    def on_decision_outcome(self, decision_id: str, outcome: dict[str, Any]) -> None:
        self.store.attach_decision_outcome(decision_id, outcome)

    def on_progress(self, progress: dict[str, Any]) -> None:
        return


def ingest_resolved_decisions(
    store: Any,
    *,
    run_id: str | None = None,
    experiment_id: str | None = None,
    limit: int = 5000,
    closes_lookup: Any | None = None,
    engine_version: str = "",
) -> dict[str, Any]:
    """Create experiences for resolved decisions that do not yet have one.

    Idempotent: existing rows are left in place. ``created`` counts only new inserts.
    """
    rows = store.list_resolved_decisions_without_experience(run_id=run_id, experiment_id=experiment_id, limit=limit)
    created = 0
    skipped = 0
    errors: list[str] = []
    run_cache: dict[str, dict[str, Any]] = {}
    strategy_cache: dict[str, dict[str, Any]] = {}
    experiment = store.get_experiment(experiment_id) if experiment_id else None
    for row in rows:
        try:
            rid = row.get("run_id")
            run = run_cache.get(rid) if rid else None
            if rid and run is None:
                run = store.get_run(rid) if hasattr(store, "get_run") else None
                if run:
                    run_cache[rid] = run
            if experiment is None and run and run.get("experiment_id"):
                experiment = store.get_experiment(run["experiment_id"])
            strategy_id = row.get("strategy_id") or (run or {}).get("strategy_id")
            strategy = strategy_cache.get(strategy_id) if strategy_id else None
            if strategy_id and strategy is None:
                strategy = store.get_strategy(strategy_id)
                if strategy:
                    strategy_cache[strategy_id] = strategy
            closes = None
            if closes_lookup is not None:
                closes = closes_lookup(row)
            payload = build_experience(
                row,
                run=run,
                experiment=experiment,
                strategy=strategy,
                closes_at_decision=closes,
                engine_version=engine_version,
            )
            inserted = store.save_experience(payload)
            if inserted:
                created += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001 - a single bad row must not abort the ingest
            errors.append(f"{row.get('decision_id')}:{type(exc).__name__}:{exc}")
            skipped += 1
    return {"created": created, "skipped": skipped, "errors": errors[:20], "scanned": len(rows)}


@dataclass
class ExperienceQuery:
    strategy_id: str | None = None
    strategy_family: str | None = None
    instrument_id: str | None = None
    timeframe: str | None = None
    regime_key: str | None = None
    split: str | None = None
    strategy_version: int | None = None
    limit: int = 200
    offset: int = 0


__all__ = [
    "DecisionCaptureSink",
    "ExperienceQuery",
    "build_experience",
    "classify_outcome",
    "experience_id_for",
    "ingest_resolved_decisions",
]
