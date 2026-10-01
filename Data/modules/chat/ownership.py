"""Response-owner invariants for Chat (Invariant A: one authoritative owner).

CognitiveRuntime may own the final answer; when it does, the direct model path
must not also produce an authoritative completion for the same turn.
"""

from __future__ import annotations

from typing import Any

from .types import ExecutionPath, ResponseOwner


def cognition_owns_final_response(
    cognition_meta: dict[str, Any] | None,
    *,
    cognition_shadow_feature: bool = False,
) -> bool:
    """True when ACTIVE cognition produced an authoritative answer.

    Shadow cognition and feature-forced shadow never own the final response.
    Missing/empty response or ownership≠cognition keeps the direct chat path.
    """
    if not cognition_meta or not isinstance(cognition_meta, dict):
        return False
    if cognition_meta.get("shadow") or cognition_shadow_feature:
        return False
    if cognition_meta.get("error"):
        return False
    if cognition_meta.get("response_ownership") != "cognition":
        return False
    response = cognition_meta.get("response")
    if not isinstance(response, str) or not response.strip():
        return False
    return True


def resolve_response_owner_and_path(
    cognition_meta: dict[str, Any] | None,
    *,
    cognition_shadow_feature: bool = False,
    team: bool = False,
) -> tuple[str, str]:
    """Return (response_owner, execution_path) for durable turn completion.

    Invariant: cognition-owned and direct are mutually exclusive owners.
    TEAM overrides when explicitly requested (orthogonal collaboration path).
    """
    if team:
        return ResponseOwner.TEAM.value, ExecutionPath.TEAM.value
    if cognition_owns_final_response(
        cognition_meta, cognition_shadow_feature=cognition_shadow_feature
    ):
        return ResponseOwner.COGNITION.value, ExecutionPath.COGNITION_OWNED.value
    return ResponseOwner.DIRECT.value, ExecutionPath.DIRECT_CHAT.value


def assert_single_response_owner(owner: str, execution_path: str) -> None:
    """Guard: cognition-owned path must not claim direct ownership (and vice versa)."""
    if execution_path == ExecutionPath.COGNITION_OWNED.value:
        if owner != ResponseOwner.COGNITION.value:
            raise AssertionError(
                f"Invariant A violated: cognition_owned path with owner={owner!r}"
            )
    if owner == ResponseOwner.COGNITION.value:
        if execution_path not in {
            ExecutionPath.COGNITION_OWNED.value,
            ExecutionPath.COGNITION_SHADOW.value,
        }:
            raise AssertionError(
                f"Invariant A violated: cognition owner with path={execution_path!r}"
            )
    if owner == ResponseOwner.DIRECT.value and execution_path == ExecutionPath.COGNITION_OWNED.value:
        raise AssertionError("Invariant A violated: direct owner on cognition_owned path")


def bounded_tool_calls_for_turn(tool_calls: list[Any] | None, *, limit: int = 24) -> list[dict[str, Any]]:
    """Persist a bounded tool-call summary on the turn — no payload duplication of large blobs."""
    out: list[dict[str, Any]] = []
    for raw in (tool_calls or [])[:limit]:
        if not isinstance(raw, dict):
            continue
        cap = raw.get("capability_id") or raw.get("module_id")
        if not cap:
            continue
        parts = raw.get("parts")
        bounded_parts: list[Any] = []
        if isinstance(parts, list):
            for part in parts[:8]:
                if isinstance(part, dict):
                    # Keep small display fields only.
                    bounded_parts.append(
                        {
                            k: part[k]
                            for k in (
                                "kind",
                                "type",
                                "title",
                                "name",
                                "url",
                                "text",
                                "message",
                                "phase",
                                "summary",
                                "error",
                                "code",
                                "artifact_id",
                                "ref",
                                "filename",
                                "artifacts",
                                "sources",
                                "rows",
                            )
                            if k in part
                        }
                    )
        item: dict[str, Any] = {
            "capability_id": str(cap),
            "status": str(raw.get("status") or "UNKNOWN"),
            "success": raw.get("success"),
            "duration_ms": raw.get("duration_ms"),
            "receipt_id": raw.get("receipt_id"),
            "error": raw.get("error"),
            "summary": raw.get("summary"),
            "provider": raw.get("provider"),
            "module_id": raw.get("module_id"),
            "result_count": raw.get("result_count"),
            "source_count": raw.get("source_count"),
            "artifact_refs": list(raw.get("artifact_refs") or [])[:12]
            if isinstance(raw.get("artifact_refs"), list)
            else [],
        }
        if bounded_parts:
            item["parts"] = bounded_parts
        out.append(item)
    return out
