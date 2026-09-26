"""Governed trading dataset semantic classification and routing.

Owned by DatasetService — not a second DatasetStatus database.
Classification is persisted on dataset/version metadata with provenance.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class DatasetDomain(str, Enum):
    GENERAL = "GENERAL"
    TRADING = "TRADING"
    FINANCE = "FINANCE"
    OTHER = "OTHER"


class TradingDatasetKind(str, Enum):
    TRADING_KNOWLEDGE = "TRADING_KNOWLEDGE"
    MARKET_OHLCV = "MARKET_OHLCV"
    MARKET_TRADES = "MARKET_TRADES"
    MARKET_QUOTES = "MARKET_QUOTES"
    MARKET_ORDERBOOK = "MARKET_ORDERBOOK"
    FUNDAMENTALS = "FUNDAMENTALS"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    MACRO = "MACRO"
    NEWS = "NEWS"
    EARNINGS_TRANSCRIPTS = "EARNINGS_TRANSCRIPTS"
    FILINGS = "FILINGS"
    REFERENCE_DATA = "REFERENCE_DATA"
    EXECUTION_DATA = "EXECUTION_DATA"
    TRAJECTORY_DATA = "TRAJECTORY_DATA"
    TRIAL_DATA = "TRIAL_DATA"
    ALTERNATIVE_DATA = "ALTERNATIVE_DATA"
    UNKNOWN_TRADING = "UNKNOWN_TRADING"


class ClassificationMethod(str, Enum):
    DETERMINISTIC_HEURISTIC = "DETERMINISTIC_HEURISTIC"
    METADATA = "METADATA"
    OPERATOR_OVERRIDE = "OPERATOR_OVERRIDE"
    MODEL_ADVISORY = "MODEL_ADVISORY"
    BRIDGE_DECLARED = "BRIDGE_DECLARED"


class DatasetRouteTarget(str, Enum):
    KNOWLEDGE_INDEX = "KNOWLEDGE_INDEX"
    MARKET_SIM_INGEST = "MARKET_SIM_INGEST"
    STRUCTURED_PIT = "STRUCTURED_PIT"
    KNOWLEDGE_EVENT = "KNOWLEDGE_EVENT"
    TRAINING_BRIDGE = "TRAINING_BRIDGE"
    HOLD_OPERATOR = "HOLD_OPERATOR"


# Column name signals (lowercased).
_OHLCV_COLS = {"open", "high", "low", "close", "volume", "o", "h", "l", "c", "v", "adj_close", "adjclose"}
_TRADE_COLS = {"price", "qty", "quantity", "trade_id", "aggressor", "side", "size"}
_QUOTE_COLS = {"bid", "ask", "bid_size", "ask_size", "bidsize", "asksize", "bid_px", "ask_px"}
_ORDERBOOK_COLS = {"bid_levels", "ask_levels", "depth", "bids", "asks", "level", "order_id"}
_FUND_COLS = {"revenue", "eps", "ebitda", "net_income", "shares_outstanding", "market_cap", "pe_ratio"}
_CA_COLS = {"split_ratio", "dividend", "ex_date", "record_date", "action_type", "corporate_action"}
_MACRO_COLS = {"cpi", "gdp", "unemployment", "interest_rate", "fed_funds", "release_id"}
_TS_COLS = {"timestamp", "ts", "time", "datetime", "date", "open_time", "close_time"}

_KNOWLEDGE_NAME_RX = re.compile(
    r"(book|paper|research|strategy|microstructure|quant|risk.?manag|whitepaper|pdf|textbook)",
    re.I,
)
_OHLCV_NAME_RX = re.compile(r"(ohlc|ohlcv|bars?|candles?|kline|1m|5m|15m|1h|1d|daily|intraday)", re.I)
_TRADE_NAME_RX = re.compile(r"(trades?|ticks?|prints?|executions?)", re.I)
_QUOTE_NAME_RX = re.compile(r"(quotes?|nbbo|bbo|top.?of.?book)", re.I)
_ORDERBOOK_NAME_RX = re.compile(r"(orderbook|order.?book|lob|l2|l3|depth)", re.I)
_NEWS_NAME_RX = re.compile(r"(news|headline|press.?release)", re.I)
_FILING_NAME_RX = re.compile(r"(filing|10-?k|10-?q|8-?k|sec|edgar)", re.I)
_EARNINGS_NAME_RX = re.compile(r"(earnings|transcript|call.?transcript)", re.I)
_TRAJECTORY_NAME_RX = re.compile(r"(trajectory|gym.?run|trading.?trajectory)", re.I)
_TRIAL_NAME_RX = re.compile(r"(trial.?ledger|trials?|hpo.?trial)", re.I)
_FUND_NAME_RX = re.compile(r"(fundamental|financials?|balance.?sheet|income.?statement)", re.I)
_CA_NAME_RX = re.compile(r"(corporate.?action|split|dividend|delist)", re.I)
_MACRO_NAME_RX = re.compile(r"(macro|economic.?release|fomc|cpi|gdp)", re.I)

_TRADING_HINT_RX = re.compile(
    r"(trad(e|ing)|market|ohlc|equity|crypto|forex|futures?|option|portfolio|broker|exchange|ticker|symbol)",
    re.I,
)


@dataclass
class DatasetClassification:
    domain: DatasetDomain
    trading_kind: TradingDatasetKind | None
    confidence: float
    method: ClassificationMethod
    route: DatasetRouteTarget
    reasons: list[str] = field(default_factory=list)
    schema_columns: list[str] = field(default_factory=list)
    source_hash: str | None = None
    license: str | None = None
    quality_status: str = "UNMEASURED"
    operator_override: bool = False
    model_advisory: dict[str, Any] | None = None
    classified_at: str | None = None
    available_at_semantics: str = "unknown"
    truth: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "tradingKind": self.trading_kind.value if self.trading_kind else None,
            "confidence": self.confidence,
            "method": self.method.value,
            "route": self.route.value,
            "reasons": list(self.reasons),
            "schemaColumns": list(self.schema_columns),
            "sourceHash": self.source_hash,
            "license": self.license,
            "qualityStatus": self.quality_status,
            "operatorOverride": self.operator_override,
            "modelAdvisory": self.model_advisory,
            "classifiedAt": self.classified_at,
            "availableAtSemantics": self.available_at_semantics,
            "truth": {
                "classification_is_not_proof_of_quality": True,
                "model_assisted_is_advisory": True,
                "operator_override_supported": True,
                "wrong_pipeline_must_not_be_silent": True,
                **dict(self.truth),
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DatasetClassification | None":
        if not isinstance(data, dict) or not data.get("domain"):
            return None
        try:
            domain = DatasetDomain(str(data.get("domain")))
        except ValueError:
            return None
        kind_raw = data.get("tradingKind") or data.get("trading_kind")
        kind = None
        if kind_raw:
            try:
                kind = TradingDatasetKind(str(kind_raw))
            except ValueError:
                kind = TradingDatasetKind.UNKNOWN_TRADING
        method_raw = data.get("method") or ClassificationMethod.DETERMINISTIC_HEURISTIC.value
        try:
            method = ClassificationMethod(str(method_raw))
        except ValueError:
            method = ClassificationMethod.DETERMINISTIC_HEURISTIC
        route_raw = data.get("route")
        try:
            route = DatasetRouteTarget(str(route_raw)) if route_raw else route_for(domain, kind)
        except ValueError:
            route = route_for(domain, kind)
        return cls(
            domain=domain,
            trading_kind=kind,
            confidence=float(data.get("confidence") or 0.0),
            method=method,
            route=route,
            reasons=list(data.get("reasons") or []),
            schema_columns=list(data.get("schemaColumns") or data.get("schema_columns") or []),
            source_hash=data.get("sourceHash") or data.get("source_hash"),
            license=data.get("license"),
            quality_status=str(data.get("qualityStatus") or data.get("quality_status") or "UNMEASURED"),
            operator_override=bool(data.get("operatorOverride") or data.get("operator_override")),
            model_advisory=data.get("modelAdvisory") if isinstance(data.get("modelAdvisory"), dict) else None,
            classified_at=data.get("classifiedAt") or data.get("classified_at"),
            available_at_semantics=str(
                data.get("availableAtSemantics") or data.get("available_at_semantics") or "unknown"
            ),
            truth=dict(data.get("truth") or {}) if isinstance(data.get("truth"), dict) else {},
        )


def route_for(domain: DatasetDomain, kind: TradingDatasetKind | None) -> DatasetRouteTarget:
    if domain != DatasetDomain.TRADING and domain != DatasetDomain.FINANCE:
        return DatasetRouteTarget.KNOWLEDGE_INDEX
    if kind is None:
        return DatasetRouteTarget.HOLD_OPERATOR
    if kind == TradingDatasetKind.TRADING_KNOWLEDGE:
        return DatasetRouteTarget.KNOWLEDGE_INDEX
    if kind in {
        TradingDatasetKind.MARKET_OHLCV,
        TradingDatasetKind.MARKET_TRADES,
        TradingDatasetKind.MARKET_QUOTES,
        TradingDatasetKind.MARKET_ORDERBOOK,
    }:
        return DatasetRouteTarget.MARKET_SIM_INGEST
    if kind in {
        TradingDatasetKind.FUNDAMENTALS,
        TradingDatasetKind.CORPORATE_ACTIONS,
        TradingDatasetKind.MACRO,
        TradingDatasetKind.REFERENCE_DATA,
    }:
        return DatasetRouteTarget.STRUCTURED_PIT
    if kind in {
        TradingDatasetKind.NEWS,
        TradingDatasetKind.EARNINGS_TRANSCRIPTS,
        TradingDatasetKind.FILINGS,
    }:
        return DatasetRouteTarget.KNOWLEDGE_EVENT
    if kind in {
        TradingDatasetKind.TRAJECTORY_DATA,
        TradingDatasetKind.TRIAL_DATA,
        TradingDatasetKind.EXECUTION_DATA,
    }:
        return DatasetRouteTarget.TRAINING_BRIDGE
    return DatasetRouteTarget.HOLD_OPERATOR


def allows_knowledge_auto_index(classification: DatasetClassification | None) -> bool:
    """Whether DatasetService may auto-route this version into Knowledge RAG."""
    if classification is None:
        return True  # GENERAL / unclassified retain prior behavior
    if classification.domain == DatasetDomain.GENERAL:
        return True
    return classification.route in {
        DatasetRouteTarget.KNOWLEDGE_INDEX,
        DatasetRouteTarget.KNOWLEDGE_EVENT,
    }


def _normalize_cols(cols: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for c in cols:
        key = re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")
        if key:
            out.add(key)
    return out


def _sample_columns_from_path(path: Path, *, max_bytes: int = 256_000) -> list[str]:
    if not path.is_file():
        return []
    suffix = path.suffix.lower()
    try:
        if suffix in {".csv", ".tsv", ".txt"}:
            delim = "\t" if suffix == ".tsv" else ","
            with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                sample = fh.read(max_bytes)
            reader = csv.reader(sample.splitlines(), delimiter=delim)
            header = next(reader, None)
            return [str(h) for h in header] if header else []
        if suffix == ".jsonl":
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        return [str(k) for k in obj.keys()]
                    break
        if suffix == ".json":
            raw = path.read_bytes()[:max_bytes]
            obj = json.loads(raw.decode("utf-8", errors="replace"))
            if isinstance(obj, dict):
                if isinstance(obj.get("columns"), list):
                    return [str(c) for c in obj["columns"]]
                return [str(k) for k in obj.keys()]
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                return [str(k) for k in obj[0].keys()]
    except Exception:  # noqa: BLE001 — classification must fail soft
        return []
    return []


def _kind_from_columns(cols: set[str]) -> tuple[TradingDatasetKind | None, float, str]:
    has_ts = bool(cols & _TS_COLS) or "open_time" in cols
    ohlcv_hits = len(cols & _OHLCV_COLS)
    if has_ts and ohlcv_hits >= 4:
        return TradingDatasetKind.MARKET_OHLCV, 0.92, f"ohlcv_columns={ohlcv_hits}"
    if has_ts and len(cols & _ORDERBOOK_COLS) >= 2:
        return TradingDatasetKind.MARKET_ORDERBOOK, 0.88, "orderbook_columns"
    if has_ts and len(cols & _QUOTE_COLS) >= 2:
        return TradingDatasetKind.MARKET_QUOTES, 0.88, "quote_columns"
    if has_ts and len(cols & _TRADE_COLS) >= 2 and ohlcv_hits < 3:
        return TradingDatasetKind.MARKET_TRADES, 0.85, "trade_columns"
    if len(cols & _FUND_COLS) >= 2:
        return TradingDatasetKind.FUNDAMENTALS, 0.8, "fundamentals_columns"
    if len(cols & _CA_COLS) >= 2:
        return TradingDatasetKind.CORPORATE_ACTIONS, 0.8, "corporate_action_columns"
    if len(cols & _MACRO_COLS) >= 1:
        return TradingDatasetKind.MACRO, 0.75, "macro_columns"
    return None, 0.0, ""


def _kind_from_name(name: str) -> tuple[TradingDatasetKind | None, float, str]:
    checks = [
        (_TRAJECTORY_NAME_RX, TradingDatasetKind.TRAJECTORY_DATA, 0.9, "name_trajectory"),
        (_TRIAL_NAME_RX, TradingDatasetKind.TRIAL_DATA, 0.85, "name_trial"),
        (_ORDERBOOK_NAME_RX, TradingDatasetKind.MARKET_ORDERBOOK, 0.85, "name_orderbook"),
        (_QUOTE_NAME_RX, TradingDatasetKind.MARKET_QUOTES, 0.8, "name_quotes"),
        (_OHLCV_NAME_RX, TradingDatasetKind.MARKET_OHLCV, 0.8, "name_ohlcv"),
        (_TRADE_NAME_RX, TradingDatasetKind.MARKET_TRADES, 0.75, "name_trades"),
        (_EARNINGS_NAME_RX, TradingDatasetKind.EARNINGS_TRANSCRIPTS, 0.8, "name_earnings"),
        (_FILING_NAME_RX, TradingDatasetKind.FILINGS, 0.8, "name_filings"),
        (_NEWS_NAME_RX, TradingDatasetKind.NEWS, 0.75, "name_news"),
        (_FUND_NAME_RX, TradingDatasetKind.FUNDAMENTALS, 0.75, "name_fundamentals"),
        (_CA_NAME_RX, TradingDatasetKind.CORPORATE_ACTIONS, 0.75, "name_corporate_actions"),
        (_MACRO_NAME_RX, TradingDatasetKind.MACRO, 0.7, "name_macro"),
        (_KNOWLEDGE_NAME_RX, TradingDatasetKind.TRADING_KNOWLEDGE, 0.7, "name_knowledge"),
    ]
    for rx, kind, conf, reason in checks:
        if rx.search(name or ""):
            return kind, conf, reason
    return None, 0.0, ""


def classify_trading_dataset(
    *,
    name: str = "",
    filename: str | None = None,
    format_name: str | None = None,
    columns: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    source_path: str | Path | None = None,
    source_hash: str | None = None,
    license: str | None = None,
    model_advisory: dict[str, Any] | None = None,
    classified_at: str | None = None,
) -> DatasetClassification:
    """Deterministic classification with optional advisory model hint.

    Operator override is applied separately via ``apply_operator_override``.
    """
    meta = dict(metadata or {})
    prov = dict(provenance or {})
    reasons: list[str] = []

    # Bridge / prior declaration wins as METADATA unless operator override later.
    declared_domain = meta.get("domain") or meta.get("datasetDomain") or prov.get("domain")
    declared_kind = (
        meta.get("tradingKind")
        or meta.get("trading_kind")
        or meta.get("kind")
        or prov.get("tradingKind")
        or prov.get("kind")
    )
    if declared_domain or declared_kind:
        domain = DatasetDomain.GENERAL
        kind = None
        method = ClassificationMethod.METADATA
        conf = 0.95
        if str(declared_kind) in {"trading_trajectory", "TRAJECTORY_DATA"}:
            domain = DatasetDomain.TRADING
            kind = TradingDatasetKind.TRAJECTORY_DATA
            reasons.append("metadata_kind=trading_trajectory")
        elif declared_kind:
            try:
                kind = TradingDatasetKind(str(declared_kind))
                domain = DatasetDomain.TRADING
                reasons.append(f"metadata_trading_kind={kind.value}")
            except ValueError:
                if _TRADING_HINT_RX.search(str(declared_kind)):
                    domain = DatasetDomain.TRADING
                    kind = TradingDatasetKind.UNKNOWN_TRADING
                    reasons.append(f"metadata_kind_unknown={declared_kind}")
                    conf = 0.55
        if declared_domain:
            try:
                domain = DatasetDomain(str(declared_domain).upper())
                reasons.append(f"metadata_domain={domain.value}")
            except ValueError:
                pass
        if domain in {DatasetDomain.TRADING, DatasetDomain.FINANCE} or kind is not None:
            if kind is None and domain == DatasetDomain.TRADING:
                kind = TradingDatasetKind.UNKNOWN_TRADING
            return DatasetClassification(
                domain=domain,
                trading_kind=kind,
                confidence=conf,
                method=method if "metadata" in ",".join(reasons) or method else ClassificationMethod.BRIDGE_DECLARED,
                route=route_for(domain, kind),
                reasons=reasons or ["declared_metadata"],
                schema_columns=list(columns or []),
                source_hash=source_hash,
                license=license,
                classified_at=classified_at,
                available_at_semantics=_available_at_semantics(kind),
                model_advisory=model_advisory,
                truth={"primary_pipeline": route_for(domain, kind).value},
            )

    cols = _normalize_cols(columns or [])
    if not cols and source_path is not None:
        sampled = _sample_columns_from_path(Path(source_path))
        cols = _normalize_cols(sampled)
    schema_cols = sorted(cols)

    name_blob = " ".join(x for x in [name, filename or "", str(source_path or "")] if x)
    kind_c, conf_c, reason_c = _kind_from_columns(cols)
    kind_n, conf_n, reason_n = _kind_from_name(name_blob)

    kind = None
    conf = 0.0
    if kind_c and conf_c >= conf_n:
        kind, conf = kind_c, conf_c
        reasons.append(reason_c)
    elif kind_n:
        kind, conf = kind_n, conf_n
        reasons.append(reason_n)
        if kind_c and kind_c != kind_n:
            reasons.append(f"column_hint_conflict={kind_c.value}")

    trading_hint = bool(_TRADING_HINT_RX.search(name_blob)) or bool(cols & ({"symbol", "ticker", "venue"} | _OHLCV_COLS))
    textish = (format_name or "").lower() in {"md", "txt", "pdf", "docx", "html"} or bool(
        re.search(r"\.(pdf|md|txt|docx)$", name_blob, re.I)
    )

    if kind is None and trading_hint and textish:
        kind = TradingDatasetKind.TRADING_KNOWLEDGE
        conf = 0.65
        reasons.append("trading_text_knowledge_heuristic")

    if kind is None and trading_hint:
        kind = TradingDatasetKind.UNKNOWN_TRADING
        conf = 0.45
        reasons.append("trading_hint_without_schema")

    domain = DatasetDomain.GENERAL
    if kind is not None:
        domain = DatasetDomain.TRADING
    elif trading_hint:
        domain = DatasetDomain.FINANCE
        reasons.append("finance_hint_without_kind")
        conf = max(conf, 0.4)

    # Model advisory may boost confidence but never silently become authority.
    if model_advisory and isinstance(model_advisory, dict):
        adv_kind = model_advisory.get("tradingKind") or model_advisory.get("kind")
        adv_conf = float(model_advisory.get("confidence") or 0.0)
        if adv_kind and kind is None:
            try:
                kind = TradingDatasetKind(str(adv_kind))
                domain = DatasetDomain.TRADING
                conf = min(0.7, max(0.3, adv_conf))
                reasons.append("model_advisory_kind")
            except ValueError:
                reasons.append("model_advisory_unrecognized")
        elif adv_kind and kind is not None:
            reasons.append("model_advisory_recorded_not_authoritative")

    method = ClassificationMethod.DETERMINISTIC_HEURISTIC
    if model_advisory and "model_advisory_kind" in reasons:
        method = ClassificationMethod.MODEL_ADVISORY

    route = route_for(domain, kind)
    return DatasetClassification(
        domain=domain,
        trading_kind=kind,
        confidence=float(conf),
        method=method,
        route=route,
        reasons=reasons or ["default_general"],
        schema_columns=schema_cols,
        source_hash=source_hash,
        license=license,
        classified_at=classified_at,
        available_at_semantics=_available_at_semantics(kind),
        model_advisory=model_advisory,
        truth={"primary_pipeline": route.value},
    )


def _available_at_semantics(kind: TradingDatasetKind | None) -> str:
    if kind in {
        TradingDatasetKind.NEWS,
        TradingDatasetKind.EARNINGS_TRANSCRIPTS,
        TradingDatasetKind.FILINGS,
        TradingDatasetKind.FUNDAMENTALS,
        TradingDatasetKind.CORPORATE_ACTIONS,
        TradingDatasetKind.MACRO,
        TradingDatasetKind.MARKET_OHLCV,
        TradingDatasetKind.MARKET_TRADES,
        TradingDatasetKind.MARKET_QUOTES,
        TradingDatasetKind.MARKET_ORDERBOOK,
    }:
        return "requires_available_at"
    if kind == TradingDatasetKind.TRADING_KNOWLEDGE:
        return "may_be_timeless_if_explicit_reference"
    return "unknown"


def apply_operator_override(
    current: DatasetClassification | None,
    *,
    domain: DatasetDomain,
    trading_kind: TradingDatasetKind | None,
    reason: str = "",
    classified_at: str | None = None,
) -> DatasetClassification:
    base_reasons = list(current.reasons) if current else []
    if reason:
        base_reasons.append(f"operator:{reason}")
    else:
        base_reasons.append("operator_override")
    return DatasetClassification(
        domain=domain,
        trading_kind=trading_kind,
        confidence=1.0,
        method=ClassificationMethod.OPERATOR_OVERRIDE,
        route=route_for(domain, trading_kind),
        reasons=base_reasons,
        schema_columns=list(current.schema_columns) if current else [],
        source_hash=current.source_hash if current else None,
        license=current.license if current else None,
        quality_status=current.quality_status if current else "UNMEASURED",
        operator_override=True,
        model_advisory=current.model_advisory if current else None,
        classified_at=classified_at or (current.classified_at if current else None),
        available_at_semantics=_available_at_semantics(trading_kind),
        truth={
            "primary_pipeline": route_for(domain, trading_kind).value,
            "operator_override": True,
        },
    )
