from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

API_BASE = "https://api.fincept.in"
API_HOST = "api.fincept.in"
DOCS_INDEX = "https://docs.fincept.in/llms.txt"
DOCS_HOST = "docs.fincept.in"
USER_AGENT = "HADES-Fincept/0.1"
DEFAULT_MAX_BYTES = 250_000
ABSOLUTE_MAX_BYTES = 2_000_000
MAX_BATCH_REQUESTS = 5
SENSITIVE_PREFIXES = (
    "/admin",
    "/auth",
    "/billing",
    "/guest",
    "/payment",
    "/subscription",
    "/user",
)


class FinceptError(RuntimeError):
    pass


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never follow redirects so authentication headers cannot leak cross-host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirectHandler())


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _parse_json_arg(raw: str, label: str, expected: type | tuple[type, ...]) -> Any:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FinceptError(f"{label} is geen geldige JSON: {exc.msg}") from exc
    if not isinstance(value, expected):
        names = expected.__name__ if isinstance(expected, type) else "/".join(t.__name__ for t in expected)
        raise FinceptError(f"{label} moet JSON-type {names} zijn.")
    return value


def _clean_path(path: str, *, allow_sensitive: bool = False) -> str:
    path = path.strip()
    if not path.startswith("/") or path.startswith("//"):
        raise FinceptError("Fincept-pad moet een relatief API-pad zijn dat met precies één '/' begint.")
    if any(ch in path for ch in ("\\", "\x00", "\r", "\n", "#", "?")):
        raise FinceptError("Fincept-pad bevat niet-toegestane tekens. Gebruik het aparte query-object voor parameters.")
    decoded = urllib.parse.unquote(path)
    if decoded.startswith("//") or "\\" in decoded:
        raise FinceptError("Fincept-pad probeert de vaste API-host te omzeilen.")
    segments = [segment for segment in decoded.split("/") if segment]
    if any(segment in {".", ".."} for segment in segments):
        raise FinceptError("Padtraversal is niet toegestaan.")
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc:
        raise FinceptError("Absolute URL's zijn niet toegestaan; de host is vastgezet op api.fincept.in.")
    if not allow_sensitive:
        lowered = decoded.lower().rstrip("/")
        if any(lowered == prefix or lowered.startswith(prefix + "/") for prefix in SENSITIVE_PREFIXES):
            raise FinceptError(
                "Account-, auth-, billing- en adminpaden zijn geblokkeerd voor de generieke data-tools. "
                "Gebruik de handmatige doctor-tool voor /user/profile."
            )
    return path


