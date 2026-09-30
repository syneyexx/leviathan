"""Selection authority — no first_eligible / models[0] execution policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.model_runtime.openai_compatible import LLMUnavailable, OpenAICompatibleLLM
from Data.modules.models import ModelControlError, ModelControlPlane
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelRequest,
    selection_reason_is_authorized,
)
from Data.modules.models.errors import NO_MODEL_ASSIGNED


@pytest.fixture()
def plane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelControlPlane:
    db_path = tmp_path / "selection.db"
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.delenv("LEVIATHAN_LLM_MODEL", raising=False)
    monkeypatch.setenv("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false")
    settings = Settings.from_env()
    MigrationRunner(settings.database_path).apply_all()
    control = ModelControlPlane(settings)
    control.bootstrap()
    control.store.set_active_model(None)
    control.router.save_config(
        {"fallbackOrder": [], "roleModelOverrides": {}, "cloudFallbackAllowed": False}
    )
    return control


def _upsert(plane: ModelControlPlane, model_id: str) -> None:
    plane.registry.store.upsert_model(
        {
            "model_id": model_id,
            "display_name": model_id,
            "provider_id": "lm_studio",
            "source": "local",
            "capabilities": ModelCapabilities(chat=CapabilityState.SUPPORTED).public_dict(),
            "lifecycle_state": "available",
            "health": "healthy",
            "metadata": {"provider_model_id": model_id},
        }
    )


def test_authorized_reason_helpers() -> None:
    assert selection_reason_is_authorized("explicit")
    assert selection_reason_is_authorized("role:coding")
    assert selection_reason_is_authorized("active_default")
    assert selection_reason_is_authorized("fallback:configured")
    assert selection_reason_is_authorized("legacy_settings_fallback")
    assert not selection_reason_is_authorized("fallback:first_eligible")
    assert not selection_reason_is_authorized("models[0]")
    assert not selection_reason_is_authorized(None)


@pytest.mark.asyncio
async def test_transport_resolve_model_fails_without_configured_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEVIATHAN_LLM_MODEL", raising=False)
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    settings = Settings.from_env()
    assert not (settings.llm_model or "").strip()
    llm = OpenAICompatibleLLM(settings)
    llm._resolved_model = None

    get_calls: list[str] = []

    class FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def get(self, url: str, headers: dict | None = None):
            get_calls.append(url)
            raise AssertionError("resolve_model must not discover models[0]")

    with mock.patch(
        "Data.modules.model_runtime.openai_compatible.httpx.AsyncClient", FakeClient
    ):
        with pytest.raises(LLMUnavailable) as exc:
            await llm.resolve_model()
    assert "NO_MODEL_ASSIGNED" in str(exc.value)
    assert get_calls == []


@pytest.mark.asyncio
async def test_transport_complete_messages_requires_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEVIATHAN_LLM_MODEL", raising=False)
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    settings = Settings.from_env()
    llm = OpenAICompatibleLLM(settings)
    llm._resolved_model = None
    with pytest.raises(LLMUnavailable) as exc:
        await llm.complete_messages([{"role": "user", "content": "hi"}])
    assert "NO_MODEL_ASSIGNED" in str(exc.value)


@pytest.mark.asyncio
async def test_transport_settings_explicit_model_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEVIATHAN_LLM_MODEL", "qwen-X")
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    settings = Settings.from_env()
    llm = OpenAICompatibleLLM(settings)
    assert await llm.resolve_model() == "qwen-X"


@pytest.mark.asyncio
async def test_transport_health_does_not_select_models_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEVIATHAN_LLM_MODEL", raising=False)
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    settings = Settings.from_env()
    llm = OpenAICompatibleLLM(settings)
    llm._resolved_model = None

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "data": [
                    {"id": "dolphin-first"},
                    {"id": "qwen-second"},
                ]
            }

    class FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def get(self, url: str, headers: dict | None = None):
            assert url.endswith("/models")
            return FakeResp()

        async def post(self, *a: Any, **k: Any):
            raise AssertionError("health must not call chat/completions")

    with mock.patch(
        "Data.modules.model_runtime.openai_compatible.httpx.AsyncClient", FakeClient
    ):
        health = await llm.health()
    assert health["available"] is True
    assert health["model"] is None
    assert health["modelConfigured"] is False
    assert health["discoveredCount"] == 2
    assert health["truth"]["provider_list_order_is_not_selection_policy"] is True


@pytest.mark.asyncio
async def test_inference_session_rejects_unauthorized_target(plane: ModelControlPlane) -> None:
    _upsert(plane, "alpha-model")
    target = plane.resolve_target(explicit_model_id="alpha-model")
    # Forge an unauthorized reason as if a stale path leaked through.
    target.route.reason = "fallback:first_eligible"
    target.route.authorized = False
    target.route.selection_source = "unauthorized"

    class BoomLLM:
        async def complete_messages(self, *a: Any, **k: Any) -> dict:
            raise AssertionError("unauthorized target must not reach transport")

    plane.bind_llm(BoomLLM())
    with pytest.raises(ModelControlError) as exc:
        async with plane.inference_session(target, consumer="test") as session:
            await session.complete_messages([{"role": "user", "content": "hi"}])
    assert exc.value.code == NO_MODEL_ASSIGNED


@pytest.mark.asyncio
async def test_authorized_inference_passes_backend_model_id(plane: ModelControlPlane) -> None:
    _upsert(plane, "exact-backend")
    plane.registry.activate("exact-backend")
    seen: dict[str, Any] = {}

    class CaptureLLM:
        async def complete_messages(self, messages: list, **kwargs: Any) -> dict:
            seen.update(kwargs)
            return {"text": "ok", "usage": {}}

    plane.bind_llm(CaptureLLM())
    async with plane.inference_session(
        consumer="test", preferred_role="chat"
    ) as session:
        assert session.backend_model_id == "exact-backend"
        await session.complete_messages([{"role": "user", "content": "hi"}])
    assert seen.get("model_id") == "exact-backend"


def test_settings_fallback_requires_concrete_model(
    plane: ModelControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LEVIATHAN_LLM_MODEL", raising=False)
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    settings = Settings.from_env()
    assert not (settings.llm_model or "").strip()
    local = ModelControlPlane(settings)
    with pytest.raises(ModelControlError) as exc:
        local.resolve_settings_external_fallback(router_error_code="NO_MODEL_ASSIGNED")
    assert exc.value.code == "ROUTER_EXHAUSTED"
    assert exc.value.details.get("hasModel") is False


def test_no_first_eligible_execution_path_in_router_source() -> None:
    from pathlib import Path

    src = Path("Data/modules/models/router.py").read_text(encoding="utf-8")
    assert 'try_model(model.id, "fallback:first_eligible")' not in src
    assert 'reason="fallback:first_eligible"' not in src
    transport = Path("Data/modules/model_runtime/openai_compatible.py").read_text(encoding="utf-8")
    assert 'models[0]["id"]' not in transport
    assert "models[0].get" not in transport
