"""Local-first compute fabric — node registry, local jobs, and LAN worker MVP.

Honesty:
- Local node fabric remains the default.
- Remote/LAN workers require explicit trusted pairing + authenticated channel.
- Only typed ``COMPUTE_JOB_TYPES`` are accepted — no generic remote shell.
- When dispatch to a remote worker is impossible: status ``blocked`` /
  ``unavailable`` (not an endless ``queued`` with only ``not_implemented``).
- Physical multi-machine remains unverified until a second host is tested;
  the integration path is coordinator + worker as two processes on one host.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest

from gen2.store import Gen2Store, new_id, utc_now


# Supported job types → mode (inspect vs execute). Keep honest — do not
# invent handlers for types that are not implemented.
COMPUTE_JOB_TYPES: dict[str, str] = {
    "ping": "inspect",
    "inspect": "inspect",
    "echo": "inspect",
    "local_info": "execute",
    "heartbeat": "execute",
    "document_chunk": "execute",
    "document_preprocess": "execute",
}

WORKER_PROTOCOL_VERSION = 1
DEFAULT_LEASE_SECONDS = 60
CAPABILITY_DOCUMENT_CHUNK = "document_chunk"


RecordFn = Callable[..., dict[str, Any]]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign_message(secret: str, body: str, *, timestamp: str, node_id: str) -> str:
    msg = f"{timestamp}.{node_id}.{body}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_message(
    secret: str,
    body: str,
    *,
    timestamp: str,
    node_id: str,
    signature: str,
    max_skew_seconds: int = 300,
) -> bool:
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > max_skew_seconds:
        return False
    expected = sign_message(secret, body, timestamp=timestamp, node_id=node_id)
    return hmac.compare_digest(expected, signature or "")


def chunk_document_text(text: str, *, target_chars: int = 800, overlap_chars: int = 80) -> list[dict[str, Any]]:
    """Minimal CPU document preprocessing/chunking used by LAN + local workers."""
    normalized = re.sub(r"\r\n?", "\n", text or "").strip()
    if not normalized:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", normalized) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target_chars * 2:
            if current:
                chunks.append(current)
                current = ""
            step = max(200, target_chars - overlap_chars)
            for start in range(0, len(paragraph), step):
                chunks.append(paragraph[start : start + target_chars])
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= target_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    out: list[dict[str, Any]] = []
    for idx, content in enumerate(chunks):
        out.append(
            {
                "index": idx,
                "content": content,
                "content_hash": _sha256_text(content),
                "token_estimate": max(1, len(content) // 4),
            }
        )
    return out


def execute_typed_job(job_type: str, payload: dict[str, Any], *, data_root: Path | None = None) -> dict[str, Any]:
    """Run a typed job locally (coordinator fallback or worker process)."""
    job_type = (job_type or "").strip().lower()
    mode = COMPUTE_JOB_TYPES.get(job_type)
    if mode is None:
        return {
            "ok": False,
            "error": f"unsupported_job_type:{job_type or 'missing'}",
            "supported_types": sorted(COMPUTE_JOB_TYPES.keys()),
        }

    if mode == "inspect":
        return {
            "ok": True,
            "mode": "inspect",
            "job_type": job_type,
            "inspection": {
                "payload_keys": sorted((payload or {}).keys()),
                "echo": payload,
            },
            "cloud_required": False,
            "note": "inspect_only_no_side_effects",
        }

    if job_type == "local_info":
        return {
            "ok": True,
            "mode": "execute",
            "job_type": job_type,
            "info": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "data_root": str(data_root) if data_root else None,
                "hostname": platform.node(),
            },
            "cloud_required": False,
        }

    if job_type == "heartbeat":
        load: dict[str, Any] = {"cpu_percent": None}
        try:
            import psutil  # type: ignore

            load["cpu_percent"] = psutil.cpu_percent(interval=0.0)
        except Exception:
            pass
        return {
            "ok": True,
            "mode": "execute",
            "job_type": job_type,
            "load": load,
            "cloud_required": False,
        }

    if job_type in {"document_chunk", "document_preprocess"}:
        text = str((payload or {}).get("text") or (payload or {}).get("content") or "")
        target = int((payload or {}).get("target_chars") or 800)
        overlap = int((payload or {}).get("overlap_chars") or 80)
        input_hash = _sha256_text(text)
        expected = (payload or {}).get("input_hash")
        if expected and expected != input_hash:
            return {
                "ok": False,
                "error": "input_hash_mismatch",
                "expected": expected,
                "actual": input_hash,
            }
        chunks = chunk_document_text(text, target_chars=target, overlap_chars=overlap)
        if not str(text or "").strip() or not chunks:
            return {
                "ok": False,
                "error": "empty_document_text",
                "mode": "execute",
                "job_type": job_type,
                "chunk_count": 0,
                "chunks": [],
                "input_hash": input_hash,
                "cloud_required": False,
                "unbounded_shell": False,
            }
        result_body = {
            "ok": True,
            "mode": "execute",
            "job_type": job_type,
            "chunk_count": len(chunks),
            "chunks": chunks,
            "input_hash": input_hash,
            "contract": {
                "version": WORKER_PROTOCOL_VERSION,
                "job_type": job_type,
                "fields": ["chunk_count", "chunks", "input_hash", "result_hash"],
            },
            "cloud_required": False,
            "unbounded_shell": False,
        }
        result_body["result_hash"] = _sha256_text(_canonical_json({
            "chunk_count": result_body["chunk_count"],
            "chunks": [{"index": c["index"], "content_hash": c["content_hash"]} for c in chunks],
            "input_hash": input_hash,
        }))
        return result_body

    return {"ok": False, "error": f"handler_missing:{job_type}"}


def ensure_local_node(store: Gen2Store, data_root: Path) -> dict[str, Any]:
    caps = {
        "hardware": platform.machine(),
        "cpu": os.cpu_count() or 1,
        "ram_gb": None,
        "gpu_vram": None,
        "models": ["lm_studio_dynamic"],
        "plugins": True,
        "storage": str(data_root),
        "permissions": {"network": "local_policy", "filesystem": "local_policy"},
        "platform": platform.system(),
        "python": platform.python_version(),
        "job_types": sorted(COMPUTE_JOB_TYPES.keys()),
        "protocol_version": WORKER_PROTOCOL_VERSION,
    }
    try:
        import psutil  # type: ignore

        caps["ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 2)
        caps["load"] = {"cpu_percent": psutil.cpu_percent(interval=0.0)}
    except Exception:
        caps["load"] = {"cpu_percent": None}
    return store.upsert_node(
        {
            "id": "node_local",
            "name": f"{platform.node() or 'local'}",
            "role": "all_in_one",
            "status": "online",
            "capabilities": caps,
            "load": caps.get("load") or {},
            "last_heartbeat": utc_now(),
        }
    )


def heartbeat(store: Gen2Store, data_root: Path, node_id: str = "node_local") -> dict[str, Any]:
    node = store.get_node(node_id) or ensure_local_node(store, data_root)
    load = dict(node.get("load") or {})
    try:
        import psutil  # type: ignore

        load["cpu_percent"] = psutil.cpu_percent(interval=0.0)
    except Exception:
        pass
    return store.upsert_node(
        {
            **node,
            "status": "online",
            "load": load,
            "last_heartbeat": utc_now(),
        }
    )


def discover_nodes(store: Gen2Store, data_root: Path) -> list[dict[str, Any]]:
    heartbeat(store, data_root)
    return store.list_nodes()


def _pairing_dir(data_root: Path) -> Path:
    path = Path(data_root) / "compute_peers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pairing_path(data_root: Path, node_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", node_id)
    return _pairing_dir(data_root) / f"{safe}.json"


def load_pairing(data_root: Path, node_id: str) -> dict[str, Any] | None:
    path = _pairing_path(data_root, node_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_pairing(data_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    node_id = str(record["node_id"])
    path = _pairing_path(data_root, node_id)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def list_pairings(data_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(_pairing_dir(data_root).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                public = {k: v for k, v in data.items() if k != "shared_secret"}
                public["has_secret"] = bool(data.get("shared_secret"))
                out.append(public)
        except Exception:
            continue
    return out


def pair_remote_node(
    store: Gen2Store,
    data_root: Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
    base_url: str | None = None,
    shared_secret: str | None = None,
    capabilities: dict[str, Any] | None = None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Explicit trusted worker pairing (local peer management — no cloud account)."""
    node_id = node_id or new_id("worker")
    secret = shared_secret or secrets.token_urlsafe(32)
    fp = fingerprint or _sha256_text(f"{node_id}:{secret}")[:32]
    caps = dict(capabilities or {})
    caps.setdefault("job_types", [CAPABILITY_DOCUMENT_CHUNK, "ping", "heartbeat"])
    caps.setdefault("protocol_version", WORKER_PROTOCOL_VERSION)
    caps.setdefault("role", "worker")
    record = {
        "ok": True,
        "status": "paired",
        "node_id": node_id,
        "name": name or node_id,
        "base_url": base_url,
        "shared_secret": secret,
        "fingerprint": fp,
        "capabilities": caps,
        "paired_at": utc_now(),
        "trusted": True,
        "cloud_account": False,
        "mode": "lan_worker_mvp",
    }
    save_pairing(data_root, record)
    store.upsert_node(
        {
            "id": node_id,
            "name": record["name"],
            "role": "worker",
            "status": "paired",
            "capabilities": {
                **caps,
                "fingerprint": fp,
                "base_url": base_url,
                "paired": True,
            },
            "load": {},
            "last_heartbeat": utc_now(),
        }
    )
    public = {k: v for k, v in record.items() if k != "shared_secret"}
    public["has_secret"] = True
    public["distributed"] = False
    public["simulated_distributed"] = False
    return public