def _normalize_query(query: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        name = str(key).strip()
        if not name or len(name) > 200:
            raise FinceptError("Queryparameter heeft een ongeldige naam.")
        values = value if isinstance(value, list) else [value]
        if len(values) > 100:
            raise FinceptError(f"Queryparameter '{name}' bevat te veel waarden.")
        for item in values:
            if item is None:
                continue
            if not isinstance(item, (str, int, float, bool)):
                raise FinceptError(f"Queryparameter '{name}' mag alleen scalars of lijsten van scalars bevatten.")
            pairs.append((name, str(item).lower() if isinstance(item, bool) else str(item)))
    return pairs


def _selected_headers(headers: Any) -> dict[str, str]:
    wanted = (
        "content-type",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "retry-after",
        "x-request-id",
        "request-id",
    )
    result: dict[str, str] = {}
    for name in wanted:
        value = headers.get(name) if headers is not None else None
        if value is not None:
            result[name] = str(value)
    return result


def _read_bounded(response: Any, max_bytes: int) -> bytes:
    raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise FinceptError(
            f"Fincept-response is groter dan {max_bytes} bytes. Verfijn de query of verhoog max_bytes (max {ABSOLUTE_MAX_BYTES})."
        )
    return raw


def _decode_payload(raw: bytes, headers: dict[str, str]) -> Any:
    text = raw.decode("utf-8", errors="replace")
    content_type = headers.get("content-type", "").lower()
    if "json" in content_type or text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def _rate_limit(headers: dict[str, str]) -> dict[str, Any]:
    def as_int(name: str) -> int | None:
        raw = headers.get(name)
        try:
            return int(raw) if raw is not None else None
        except ValueError:
            return None

    return {
        "limit": as_int("x-ratelimit-limit"),
        "remaining": as_int("x-ratelimit-remaining"),
        "reset": as_int("x-ratelimit-reset"),
        "retry_after": as_int("retry-after"),
    }


def _knowledge_item(*, method: str, path: str, uri: str, data: Any, status: int, headers: dict[str, str], retrieved_at: str) -> dict[str, Any]:
    content = data if isinstance(data, str) else _pretty_json(data)
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    return {
        "title": f"Fincept API {method} {path}",
        "uri": uri,
        "source_type": "fincept_api",
        "content": content,
        "metadata": {
            "provider": "Fincept",
            "method": method,
            "endpoint": path,
            "status_code": status,
            "retrieved_at": retrieved_at,
            "content_sha256": digest,
            "rate_limit": _rate_limit(headers),
        },
    }


def _api_request(
    *,
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
    body: Any = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: int = 30,
    allow_sensitive: bool = False,
) -> dict[str, Any]:
    method = method.upper()
    if method not in {"GET", "POST"}:
        raise FinceptError("Alleen GET en POST zijn toegestaan.")
    if max_bytes < 1 or max_bytes > ABSOLUTE_MAX_BYTES:
        raise FinceptError(f"max_bytes moet tussen 1 en {ABSOLUTE_MAX_BYTES} liggen.")
    timeout = max(3, min(int(timeout), 60))
    query = query or {}
    safe_path = _clean_path(path, allow_sensitive=allow_sensitive)
    encoded_query = urllib.parse.urlencode(_normalize_query(query), doseq=True)
    uri = API_BASE + safe_path + ("?" + encoded_query if encoded_query else "")
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme != "https" or parsed.hostname != API_HOST:
        raise FinceptError("Interne hostvalidatie faalde; request is geblokkeerd.")

    api_key = os.getenv("FINCEPT_API_KEY", "").strip()
    if not api_key:
        raise FinceptError("FINCEPT_API_KEY ontbreekt. Stel de sleutel als environment variable in; zet hem nooit in toolinput of Git.")

    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "X-API-Key": api_key,
    }
    session_token = os.getenv("FINCEPT_SESSION_TOKEN", "").strip()
    if session_token:
        headers["X-Session-Token"] = session_token

    data: bytes | None = None
    if method == "POST":
        if body is None:
            body = {}
        if not isinstance(body, (dict, list)):
            raise FinceptError("POST-body moet een JSON-object of JSON-lijst zijn.")
        data = _json_text(body).encode("utf-8")
        if len(data) > 200_000:
            raise FinceptError("POST-body is groter dan 200 kB en wordt geweigerd.")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(uri, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with _opener().open(request, timeout=timeout) as response:
            status = int(response.getcode())
            response_headers = _selected_headers(response.headers)
            raw = _read_bounded(response, max_bytes)
    except urllib.error.HTTPError as exc:
        response_headers = _selected_headers(exc.headers)
        raw = exc.read(min(max_bytes, 64_000))
        payload = _decode_payload(raw, response_headers)
        raise FinceptError(
            _json_text(
                {
                    "message": "Fincept API request mislukt",
                    "status_code": int(exc.code),
                    "path": safe_path,
                    "rate_limit": _rate_limit(response_headers),
                    "response": payload,
                }
            )
        ) from exc
    except urllib.error.URLError as exc:
        raise FinceptError(f"Fincept API is niet bereikbaar: {exc.reason}") from exc

    retrieved_at = utc_now()
    payload = _decode_payload(raw, response_headers)
    evidence = _knowledge_item(
        method=method,
        path=safe_path,
        uri=uri,
        data=payload,
        status=status,
        headers=response_headers,
        retrieved_at=retrieved_at,
    )
    return {
        "ok": 200 <= status < 300,
        "provider": "Fincept",
        "retrieved_at": retrieved_at,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": {"method": method, "path": safe_path, "uri": uri},
        "status_code": status,
        "rate_limit": _rate_limit(response_headers),
        "data": payload,
        "hades_knowledge": [evidence],
    }


def command_doctor(args: argparse.Namespace) -> dict[str, Any]:
    key = os.getenv("FINCEPT_API_KEY", "").strip()
    result: dict[str, Any] = {
        "ok": bool(key),
        "provider": "Fincept",
        "api_base": API_BASE,
        "docs_index": DOCS_INDEX,
        "api_key_configured": bool(key),
        "session_token_configured": bool(os.getenv("FINCEPT_SESSION_TOKEN", "").strip()),
        "security": {
            "credentials_from_environment_only": True,
            "fixed_api_host": API_HOST,
            "redirects_followed": False,
            "ambient_proxy_disabled": True,
        },
    }
    if not key:
        result["error"] = "FINCEPT_API_KEY ontbreekt"
    probe = str(args.probe).strip().lower() in {"1", "true", "yes", "on"}
    if probe:
        if not key:
            raise FinceptError("Probe aangevraagd maar FINCEPT_API_KEY ontbreekt.")
        profile = _api_request(
            method="GET",
            path="/user/profile",
            query={},
            max_bytes=min(args.max_bytes, 100_000),
            timeout=args.timeout,
            allow_sensitive=True,
        )
        result["probe"] = {
            "ok": profile["ok"],
            "status_code": profile["status_code"],
            "latency_ms": profile["latency_ms"],
            "rate_limit": profile["rate_limit"],
        }
        if not profile.get("ok"):
            result["ok"] = False
            result["error"] = result.get("error") or f"probe_failed_status_{profile.get('status_code')}"
    return result


def _fetch_docs_index(max_bytes: int = 1_000_000, timeout: int = 20) -> str:
    request = urllib.request.Request(DOCS_INDEX, headers={"Accept": "text/plain", "User-Agent": USER_AGENT}, method="GET")
    try:
        with _opener().open(request, timeout=max(3, min(timeout, 60))) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != DOCS_HOST:
                raise FinceptError("Documentatiehostvalidatie faalde.")
            raw = _read_bounded(response, max_bytes)
            return raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise FinceptError(f"Fincept-documentatie gaf HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise FinceptError(f"Fincept-documentatie is niet bereikbaar: {exc.reason}") from exc


def command_catalog(args: argparse.Namespace) -> dict[str, Any]:
    text = _fetch_docs_index(timeout=args.timeout)
    query = args.query.strip().lower()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if query:
        tokens = [token for token in re.split(r"\s+", query) if token]
        lines = [line for line in lines if all(token in line.lower() for token in tokens)]
    matches = lines[: args.limit]
    ok = True
    error = None
    if query and not matches:
        ok = False
        error = "no catalog matches for query"
    elif not matches:
        ok = False
        error = "empty Fincept catalog"
    payload = {
        "ok": ok,
        "provider": "Fincept",
        "source": DOCS_INDEX,
        "query": args.query,
        "matches": matches,
        "match_count_returned": len(matches),
        "more_matches_possible": len(lines) > len(matches),
        "usage": "Gebruik een relatief endpointpad uit de Fincept-documentatie met fincept_get of handmatig met fincept_post.",
    }
    if error:
        payload["error"] = error
    return payload


def command_get(args: argparse.Namespace) -> dict[str, Any]:
    query = _parse_json_arg(args.query, "query", dict)
    return _api_request(
        method="GET",
        path=args.path,
        query=query,
        max_bytes=args.max_bytes,
        timeout=args.timeout,
    )


def command_post(args: argparse.Namespace) -> dict[str, Any]:
    query = _parse_json_arg(args.query, "query", dict)
    body = _parse_json_arg(args.body, "body", (dict, list))
    return _api_request(
        method="POST",
        path=args.path,
        query=query,
        body=body,
        max_bytes=args.max_bytes,
        timeout=args.timeout,
    )


def command_batch_get(args: argparse.Namespace) -> dict[str, Any]:
    batch = _parse_json_arg(args.batch, "batch", dict)
    requests = batch.get("requests")
    if not isinstance(requests, list) or not requests:
        raise FinceptError("batch.requests moet een niet-lege lijst zijn.")
    if len(requests) > MAX_BATCH_REQUESTS:
        raise FinceptError(f"Maximaal {MAX_BATCH_REQUESTS} GET-requests per batch om credits/rate-limits te begrenzen.")
    delay_ms = int(batch.get("delay_ms", 150))
    if delay_ms < 0 or delay_ms > 2_000:
        raise FinceptError("batch.delay_ms moet tussen 0 en 2000 liggen.")
    max_bytes_each = int(batch.get("max_bytes_each", min(args.max_bytes, 150_000)))
    if max_bytes_each < 1 or max_bytes_each > min(args.max_bytes, ABSOLUTE_MAX_BYTES):
        raise FinceptError("batch.max_bytes_each ligt buiten de toegestane grens.")

    results: list[dict[str, Any]] = []
    knowledge: list[dict[str, Any]] = []
    for index, item in enumerate(requests):
        if not isinstance(item, dict):
            raise FinceptError(f"batch.requests[{index}] moet een object zijn.")
        path = str(item.get("path", ""))
        query = item.get("query", {})
        if not isinstance(query, dict):
            raise FinceptError(f"batch.requests[{index}].query moet een object zijn.")
        result = _api_request(
            method="GET",
            path=path,
            query=query,
            max_bytes=max_bytes_each,
            timeout=args.timeout,
        )
        knowledge.extend(result.pop("hades_knowledge", []))
        results.append(result)
        remaining = result.get("rate_limit", {}).get("remaining")
        if isinstance(remaining, int) and remaining <= 2 and index + 1 < len(requests):
            raise FinceptError("Batch vroegtijdig gestopt: Fincept rate-limit remaining is <= 2.")
        if delay_ms and index + 1 < len(requests):
            time.sleep(delay_ms / 1000)

    all_ok = all(bool(item.get("ok", True)) for item in results) if results else False
    payload = {
        "ok": all_ok,
        "provider": "Fincept",
        "retrieved_at": utc_now(),
        "count": len(results),
        "results": results,
        "hades_knowledge": knowledge,
    }
    if not all_ok:
        payload["error"] = "one or more batch GET requests failed"
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fincept_hades", description="Secure Fincept Data API adapter for HADES")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--probe", choices=("true", "false"), default="false")
    doctor.add_argument("--max-bytes", type=int, default=100_000)
    doctor.add_argument("--timeout", type=int, default=20)
    doctor.set_defaults(handler=command_doctor)

    catalog = sub.add_parser("catalog")
    catalog.add_argument("--query", default="")
    catalog.add_argument("--limit", type=int, default=50)
    catalog.add_argument("--timeout", type=int, default=20)
    catalog.set_defaults(handler=command_catalog)

    get_cmd = sub.add_parser("get")
    get_cmd.add_argument("--path", required=True)
    get_cmd.add_argument("--query", default="{}")
    get_cmd.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    get_cmd.add_argument("--timeout", type=int, default=30)
    get_cmd.set_defaults(handler=command_get)

    post = sub.add_parser("post")
    post.add_argument("--path", required=True)
    post.add_argument("--query", default="{}")
    post.add_argument("--body", default="{}")
    post.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    post.add_argument("--timeout", type=int, default=30)
    post.set_defaults(handler=command_post)

    batch = sub.add_parser("batch-get")
    batch.add_argument("--batch", required=True)
    batch.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    batch.add_argument("--timeout", type=int, default=30)
    batch.set_defaults(handler=command_batch_get)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if isinstance(payload, dict) and payload.get("ok") is False:
            return 2
        return 0
    except FinceptError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "provider": "Fincept"}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"Onverwachte pluginfout: {type(exc).__name__}: {exc}", "provider": "Fincept"}, ensure_ascii=False, sort_keys=True))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
