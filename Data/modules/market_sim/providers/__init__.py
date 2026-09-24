"""Market data providers — extensible adapters for historical + live paper feeds."""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_text

from ..ohlcv import load_ohlcv, validate_ohlcv_file
from ..types import Bar, MarketSimError


@dataclass
class ProviderStatus:
    provider_id: str
    reachable: bool
    authenticated: bool
    latency_ms: float | None
    detail: str
    license_note: str = ""
    data_kinds: list[str] = field(default_factory=lambda: ["ohlcv"])

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "reachable": self.reachable,
            "authenticated": self.authenticated,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "license_note": self.license_note,
            "data_kinds": self.data_kinds,
        }


class MarketDataProvider(ABC):
    provider_id: str
    license_note: str = ""

    @abstractmethod
    def ping(self) -> bool: ...

    @abstractmethod
    def status(self) -> ProviderStatus: ...

    @abstractmethod
    def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int = 500,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> list[Bar]: ...

    def fetch_quote(self, symbol: str) -> dict[str, Any] | None:
        return None


def _http_get(url: str, *, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "LeviathanMarketSim/1.0 (research; paper-only)"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


class CsvLocalProvider(MarketDataProvider):
    provider_id = "csv_local"
    license_note = "User-supplied local files; license is operator responsibility."

    def __init__(self, markets_root: Path) -> None:
        self.markets_root = Path(markets_root)

    def ping(self) -> bool:
        return self.markets_root.exists()

    def status(self) -> ProviderStatus:
        ok = self.ping()
        return ProviderStatus(
            provider_id=self.provider_id,
            reachable=ok,
            authenticated=False,
            latency_ms=0.0,
            detail="local filesystem" if ok else "markets_root missing",
            license_note=self.license_note,
        )

    def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int = 500,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> list[Bar]:
        candidates = list(self.markets_root.glob(f"{symbol}_{timeframe}.*"))
        candidates += list(self.markets_root.glob(f"**/{symbol}_{timeframe}.*"))
        if not candidates:
            raise MarketSimError("PROVIDER_NO_DATA", f"No local file for {symbol}_{timeframe}")
        path = candidates[0]
        bars = load_ohlcv(str(path), start_ts=start_ts, end_ts=end_ts)
        return bars[-limit:]


class BinancePublicProvider(MarketDataProvider):
    """Unauthenticated public klines via data-api.binance.vision (market-data only)."""

    provider_id = "binance_public"
    license_note = (
        "Binance public market data API (no key). Usage subject to Binance Terms. "
        "Not a brokerage; no authenticated trading endpoints used."
    )
    BASE = "https://data-api.binance.vision"

    INTERVAL_MAP = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1D": "1d",
        "1d": "1d",
    }

    def ping(self) -> bool:
        try:
            _http_get(f"{self.BASE}/api/v3/ping", timeout=8.0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> ProviderStatus:
        import time

        t0 = time.perf_counter()
        ok = False
        detail = "unreachable"
        try:
            _http_get(f"{self.BASE}/api/v3/ping", timeout=8.0)
            ok = True
            detail = "data-api.binance.vision reachable"
        except Exception as exc:  # noqa: BLE001
            detail = f"unreachable: {exc}"
        latency = (time.perf_counter() - t0) * 1000.0
        return ProviderStatus(
            provider_id=self.provider_id,
            reachable=ok,
            authenticated=False,
            latency_ms=round(latency, 1),
            detail=detail,
            license_note=self.license_note,
        )

    def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int = 500,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> list[Bar]:
        interval = self.INTERVAL_MAP.get(timeframe)
        if not interval:
            raise MarketSimError("UNSUPPORTED_TIMEFRAME", timeframe)
        params: dict[str, Any] = {
            "symbol": symbol.upper().replace("/", "").replace("-", ""),
            "interval": interval,
            "limit": min(max(limit, 1), 1000),
        }
        if start_ts:
            params["startTime"] = int(datetime.fromisoformat(start_ts.replace("Z", "+00:00")).timestamp() * 1000)
        if end_ts:
            params["endTime"] = int(datetime.fromisoformat(end_ts.replace("Z", "+00:00")).timestamp() * 1000)
        qs = urllib.parse.urlencode(params)
        url = f"{self.BASE}/api/v3/klines?{qs}"
        try:
            raw = _http_get(url, timeout=30.0)
        except urllib.error.HTTPError as exc:
            raise MarketSimError("PROVIDER_HTTP", f"Binance HTTP {exc.code}") from exc
        except Exception as exc:  # noqa: BLE001
            raise MarketSimError("PROVIDER_ERROR", str(exc)) from exc
        rows = json.loads(raw.decode("utf-8"))
        bars: list[Bar] = []
        for row in rows:
            open_ms = int(row[0])
            ts = datetime.fromtimestamp(open_ms / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")
            bars.append(
                Bar(
                    ts=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
        return bars

    def fetch_quote(self, symbol: str) -> dict[str, Any] | None:
        sym = symbol.upper().replace("/", "").replace("-", "")
        try:
            raw = _http_get(f"{self.BASE}/api/v3/ticker/price?symbol={sym}", timeout=10.0)
            data = json.loads(raw.decode("utf-8"))
            return {
                "symbol": data.get("symbol", sym),
                "price": float(data["price"]),
                "provider": self.provider_id,
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "delayed": False,
            }
        except Exception:  # noqa: BLE001
            return None


class StooqPublicProvider(MarketDataProvider):
    """Public daily equity CSV from Stooq (no API key)."""

    provider_id = "stooq_public"
    license_note = "Stooq public CSV download. Respect Stooq terms; research/paper use."

    def ping(self) -> bool:
        try:
            _http_get("https://stooq.com/q/d/l/?s=aapl.us&i=d", timeout=10.0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> ProviderStatus:
        import time

        t0 = time.perf_counter()
        ok = self.ping()
        return ProviderStatus(
            provider_id=self.provider_id,
            reachable=ok,
            authenticated=False,
            latency_ms=round((time.perf_counter() - t0) * 1000.0, 1),
            detail="stooq daily CSV" if ok else "unreachable",
            license_note=self.license_note,
        )

    def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int = 500,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> list[Bar]:
        if timeframe not in {"1D", "1d", "d"}:
            # Stooq free endpoint is daily; refuse claiming intraday
            raise MarketSimError(
                "UNSUPPORTED_TIMEFRAME",
                "Stooq public adapter supports daily bars only",
            )
        sym = symbol.lower()
        if not sym.endswith(".us"):
            sym = f"{sym}.us"
        url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(sym)}&i=d"
        try:
            raw = _http_get(url, timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            raise MarketSimError("PROVIDER_ERROR", str(exc)) from exc
        text = raw.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        bars: list[Bar] = []
        for row in reader:
            date = (row.get("Date") or row.get("date") or "").strip()
            if not date:
                continue
            ts = f"{date}T00:00:00+00:00"
            if start_ts and ts < start_ts:
                continue
            if end_ts and ts > end_ts:
                continue
            try:
                bars.append(
                    Bar(
                        ts=ts,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row.get("Volume") or 0),
                    )
                )
            except (KeyError, ValueError):
                continue
        return bars[-limit:]


@dataclass
class ProviderRegistry:
    providers: dict[str, MarketDataProvider] = field(default_factory=dict)

    def register(self, provider: MarketDataProvider) -> None:
        self.providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> MarketDataProvider:
        if provider_id not in self.providers:
            raise MarketSimError("PROVIDER_UNKNOWN", provider_id, http_status=404)
        return self.providers[provider_id]

    def status_all(self) -> list[dict[str, Any]]:
        out = []
        for p in self.providers.values():
            try:
                out.append(p.status().public_dict())
            except Exception as exc:  # noqa: BLE001
                out.append(
                    ProviderStatus(
                        provider_id=p.provider_id,
                        reachable=False,
                        authenticated=False,
                        latency_ms=None,
                        detail=str(exc),
                        license_note=getattr(p, "license_note", ""),
                    ).public_dict()
                )
        return out

    def import_to_csv(
        self,
        provider_id: str,
        symbol: str,
        timeframe: str,
        dest_dir: Path,
        *,
        limit: int = 500,
    ) -> dict[str, Any]:
        provider = self.get(provider_id)
        bars = provider.fetch_historical(symbol, timeframe, limit=limit)
        if not bars:
            raise MarketSimError("PROVIDER_EMPTY", f"{provider_id} returned no bars")
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{symbol.upper()}_{timeframe}.csv"
        path = dest_dir / fname
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for b in bars:
                w.writerow([b.ts, b.open, b.high, b.low, b.close, b.volume])
        content = path.read_text(encoding="utf-8")
        return {
            "path": str(path),
            "relative_path": fname,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "bar_count": len(bars),
            "content_hash": sha256_text(content),
            "provider_id": provider_id,
            "start_ts": bars[0].ts,
            "end_ts": bars[-1].ts,
            "license_note": provider.license_note,
            "kind": "ohlcv",
            "validation": validate_ohlcv_file(str(path)).public_dict(),
        }


def default_registry(markets_root: Path) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register(CsvLocalProvider(markets_root))
    reg.register(BinancePublicProvider())
    reg.register(StooqPublicProvider())
    return reg