def advertise_capabilities(
    store: Gen2Store,
    data_root: Path,
    node_id: str,
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    pairing = load_pairing(data_root, node_id)
    if not pairing:
        return {
            "ok": False,
            "status": "unavailable",
            "error": "worker_not_paired",
            "node_id": node_id,
        }
    caps = dict(pairing.get("capabilities") or {})
    caps.update(capabilities or {})
    pairing["capabilities"] = caps
    save_pairing(data_root, pairing)
    node = store.get_node(node_id) or {}
    store.upsert_node(
        {
            **node,
            "id": node_id,
            "name": pairing.get("name") or node_id,
            "role": "worker",
            "status": node.get("status") or "paired",
            "capabilities": {**caps, "fingerprint": pairing.get("fingerprint"), "base_url": pairing.get("base_url")},
            "load": node.get("load") or {},
            "last_heartbeat": utc_now(),
        }
    )
    return {"ok": True, "status": "advertised", "node_id": node_id, "capabilities": caps}


def authenticated_channel(
    data_root: Path,
    node_id: str,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """HMAC-authenticated HTTP call to a paired worker. Validates node identity."""
    pairing = load_pairing(data_root, node_id)
    if not pairing:
        return {"ok": False, "status": "unavailable", "error": "worker_not_paired"}
    base = pairing.get("base_url")
    if not base:
        return {"ok": False, "status": "unavailable", "error": "worker_base_url_missing"}
    secret = str(pairing.get("shared_secret") or "")
    body_obj = payload or {}
    body = _canonical_json(body_obj)
    timestamp = str(time.time())
    signature = sign_message(secret, body, timestamp=timestamp, node_id=node_id)
    url = str(base).rstrip("/") + path
    req = urlrequest.Request(
        url,
        data=body.encode("utf-8"),
        method=method.upper(),
        headers={
            "Content-Type": "application/json",
            "X-HADES-Node-Id": node_id,
            "X-HADES-Timestamp": timestamp,
            "X-HADES-Signature": signature,
            "X-HADES-Fingerprint": str(pairing.get("fingerprint") or ""),
            "X-HADES-Protocol": str(WORKER_PROTOCOL_VERSION),
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            # Validate worker identity echo when present.
            if data.get("fingerprint") and pairing.get("fingerprint"):
                if data["fingerprint"] != pairing["fingerprint"]:
                    return {
                        "ok": False,
                        "status": "blocked",
                        "error": "node_identity_mismatch",
                        "expected": pairing["fingerprint"],
                        "actual": data.get("fingerprint"),
                    }
            return {"ok": True, "status": "ok", "response": data, "http_status": getattr(resp, "status", 200)}
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        return {"ok": False, "status": "unavailable", "error": f"http_{exc.code}", "detail": detail[:500]}
    except urlerror.URLError as exc:
        return {"ok": False, "status": "unavailable", "error": f"connection_failed:{exc.reason}"}
    except Exception as exc:
        return {"ok": False, "status": "unavailable", "error": str(exc)}


def lease_remote_job(
    store: Gen2Store,
    job_id: str,
    *,
    node_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    lease_token: str | None = None,
) -> dict[str, Any]:
    job = store.get_remote_job(job_id)
    if not job:
        return {"ok": False, "status": "unavailable", "error": "job_not_found"}
    if job.get("status") in {"completed", "failed", "cancelled", "blocked"}:
        return {"ok": False, "status": job["status"], "error": "job_terminal", "job": job}
    existing = dict((job.get("result") or {}).get("lease") or {})
    existing_token = str(existing.get("token") or "")
    existing_node = str(existing.get("node_id") or "")
    expires_at = float(existing.get("expires_at") or 0)
    # Refuse overwrite of an unexpired lease held by another node (duplicate execution risk).
    if (
        job.get("status") == "leased"
        and existing_token
        and expires_at > time.time()
        and existing_node
        and existing_node != str(node_id)
        and (not lease_token or lease_token != existing_token)
    ):
        return {
            "ok": False,
            "status": "leased",
            "error": "lease_held",
            "held_by": existing_node,
            "expires_at": expires_at,
            "job": job,
        }
    # Same node renew / same token renew is allowed.
    token = lease_token or existing_token or secrets.token_urlsafe(16)
    if lease_token and existing_token and lease_token != existing_token and expires_at > time.time():
        return {"ok": False, "status": "leased", "error": "lease_token_mismatch", "job": job}
    expires = time.time() + max(5, int(lease_seconds))
    result = dict(job.get("result") or {})
    result["lease"] = {
        "token": token,
        "node_id": node_id,
        "expires_at": expires,
        "leased_at": time.time(),
    }
    updated = store.update_remote_job(job_id, status="leased", result=result) or job
    return {"ok": True, "status": "leased", "lease_token": token, "expires_at": expires, "job": updated}


def ack_remote_result(
    store: Gen2Store,
    job_id: str,
    *,
    lease_token: str,
    result: dict[str, Any],
    error: str | None = None,
) -> dict[str, Any]:
    job = store.get_remote_job(job_id)
    if not job:
        return {"ok": False, "error": "job_not_found"}
    lease = ((job.get("result") or {}).get("lease") or {})
    if lease.get("token") and lease.get("token") != lease_token:
        return {"ok": False, "status": "blocked", "error": "lease_token_mismatch"}
    if lease.get("expires_at") and float(lease["expires_at"]) < time.time():
        updated = store.update_remote_job(job_id, status="queued", error="lease_expired") or job
        return {"ok": False, "status": "unavailable", "error": "lease_expired", "job": updated}
    status = "failed" if error else "completed"
    body = dict(result or {})
    body["acked_at"] = utc_now()
    body["lease_token_acked"] = lease_token
    updated = store.update_remote_job(job_id, status=status, result=body, error=error) or job
    return {"ok": True, "status": status, "job": updated}


def idempotent_remote_dispatch(
    store: Gen2Store,
    data_root: Path,
    *,
    payload: dict[str, Any],
    node_id: str,
    idempotency_key: str,
    mission_id: str | None = None,
    record_fn: RecordFn | None = None,
    network_allowed: bool = True,
    prefer_local_fallback: bool = True,
) -> dict[str, Any]:
    """Dispatch with durable id + idempotency; falls back locally when remote unavailable."""
    # Reuse existing job with same idempotency key when present in recent jobs.
    for existing in store.list_remote_jobs(limit=100):
        prev = (existing.get("payload") or {}).get("_idempotency_key")
        if prev and prev == idempotency_key and existing.get("node_id") == node_id:
            return {**existing, "idempotent_replay": True}

    body = dict(payload or {})
    body["_idempotency_key"] = idempotency_key
    return dispatch_job(
        store,
        data_root,
        payload=body,
        mission_id=mission_id,
        node_id=node_id,
        record_fn=record_fn,
        network_allowed=network_allowed,
        prefer_local_fallback=prefer_local_fallback,
    )


def _policy_network_allowed(network_allowed: bool | None) -> bool:
    if network_allowed is False:
        return False
    # Honor optional env / control hint without requiring cloud.
    blocked = os.environ.get("HADES_BLOCK_NETWORK", "").strip().lower() in {"1", "true", "yes"}
    return not blocked


def dispatch_job(
    store: Gen2Store,
    data_root: Path,
    *,
    payload: dict[str, Any],
    mission_id: str | None = None,
    node_id: str | None = None,
    record_fn: RecordFn | None = None,
    network_allowed: bool | None = None,
    prefer_local_fallback: bool = True,
) -> dict[str, Any]:
    def _record(run_id: str, event_type: str, payload_body: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        if record_fn is not None:
            return record_fn(run_id, event_type, payload_body, **kwargs)
        return {}

    nodes = discover_nodes(store, data_root)
    online = [n for n in nodes if n.get("status") in {"online", "paired", "busy"}]
    if not online:
        raise RuntimeError("no online nodes")
    target = next((n for n in online if n["id"] == node_id), None) if node_id else online[0]
    if not target:
        # Explicit target missing/offline → blocked/unavailable, not endless queue.
        job = store.create_remote_job(
            {
                "node_id": node_id or "unknown",
                "mission_id": mission_id,
                "status": "blocked",
                "payload": payload,
                "result": {"ok": False, "outcome": "unavailable", "error": "node_not_found_or_offline"},
            }
        )
        store.update_remote_job(job["id"], error="node_not_found_or_offline")
        _record(job["id"], "RUN_FAILED", {"error": "node_not_found_or_offline"}, component="compute_fabric")
        return store.get_remote_job(job["id"]) or job

    job_type = str(
        (payload or {}).get("type")
        or (payload or {}).get("op")
        or (payload or {}).get("job_type")
        or ""
    ).strip().lower()
    mode = COMPUTE_JOB_TYPES.get(job_type)

    idem = (payload or {}).get("_idempotency_key")
    job = store.create_remote_job(
        {
            "node_id": target["id"],
            "mission_id": mission_id,
            "status": "queued",
            "payload": payload,
        }
    )
    if idem:
        result0 = dict(job.get("result") or {})
        result0["idempotency_key"] = idem
        job = store.update_remote_job(job["id"], result=result0) or job

    if mode is None:
        error = f"unsupported_job_type:{job_type or 'missing'}"
        job = store.update_remote_job(
            job["id"],
            status="failed",
            error=error,
            result={"ok": False, "mode": "rejected", "supported_types": sorted(COMPUTE_JOB_TYPES.keys())},
        ) or job
        _record(job["id"], "RUN_FAILED", {"error": error}, component="compute_fabric")
        return job

    # Local execution path
    if target["id"] == "node_local":
        result = execute_typed_job(job_type, payload or {}, data_root=data_root)
        if job_type == "heartbeat":
            node = heartbeat(store, data_root, target["id"])
            result = {
                **result,
                "executed_on": "node_local",
                "node": {"id": node["id"], "status": node.get("status"), "load": node.get("load")},
            }
        else:
            result = {**result, "executed_on": "node_local"}
        status = "completed" if result.get("ok") else "failed"
        job = store.update_remote_job(
            job["id"],
            status=status,
            result=result,
            error=None if result.get("ok") else str(result.get("error") or "failed"),
        ) or job
        _record(
            job["id"],
            "TOOL_STARTED" if status == "completed" else "RUN_FAILED",
            {"node_id": target["id"], "mode": mode, "job_type": job_type},
            component="compute_fabric",
        )
        return job

    # Remote / LAN worker path
    if not _policy_network_allowed(network_allowed):
        job = store.update_remote_job(
            job["id"],
            status="blocked",
            error="network_policy_blocked",
            result={
                "ok": False,
                "outcome": "blocked",
                "error": "network_policy_blocked",
                "local_fallback_available": True,
            },
        ) or job
        if prefer_local_fallback:
            local = execute_typed_job(job_type, payload or {}, data_root=data_root)
            local["executed_on"] = "node_local_fallback"
            local["fallback_reason"] = "network_policy_blocked"
            job = store.update_remote_job(
                job["id"],
                status="completed" if local.get("ok") else "failed",
                result=local,
                error=None if local.get("ok") else str(local.get("error")),
            ) or job
        _record(job["id"], "RUN_FAILED" if job["status"] != "completed" else "TOOL_STARTED", {"policy": "network_blocked"}, component="compute_fabric")
        return job

    pairing = load_pairing(data_root, target["id"])
    if not pairing:
        job = store.update_remote_job(
            job["id"],
            status="blocked",
            error="worker_not_paired",
            result={"ok": False, "outcome": "unavailable", "error": "worker_not_paired"},
        ) or job
        if prefer_local_fallback:
            local = execute_typed_job(job_type, payload or {}, data_root=data_root)
            local["executed_on"] = "node_local_fallback"
            local["fallback_reason"] = "worker_not_paired"
            job = store.update_remote_job(
                job["id"],
                status="completed" if local.get("ok") else "failed",
                result={**local, "remote_outcome": "unavailable"},
                error=None if local.get("ok") else str(local.get("error")),
            ) or job
        _record(job["id"], "RUN_FAILED" if job.get("status") != "completed" else "TOOL_STARTED", {"error": "worker_not_paired"}, component="compute_fabric")
        return job

    # Capability / version check
    caps = pairing.get("capabilities") or target.get("capabilities") or {}
    allowed_types = set(caps.get("job_types") or [])
    if allowed_types and job_type not in allowed_types:
        job = store.update_remote_job(
            job["id"],
            status="blocked",
            error="capability_missing",
            result={"ok": False, "outcome": "blocked", "error": "capability_missing", "job_type": job_type},
        ) or job
        _record(job["id"], "RUN_FAILED", {"error": "capability_missing"}, component="compute_fabric")
        return job
    proto = int(caps.get("protocol_version") or 0)
    if proto and proto > WORKER_PROTOCOL_VERSION:
        job = store.update_remote_job(
            job["id"],
            status="blocked",
            error="protocol_incompatible",
            result={"ok": False, "outcome": "blocked", "error": "protocol_incompatible"},
        ) or job
        _record(job["id"], "RUN_FAILED", {"error": "protocol_incompatible"}, component="compute_fabric")
        return job

    if not pairing.get("base_url"):
        job = store.update_remote_job(
            job["id"],
            status="unavailable",
            error="worker_unreachable",
            result={"ok": False, "outcome": "unavailable", "error": "worker_base_url_missing", "note": "not_queued_endlessly"},
        ) or job
        if prefer_local_fallback:
            local = execute_typed_job(job_type, payload or {}, data_root=data_root)
            local["executed_on"] = "node_local_fallback"
            local["fallback_reason"] = "worker_base_url_missing"
            job = store.update_remote_job(
                job["id"],
                status="completed" if local.get("ok") else "failed",
                result={**local, "remote_outcome": "unavailable"},
                error=None if local.get("ok") else str(local.get("error")),
            ) or job
        return job

    lease = lease_remote_job(store, job["id"], node_id=target["id"])
    if not lease.get("ok"):
        return store.get_remote_job(job["id"]) or job

    channel = authenticated_channel(
        data_root,
        target["id"],
        method="POST",
        path="/v1/jobs/execute",
        payload={
            "job_id": job["id"],
            "job_type": job_type,
            "payload": payload,
            "lease_token": lease["lease_token"],
            "input_hash": _sha256_text(_canonical_json(payload)),
            "protocol_version": WORKER_PROTOCOL_VERSION,
        },
        timeout=30.0,
    )
    if not channel.get("ok"):
        outcome = channel.get("status") or "unavailable"
        err = str(channel.get("error") or "remote_dispatch_failed")
        job = store.update_remote_job(
            job["id"],
            status="blocked" if outcome == "blocked" else "unavailable",
            error=err,
            result={"ok": False, "outcome": outcome, "error": err, "note": "not_queued_endlessly"},
        ) or job
        if prefer_local_fallback:
            local = execute_typed_job(job_type, payload or {}, data_root=data_root)
            local["executed_on"] = "node_local_fallback"
            local["fallback_reason"] = err
            job = store.update_remote_job(
                job["id"],
                status="completed" if local.get("ok") else "failed",
                result={**local, "remote_outcome": outcome},
                error=None if local.get("ok") else str(local.get("error")),
            ) or job
        _record(job["id"], "RUN_FAILED" if job.get("status") not in {"completed"} else "TOOL_STARTED", {"error": err}, component="compute_fabric")
        return job

    remote_result = channel.get("response") or {}
    # Hash/contract checks
    if remote_result.get("ok") and job_type in {"document_chunk", "document_preprocess"}:
        expected_input = _sha256_text(str((payload or {}).get("text") or (payload or {}).get("content") or ""))
        if remote_result.get("input_hash") and remote_result["input_hash"] != expected_input:
            job = store.update_remote_job(
                job["id"],
                status="failed",
                error="result_input_hash_mismatch",
                result={"ok": False, "error": "result_input_hash_mismatch", "remote": remote_result},
            ) or job
            return job

    ack = ack_remote_result(
        store,
        job["id"],
        lease_token=str(lease["lease_token"]),
        result={**remote_result, "executed_on": target["id"], "mode": mode},
        error=None if remote_result.get("ok") else str(remote_result.get("error") or "worker_failed"),
    )
    job = ack.get("job") or store.get_remote_job(job["id"]) or job
    # Worker heartbeat / visible status
    store.upsert_node(
        {
            **target,
            "status": "online",
            "last_heartbeat": utc_now(),
            "load": (remote_result.get("load") or target.get("load") or {}),
        }
    )
    _record(
        job["id"],
        "TOOL_STARTED" if job.get("status") == "completed" else "RUN_FAILED",
        {"node_id": target["id"], "mode": mode, "job_type": job_type, "lan": True},
        component="compute_fabric",
    )
    return job


def cancel_job(
    store: Gen2Store,
    job_id: str,
    *,
    record_fn: RecordFn | None = None,
    data_root: Path | None = None,
) -> dict[str, Any]:
    job = store.get_remote_job(job_id)
    if not job:
        raise ValueError("job not found")
    if job["status"] in {"completed", "failed", "cancelled", "blocked"}:
        return job
    # Best-effort cancel notify to paired worker.
    if data_root is not None:
        pairing = load_pairing(data_root, str(job.get("node_id") or ""))
        if pairing and pairing.get("base_url"):
            authenticated_channel(
                data_root,
                str(job["node_id"]),
                method="POST",
                path="/v1/jobs/cancel",
                payload={"job_id": job_id},
                timeout=5.0,
            )
    updated = store.update_remote_job(job_id, status="cancelled") or job
    if record_fn is not None:
        record_fn(job_id, "RUN_CANCELLED", {}, component="compute_fabric")
    return updated


def recover_expired_leases(store: Gen2Store) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    now = time.time()
    for job in store.list_remote_jobs(limit=200):
        if job.get("status") != "leased":
            continue
        lease = ((job.get("result") or {}).get("lease") or {})
        exp = lease.get("expires_at")
        if exp is not None and float(exp) < now:
            updated = store.update_remote_job(job["id"], status="queued", error="lease_expired_recovered") or job
            recovered.append(updated)
    return recovered


def worker_status(store: Gen2Store, data_root: Path) -> dict[str, Any]:
    nodes = discover_nodes(store, data_root)
    peers = list_pairings(data_root)
    return {
        "local": next((n for n in nodes if n["id"] == "node_local"), None),
        "nodes": nodes,
        "paired_workers": peers,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "supported_job_types": sorted(COMPUTE_JOB_TYPES.keys()),
        "mode": "lan_worker_mvp",
        "physical_multi_machine_verified": False,
        "note": "Peer management is local (no cloud account). Multi-host remains unverified.",
    }


# ---------------------------------------------------------------------------
# Worker HTTP process (coordinator + worker as two processes on one host)
# ---------------------------------------------------------------------------


class LanWorkerServer:
    """Minimal authenticated LAN worker for typed jobs (no remote shell)."""

    def __init__(
        self,
        *,
        node_id: str,
        shared_secret: str,
        fingerprint: str,
        host: str = "127.0.0.1",
        port: int = 0,
        capabilities: dict[str, Any] | None = None,
    ) -> None:
        self.node_id = node_id
        self.shared_secret = shared_secret
        self.fingerprint = fingerprint
        self.host = host
        self.port = port
        self.capabilities = capabilities or {
            "job_types": [CAPABILITY_DOCUMENT_CHUNK, "ping", "heartbeat", "local_info"],
            "protocol_version": WORKER_PROTOCOL_VERSION,
        }
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._cancel: set[str] = set()
        self.jobs_executed = 0

    @property
    def base_url(self) -> str:
        if not self._httpd:
            raise RuntimeError("server_not_started")
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> str:
        worker = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                return

            def _read_json(self) -> tuple[dict[str, Any], str]:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                text = raw.decode("utf-8")
                try:
                    data = json.loads(text) if text else {}
                except Exception:
                    data = {}
                # Re-canonicalize from parsed object for HMAC (clients send canonical JSON).
                return data if isinstance(data, dict) else {}, text

            def _unauthorized(self, msg: str) -> None:
                body = json.dumps({"ok": False, "error": msg}).encode()
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _ok(self, payload: dict[str, Any], code: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth(self, body_text: str) -> bool:
                node = self.headers.get("X-HADES-Node-Id") or ""
                ts = self.headers.get("X-HADES-Timestamp") or ""
                sig = self.headers.get("X-HADES-Signature") or ""
                fp = self.headers.get("X-HADES-Fingerprint") or ""
                if node != worker.node_id:
                    return False
                if fp and fp != worker.fingerprint:
                    return False
                return verify_message(worker.shared_secret, body_text, timestamp=ts, node_id=node, signature=sig)

            def do_POST(self) -> None:  # noqa: N802
                data, raw = self._read_json()
                # Clients sign canonical JSON; prefer verifying against canonical form.
                canonical = _canonical_json(data)
                if not (self._auth(canonical) or self._auth(raw)):
                    self._unauthorized("auth_failed")
                    return
                if self.path == "/v1/jobs/execute":
                    job_id = str(data.get("job_id") or "")
                    if job_id in worker._cancel:
                        self._ok({"ok": False, "error": "cancelled", "fingerprint": worker.fingerprint})
                        return
                    job_type = str(data.get("job_type") or "")
                    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
                    result = execute_typed_job(job_type, payload or {})
                    result["fingerprint"] = worker.fingerprint
                    result["worker_node_id"] = worker.node_id
                    result["lease_token"] = data.get("lease_token")
                    worker.jobs_executed += 1
                    self._ok(result)
                    return
                if self.path == "/v1/jobs/cancel":
                    job_id = str(data.get("job_id") or "")
                    worker._cancel.add(job_id)
                    self._ok({"ok": True, "cancelled": job_id, "fingerprint": worker.fingerprint})
                    return
                if self.path == "/v1/capabilities":
                    self._ok(
                        {
                            "ok": True,
                            "fingerprint": worker.fingerprint,
                            "capabilities": worker.capabilities,
                            "node_id": worker.node_id,
                        }
                    )
                    return
                self._ok({"ok": False, "error": "unknown_path"}, code=404)

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def process_local_queue(
    store: Gen2Store,
    data_root: Path,
    *,
    limit: int = 20,
    record_fn: RecordFn | None = None,
) -> dict[str, Any]:
    """Drain queued jobs targeted at ``node_local`` (single-node solidity)."""
    ensure_local_node(store, data_root)
    processed: list[dict[str, Any]] = []
    for job in store.list_remote_jobs(limit=200):
        if len(processed) >= max(1, min(int(limit), 100)):
            break
        if job.get("status") != "queued":
            continue
        if str(job.get("node_id") or "") not in {"node_local", "", "local"}:
            continue
        payload = dict(job.get("payload") or {})
        job_type = str(
            payload.get("type") or payload.get("op") or payload.get("job_type") or ""
        ).strip().lower()
        result = execute_typed_job(job_type, payload, data_root=data_root)
        status = "completed" if result.get("ok") else "failed"
        if job_type not in COMPUTE_JOB_TYPES:
            status = "failed"
            result = {
                "ok": False,
                "error": f"unsupported_job_type:{job_type or 'missing'}",
                "supported_types": sorted(COMPUTE_JOB_TYPES.keys()),
                "mode": "rejected",
            }
        updated = store.update_remote_job(
            job["id"],
            status=status,
            result={**result, "executed_on": "node_local", "queue_drained": True},
            error=None if result.get("ok") else str(result.get("error") or "failed"),
        ) or job
        if record_fn is not None:
            record_fn(
                job["id"],
                "TOOL_STARTED" if status == "completed" else "RUN_FAILED",
                {"queue": "local", "job_type": job_type},
                component="compute_fabric",
            )
        processed.append(updated)
    failed = [j for j in processed if str(j.get("status") or "") == "failed"]
    return {
        "ok": not failed,
        "processed": len(processed),
        "failed_count": len(failed),
        "jobs": processed,
        "mode": "single_node_local_queue",
        "multi_host": False,
        "error": "queue_jobs_failed" if failed else None,
    }


def single_node_solidity_gate(store: Gen2Store, data_root: Path) -> dict[str, Any]:
    """Explicit gate: single-node queue/dispatch/heartbeat must pass before multi-host (L6)."""
    node = ensure_local_node(store, data_root)
    beat = heartbeat(store, data_root, node["id"])
    ping = dispatch_job(store, data_root, payload={"op": "ping"})
    queued = store.create_remote_job(
        {"node_id": "node_local", "status": "queued", "payload": {"op": "echo", "msg": "gate"}}
    )
    drained = process_local_queue(store, data_root, limit=5)
    peers = list_pairings(data_root)
    checks = {
        "local_node_online": beat.get("status") == "online",
        "dispatch_ping_completed": ping.get("status") == "completed",
        "queue_drain_processed": drained.get("processed", 0) >= 1,
        "no_unbounded_shell": "shell" not in COMPUTE_JOB_TYPES,
    }
    passed = all(checks.values())
    return {
        "gate": "L6_single_node_solidity",
        "passed": passed,
        "checks": checks,
        "queued_probe_id": queued["id"],
        "paired_workers": len(peers),
        "multi_host_deferred": True,
        "multi_host_allowed": False,
        "physical_multi_machine_verified": False,
        "note": "Multi-host remains deferred until this gate stays green and a second host is verified.",
    }


def distributed_fabric_status(data_root: Path | None = None) -> dict[str, Any]:
    peers = list_pairings(data_root) if data_root else []
    return {
        "implemented_local": True,
        "implemented_lan_worker_mvp": True,
        "implemented_distributed": False,
        "available_on_host": True,
        "operationally_tested_distributed": False,
        "operationally_tested_lan_same_host": True,
        "quality_evaluated": False,
        "paired_workers": len(peers),
        "supported_job_types": sorted(COMPUTE_JOB_TYPES.keys()),
        "unbounded_remote_shell": False,
        "cloud_account_required": False,
        "mode": "lan_worker_mvp",
        "remote_dispatch": "paired_lan_or_blocked",
        "simulated_distributed": False,
        "multi_host_deferred": True,
        "multi_host_gate": "L6_single_node_solidity",
        "interfaces": [
            "node_identity",
            "pairing",
            "authenticated_channel",
            "capability_advertisement",
            "job_lease",
            "heartbeat",
            "reconnect_via_lease_recovery",
            "cancellation",
            "idempotent_dispatch",
            "result_provenance",
            "input_result_hash_contracts",
            "local_queue_drain",
            "single_node_solidity_gate",
        ],
    }


# Back-compat class name referenced by older docs/tests.
class DistributedNodeIdentity:
    """Stable node identity for peering."""

    def __init__(self, node_id: str, public_key_fingerprint: str | None = None) -> None:
        self.node_id = node_id
        self.public_key_fingerprint = public_key_fingerprint

    def to_public(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "public_key_fingerprint": self.public_key_fingerprint,
            "distributed": False,
            "lan_worker_mvp": True,
        }
