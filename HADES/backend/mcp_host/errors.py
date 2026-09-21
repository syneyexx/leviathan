"""Typed MCP JSON-RPC / transport error model (2026-07-28 normative codes).

Normative codes (spec error-code allocation):
- -32020 HeaderMismatch
- -32021 MissingRequiredClientCapability
- -32022 UnsupportedProtocolVersion

Legacy evidence for dual-era fallback must come from typed classification,
never from substring matching of status text alone when a structured body exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


HEADER_MISMATCH = -32020
MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
UNSUPPORTED_PROTOCOL_VERSION = -32022
METHOD_NOT_FOUND = -32601

MODERN_PROTOCOL_ERROR_CODES = frozenset(
    {
        HEADER_MISMATCH,
        MISSING_REQUIRED_CLIENT_CAPABILITY,
        UNSUPPORTED_PROTOCOL_VERSION,
    }
)


@dataclass
class McpJsonRpcError:
    code: int
    message: str
    data: Any = None
    http_status: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_header_mismatch(self) -> bool:
        return self.code == HEADER_MISMATCH

    @property
    def is_missing_capability(self) -> bool:
        return self.code == MISSING_REQUIRED_CLIENT_CAPABILITY

    @property
    def is_unsupported_protocol_version(self) -> bool:
        return self.code == UNSUPPORTED_PROTOCOL_VERSION

    @property
    def is_method_not_found(self) -> bool:
        return self.code == METHOD_NOT_FOUND

    @property
    def is_recognized_modern_error(self) -> bool:
        return self.code in MODERN_PROTOCOL_ERROR_CODES

    def supported_versions(self) -> list[str]:
        if not isinstance(self.data, dict):
            return []
        supported = self.data.get("supported")
        if isinstance(supported, list):
            return [str(v) for v in supported]
        return []

    def requested_version(self) -> str | None:
        if not isinstance(self.data, dict):
            return None
        requested = self.data.get("requested")
        return str(requested) if requested is not None else None


class McpProtocolError(RuntimeError):
    """Raised for protocol-level failures with structured classification."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "protocol",
        rpc: McpJsonRpcError | None = None,
        http_status: int | None = None,
        legacy_evidence: bool = False,
        auth_challenge: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.rpc = rpc
        self.http_status = http_status if http_status is not None else (rpc.http_status if rpc else None)
        self.legacy_evidence = legacy_evidence
        self.auth_challenge = auth_challenge or {}


def parse_jsonrpc_error_body(payload: Any, *, http_status: int | None = None) -> McpJsonRpcError | None:
    """Parse a JSON-RPC error object or envelope into a typed error."""
    if payload is None:
        return None
    data = payload
    if isinstance(payload, (bytes, bytearray)):
        try:
            data = json.loads(payload.decode("utf-8", errors="replace"))
        except Exception:
            return None
    elif isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except Exception:
            # Bare error object sometimes appears as dumped JSON already.
            try:
                data = json.loads(text)
            except Exception:
                return None
    if not isinstance(data, dict):
        return None
    error = data.get("error") if "error" in data else data
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    if not isinstance(code, int):
        return None
    return McpJsonRpcError(
        code=code,
        message=str(error.get("message") or ""),
        data=error.get("data"),
        http_status=http_status,
        raw=dict(error),
    )


def classify_http_probe_failure(
    *,
    http_status: int | None,
    body: Any = None,
    transport_kind: str | None = None,
) -> dict[str, Any]:
    """Classify a modern HTTP probe failure for era negotiation.

    Returns keys:
      action: raise | legacy_fallback | retry_version
      kind: auth | permission | transport | timeout | protocol | ...
      rpc: optional McpJsonRpcError
      legacy_evidence: bool
    """
    rpc = parse_jsonrpc_error_body(body, http_status=http_status)
    if transport_kind == "timeout":
        return {"action": "raise", "kind": "timeout", "rpc": rpc, "legacy_evidence": False}
    if transport_kind == "network":
        return {"action": "raise", "kind": "transport", "rpc": rpc, "legacy_evidence": False}
    if http_status == 401:
        return {"action": "raise", "kind": "auth", "rpc": rpc, "legacy_evidence": False}
    if http_status == 403:
        return {"action": "raise", "kind": "permission", "rpc": rpc, "legacy_evidence": False}
    if http_status is not None and http_status >= 500:
        return {"action": "raise", "kind": "transport", "rpc": rpc, "legacy_evidence": False}
    if rpc is not None:
        if rpc.is_unsupported_protocol_version:
            return {"action": "retry_version", "kind": "protocol", "rpc": rpc, "legacy_evidence": False}
        if rpc.is_header_mismatch or rpc.is_missing_capability:
            # Modern server / client bug — never treat as legacy evidence.
            return {"action": "raise", "kind": "protocol", "rpc": rpc, "legacy_evidence": False}
        if rpc.is_method_not_found:
            return {"action": "legacy_fallback", "kind": "protocol", "rpc": rpc, "legacy_evidence": True}
        if rpc.is_recognized_modern_error:
            return {"action": "raise", "kind": "protocol", "rpc": rpc, "legacy_evidence": False}
    # Spec: HTTP dual-era fallback after inspecting a 400 body without recognized modern error.
    if http_status in {400, 404, 405}:
        return {"action": "legacy_fallback", "kind": "protocol", "rpc": rpc, "legacy_evidence": True}
    if http_status is not None and 400 <= http_status < 500:
        # Unrecognized 4xx without modern body — legacy evidence per dual-era HTTP rules.
        return {"action": "legacy_fallback", "kind": "protocol", "rpc": rpc, "legacy_evidence": True}
    return {"action": "raise", "kind": "protocol", "rpc": rpc, "legacy_evidence": False}
