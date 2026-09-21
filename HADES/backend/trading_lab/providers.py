"""Market data providers.

Every provider answers the same three questions before it is used: is it configured, is it
reachable, and what is the licence of what it returns. A provider that is missing credentials
says so plainly instead of silently returning nothing or falling back to invented data.

Shipped providers:

- ``csv_import`` — always available, the honest default. You supply the file.
- ``synthetic`` — clearly labelled generated data for smoke tests. Every dataset created this
  way carries ``is_synthetic=True`` and the UI is required to show it.
- ``binance_public`` / ``coingecko_public`` — optional public HTTP endpoints, disabled unless
  the operator turns networking on. They fail cleanly to "unavailable offline".
- ``stooq_public`` — optional public daily equity/index history over HTTP.

There is no paid vendor adapter with a hardcoded key, and no adapter pretends to deliver
survivorship-bias-free point-in-time fundamentals. Those remain openly missing.
"""

from __future__ import annotations

import csv
import io
import json
import math
import random
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from trading_lab.calendars import get_calendar, timeframe_seconds

DEFAULT_TIMEOUT = 20


@dataclass
class ProviderStatus:
    provider_id: str
    name: str
    kind: str
    configured: bool
    reachable: bool | None
    licence: str
    coverage: str
    requires_network: bool
    missing_requirements: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def usable(self) -> bool:
        """Usable now, with the current settings. Missing requirements always win."""
        return self.configured and not self.missing_requirements and self.reachable is not False

    @property
    def reason(self) -> str:
        if self.usable:
            return self.detail or f"available; licence: {self.licence}"
        if self.missing_requirements:
            return "missing: " + "; ".join(self.missing_requirements)
        if self.reachable is False:
            return self.detail or "unreachable"
        return self.detail or "not configured"

    def as_json(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "kind": self.kind,
            "configured": self.configured,
            "reachable": self.reachable,
            "usable": self.usable,
            "reason": self.reason,
            "licence": self.licence,
            "coverage": self.coverage,
            "requires_network": self.requires_network,
            "missing_requirements": list(self.missing_requirements),
            "detail": self.detail,
        }


class ProviderError(RuntimeError):
    pass


class MarketDataProvider:
    provider_id = "base"
    name = "base"
    kind = "import"
    requires_network = False
    licence = "unspecified"
    coverage = ""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = dict(settings or {})

    @property
    def network_enabled(self) -> bool:
        return bool(self.settings.get("allow_network", False))

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            name=self.name,
            kind=self.kind,
            configured=True,
            reachable=None,
            licence=self.licence,
            coverage=self.coverage,
            requires_network=self.requires_network,
        )

    def fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str | None,
        end: str | None,
        limit: int = 5000,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raise NotImplementedError


