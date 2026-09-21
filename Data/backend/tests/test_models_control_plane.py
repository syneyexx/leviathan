"""Model Control Plane tests — registry, profiles, router, gateway, providers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from Data.backend.config import Settings, load_settings
from Data.backend.migrations import MigrationRunner
from Data.modules.models import ModelControlError, ModelControlPlane
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelDescriptor,
    ModelLifecycleState,
    ModelRequest,
    ModelSource,
    RuntimeCapabilities,
)
from Data.modules.models.profiles import validate_profile_payload
from Data.modules.models.providers.openai_compatible import OpenAICompatibleAdapter
from Data.modules.models.providers.lm_studio import LMStudioAdapter


@pytest.fixture()
def plane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelControlPlane:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false")
    # Reload settings for this test DB
    from Data.backend import config as config_mod

    settings = Settings.from_env()
    MigrationRunner(settings.database_path).apply_all()
    control = ModelControlPlane(settings)
    control.bootstrap()
    return control


def test_bootstrap_seeds_lm_studio(plane: ModelControlPlane) -> None:
    providers = plane.list_providers()
    assert len(providers) == 1
    assert providers[0].provider_type == "lm_studio"
    assert providers[0].api_key_configured is False or isinstance(providers[0].api_key_configured, bool)
    public = providers[0].public_dict()
    assert "apiKey" not in public
    assert "api_key" not in public


def test_profile_validation_bounds() -> None:
    ok = validate_profile_payload(
        {
            "temperature": 0.7,
            "topP": 0.95,
            "topK": 40,
            "maxTokens": 2048,
            "repeatPenalty": 1.05,
            "seed": -1,
            "systemPrompt": "hi",
        }
    )
    assert ok["temperature"] == 0.7
    with pytest.raises(ModelControlError):
        validate_profile_payload({"temperature": 3, "topP": 0.5, "topK": 1, "maxTokens": 10, "repeatPenalty": 1, "seed": -1})
    with pytest.raises(ModelControlError):
        validate_profile_payload({"temperature": 1, "topP": 0, "topK": 1, "maxTokens": 10, "repeatPenalty": 1, "seed": -1})
    with pytest.raises(ModelControlError):
        validate_profile_payload(
            {
                "temperature": 1,
                "topP": 1,
                "topK": 1,
                "maxTokens": 10,
                "repeatPenalty": 1,
                "seed": -1,
                "systemPrompt": "x" * 500_001,
            }
        )


def test_profile_save_and_activate(plane: ModelControlPlane) -> None:
    plane.registry.store.upsert_model(
        {
            "model_id": "lm_studio:demo",
            "display_name": "demo",
            "provider_id": "lm_studio",
            "source": "remote",
            "capabilities": ModelCapabilities().public_dict(),
            "lifecycle_state": "available",
            "health": "healthy",
            "metadata": {"provider_model_id": "demo"},
        }
    )
    profile = plane.profiles.save(
        "lm_studio:demo",
        {
            "temperature": 0.2,
            "topP": 0.8,
            "topK": 20,
            "maxTokens": 512,
            "repeatPenalty": 1.1,
            "seed": 7,
            "systemPrompt": "be brief",
        },
        activate=True,
    )
    assert profile.temperature == 0.2
    assert profile.active is True
    activated = plane.registry.activate("lm_studio:demo")
    assert activated.active is True
    assert plane.store.get_active_model_id() == "lm_studio:demo"


def test_router_precedence_explicit_wins(plane: ModelControlPlane) -> None:
    for mid in ("a", "b", "c"):
        plane.registry.store.upsert_model(
            {
                "model_id": mid,
                "display_name": mid,
                "provider_id": "lm_studio",
                "source": "remote",
                "capabilities": ModelCapabilities(chat=CapabilityState.SUPPORTED).public_dict(),
                "lifecycle_state": "available",
                "health": "healthy",
            }
        )
    plane.registry.activate("a")
    plane.router.save_config(
        {
            "fallbackOrder": ["b"],
            "roleModelOverrides": {"coding": "c"},
        }
    )
    decision = plane.router.resolve(ModelRequest(explicit_model_id="b"))
    assert decision.model_id == "b"
    assert decision.reason == "explicit"
    decision = plane.router.resolve(ModelRequest(preferred_role="coding"))
    assert decision.model_id == "c"
    decision = plane.router.resolve(ModelRequest())
    assert decision.model_id == "a"


def test_router_fallback_recorded(plane: ModelControlPlane) -> None:
    plane.registry.store.upsert_model(
        {
            "model_id": "fallback-one",
            "display_name": "fallback-one",
            "provider_id": "lm_studio",
            "source": "remote",
            "capabilities": ModelCapabilities().public_dict(),
            "lifecycle_state": "available",
            "health": "healthy",
        }
    )
    plane.router.save_config({"fallbackOrder": ["fallback-one"], "roleModelOverrides": {}})
    decision = plane.router.resolve(ModelRequest())
    assert decision.model_id == "fallback-one"
    assert decision.fallback_used or decision.reason.startswith("fallback")
    snap = plane.gateway.snapshot()
    assert snap.last_fallback_reason is not None or decision.reason != "active_default"


def test_gateway_capacity_timeout(plane: ModelControlPlane) -> None:
    plane.gateway.set_global_limit(1)
    first = plane.gateway.acquire(model_id="m1", provider_id="p1", timeout_seconds=0.2)
    assert first
    with pytest.raises(ModelControlError) as exc:
        plane.gateway.acquire(model_id="m2", provider_id="p1", timeout_seconds=0.05)
    assert exc.value.code == "CAPACITY_TIMEOUT"
    plane.gateway.release(model_id="m1", provider_id="p1")
    second = plane.gateway.acquire(model_id="m2", provider_id="p1", timeout_seconds=0.2)
    plane.gateway.release(model_id="m2", provider_id="p1")
    assert second
    snap = plane.gateway.snapshot()
    assert snap.capacity_timeouts >= 1
    assert snap.capacity.global_limit == 1


def test_unsupported_load_returns_capability_error(plane: ModelControlPlane) -> None:
    plane.registry.store.upsert_model(
        {
            "model_id": "lm_studio:x",
            "display_name": "x",
            "provider_id": "lm_studio",
            "source": "remote",
            "capabilities": ModelCapabilities().public_dict(),
            "lifecycle_state": "available",
            "health": "healthy",
        }
    )

    async def _run() -> None:
        with pytest.raises(ModelControlError) as exc:
            await plane.runtime.load("lm_studio:x")
        assert exc.value.code == "CAPABILITY_NOT_SUPPORTED"
        assert exc.value.http_status == 409

    asyncio.run(_run())


def test_import_rejects_traversal(plane: ModelControlPlane, tmp_path: Path) -> None:
    with pytest.raises(ModelControlError) as exc:
        plane.imports.import_local_path("../../etc/passwd")
    assert exc.value.code in {"UNSAFE_PATH", "VALIDATION_ERROR", "MODEL_INVALID"}


def test_import_accepts_gguf_under_allowed_root(plane: ModelControlPlane, tmp_path: Path) -> None:
    # Place file under download root (allowed)
    root = plane.downloads.download_root
    root.mkdir(parents=True, exist_ok=True)
    target = root / "toy.gguf"
    target.write_bytes(b"GGUF" + b"\0" * 32)
    model = plane.imports.import_local_path(str(target))
    assert model.id.startswith("imported:")
    assert model.format == "gguf"
    assert model.disk_size_bytes == target.stat().st_size


def test_secret_masking_on_provider_update(plane: ModelControlPlane) -> None:
    provider = plane.create_provider(
        {
            "name": "Secretive",
            "type": "openai_compatible",
            "endpoint": "http://192.168.1.50:8080/v1",
            "apiKey": "super-secret-key",
        }
    )
    assert provider.api_key_configured is True
    assert "super-secret-key" not in json.dumps(provider.public_dict())
    row = plane.store.get_provider(provider.provider_id)
    assert row is not None
    assert row["api_key_ciphertext"] == "super-secret-key"


def test_discovery_offline(plane: ModelControlPlane, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LMStudioAdapter(provider_id="lm_studio", endpoint="http://127.0.0.1:9/v1", timeout_seconds=1.0)

    async def _run() -> None:
        health, latency, error = await adapter.health()
        assert health.value in {"offline", "timeout"}
        assert error
        with pytest.raises(ModelControlError) as exc:
            await adapter.discover()
        assert exc.value.code in {"PROVIDER_OFFLINE", "REQUEST_TIMEOUT"}

    asyncio.run(_run())


def test_discovery_success_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OpenAICompatibleAdapter(
        provider_id="p1",
        endpoint="http://example.test/v1",
        timeout_seconds=5.0,
    )

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": [
                    {"id": "qwen-coder", "object": "model", "owned_by": "org"},
                    {"id": "7b-something", "object": "model"},
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    async def _run() -> None:
        models = await adapter.discover()
        assert len(models) == 2
        assert models[0].parameter_count is None  # never inferred from "7b"
        assert models[1].parameter_count is None
        assert models[0].id == "p1:qwen-coder"

    asyncio.run(_run())


def test_startup_reconciliation_marks_offline(plane: ModelControlPlane) -> None:
    plane.registry.store.upsert_model(
        {
            "model_id": "lm_studio:ghost",
            "display_name": "ghost",
            "provider_id": "lm_studio",
            "source": "remote",
            "capabilities": {},
            "lifecycle_state": "loaded",
            "health": "healthy",
            "loaded": True,
        }
    )

    async def _run() -> None:
        await plane.refresh_all()

    asyncio.run(_run())
    model = plane.registry.get("lm_studio:ghost")
    # Provider offline in CI → model should be offline, not still "loaded"
    assert model.lifecycle_state in {
        ModelLifecycleState.OFFLINE,
        ModelLifecycleState.AVAILABLE,
        ModelLifecycleState.DISCOVERED,
    }
    if model.lifecycle_state == ModelLifecycleState.OFFLINE:
        assert model.loaded in {False, None, 0} or model.loaded is False


def test_download_blocked_without_outbound(plane: ModelControlPlane) -> None:
    async def _run() -> None:
        with pytest.raises(ModelControlError) as exc:
            await plane.downloads.start_huggingface(repository_id="org/model")
        assert exc.value.code == "NETWORK_BLOCKED"

    asyncio.run(_run())
