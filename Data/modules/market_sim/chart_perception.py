"""Deterministic server-side chart snapshot renderer + typed ChartObservation.

Renders from canonical OHLCV bars — never screenshots browser UI.
Chart observations are HYPOTHESES; numeric research perception remains primary.
No private Ollama/OpenAI clients. No editor vision. No order placement.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from Data.modules.common.hashing import sha256_bytes, sha256_text

from .epistemic import compare_ts
from .types import Bar, CausalityViolation, MarketSimError


CHART_RENDERER_VERSION = "chart_svg_v1"
CHART_OBSERVATION_SCHEMA_VERSION = "chart_observation-1"
MAX_CHART_BYTES = 512_000
MAX_BARS_RENDERED = 500


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _coerce_bar(raw: Any) -> Bar | None:
    if isinstance(raw, Bar):
        return raw
    if not isinstance(raw, Mapping):
        return None
    ts = str(raw.get("ts") or raw.get("timestamp") or raw.get("time") or "").strip()
    if not ts:
        return None
    try:
        return Bar(
            ts=ts,
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw.get("volume") or 0.0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _coerce_bars(raw_bars: Sequence[Any] | None) -> list[Bar]:
    out: list[Bar] = []
    for item in raw_bars or []:
        bar = _coerce_bar(item)
        if bar is not None:
            out.append(bar)
    return out


def _filter_window(
    bars: Sequence[Bar],
    *,
    as_of: str,
    start_ts: str,
    end_ts: str,
) -> list[Bar]:
    if compare_ts(end_ts, as_of) > 0:
        raise CausalityViolation(
            f"Chart render end_ts {end_ts} exceeds as_of {as_of}"
        )
    if compare_ts(start_ts, end_ts) > 0:
        raise MarketSimError(
            "INVALID_WINDOW",
            f"start_ts {start_ts} after end_ts {end_ts}",
            http_status=400,
        )
    visible: list[Bar] = []
    for bar in bars:
        if compare_ts(bar.ts, as_of) > 0:
            raise CausalityViolation(
                f"Chart render refused future bar {bar.ts} (as_of={as_of})"
            )
        if compare_ts(bar.ts, start_ts) < 0:
            continue
        if compare_ts(bar.ts, end_ts) > 0:
            continue
        visible.append(bar)
    return visible


def _escape_svg(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_ohlcv_svg(
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str,
    as_of: str,
    overlays: Mapping[str, Any] | None,
    style_version: str,
    width: int = 960,
    height: int = 540,
) -> bytes:
    """Minimal deterministic SVG candlestick chart — zero third-party deps."""
    pad_l, pad_r, pad_t, pad_b = 48, 16, 36, 48
    plot_w = max(1, width - pad_l - pad_r)
    plot_h = max(1, height - pad_t - pad_b)

    use = list(bars[-MAX_BARS_RENDERED:])
    if not use:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
            f'<rect width="100%" height="100%" fill="#0f1419"/>'
            f'<text x="{pad_l}" y="{pad_t}" fill="#9aa4b2" font-family="monospace" font-size="14">'
            f"{_escape_svg(symbol or 'UNKNOWN')} {_escape_svg(timeframe)} — no visible bars"
            f"</text></svg>"
        )
        return svg.encode("utf-8")

    highs = [b.high for b in use]
    lows = [b.low for b in use]
    ymin = min(lows)
    ymax = max(highs)
    if ymax <= ymin:
        ymax = ymin + 1.0
    y_span = ymax - ymin

    def y_at(price: float) -> float:
        return pad_t + (1.0 - (price - ymin) / y_span) * plot_h

    n = len(use)
    slot = plot_w / n
    body_w = max(1.0, min(12.0, slot * 0.6))

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" data-renderer="{CHART_RENDERER_VERSION}" '
        f'data-style="{_escape_svg(style_version)}">',
        '<rect width="100%" height="100%" fill="#0f1419"/>',
        f'<text x="{pad_l}" y="22" fill="#e7ecf3" font-family="monospace" font-size="14">'
        f"{_escape_svg(symbol or 'UNKNOWN')} · {_escape_svg(timeframe)} · as_of={_escape_svg(as_of)}"
        f"</text>",
        f'<text x="{pad_l}" y="{height - 16}" fill="#6b7280" font-family="monospace" font-size="11">'
        f"bars={n} · {_escape_svg(use[0].ts)} → {_escape_svg(use[-1].ts)} · advisory_only"
        f"</text>",
    ]

    # Grid lines
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = pad_t + frac * plot_h
        px = ymax - frac * y_span
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.2f}" x2="{width - pad_r}" y2="{y:.2f}" '
            f'stroke="#1f2937" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="4" y="{y + 4:.2f}" fill="#6b7280" font-family="monospace" font-size="10">'
            f"{px:.4g}</text>"
        )

    for i, bar in enumerate(use):
        cx = pad_l + (i + 0.5) * slot
        y_h = y_at(bar.high)
        y_l = y_at(bar.low)
        y_o = y_at(bar.open)
        y_c = y_at(bar.close)
        up = bar.close >= bar.open
        color = "#22c55e" if up else "#ef4444"
        parts.append(
            f'<line x1="{cx:.2f}" y1="{y_h:.2f}" x2="{cx:.2f}" y2="{y_l:.2f}" '
            f'stroke="{color}" stroke-width="1"/>'
        )
        top = min(y_o, y_c)
        bh = max(1.0, abs(y_c - y_o))
        parts.append(
            f'<rect x="{cx - body_w / 2:.2f}" y="{top:.2f}" width="{body_w:.2f}" height="{bh:.2f}" '
            f'fill="{color}" stroke="{color}"/>'
        )

    # Optional overlay markers (labels only — no fabricated levels)
    if overlays:
        label = overlays.get("label") or overlays.get("title")
        if label:
            parts.append(
                f'<text x="{width - pad_r - 8}" y="22" fill="#93c5fd" font-family="monospace" '
                f'font-size="11" text-anchor="end">{_escape_svg(str(label))}</text>'
            )
        # Deterministic SMA overlay if precomputed values supplied (never invent).
        sma = overlays.get("sma") or overlays.get("sma_values")
        if isinstance(sma, (list, tuple)) and len(sma) == n:
            path_pts: list[str] = []
            for i, val in enumerate(sma):
                try:
                    price = float(val)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
                cx = pad_l + (i + 0.5) * slot
                path_pts.append(f"{cx:.2f},{y_at(price):.2f}")
            if len(path_pts) >= 2:
                parts.append(
                    f'<polyline fill="none" stroke="#60a5fa" stroke-width="1.5" '
                    f'points="{" ".join(path_pts)}"/>'
                )

    parts.append("</svg>")
    data = "".join(parts).encode("utf-8")
    if len(data) > MAX_CHART_BYTES:
        # Bound size: re-render with fewer bars rather than truncate mid-tag.
        if len(use) > 50:
            return _render_ohlcv_svg(
                use[::2],
                symbol=symbol,
                timeframe=timeframe,
                as_of=as_of,
                overlays=overlays,
                style_version=style_version,
                width=width,
                height=height,
            )
        data = data[:MAX_CHART_BYTES]
    return data


@dataclass(frozen=True)
class ChartRenderResult:
    """Deterministic chart artifact payload ready for ArtifactStore."""

    bytes_data: bytes
    content_type: str
    render_spec_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def data(self) -> bytes:
        return self.bytes_data

    def public_dict(self) -> dict[str, Any]:
        return {
            "content_type": self.content_type,
            "render_spec_hash": self.render_spec_hash,
            "size_bytes": len(self.bytes_data),
            "metadata": dict(self.metadata),
            "truth": {
                "rendered_from_ohlcv": True,
                "not_browser_screenshot": True,
                "bounded_size": len(self.bytes_data) <= MAX_CHART_BYTES,
            },
        }


def render_chart_snapshot(
    *,
    bars: list[dict] | Sequence[Any] | None,
    symbol: str,
    timeframe: str,
    as_of: str,
    start_ts: str,
    end_ts: str,
    overlays: dict | None = None,
    style_version: str = "v1",
    dataset_id: str | None = None,
    dataset_version: str | None = None,
    dataset_hash: str | None = None,
    source_id: str | None = None,
) -> ChartRenderResult:
    """Render a deterministic SVG chart from canonical OHLCV (end_ts <= as_of)."""
    if not as_of:
        raise MarketSimError("INVALID_AS_OF", "as_of required for chart render")
    coerced = _coerce_bars(bars)
    window = _filter_window(coerced, as_of=as_of, start_ts=start_ts, end_ts=end_ts)
    overlay_spec = dict(overlays or {})

    identity = {
        "source_id": source_id or "",
        "dataset_id": dataset_id or "",
        "dataset_version": dataset_version or "",
        "dataset_hash": dataset_hash or "",
        "symbol": symbol,
        "timeframe": timeframe,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "as_of": as_of,
        "bar_count": len(window),
        "style_version": style_version,
        "overlay_spec": overlay_spec,
        "renderer_version": CHART_RENDERER_VERSION,
        # Include last/first bar hashes for identity stability without raw OHLCV dump.
        "first_ts": window[0].ts if window else "",
        "last_ts": window[-1].ts if window else "",
        "ohlcv_fingerprint": sha256_text(
            _canon(
                [
                    {
                        "ts": b.ts,
                        "o": b.open,
                        "h": b.high,
                        "l": b.low,
                        "c": b.close,
                        "v": b.volume,
                    }
                    for b in window
                ]
            )
        )
        if window
        else "",
    }
    render_spec_hash = sha256_text(_canon(identity))

    svg_bytes = _render_ohlcv_svg(
        window,
        symbol=symbol,
        timeframe=timeframe,
        as_of=as_of,
        overlays=overlay_spec,
        style_version=style_version,
    )
    if len(svg_bytes) > MAX_CHART_BYTES:
        svg_bytes = svg_bytes[:MAX_CHART_BYTES]

    content_hash = sha256_bytes(svg_bytes)
    metadata = {
        **identity,
        "content_hash": content_hash,
        "content_type": "image/svg+xml",
        "artifact_ready": True,
        "size_bytes": len(svg_bytes),
        "render_spec_hash": render_spec_hash,
    }
    return ChartRenderResult(
        bytes_data=svg_bytes,
        content_type="image/svg+xml",
        render_spec_hash=render_spec_hash,
        metadata=metadata,
    )


# --- ChartObservation (VLM hypothesis layer) ---------------------------------

_TREND_VISUAL = frozenset({"up", "down", "sideways", "unclear", "unknown"})
_VOL_VISUAL = frozenset({"low", "medium", "high", "expanding", "compressing", "unclear", "unknown"})
_BREAKOUT = frozenset(
    {
        "none",
        "breakout_up",
        "breakout_down",
        "failed_breakout_up",
        "failed_breakout_down",
        "unclear",
        "unknown",
    }
)


@dataclass
class ChartObservation:
    """Typed VLM chart observation — pattern labels are HYPOTHESES only."""

    observation_id: str
    chart_artifact_id: str
    symbol: str
    timeframe: str
    as_of: str
    visible_window: dict[str, Any]
    market_structure: str
    trend_visual: str
    volatility_visual: str
    compression_expansion: str
    breakout_or_failed_breakout: str
    support_resistance_candidates: list[dict[str, Any]]
    volume_pattern: str
    notable_pattern_candidates: list[str]
    uncertainty: float
    confidence: float
    rationale_summary: str
    evidence_refs: list[str]
    model_id: str
    model_revision: str
    render_spec_hash: str
    created_at: str
    schema_version: str = CHART_OBSERVATION_SCHEMA_VERSION

    def public_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "chart_artifact_id": self.chart_artifact_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "as_of": self.as_of,
            "visible_window": dict(self.visible_window),
            "market_structure": self.market_structure,
            "trend_visual": self.trend_visual,
            "volatility_visual": self.volatility_visual,
            "compression_expansion": self.compression_expansion,
            "breakout_or_failed_breakout": self.breakout_or_failed_breakout,
            "support_resistance_candidates": list(self.support_resistance_candidates),
            "volume_pattern": self.volume_pattern,
            "notable_pattern_candidates": list(self.notable_pattern_candidates),
            "uncertainty": self.uncertainty,
            "confidence": self.confidence,
            "rationale_summary": self.rationale_summary,
            "evidence_refs": list(self.evidence_refs),
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "render_spec_hash": self.render_spec_hash,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "truth": {
                "pattern_labels_are_hypotheses": True,
                "chart_advisory_only": True,
                "numeric_perception_is_primary": True,
                "never_silently_prefer_vlm": True,
            },
        }


def chart_observation_schema() -> dict[str, Any]:
    """Public JSON-ish schema for ChartObservation validation / prompts."""
    return {
        "schema_version": CHART_OBSERVATION_SCHEMA_VERSION,
        "type": "object",
        "required": [
            "observation_id",
            "chart_artifact_id",
            "symbol",
            "timeframe",
            "as_of",
            "visible_window",
            "market_structure",
            "trend_visual",
            "volatility_visual",
            "compression_expansion",
            "breakout_or_failed_breakout",
            "support_resistance_candidates",
            "volume_pattern",
            "notable_pattern_candidates",
            "uncertainty",
            "confidence",
            "rationale_summary",
            "evidence_refs",
            "model_id",
            "model_revision",
            "render_spec_hash",
            "created_at",
        ],
        "properties": {
            "observation_id": {"type": "string"},
            "chart_artifact_id": {"type": "string"},
            "symbol": {"type": "string"},
            "timeframe": {"type": "string"},
            "as_of": {"type": "string"},
            "visible_window": {
                "type": "object",
                "properties": {
                    "start_ts": {"type": "string"},
                    "end_ts": {"type": "string"},
                },
            },
            "market_structure": {"type": "string"},
            "trend_visual": {"type": "string", "enum": sorted(_TREND_VISUAL)},
            "volatility_visual": {"type": "string", "enum": sorted(_VOL_VISUAL)},
            "compression_expansion": {"type": "string"},
            "breakout_or_failed_breakout": {"type": "string", "enum": sorted(_BREAKOUT)},
            "support_resistance_candidates": {
                "type": "array",
                "items": {"type": "object"},
                "note": "HYPOTHESIS levels — not measured support/resistance",
            },
            "volume_pattern": {"type": "string"},
            "notable_pattern_candidates": {
                "type": "array",
                "items": {"type": "string"},
                "note": "HYPOTHESIS pattern labels",
            },
            "uncertainty": {"type": "number", "minimum": 0, "maximum": 1},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale_summary": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "model_id": {"type": "string"},
            "model_revision": {"type": "string"},
            "render_spec_hash": {"type": "string"},
            "created_at": {"type": "string"},
        },
        "truth": {
            "pattern_labels_are_hypotheses": True,
            "chart_advisory_only": True,
        },
    }


def _clip01(raw: Any, default: float = 0.5) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


def validate_chart_observation(raw: dict) -> ChartObservation:
    """Validate and normalize a raw dict into ChartObservation."""
    if not isinstance(raw, dict):
        raise MarketSimError("INVALID_CHART_OBSERVATION", "observation must be a dict")

    def req_str(key: str, *, allow_empty: bool = False) -> str:
        val = raw.get(key)
        if val is None:
            # Accept camelCase aliases
            camel = "".join(
                w.capitalize() if i else w for i, w in enumerate(key.split("_"))
            )
            # simpler: chartArtifactId style
            parts = key.split("_")
            camel = parts[0] + "".join(p.title() for p in parts[1:])
            val = raw.get(camel)
        if val is None or (not allow_empty and str(val).strip() == ""):
            raise MarketSimError(
                "INVALID_CHART_OBSERVATION",
                f"missing required field: {key}",
                http_status=422,
            )
        return str(val)

    trend = str(raw.get("trend_visual") or raw.get("trendVisual") or "unknown").lower()
    if trend not in _TREND_VISUAL:
        trend = "unknown"
    vol = str(raw.get("volatility_visual") or raw.get("volatilityVisual") or "unknown").lower()
    if vol not in _VOL_VISUAL:
        vol = "unknown"
    brk = str(
        raw.get("breakout_or_failed_breakout")
        or raw.get("breakoutOrFailedBreakout")
        or "unknown"
    ).lower()
    if brk not in _BREAKOUT:
        brk = "unknown"

    window_raw = raw.get("visible_window") or raw.get("visibleWindow") or {}
    if not isinstance(window_raw, dict):
        raise MarketSimError("INVALID_CHART_OBSERVATION", "visible_window must be object")

    sr = raw.get("support_resistance_candidates") or raw.get("supportResistanceCandidates") or []
    if not isinstance(sr, list):
        raise MarketSimError(
            "INVALID_CHART_OBSERVATION",
            "support_resistance_candidates must be a list",
        )
    patterns = raw.get("notable_pattern_candidates") or raw.get("notablePatternCandidates") or []
    if not isinstance(patterns, list):
        raise MarketSimError(
            "INVALID_CHART_OBSERVATION",
            "notable_pattern_candidates must be a list",
        )
    refs = raw.get("evidence_refs") or raw.get("evidenceRefs") or []
    if not isinstance(refs, list):
        raise MarketSimError("INVALID_CHART_OBSERVATION", "evidence_refs must be a list")

    obs_id = str(raw.get("observation_id") or raw.get("observationId") or "").strip()
    if not obs_id:
        obs_id = str(uuid.uuid4())

    return ChartObservation(
        observation_id=obs_id,
        chart_artifact_id=req_str("chart_artifact_id", allow_empty=True),
        symbol=req_str("symbol"),
        timeframe=req_str("timeframe", allow_empty=True),
        as_of=req_str("as_of"),
        visible_window={
            "start_ts": str(window_raw.get("start_ts") or window_raw.get("startTs") or ""),
            "end_ts": str(window_raw.get("end_ts") or window_raw.get("endTs") or ""),
            **{
                k: v
                for k, v in window_raw.items()
                if k not in {"start_ts", "end_ts", "startTs", "endTs"}
            },
        },
        market_structure=str(raw.get("market_structure") or raw.get("marketStructure") or "unknown"),
        trend_visual=trend,
        volatility_visual=vol,
        compression_expansion=str(
            raw.get("compression_expansion") or raw.get("compressionExpansion") or "unknown"
        ),
        breakout_or_failed_breakout=brk,
        support_resistance_candidates=[dict(x) if isinstance(x, dict) else {"label": str(x)} for x in sr],
        volume_pattern=str(raw.get("volume_pattern") or raw.get("volumePattern") or "unknown"),
        notable_pattern_candidates=[str(x) for x in patterns],
        uncertainty=_clip01(raw.get("uncertainty"), 0.5),
        confidence=_clip01(raw.get("confidence"), 0.5),
        rationale_summary=str(raw.get("rationale_summary") or raw.get("rationaleSummary") or ""),
        evidence_refs=[str(x) for x in refs],
        model_id=str(raw.get("model_id") or raw.get("modelId") or ""),
        model_revision=str(raw.get("model_revision") or raw.get("modelRevision") or ""),
        render_spec_hash=str(raw.get("render_spec_hash") or raw.get("renderSpecHash") or ""),
        created_at=str(raw.get("created_at") or raw.get("createdAt") or _utc_now()),
        schema_version=str(raw.get("schema_version") or CHART_OBSERVATION_SCHEMA_VERSION),
    )


def _numeric_trend_label(perception: Mapping[str, Any]) -> str | None:
    """Extract numeric trend direction from research perception public_dict."""
    trend = perception.get("trend")
    if isinstance(trend, Mapping):
        # MeasuredValue shape
        if "value" in trend:
            inner = trend.get("value")
            if isinstance(inner, Mapping):
                direction = inner.get("direction")
                if direction:
                    return str(direction).lower()
            if isinstance(inner, str):
                return inner.lower()
        direction = trend.get("direction")
        if direction:
            return str(direction).lower()
    # Nested market_state
    ms = perception.get("market_state")
    if isinstance(ms, Mapping):
        val = ms.get("value") if "value" in ms else ms
        if isinstance(val, Mapping):
            t = val.get("trend") or {}
            if isinstance(t, Mapping) and t.get("direction"):
                return str(t["direction"]).lower()
    return None


def _normalize_trend_for_compare(label: str | None) -> str | None:
    if not label:
        return None
    key = label.strip().lower()
    if key in {"up", "bull", "bullish", "uptrend", "rising"}:
        return "up"
    if key in {"down", "bear", "bearish", "downtrend", "falling"}:
        return "down"
    if key in {"flat", "sideways", "neutral", "range", "ranging"}:
        return "sideways"
    if key in {"unclear", "unknown"}:
        return None
    return key


def crosscheck_chart_vs_numeric(
    *,
    observation: ChartObservation,
    perception: dict,
) -> list[dict]:
    """Compare VLM chart hypotheses vs numeric perception; record CONFLICTS.

    Never silently prefers the VLM. Numeric perception remains primary.
    """
    findings: list[dict[str, Any]] = []
    if not isinstance(perception, dict):
        findings.append(
            {
                "kind": "UNAVAILABLE",
                "field": "perception",
                "detail": "perception must be a dict",
                "prefer": "numeric",
            }
        )
        return findings

    numeric_trend = _normalize_trend_for_compare(_numeric_trend_label(perception))
    visual_trend = _normalize_trend_for_compare(observation.trend_visual)

    if numeric_trend is None and visual_trend is None:
        findings.append(
            {
                "kind": "UNCOMPARED",
                "field": "trend",
                "detail": "both numeric and visual trend unmeasured/unclear",
                "prefer": "numeric",
            }
        )
    elif numeric_trend is None:
        findings.append(
            {
                "kind": "ADVISORY_ONLY",
                "field": "trend",
                "visual": visual_trend,
                "numeric": None,
                "detail": "visual trend present but numeric trend UNMEASURED — do not promote VLM",
                "prefer": "numeric",
            }
        )
    elif visual_trend is None:
        findings.append(
            {
                "kind": "OK",
                "field": "trend",
                "visual": None,
                "numeric": numeric_trend,
                "detail": "numeric trend available; visual unclear",
                "prefer": "numeric",
            }
        )
    elif numeric_trend != visual_trend:
        findings.append(
            {
                "kind": "CONFLICT",
                "field": "trend",
                "visual": visual_trend,
                "numeric": numeric_trend,
                "observation_trend_visual": observation.trend_visual,
                "detail": "VLM trend_visual disagrees with numeric trend — prefer numeric",
                "prefer": "numeric",
                "truth": {"never_silently_prefer_vlm": True},
            }
        )
    else:
        findings.append(
            {
                "kind": "AGREE",
                "field": "trend",
                "visual": visual_trend,
                "numeric": numeric_trend,
                "prefer": "numeric",
            }
        )

    findings.append(
        {
            "kind": "POLICY",
            "field": "*",
            "detail": "chart observations are advisory hypotheses; numeric perception is primary",
            "prefer": "numeric",
            "truth": {
                "chart_advisory_only": True,
                "never_silently_prefer_vlm": True,
            },
        }
    )
    return findings


def select_chart_capable_model(vision_profile: Any) -> tuple[str, Any]:
    """Select a chart-capable vision model.

    Requires visionProfile.charts == SUPPORTED (string compare).
    UNMEASURED is NOT SUPPORTED.
    Returns (\"AVAILABLE\", model_info) or (\"UNAVAILABLE\", reason).
    """
    profile: Mapping[str, Any]
    if vision_profile is None:
        return ("UNAVAILABLE", {"reason": "vision_profile_missing"})
    if hasattr(vision_profile, "public_dict") and callable(vision_profile.public_dict):
        profile = vision_profile.public_dict()
    elif isinstance(vision_profile, Mapping):
        # Nested visionProfile key common on capability payloads
        if "visionProfile" in vision_profile and isinstance(vision_profile["visionProfile"], Mapping):
            profile = vision_profile["visionProfile"]
        elif "vision_profile" in vision_profile and isinstance(vision_profile["vision_profile"], Mapping):
            profile = vision_profile["vision_profile"]
        else:
            profile = vision_profile
    else:
        return ("UNAVAILABLE", {"reason": "vision_profile_invalid_type"})

    charts_raw = profile.get("charts")
    charts = str(charts_raw).strip() if charts_raw is not None else ""
    # Strict string compare against SUPPORTED / supported — UNMEASURED fails.
    if charts not in {"SUPPORTED", "supported"}:
        return (
            "UNAVAILABLE",
            {
                "reason": "charts_not_supported",
                "charts": charts or None,
                "truth": {
                    "unmeasured_is_not_supported": True,
                    "required": "SUPPORTED",
                },
            },
        )

    model_info = {
        "charts": charts,
        "vision_profile": dict(profile),
        "status": "AVAILABLE",
    }
    # Pass through optional model identity if present on the profile payload.
    for key in ("model_id", "modelId", "model_revision", "modelRevision", "provider"):
        if key in profile:
            model_info[key] = profile[key]
    return ("AVAILABLE", model_info)


def store_chart_artifact(
    artifact_store: Any,
    render_result: ChartRenderResult,
    *,
    namespace: str = "trading.research.chart",
) -> str | None:
    """Persist chart bytes via ArtifactStore.create_from_bytes when available.

    Returns artifact_id or None when store is missing / unsupported.
    """
    if artifact_store is None:
        return None
    create = getattr(artifact_store, "create_from_bytes", None)
    if not callable(create):
        return None

    meta = dict(render_result.metadata or {})
    meta["namespace"] = namespace
    meta["render_spec_hash"] = render_result.render_spec_hash
    filename = f"chart_{render_result.render_spec_hash[:16]}.svg"
    try:
        record = create(
            data=render_result.bytes_data,
            artifact_type=namespace,
            producer="market_sim.chart_perception",
            filename=filename,
            metadata=meta,
        )
    except TypeError:
        # Some stores use positional / alternate kw names — best-effort.
        try:
            record = create(
                render_result.bytes_data,
                namespace,
                "market_sim.chart_perception",
                filename,
            )
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001
        return None

    if record is None:
        return None
    if isinstance(record, str):
        return record
    artifact_id = getattr(record, "artifact_id", None)
    if artifact_id:
        return str(artifact_id)
    if isinstance(record, Mapping) and record.get("artifact_id"):
        return str(record["artifact_id"])
    return None