class CsvImportProvider(MarketDataProvider):
    provider_id = "csv_import"
    name = "CSV / text import"
    kind = "import"
    licence = "operator supplied"
    coverage = "whatever you import; no built-in history"

    def parse(self, text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        stripped = text.lstrip()
        if stripped.startswith("[") or stripped.startswith("{"):
            return self._parse_json(stripped)
        return self._parse_csv(text)

    @staticmethod
    def _parse_json(text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        payload = json.loads(text)
        if isinstance(payload, dict):
            for key in ("rows", "data", "candles", "bars", "result"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
            else:
                raise ProviderError("json_import_needs_a_list_or_a_rows_key")
        rows: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(item)
            elif isinstance(item, (list, tuple)) and len(item) >= 5:
                rows.append(
                    {
                        "timestamp": item[0],
                        "open": item[1],
                        "high": item[2],
                        "low": item[3],
                        "close": item[4],
                        "volume": item[5] if len(item) > 5 else 0,
                    }
                )
        return rows, {"format": "json", "rows": len(rows)}

    @staticmethod
    def _parse_csv(text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if not reader.fieldnames:
            raise ProviderError("csv_has_no_header_row")
        rows = [dict(row) for row in reader]
        return rows, {"format": "csv", "delimiter": delimiter, "columns": reader.fieldnames, "rows": len(rows)}


class SyntheticProvider(MarketDataProvider):
    provider_id = "synthetic"
    name = "Synthetic generator"
    kind = "synthetic"
    licence = "generated locally — not market data"
    coverage = "any window you ask for, none of it real"

    def fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str | None,
        end: str | None,
        limit: int = 5000,
        seed: int | None = None,
        regime: str = "mixed",
        start_price: float = 100.0,
        calendar_id: str = "24x7",
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        step = timeframe_seconds(timeframe)
        begin = datetime.fromisoformat(start) if start else datetime.now(tz=UTC) - timedelta(seconds=step * limit)
        if begin.tzinfo is None:
            begin = begin.replace(tzinfo=UTC)
        finish = datetime.fromisoformat(end) if end else begin + timedelta(seconds=step * limit)
        if finish.tzinfo is None:
            finish = finish.replace(tzinfo=UTC)
        calendar = get_calendar(calendar_id)
        rng = random.Random(seed if seed is not None else 20240101)
        rows: list[dict[str, Any]] = []
        price = float(start_price)
        moment = begin
        drift_per_step = {"bull": 0.0004, "bear": -0.0004, "flat": 0.0, "mixed": 0.0}.get(regime, 0.0)
        volatility = {"bull": 0.008, "bear": 0.012, "flat": 0.003, "mixed": 0.01}.get(regime, 0.01)
        index = 0
        while moment < finish and len(rows) < limit:
            if calendar.is_open(moment):
                drift = drift_per_step
                if regime == "mixed":
                    cycle = math.sin(index / 180.0)
                    drift = 0.0006 * cycle
                shock = rng.gauss(drift, volatility)
                open_price = price
                close_price = max(0.01, price * (1.0 + shock))
                high = max(open_price, close_price) * (1.0 + abs(rng.gauss(0, volatility / 3)))
                low = min(open_price, close_price) * (1.0 - abs(rng.gauss(0, volatility / 3)))
                rows.append(
                    {
                        "timestamp": moment.isoformat().replace("+00:00", "Z"),
                        "open": round(open_price, 6),
                        "high": round(high, 6),
                        "low": round(max(0.005, low), 6),
                        "close": round(close_price, 6),
                        "volume": round(abs(rng.gauss(1000, 250)), 4),
                    }
                )
                price = close_price
                index += 1
            moment = moment + timedelta(seconds=step)
        return rows, {
            "synthetic": True,
            "seed": seed if seed is not None else 20240101,
            "regime": regime,
            "warning": "generated data — results from it say nothing about real markets",
        }


class _HttpProvider(MarketDataProvider):
    requires_network = True

    def _get(self, url: str) -> Any:
        if not self.network_enabled:
            raise ProviderError(
                f"network_disabled: {self.provider_id} needs outbound HTTP. Enable it in Trading Lab settings; "
                "HADES keeps networking off by default."
            )
        request = urllib.request.Request(url, headers={"User-Agent": "HADES-TradingLab/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"http_error:{exc.code} from {self.provider_id}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"unreachable:{self.provider_id}:{exc.reason}") from exc
        except OSError as exc:
            raise ProviderError(f"network_failure:{self.provider_id}:{exc}") from exc
        return body

    def status(self) -> ProviderStatus:
        base = super().status()
        base.configured = self.network_enabled
        if not self.network_enabled:
            base.missing_requirements = ["allow_network=true in Trading Lab settings"]
            base.detail = "offline by design; enable networking to use this provider"
        return base


class BinancePublicProvider(_HttpProvider):
    provider_id = "binance_public"
    name = "Binance public klines"
    kind = "download"
    licence = "public endpoint, subject to the venue's terms; verify before redistribution"
    coverage = "crypto spot and perpetual OHLCV, roughly 2017 to present"

    _INTERVALS = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
        "1w": "1w",
    }

    def fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str | None,
        end: str | None,
        limit: int = 5000,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        interval = self._INTERVALS.get(timeframe)
        if interval is None:
            raise ProviderError(f"unsupported_timeframe_for_binance:{timeframe}")
        market = symbol.replace("/", "").replace("-", "").upper()
        rows: list[dict[str, Any]] = []
        cursor = int(datetime.fromisoformat(start).timestamp() * 1000) if start else None
        stop = int(datetime.fromisoformat(end).timestamp() * 1000) if end else None
        pages = 0
        while len(rows) < limit and pages < 40:
            params = {"symbol": market, "interval": interval, "limit": str(min(1000, limit - len(rows)))}
            if cursor is not None:
                params["startTime"] = str(cursor)
            if stop is not None:
                params["endTime"] = str(stop)
            url = "https://api.binance.com/api/v3/klines?" + urllib.parse.urlencode(params)
            payload = json.loads(self._get(url))
            if not payload:
                break
            for item in payload:
                open_ms = int(item[0])
                rows.append(
                    {
                        "timestamp": datetime.fromtimestamp(open_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z"),
                        "open": item[1],
                        "high": item[2],
                        "low": item[3],
                        "close": item[4],
                        "volume": item[5],
                    }
                )
            cursor = int(payload[-1][0]) + 1
            pages += 1
            if len(payload) < 1000:
                break
        return rows, {"provider": self.provider_id, "market": market, "interval": interval, "pages": pages}


class StooqPublicProvider(_HttpProvider):
    provider_id = "stooq_public"
    name = "Stooq daily history"
    kind = "download"
    licence = "public endpoint for personal use; check the terms before redistribution"
    coverage = "daily equity, index and FX history, often back to the 1990s or 2000s"

    def fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str | None,
        end: str | None,
        limit: int = 20000,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if timeframe not in {"1d", "1w", "1mo"}:
            raise ProviderError(f"stooq_supports_daily_and_coarser_only:{timeframe}")
        interval = {"1d": "d", "1w": "w", "1mo": "m"}[timeframe]
        ticker = symbol.lower().replace("/", "").replace(":", "")
        url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(ticker)}&i={interval}"
        body = self._get(url)
        if body.strip().lower().startswith("<"):
            raise ProviderError("stooq_returned_html: the symbol is probably unknown to this endpoint")
        reader = csv.DictReader(io.StringIO(body))
        rows: list[dict[str, Any]] = []
        for row in reader:
            if not row.get("Date"):
                continue
            rows.append(
                {
                    "timestamp": f"{row['Date']}T00:00:00Z",
                    "open": row.get("Open"),
                    "high": row.get("High"),
                    "low": row.get("Low"),
                    "close": row.get("Close"),
                    "volume": row.get("Volume") or 0,
                }
            )
        if start:
            rows = [row for row in rows if row["timestamp"] >= start]
        if end:
            rows = [row for row in rows if row["timestamp"] <= end]
        return rows[:limit], {"provider": self.provider_id, "ticker": ticker, "interval": interval}


class CoinGeckoPublicProvider(_HttpProvider):
    provider_id = "coingecko_public"
    name = "CoinGecko daily OHLC"
    kind = "download"
    licence = "public demo endpoint with rate limits; attribution required"
    coverage = "daily crypto OHLC; the free tier caps the lookback window"

    def fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str | None,
        end: str | None,
        limit: int = 3650,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if timeframe != "1d":
            raise ProviderError(f"coingecko_adapter_supports_1d_only:{timeframe}")
        coin = (self.settings.get("coingecko_ids") or {}).get(symbol.upper()) or symbol.lower().split("/")[0]
        vs_currency = symbol.split("/")[-1].lower() if "/" in symbol else "usd"
        days = str(min(3650, max(1, limit)))
        url = (
            f"https://api.coingecko.com/api/v3/coins/{urllib.parse.quote(coin)}/ohlc"
            f"?vs_currency={urllib.parse.quote(vs_currency)}&days={days}"
        )
        payload = json.loads(self._get(url))
        rows = [
            {
                "timestamp": datetime.fromtimestamp(int(item[0]) / 1000, tz=UTC).isoformat().replace("+00:00", "Z"),
                "open": item[1],
                "high": item[2],
                "low": item[3],
                "close": item[4],
                "volume": 0,
            }
            for item in payload
        ]
        return rows, {
            "provider": self.provider_id,
            "coin": coin,
            "volume_missing": True,
            "warning": "this endpoint returns no volume, so participation limits fall back to unrestricted fills",
        }


PROVIDER_CLASSES: dict[str, type[MarketDataProvider]] = {
    CsvImportProvider.provider_id: CsvImportProvider,
    SyntheticProvider.provider_id: SyntheticProvider,
    BinancePublicProvider.provider_id: BinancePublicProvider,
    StooqPublicProvider.provider_id: StooqPublicProvider,
    CoinGeckoPublicProvider.provider_id: CoinGeckoPublicProvider,
}


# Data that a serious research desk would have and this installation does not. Stated once,
# here, so the UI and the reports can quote it instead of quietly leaving gaps.
KNOWN_DATA_GAPS: list[dict[str, str]] = [
    {
        "area": "corporate actions",
        "missing": "a licensed split, dividend and symbol-change history",
        "consequence": "equity backtests are only correct for instruments whose actions you import yourself",
    },
    {
        "area": "point-in-time index membership",
        "missing": "historical constituent lists with add/remove dates",
        "consequence": "any universe built from today's members carries survivorship bias; the registry can store membership but ships none",
    },
    {
        "area": "options",
        "missing": "historical option chains with implied volatility and greeks",
        "consequence": "the option_volatility family cannot run on real data; the pricing and greeks code is exercised on imported or synthetic input only",
    },
    {
        "area": "order book",
        "missing": "level-2 depth and full quote tape",
        "consequence": "market making and queue-position-sensitive execution research is blocked by design rather than approximated",
    },
    {
        "area": "funding and borrow",
        "missing": "historical perpetual funding rates and stock borrow fees",
        "consequence": "carry strategies report missing_funding_data; borrow cost falls back to the instrument's configured annual rate",
    },
    {
        "area": "fundamentals and estimates",
        "missing": "point-in-time financial statements and analyst estimates",
        "consequence": "no fundamental factor research is possible in this installation",
    },
]


def build_provider(provider_id: str, settings: dict[str, Any] | None = None) -> MarketDataProvider:
    cls = PROVIDER_CLASSES.get(provider_id)
    if cls is None:
        raise ProviderError(f"unknown_provider:{provider_id}")
    return cls(settings)


def provider_statuses(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [build_provider(provider_id, settings).status().as_json() for provider_id in PROVIDER_CLASSES]


__all__ = [
    "BinancePublicProvider",
    "CoinGeckoPublicProvider",
    "CsvImportProvider",
    "KNOWN_DATA_GAPS",
    "MarketDataProvider",
    "PROVIDER_CLASSES",
    "ProviderError",
    "ProviderStatus",
    "StooqPublicProvider",
    "SyntheticProvider",
    "build_provider",
    "provider_statuses",
]
