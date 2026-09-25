"""Market data providers — extensible adapters for historical + live paper feeds.

Remote network calls must run under provider_io workers in production.
Providers accept an injectable HttpTransport so Control Plane code never owns
the network loop. Pagination + backoff live here as domain fetch policy;
transport execution still occurs on the worker that supplied the transport.
"""

from __future__ import annotations

import csv
import io
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from Data.modules.common.hashing import sha256_text
from Data.modules.common.retry import RetryPolicy

from ..ohlcv import load_ohlcv, validate_ohlcv_file
from ..types import Bar, MarketSimError
from .http_transport import HttpTransport, UrllibTransport, request_with_retry


@dataclass
class ProviderStatus:
    provider_id: str
    reachable: bool
    authenticated: bool
    latency_ms: float | None
    detail: str
    license_note: str = ""
    license_state: str = "PUBLIC_TERMS_APPLY"
    data_kinds: list[str] = field(default_factory=lambda: ["ohlcv"])

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "reachable": self.reachable,
            "authenticated": self.authenticated,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "license_note": self.license_note,
            "license_state": self.license_state,
            "data_kinds": self.data_kinds,
        }


class MarketDataProvider(ABC):
    provider_id: str
    license_note: str = ""
    license_state: str = "PUBLIC_TERMS_APPLY"

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


