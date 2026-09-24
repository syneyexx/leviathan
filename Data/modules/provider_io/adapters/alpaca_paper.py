"""Alpaca paper trading adapter — remote HTTP owned by provider_io workers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from Data.modules.provider_io.clients import ProviderClientPool
from Data.modules.provider_io.credentials import ResolvedCredential
from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.policy import DeadlineBudget, ProviderPolicyRegistry
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import ProviderExecutionResult, ProviderRequest


CancelCheck = Callable[[], bool]
PAPER_BASE = "https://paper-api.alpaca.markets"


def _resolve_alpaca_headers(credential: ResolvedCredential) -> dict[str, str]:
    key_id = None
    secret = None
    if credential.headers:
        key_id = credential.headers.get("APCA-API-KEY-ID")
        secret = credential.headers.get("APCA-API-SECRET-KEY")
    if credential.extra:
        key_id = key_id or credential.extra.get("key_id")
        secret = secret or credential.extra.get("secret")
    if not key_id:
        key_id = (
            (os.environ.get("LEVIATHAN_ALPACA_PAPER_KEY_ID") or "").strip()
            or (os.environ.get("ALPACA_API_KEY") or "").strip()
            or (os.environ.get("ALPACA_API_KEY_ID") or "").strip()
        )
    if not secret:
        secret = (
            (os.environ.get("LEVIATHAN_ALPACA_PAPER_SECRET") or "").strip()
            or (os.environ.get("ALPACA_API_SECRET") or "").strip()
            or (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
        )
    if not key_id or not secret:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_NOT_CONFIGURED,
            "Alpaca paper credentials not configured",
            provider="alpaca_paper",
            http_status=503,
        )
    return {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret,
        "Content-Type": "application/json",
    }


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        snippet = ""
        try:
            snippet = exc.read().decode()[:500]
        except Exception:  # noqa: BLE001
            pass
        if exc.code in (401, 403):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_AUTH_FAILED,
                f"Alpaca auth failed (HTTP {exc.code})",
                provider="alpaca_paper",
                http_status=exc.code,
                details={"body": snippet},
            ) from exc
        if exc.code == 429:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RATE_LIMITED,
                "Alpaca rate limited",
                provider="alpaca_paper",
                retryable=True,
                http_status=429,
            ) from exc
        if 500 <= exc.code <= 599:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
                f"Alpaca upstream error (HTTP {exc.code})",
                provider="alpaca_paper",
                retryable=True,
                http_status=exc.code,
            ) from exc
        raise ProviderError(
            ProviderErrorCode.PROVIDER_INVALID_REQUEST,
            f"Alpaca rejected request (HTTP {exc.code})",
            provider="alpaca_paper",
            http_status=exc.code,
            details={"body": snippet},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            f"Alpaca connection error: {exc}",
            provider="alpaca_paper",
            retryable=True,
        ) from exc


class AlpacaPaperAdapter:
    name = "alpaca_paper"

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
        del clients, policy, stream_store
        payload = dict(request.payload or {})
        action = str(
            payload.get("action") or request.capability.replace("alpaca.paper", "").strip(".") or "account"
        ).strip().lower()
        if action in {"alpaca.paper", "paper", ""}:
            action = str(payload.get("action") or "account").strip().lower()

        budget.raise_if_exhausted()
        if cancel_check and cancel_check():
            raise ProviderError(
                ProviderErrorCode.EXECUTION_CANCELLED,
                "Cancelled before Alpaca call",
                provider="alpaca_paper",
            )

        headers = _resolve_alpaca_headers(credential)
        timeout = min(20.0, max(1.0, budget.remaining()))

        if action == "place":
            symbol = str(payload.get("symbol") or "").strip()
            side = str(payload.get("side") or "").strip()
            qty = float(payload.get("qty") or 0)
            client_order_id = str(payload.get("client_order_id") or "").strip()
            if not symbol or not side or qty <= 0 or not client_order_id:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                    "alpaca place requires symbol, side, qty, client_order_id",
                    provider="alpaca_paper",
                )
            data = _http_json(
                "POST",
                f"{PAPER_BASE}/v2/orders",
                headers=headers,
                body={
                    "symbol": symbol.upper(),
                    "qty": str(qty),
                    "side": side.lower(),
                    "type": "market",
                    "time_in_force": "day",
                    "client_order_id": client_order_id,
                },
                timeout=timeout,
            )
            return ProviderExecutionResult(
                status="succeeded",
                structured=data,
                provider="alpaca_paper",
                finish_reason="stop",
                metadata={"action": "place"},
            )

        if action == "reconcile":
            broker_order_id = str(payload.get("broker_order_id") or "").strip()
            if not broker_order_id:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                    "alpaca reconcile requires broker_order_id",
                    provider="alpaca_paper",
                )
            data = _http_json(
                "GET",
                f"{PAPER_BASE}/v2/orders/{broker_order_id}",
                headers=headers,
                timeout=timeout,
            )
            return ProviderExecutionResult(
                status="succeeded",
                structured=data,
                provider="alpaca_paper",
                finish_reason="stop",
                metadata={"action": "reconcile"},
            )

        if action == "account":
            data = _http_json(
                "GET",
                f"{PAPER_BASE}/v2/account",
                headers=headers,
                timeout=timeout,
            )
            return ProviderExecutionResult(
                status="succeeded",
                structured=data,
                provider="alpaca_paper",
                finish_reason="stop",
                metadata={"action": "account"},
            )

        raise ProviderError(
            ProviderErrorCode.PROVIDER_INVALID_REQUEST,
            f"Unknown alpaca action: {action}",
            provider="alpaca_paper",
        )
