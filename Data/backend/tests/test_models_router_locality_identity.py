"""Production regressions: router identity ambiguity + execution locality."""

from __future__ import annotations

from pathlib import Path

import pytest

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.models import ModelControlError, ModelControlPlane
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelLifecycleState,
    ModelRequest,
    ModelSource,
)
from Data.modules.models.errors import AMBIGUOUS_MODEL_ID, MODEL_NOT_FOUND
from Data.modules.models.locality import (
    is_local_execution_eligible,
    model_execution_locality,
)
from Data.modules.provider_io.endpoint_locality import EndpointLocality


@pytest.fixture()
def plane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelControlPlane:
    db_path = tmp_path / "locality.db"
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
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


def _upsert(
    plane: ModelControlPlane,
    *,
    model_id: str,
    display_name: str,
    provider_model_id: str | None = None,
    source: str = "remote",
    endpoint: str | None = None,
    lifecycle: str = "available",
    health: str = "healthy",
    context_window: int | None = 8192,
    chat: CapabilityState = CapabilityState.SUPPORTED,
) -> None:
    plane.registry.store.upsert_model(
        {
            "model_id": model_id,
            "display_name": display_name,
            "provider_id": "lm_studio",
            "source": source,
            "endpoint": endpoint,
            "context_window": context_window,
            "capabilities": ModelCapabilities(chat=chat).public_dict(),
            "lifecycle_state": lifecycle,
            "health": health,
            "metadata": {
                "provider_model_id": provider_model_id or display_name,
            },
        }
    )


def test_ambiguous_display_name_raises_with_candidates(plane: ModelControlPlane) -> None:
    _upsert(plane, model_id="lm_studio:a", display_name="twin", provider_model_id="twin-a")
    _upsert(plane, model_id="lm_studio:b", display_name="twin", provider_model_id="twin-b")
    with pytest.raises(ModelControlError) as exc:
        plane.registry.get("twin")
    assert exc.value.code == AMBIGUOUS_MODEL_ID
    candidates = exc.value.details.get("candidateCanonicalIds") or []
    assert set(candidates) == {"lm_studio:a", "lm_studio:b"}


def test_ambiguous_provider_model_id_via_router(plane: ModelControlPlane) -> None:
    _upsert(
        plane,
        model_id="lm_studio:x1",
        display_name="X One",
        provider_model_id="shared-id",
    )
    _upsert(
        plane,
        model_id="lm_studio:x2",
        display_name="X Two",
        provider_model_id="shared-id",
    )
    with pytest.raises(ModelControlError) as exc:
        plane.router.resolve(ModelRequest(explicit_model_id="shared-id"))
    assert exc.value.code == AMBIGUOUS_MODEL_ID
    assert "candidateCanonicalIds" in (exc.value.details or {})


def test_local_only_localhost_lm_studio_eligible(plane: ModelControlPlane) -> None:
    # REMOTE acquisition source is fine when execution endpoint is LOCAL_TRUSTED.
    _upsert(
        plane,
        model_id="lm_studio:local-chat",
        display_name="local-chat",
        source="remote",
        endpoint="http://127.0.0.1:1234/v1",
    )
    model = plane.registry.get("lm_studio:local-chat")
    assert model_execution_locality(model) == EndpointLocality.LOCAL_TRUSTED
    assert is_local_execution_eligible(model) is True
    decision = plane.router.resolve(
        ModelRequest(explicit_model_id="lm_studio:local-chat", locality="local_only")
    )
    assert decision.model_id == "lm_studio:local-chat"


def test_remote_public_endpoint_rejected_for_local_only(plane: ModelControlPlane) -> None:
    _upsert(
        plane,
        model_id="api:cloud",
        display_name="cloud",
        source="api",
        endpoint="https://api.openai.com/v1",
    )
    model = plane.registry.get("api:cloud")
    assert is_local_execution_eligible(model) is False
    with pytest.raises(ModelControlError) as exc:
        plane.router.resolve(
            ModelRequest(explicit_model_id="api:cloud", locality="local_only")
        )
    assert exc.value.code in {MODEL_NOT_FOUND, "MODEL_NOT_FOUND"}


def test_downloaded_source_with_remote_endpoint_not_automatically_local(
    plane: ModelControlPlane,
) -> None:
    _upsert(
        plane,
        model_id="dl:weights",
        display_name="weights",
        source="downloaded",
        endpoint="https://inference.example.com/v1",
    )
    model = plane.registry.get("dl:weights")
    # Explicit remote execution endpoint wins over downloaded acquisition source.
    assert model.source == ModelSource.DOWNLOADED
    assert model_execution_locality(model) == EndpointLocality.REMOTE
    assert is_local_execution_eligible(model) is False


def test_unknown_hard_context_capacity_rejects(plane: ModelControlPlane) -> None:
    _upsert(
        plane,
        model_id="lm_studio:noctx",
        display_name="noctx",
        endpoint="http://127.0.0.1:1234/v1",
        context_window=None,
    )
    # Ensure DB stored null context.
    model = plane.registry.get("lm_studio:noctx")
    assert model.context_window is None
    with pytest.raises(ModelControlError):
        plane.router.resolve(
            ModelRequest(
                explicit_model_id="lm_studio:noctx",
                minimum_context_window=4096,
            )
        )


def test_offline_previously_active_not_selected_as_active_default(
    plane: ModelControlPlane,
) -> None:
    _upsert(
        plane,
        model_id="lm_studio:was-active",
        display_name="was-active",
        endpoint="http://127.0.0.1:1234/v1",
        lifecycle="offline",
        health="offline",
    )
    _upsert(
        plane,
        model_id="lm_studio:fallback",
        display_name="fallback",
        endpoint="http://127.0.0.1:1234/v1",
        lifecycle="available",
    )
    plane.store.set_active_model("lm_studio:was-active")
    plane.router.save_config(
        {
            "fallbackOrder": ["lm_studio:fallback"],
            "roleModelOverrides": {},
            "cloudFallbackAllowed": False,
        }
    )
    decision = plane.router.resolve(ModelRequest())
    assert decision.model_id == "lm_studio:fallback"
    assert decision.reason != "active_default"
    assert decision.reason.startswith("fallback")