def _parse_iso_ms(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
    seen: set[str] = set()
    out: list[Bar] = []
    for bar in bars:
        key = bar.ts
        if key in seen:
            continue
        seen.add(key)
        out.append(bar)
    out.sort(key=lambda b: b.ts)
    return out


class CsvLocalProvider(MarketDataProvider):
    provider_id = "csv_local"
    license_note = "User-supplied local files; license is operator responsibility."
    license_state = "OPERATOR_SUPPLIED"

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
            license_state=self.license_state,
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
        path = sorted(candidates)[0]
        bars = load_ohlcv(str(path), start_ts=start_ts, end_ts=end_ts)
        return bars[-limit:]


class BinancePublicProvider(MarketDataProvider):
    """Unauthenticated public klines via data-api.binance.vision (market-data only).

    Pagination: continues past the API's 1000-bar single-request ceiling until
    ``limit`` / ``end_ts`` is satisfied. No authenticated trading endpoints.
    """

    provider_id = "binance_public"
    license_note = (
        "Binance public market data API (no key). Usage subject to Binance Terms. "
        "Not a brokerage; no authenticated trading endpoints used."
    )
    license_state = "PUBLIC_TERMS_APPLY"
    BASE = "https://data-api.binance.vision"
    PAGE_SIZE = 1000

    INTERVAL_MAP = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1D": "1d",
        "1d": "1d",
    }

    INTERVAL_MS = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        retry: RetryPolicy | None = None,
        cancel_check: Any | None = None,
        allow_legacy_urllib: bool = False,
    ) -> None:
        if transport is None and not allow_legacy_urllib:
            # Domain default still constructs; MarketDataAdapter always injects worker transport.
            transport = UrllibTransport()
        self._transport = transport or UrllibTransport()
        self._retry = retry or RetryPolicy(max_attempts=4, base_seconds=0.5, max_seconds=30.0)
        self._cancel_check = cancel_check

    def _get(self, url: str, *, timeout: float = 30.0) -> bytes:
        resp = request_with_retry(
            self._transport,
            "GET",
            url,
            timeout=timeout,
            retry=self._retry,
            cancel_check=self._cancel_check,
        )
        return resp.body

    def ping(self) -> bool:
        try:
            self._get(f"{self.BASE}/api/v3/ping", timeout=8.0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> ProviderStatus:
        import time

        t0 = time.perf_counter()
        ok = False
        detail = "unreachable"
        try:
            self._get(f"{self.BASE}/api/v3/ping", timeout=8.0)
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
            license_state=self.license_state,
        )

    def _row_to_bar(self, row: list[Any]) -> Bar:
        open_ms = int(row[0])
        ts = datetime.fromtimestamp(open_ms / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")
        return Bar(
            ts=ts,
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
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
        """Paginated klines fetch — continues beyond the 1000-bar API ceiling."""
        interval = self.INTERVAL_MAP.get(timeframe)
        if not interval:
            raise MarketSimError("UNSUPPORTED_TIMEFRAME", timeframe)
        want = max(1, int(limit))
        sym = symbol.upper().replace("/", "").replace("-", "")
        end_ms = _parse_iso_ms(end_ts) if end_ts else None
        start_ms = _parse_iso_ms(start_ts) if start_ts else None

        # Pagination cursor: walk forward from startTime (or backward from end when only end set).
        collected: list[Bar] = []
        cursor_start = start_ms
        pages = 0
        max_pages = max(1, (want + self.PAGE_SIZE - 1) // self.PAGE_SIZE) + 2

        while len(collected) < want and pages < max_pages:
            pages += 1
            page_limit = min(self.PAGE_SIZE, want - len(collected))
            params: dict[str, Any] = {
                "symbol": sym,
                "interval": interval,
                "limit": page_limit if page_limit > 0 else self.PAGE_SIZE,
            }
            if cursor_start is not None:
                params["startTime"] = cursor_start
            if end_ms is not None:
                params["endTime"] = end_ms
            url = f"{self.BASE}/api/v3/klines?{urlencode(params)}"
            raw = self._get(url, timeout=30.0)
            rows = json.loads(raw.decode("utf-8"))
            if not isinstance(rows, list) or not rows:
                break
            page_bars = [self._row_to_bar(row) for row in rows]
            collected.extend(page_bars)
            collected = _dedupe_bars(collected)
            last_open_ms = int(rows[-1][0])
            step = self.INTERVAL_MS.get(interval, 60_000)
            next_start = last_open_ms + step
            if cursor_start is not None and next_start <= cursor_start:
                break
            cursor_start = next_start
            if end_ms is not None and cursor_start > end_ms:
                break
            if len(rows) < page_limit:
                break
            if self._cancel_check and self._cancel_check():
                raise MarketSimError("EXECUTION_CANCELLED", "Cancelled during pagination", http_status=499)

        if end_ts:
            collected = [b for b in collected if b.ts <= end_ts.replace("Z", "+00:00") or b.ts <= end_ts]
        if start_ts:
            collected = [b for b in collected if b.ts >= start_ts.replace("Z", "+00:00") or b.ts >= start_ts]
        return _dedupe_bars(collected)[:want] if start_ms is None and end_ms is None else _dedupe_bars(collected)[-want:]

    def fetch_quote(self, symbol: str) -> dict[str, Any] | None:
        sym = symbol.upper().replace("/", "").replace("-", "")
        try:
            raw = self._get(f"{self.BASE}/api/v3/ticker/price?symbol={sym}", timeout=10.0)
            data = json.loads(raw.decode("utf-8"))
            received_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return {
                "symbol": data.get("symbol", sym),
                "price": float(data["price"]),
                "provider": self.provider_id,
                "ts": received_at,
                "exchange_ts": None,  # ticker/price does not supply venue time
                "received_at": received_at,
                "available_at": received_at,
                "delayed": False,
                "license_state": self.license_state,
                "truth": {
                    "last_price_only": True,
                    "not_bid_ask": True,
                    "not_orderbook": True,
                },
            }
        except Exception:  # noqa: BLE001
            return None


class StooqPublicProvider(MarketDataProvider):
    """Public daily equity CSV from Stooq (no API key)."""

    provider_id = "stooq_public"
    license_note = "Stooq public CSV download. Respect Stooq terms; research/paper use."
    license_state = "PUBLIC_TERMS_APPLY"

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        retry: RetryPolicy | None = None,
        cancel_check: Any | None = None,
        allow_legacy_urllib: bool = False,
    ) -> None:
        self._transport = transport or UrllibTransport()
        self._retry = retry or RetryPolicy(max_attempts=4, base_seconds=0.5, max_seconds=30.0)
        self._cancel_check = cancel_check
        del allow_legacy_urllib

    def _get(self, url: str, *, timeout: float = 30.0) -> bytes:
        resp = request_with_retry(
            self._transport,
            "GET",
            url,
            timeout=timeout,
            retry=self._retry,
            cancel_check=self._cancel_check,
        )
        return resp.body

    def ping(self) -> bool:
        try:
            self._get("https://stooq.com/q/d/l/?s=aapl.us&i=d", timeout=10.0)
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
            license_state=self.license_state,
            data_kinds=["ohlcv_daily"],
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
            raise MarketSimError(
                "UNSUPPORTED_TIMEFRAME",
                "Stooq public adapter supports daily bars only",
            )
        sym = symbol.lower()
        if not sym.endswith(".us"):
            sym = f"{sym}.us"
        from urllib.parse import quote

        url = f"https://stooq.com/q/d/l/?s={quote(sym)}&i=d"
        raw = self._get(url, timeout=30.0)
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
    transport: HttpTransport | None = None
    cancel_check: Any | None = None

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
                        license_state=getattr(p, "license_state", "UNKNOWN"),
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
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> dict[str, Any]:
        provider = self.get(provider_id)
        bars = provider.fetch_historical(
            symbol, timeframe, limit=limit, start_ts=start_ts, end_ts=end_ts
        )
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
            "license_state": getattr(provider, "license_state", "PUBLIC_TERMS_APPLY"),
            "kind": "ohlcv",
            "validation": validate_ohlcv_file(str(path)).public_dict(),
            "pagination": True if provider_id == "binance_public" else False,
        }


def default_registry(
    markets_root: Path,
    *,
    transport: HttpTransport | None = None,
    cancel_check: Any | None = None,
) -> ProviderRegistry:
    reg = ProviderRegistry(transport=transport, cancel_check=cancel_check)
    reg.register(CsvLocalProvider(markets_root))
    kwargs: dict[str, Any] = {"cancel_check": cancel_check}
    if transport is not None:
        kwargs["transport"] = transport
    else:
        kwargs["allow_legacy_urllib"] = True
    reg.register(BinancePublicProvider(**kwargs))
    reg.register(StooqPublicProvider(**kwargs))
    return reg
