"""Market data fetch adapter — runs Binance/Stooq I/O off the Control Plane."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from Data.modules.provider_io.clients import ProviderClientPool
from Data.modules.provider_io.credentials import ResolvedCredential
from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.policy import DeadlineBudget, ProviderPolicyRegistry
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import ProviderExecutionResult, ProviderRequest


CancelCheck = Callable[[], bool]


class MarketDataAdapter:
    name = "market_data"

    def execute(
        self,
        request: ProviderRequest,
        *,
        clients: ProviderClientPool,
        credential: ResolvedCredential,
        policy: ProviderPolicyRegistry,
        budget: DeadlineBudget,
        stream_store: ProviderStreamStore | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ProviderExecutionResult:
        del credential, stream_store
        payload = dict(request.payload or {})
        provider_id = str(payload.get("provider_id") or request.provider or "").strip()
        symbol = str(payload.get("symbol") or "").strip()
        timeframe = str(payload.get("timeframe") or "1d").strip()
        limit = int(payload.get("limit") or 500)
        start_ts = payload.get("start_ts")
        end_ts = payload.get("end_ts")
        markets_root = Path(str(payload.get("markets_root") or ""))
        if not provider_id or not symbol:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                "market.fetch requires provider_id and symbol",
                provider=provider_id or request.provider,
            )
        if not markets_root:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                "market.fetch requires markets_root reference",
                provider=provider_id,
            )
        budget.raise_if_exhausted()
        if cancel_check and cancel_check():
            raise ProviderError(
                ProviderErrorCode.EXECUTION_CANCELLED,
                "Cancelled before market fetch",
                provider=provider_id,
            )

        from Data.modules.market_sim.providers import default_registry
        from Data.modules.market_sim.providers.http_transport import HttpxTransport
        from Data.modules.market_sim.types import MarketSimError

        transport = HttpxTransport(clients.client(name="market_fetch"), provider=provider_id)
        registry = default_registry(
            markets_root,
            transport=transport,
            cancel_check=cancel_check,
        )
        try:
            result = registry.import_to_csv(
                provider_id,
                symbol,
                timeframe,
                markets_root,
                limit=limit,
                start_ts=str(start_ts) if start_ts else None,
                end_ts=str(end_ts) if end_ts else None,
            )
        except MarketSimError as exc:
            code = getattr(exc, "code", "")
            if code == "PROVIDER_RATE_LIMITED":
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_RATE_LIMITED,
                    str(exc),
                    provider=provider_id,
                    retryable=True,
                    http_status=429,
                    details={"market_code": code},
                ) from exc
            if code == "EXECUTION_CANCELLED":
                raise ProviderError(
                    ProviderErrorCode.EXECUTION_CANCELLED,
                    str(exc),
                    provider=provider_id,
                    retryable=False,
                ) from exc
            raise ProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE
                if code not in {"PROVIDER_UNKNOWN", "PROVIDER_EMPTY", "UNSUPPORTED_TIMEFRAME", "NETWORK_BLOCKED"}
                else ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                str(exc),
                provider=provider_id,
                retryable=False,
                details={"market_code": code},
            ) from exc
        # Touch policy so host/rate telemetry stays coherent for market fetches.
        _ = policy
        return ProviderExecutionResult(
            status="succeeded",
            structured=dict(result),
            provider=provider_id,
            finish_reason="stop",
            metadata={
                "capability": "market.fetch",
                "symbol": symbol,
                "timeframe": timeframe,
                "pagination": bool(result.get("pagination")),
                "bar_count": result.get("bar_count"),
                "license_state": result.get("license_state"),
            },
        )
