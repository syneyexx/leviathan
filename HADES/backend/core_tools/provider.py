"""In-process invoke path for HADES core tools."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .catalog import (
    CAPABILITIES_INSPECT,
    CAPABILITIES_INVOKE,
    CAPABILITIES_SEARCH,
    CAPABILITY_SEARCH_ALIASES,
    CORE_PLUGIN_ID,
    DISCOVER_ALIASES,
    DISCOVER_PLUGINS,
    FS_LIST,
    FS_READ,
    FS_WRITE,
    KNOWLEDGE_SEARCH,
    MEMORY_PROPOSE,
    TERMINAL,
    WEB_FETCH,
    _canonical_core_name,
    is_capability_broker_tool,
    is_core_tool,
)
from .jail import resolve_inside_jail, resolve_jail_root

_MAX_READ_BYTES = 200_000
_MAX_LIST_ENTRIES = 500
_TEXT_SAMPLE = 4096


def record_core_blocked(
    *,
    platform_db: Any | None,
    tool_name: str,
    arguments: dict[str, Any],
    reason_code: str,
    error: str,
    invocation_type: str = "autonomous",
) -> dict[str, Any]:
    """Persist a blocked core-tool observation when a platform DB is available."""
    started = time.perf_counter()
    payload = {
        "id": None,
        "plugin_id": CORE_PLUGIN_ID,
        "tool_name": tool_name,
        "status": "blocked",
        "error": error,
        "reason_code": reason_code,
        "exit_code": None,
        "invocation_type": invocation_type,
        "stdout": "",
        "stderr": error,
        "output": json.dumps({"status": "blocked", "reason_code": reason_code, "error": error}, ensure_ascii=False),
        "metadata": {"core": True, "reason_code": reason_code, "rejected": True},
        "duration_ms": 0,
    }
    if platform_db is None:
        return payload
    try:
        call_id = platform_db.create_tool_call(
            CORE_PLUGIN_ID,
            tool_name,
            arguments,
            invocation_type=invocation_type,
            approved_by_user=False,
            metadata={"core": True, "reason_code": reason_code, "rejected": True},
        )
        finished = platform_db.finish_tool_call(
            call_id,
            "blocked",
            stderr=error,
            error=error,
            duration_ms=int((time.perf_counter() - started) * 1000),
            metadata={"core": True, "reason_code": reason_code, "rejected": True},
            output=payload["output"],
        )
        if isinstance(finished, dict):
            return {**payload, **finished, "reason_code": reason_code, "status": "blocked"}
        payload["id"] = call_id
    except Exception as exc:
        payload["metadata"]["persist_error"] = type(exc).__name__
    return payload


def _policy_blocked(kind: str | None, settings: dict[str, Any], *, approved: bool = False) -> dict[str, Any] | None:
    if not kind:
        return None
    key = f"{kind}_policy"
    # Aliases used elsewhere in HADES.
    if kind == "network":
        raw = settings.get(key, settings.get("network_policy", "block"))
    elif kind == "file_read":
        raw = settings.get(key, settings.get("file_read_policy", "allow"))
    elif kind == "file_write":
        raw = settings.get(key, settings.get("file_write_policy", "ask"))
    elif kind == "subprocess":
        raw = settings.get(key, settings.get("subprocess_policy", "allow"))
    else:
        raw = settings.get(key)
    policy = str(raw or "allow").strip().lower()
    if policy == "allow":
        return None
    if policy == "block":
        return {
            "reason_code": f"{kind}_policy=block" if kind != "network" else "network_policy=block",
            "error": f"Core tool blocked by global {kind}_policy=block",
        }
    if policy == "ask":
        if not approved:
            return {
                "reason_code": f"{kind}_policy=ask",
                "error": f"Core tool requires explicit approval for {kind}_policy=ask",
                "status": "approval_required",
            }
        return None
    return {
        "reason_code": f"unknown_{kind}_policy",
        "error": f"Unknown {kind}_policy={policy!r} — fail-closed",
    }


def _looks_binary(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    # High ratio of non-text bytes → refuse dump.
    if not sample:
        return False
    textish = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b < 127)
    return (textish / max(1, len(sample))) < 0.85


def _finish_ok(
    *,
    tool_name: str,
    started: float,
    stdout: str = "",
    output: Any = None,
    metadata: dict[str, Any] | None = None,
    platform_db: Any | None = None,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = output if output is not None else stdout
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    row = {
        "id": None,
        "plugin_id": CORE_PLUGIN_ID,
        "tool_name": tool_name,
        "status": "completed",
        "error": None,
        "exit_code": 0,
        "invocation_type": "autonomous",
        "stdout": stdout or text[:100_000],
        "stderr": "",
        "output": text[:100_000],
        "structured_output": body if isinstance(body, dict) else None,
        "metadata": {"core": True, **(metadata or {})},
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    if platform_db is not None:
        try:
            call_id = platform_db.create_tool_call(
                CORE_PLUGIN_ID,
                tool_name,
                arguments or {},
                invocation_type="autonomous",
                approved_by_user=False,
                metadata={"core": True},
            )
            finished = platform_db.finish_tool_call(
                call_id,
                "completed",
                stdout=row["stdout"],
                output=row["output"],
                exit_code=0,
                duration_ms=row["duration_ms"],
                metadata=row["metadata"],
            )
            if isinstance(finished, dict):
                return {**row, **finished, "status": "completed", "structured_output": row["structured_output"]}
            row["id"] = call_id
        except Exception as exc:
            row["metadata"]["persist_error"] = type(exc).__name__
    return row


def invoke_core_tool(
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    data_root: Path | str,
    settings: dict[str, Any] | None = None,
    platform_db: Any | None = None,
    database: Any | None = None,
    terminal_service: Any | None = None,
    web_research: Any | None = None,
    discover_fn: Callable[..., dict[str, Any]] | None = None,
    capability_broker: Any | None = None,
    approved_file_write: bool = False,
    approved_network: bool = False,
    approved_subprocess: bool = False,
    approved_capability: bool = False,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    """Execute one core tool in-process. Never spawns a plugin subprocess for these."""
    started = time.perf_counter()
    name = _canonical_core_name(str(tool_name or "")) or str(tool_name or "").strip()
    args = arguments if isinstance(arguments, dict) else {}
    cfg = dict(settings or {})
    root = Path(data_root).expanduser().resolve(strict=False)
    ws = Path(workspace).expanduser().resolve(strict=False) if workspace else None

    if not is_core_tool(name) and name not in DISCOVER_ALIASES:
        return record_core_blocked(
            platform_db=platform_db,
            tool_name=name,
            arguments=args,
            reason_code="unknown_tool",
            error=f"Unknown core tool '{name}'",
        )

    # --- Capability broker tools (search / inspect / invoke) ---------------
    if is_capability_broker_tool(name) or name in CAPABILITY_SEARCH_ALIASES:
        broker = capability_broker
        if broker is None:
            # Fall back: legacy discover_fn for search-only aliases.
            if name in CAPABILITY_SEARCH_ALIASES or name in DISCOVER_ALIASES or name == DISCOVER_PLUGINS:
                if discover_fn is None:
                    return record_core_blocked(
                        platform_db=platform_db,
                        tool_name=name,
                        arguments=args,
                        reason_code="unknown_tool",
                        error="Capability broker / discover function unavailable",
                    )
                page = discover_fn(
                    str(args.get("query") or ""),
                    limit=min(20, int(args.get("limit") or 8)),
                    offset=max(0, int(args.get("offset") or 0)),
                    category=str(args["category"]) if args.get("category") else None,
                )
                return _finish_ok(
                    tool_name=CAPABILITIES_SEARCH if name != DISCOVER_PLUGINS else DISCOVER_PLUGINS,
                    started=started,
                    output=page,
                    platform_db=platform_db,
                    arguments=args,
                    metadata={"discovery": True, "broker": False},
                )
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="unknown_tool",
                error="Capability broker unavailable",
            )

        if name in CAPABILITY_SEARCH_ALIASES or name in DISCOVER_ALIASES or name == DISCOVER_PLUGINS:
            page = broker.search(
                str(args.get("query") or ""),
                limit=min(20, int(args.get("limit") or 5)),
            )
            # Preserve a tools[] shape for older callers that expect discover pagination.
            compact_tools = [
                {
                    "capability_id": m.get("capability_id"),
                    "plugin_id": str(m.get("capability_id") or "").split(":")[1]
                    if str(m.get("capability_id") or "").count(":") >= 2
                    else "",
                    "tool_name": m.get("name"),
                    "description": m.get("description"),
                    "available": m.get("available"),
                    "availability_reason": m.get("availability_reason"),
                    "score": m.get("score"),
                }
                for m in page.get("matches") or []
            ]
            output = {
                **page,
                "tools": compact_tools,
                "total": page.get("total_indexed"),
                "offset": 0,
                "next_offset": None,
            }
            return _finish_ok(
                tool_name=CAPABILITIES_SEARCH if name != DISCOVER_PLUGINS else DISCOVER_PLUGINS,
                started=started,
                output=output,
                platform_db=platform_db,
                arguments=args,
                metadata={"discovery": True, "broker": True, "capability_search_used": True},
            )

        if name == CAPABILITIES_INSPECT:
            cap_id = str(args.get("capability_id") or "").strip()
            if not cap_id:
                return record_core_blocked(
                    platform_db=platform_db,
                    tool_name=name,
                    arguments=args,
                    reason_code="invalid_arguments",
                    error="capability_id is required",
                )
            detail = broker.inspect(cap_id)
            return _finish_ok(
                tool_name=CAPABILITIES_INSPECT,
                started=started,
                output=detail,
                platform_db=platform_db,
                arguments=args,
                metadata={"broker": True, "capability_id": cap_id},
            )

        if name == CAPABILITIES_INVOKE:
            cap_id = str(args.get("capability_id") or "").strip()
            if not cap_id:
                return record_core_blocked(
                    platform_db=platform_db,
                    tool_name=name,
                    arguments=args,
                    reason_code="invalid_arguments",
                    error="capability_id is required",
                )
            invoke_args = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
            # Never trust model-supplied security metadata nested in arguments.
            forged = args.get("autonomous"), args.get("trust"), args.get("effects")
            _ = forged
            result = broker.invoke(
                cap_id,
                invoke_args,
                approved_by_user=bool(approved_capability),
                approved_network=bool(approved_network),
                approved_file_read=False,
                approved_file_write=bool(approved_file_write),
                approved_subprocess=bool(approved_subprocess),
                model_metadata={k: args[k] for k in ("autonomous", "trust", "effects") if k in args},
            )
            status = str(result.get("status") or "completed")
            if status in {"blocked", "approval_required", "failed"}:
                # Persist as a core observation wrapping the broker outcome.
                if platform_db is not None:
                    try:
                        call_id = platform_db.create_tool_call(
                            CORE_PLUGIN_ID,
                            CAPABILITIES_INVOKE,
                            args,
                            invocation_type="autonomous",
                            approved_by_user=bool(approved_capability),
                            metadata={"core": True, "broker": True, "capability_id": cap_id},
                        )
                        finished = platform_db.finish_tool_call(
                            call_id,
                            status,
                            stderr=str(result.get("error") or ""),
                            error=str(result.get("error") or ""),
                            output=json.dumps(result, ensure_ascii=False)[:100_000],
                            duration_ms=int(result.get("duration_ms") or (time.perf_counter() - started) * 1000),
                            metadata={
                                "core": True,
                                "broker": True,
                                "capability_id": cap_id,
                                "reason_code": result.get("reason_code"),
                                "selected_capability_id": cap_id,
                                "provider": result.get("provider"),
                                "provider_id": result.get("provider_id"),
                                "approval_required": status == "approval_required",
                                "blocked_reason": result.get("reason_code") if status == "blocked" else None,
                                "execution_status": status,
                            },
                        )
                        if isinstance(finished, dict):
                            return {**result, **finished, "status": status, "structured_output": result}
                    except Exception as exc:
                        result = {**result, "persist_error": type(exc).__name__}
                return result
            return _finish_ok(
                tool_name=CAPABILITIES_INVOKE,
                started=started,
                output=result,
                platform_db=platform_db,
                arguments=args,
                metadata={
                    "broker": True,
                    "capability_id": cap_id,
                    "selected_capability_id": cap_id,
                    "provider": result.get("provider"),
                    "provider_id": result.get("provider_id"),
                    "execution_status": status,
                },
            )


    if name == WEB_FETCH:
        gate = _policy_blocked("network", cfg, approved=approved_network)
        if gate:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code=str(gate["reason_code"]),
                error=str(gate["error"]),
            )
        url = str(args.get("url") or "").strip()
        if not url:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="invalid_arguments",
                error="url is required",
            )
        max_chars = int(args.get("max_chars") or 12_000)
        max_chars = max(200, min(50_000, max_chars))
        if web_research is None:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="network_policy=block",
                error="Web research service unavailable",
            )
        try:
            import asyncio

            async def _fetch() -> Any:
                return await web_research.fetch(url)

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # Caller should use async path; fall back to thread-hostile sync refusal.
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    crawl = pool.submit(lambda: asyncio.run(_fetch())).result(timeout=60)
            else:
                crawl = asyncio.run(_fetch())
            text = str(getattr(crawl, "text", "") or "")[:max_chars]
            title = str(getattr(crawl, "title", "") or "")
            return _finish_ok(
                tool_name=name,
                started=started,
                output={
                    "url": url,
                    "title": title,
                    "text": text,
                    "provenance": f"web_fetch:{url}",
                    "truncated": len(str(getattr(crawl, "text", "") or "")) > max_chars,
                },
                platform_db=platform_db,
                arguments=args,
            )
        except Exception as exc:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="network_error",
                error=f"web_fetch failed: {exc}",
            )

    if name in {FS_LIST, FS_READ}:
        gate = _policy_blocked("file_read", cfg)
        if gate:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code=str(gate["reason_code"]),
                error=str(gate["error"]),
            )
        target, reason = resolve_inside_jail(
            str(args.get("path") or ".") if name == FS_LIST else str(args.get("path") or ""),
            data_root=root,
            workspace=ws,
            default_relative="." if name == FS_LIST else "",
        )
        if reason or target is None:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code=reason or "path_outside_jail",
                error="Path is outside the HADES data/workspace jail",
            )
        if name == FS_LIST:
            if not target.exists():
                return record_core_blocked(
                    platform_db=platform_db,
                    tool_name=name,
                    arguments=args,
                    reason_code="not_found",
                    error=f"Path not found: {target}",
                )
            if not target.is_dir():
                return record_core_blocked(
                    platform_db=platform_db,
                    tool_name=name,
                    arguments=args,
                    reason_code="not_a_directory",
                    error=f"Not a directory: {target}",
                )
            entries = []
            for child in sorted(target.iterdir(), key=lambda p: p.name.lower())[:_MAX_LIST_ENTRIES]:
                entries.append(
                    {
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": child.stat().st_size if child.is_file() else None,
                    }
                )
            jail = resolve_jail_root(root, workspace=ws)
            return _finish_ok(
                tool_name=name,
                started=started,
                output={"path": str(target.relative_to(jail)), "entries": entries, "jail": str(jail)},
                platform_db=platform_db,
                arguments=args,
            )
        # FS_READ
        if not target.is_file():
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="not_a_file",
                error=f"Not a readable file: {target}",
            )
        size = target.stat().st_size
        if size > _MAX_READ_BYTES:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="file_too_large",
                error=f"File exceeds {_MAX_READ_BYTES} byte read cap",
            )
        raw = target.read_bytes()
        if _looks_binary(raw[:_TEXT_SAMPLE]):
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="binary_refused",
                error="Binary file dumps are not allowed via hades.fs_read",
            )
        text = raw.decode("utf-8", errors="replace")
        jail = resolve_jail_root(root, workspace=ws)
        return _finish_ok(
            tool_name=name,
            started=started,
            output={"path": str(target.relative_to(jail)), "content": text, "bytes": len(raw)},
            platform_db=platform_db,
            arguments=args,
        )

    if name == FS_WRITE:
        gate = _policy_blocked("file_write", cfg, approved=approved_file_write)
        if gate:
            status = str(gate.get("status") or "blocked")
            row = record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code=str(gate["reason_code"]),
                error=str(gate["error"]),
            )
            if status == "approval_required":
                row["status"] = "approval_required"
            return row
        target, reason = resolve_inside_jail(
            str(args.get("path") or ""),
            data_root=root,
            workspace=ws,
            default_relative="",
        )
        if reason or target is None:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code=reason or "path_outside_jail",
                error="Path is outside the HADES data/workspace jail",
            )
        content = str(args.get("content") if args.get("content") is not None else "")
        overwrite = bool(args.get("overwrite", True))
        if target.exists() and not overwrite:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="exists",
                error="File exists and overwrite=false",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        jail = resolve_jail_root(root, workspace=ws)
        return _finish_ok(
            tool_name=name,
            started=started,
            output={"path": str(target.relative_to(jail)), "bytes_written": len(content.encode("utf-8"))},
            platform_db=platform_db,
            arguments=args,
        )

    if name == TERMINAL:
        gate = _policy_blocked("subprocess", cfg, approved=approved_subprocess)
        if gate:
            status = str(gate.get("status") or "blocked")
            row = record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code=str(gate["reason_code"]),
                error=str(gate["error"]),
            )
            if status == "approval_required":
                row["status"] = "approval_required"
            return row
        argv = args.get("argv")
        if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv) or not argv:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="invalid_arguments",
                error="argv must be a non-empty string array",
            )
        if terminal_service is None:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="terminal_unavailable",
                error="Terminal service unavailable",
            )
        try:
            result = terminal_service.run(
                argv,
                cwd=str(args.get("cwd") or "") or None,
                timeout_seconds=int(args.get("timeout_seconds") or 30),
                settings={**cfg, "autonomous": True},
            )
            if isinstance(result, dict):
                status = str(result.get("status") or "completed")
                return {
                    "id": result.get("id"),
                    "plugin_id": CORE_PLUGIN_ID,
                    "tool_name": name,
                    "status": status,
                    "error": result.get("error"),
                    "exit_code": result.get("exit_code"),
                    "invocation_type": "autonomous",
                    "stdout": result.get("stdout") or "",
                    "stderr": result.get("stderr") or "",
                    "output": result.get("output") or result.get("stdout") or "",
                    "metadata": {"core": True, **(result.get("metadata") or {})},
                    "duration_ms": result.get("duration_ms") or int((time.perf_counter() - started) * 1000),
                }
            return _finish_ok(tool_name=name, started=started, stdout=str(result), platform_db=platform_db, arguments=args)
        except PermissionError as exc:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="subprocess_policy=block",
                error=str(exc),
            )
        except Exception as exc:
            return {
                "id": None,
                "plugin_id": CORE_PLUGIN_ID,
                "tool_name": name,
                "status": "failed",
                "error": str(exc),
                "exit_code": 1,
                "invocation_type": "autonomous",
                "stdout": "",
                "stderr": str(exc),
                "metadata": {"core": True},
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }

    if name == KNOWLEDGE_SEARCH:
        query = str(args.get("query") or "").strip()
        limit = max(1, min(20, int(args.get("limit") or 8)))
        if not query:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="invalid_arguments",
                error="query is required",
            )
        if platform_db is None or not hasattr(platform_db, "search_knowledge"):
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="knowledge_unavailable",
                error="Knowledge store unavailable",
            )
        matches = platform_db.search_knowledge(query, limit)
        enriched = []
        for item in matches or []:
            enriched.append(
                {
                    **item,
                    "provenance": item.get("provenance")
                    or item.get("uri")
                    or item.get("source_id")
                    or item.get("id")
                    or "knowledge:unknown",
                }
            )
        return _finish_ok(
            tool_name=name,
            started=started,
            output={"query": query, "matches": enriched},
            platform_db=platform_db,
            arguments=args,
        )

    if name == MEMORY_PROPOSE:
        title = str(args.get("title") or "").strip()
        content = str(args.get("content") or "").strip()
        if not title or not content:
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="invalid_arguments",
                error="title and content are required",
            )
        if database is None or not hasattr(database, "create_memory_proposal"):
            return record_core_blocked(
                platform_db=platform_db,
                tool_name=name,
                arguments=args,
                reason_code="memory_unavailable",
                error="Memory database unavailable",
            )
        proposal = database.create_memory_proposal(
            {
                "title": title,
                "content": content,
                "summary": str(args.get("summary") or "").strip(),
                "collection": str(args.get("collection") or "Algemeen"),
                "origin_kind": "model_inference",
            }
        )
        return _finish_ok(
            tool_name=name,
            started=started,
            output={
                "proposal_id": proposal.get("id"),
                "status": proposal.get("status") or "pending",
                "auto_promoted": False,
                "note": "Proposal created; user must accept before it becomes durable memory.",
            },
            platform_db=platform_db,
            arguments=args,
        )

    return record_core_blocked(
        platform_db=platform_db,
        tool_name=name,
        arguments=args,
        reason_code="unknown_tool",
        error=f"Unhandled core tool '{name}'",
    )
