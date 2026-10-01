"""Invariant A: single authoritative response owner for Chat turns."""

from __future__ import annotations

import pytest

from Data.modules.chat.ownership import (
    assert_single_response_owner,
    bounded_tool_calls_for_turn,
    cognition_owns_final_response,
    resolve_response_owner_and_path,
)
from Data.modules.chat.types import ExecutionPath, ResponseOwner


def test_cognition_owns_only_when_active_with_response() -> None:
    assert cognition_owns_final_response(None) is False
    assert cognition_owns_final_response({"shadow": True, "response": "x", "response_ownership": "cognition"}) is False
    assert cognition_owns_final_response(
        {"response": "hi", "response_ownership": "cognition"},
        cognition_shadow_feature=True,
    ) is False
    assert cognition_owns_final_response({"response": "hi", "response_ownership": "cognition", "error": "boom"}) is False
    assert cognition_owns_final_response({"response": "  ", "response_ownership": "cognition"}) is False
    assert cognition_owns_final_response({"response": "hi", "response_ownership": "direct"}) is False
    assert cognition_owns_final_response({"response": "hi", "response_ownership": "cognition"}) is True


def test_resolve_owner_path_mutually_exclusive() -> None:
    owner, path = resolve_response_owner_and_path(
        {"response": "ok", "response_ownership": "cognition"}
    )
    assert owner == ResponseOwner.COGNITION.value
    assert path == ExecutionPath.COGNITION_OWNED.value
    assert_single_response_owner(owner, path)

    owner, path = resolve_response_owner_and_path(None)
    assert owner == ResponseOwner.DIRECT.value
    assert path == ExecutionPath.DIRECT_CHAT.value
    assert_single_response_owner(owner, path)

    owner, path = resolve_response_owner_and_path(None, team=True)
    assert owner == ResponseOwner.TEAM.value
    assert path == ExecutionPath.TEAM.value


def test_assert_single_response_owner_rejects_cross_claims() -> None:
    with pytest.raises(AssertionError):
        assert_single_response_owner(
            ResponseOwner.DIRECT.value, ExecutionPath.COGNITION_OWNED.value
        )
    with pytest.raises(AssertionError):
        assert_single_response_owner(
            ResponseOwner.COGNITION.value, ExecutionPath.DIRECT_CHAT.value
        )


def test_bounded_tool_calls_skip_payload_bloat() -> None:
    raw = [
        {
            "capability_id": "web.search",
            "status": "COMPLETED",
            "success": True,
            "parts": [{"kind": "text", "text": "ok", "huge": "x" * 100}, "skip"],
            "artifact_refs": [f"a{i}" for i in range(20)],
        },
        {"status": "OK"},  # missing capability_id / module_id
        "not-a-dict",
    ]
    out = bounded_tool_calls_for_turn(raw, limit=24)
    assert len(out) == 1
    assert out[0]["capability_id"] == "web.search"
    assert len(out[0]["artifact_refs"]) == 12
    assert "huge" not in out[0]["parts"][0]
    assert out[0]["parts"][0]["text"] == "ok"
