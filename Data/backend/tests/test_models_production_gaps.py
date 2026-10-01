"""Missing production regressions: probe concurrency/cancel, SDK timeout,
resource estimate status, rerank≠embeddings family inference.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.models import ModelControlPlane
from Data.modules.models.capability_eligibility import apply_family_capability_inference
from Data.modules.models.capability_probe import CapabilityProbeService
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelDescriptor,
    ModelSource,
)
from Data.modules.models.errors import REQUEST_TIMEOUT, ModelControlError
from Data.modules.models.lm_studio_sdk import sdk_load_model
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore


def _desc(model_id: str, display: str, **cap_kw) -> ModelDescriptor:
    caps = ModelCapabilities(**cap_kw) if cap_kw else ModelCapabilities()
    return ModelDescriptor(
        id=model_id,
        display_name=display,
        provider_id="p",
        source=ModelSource.LOCAL,
        capabilities=caps,
        endpoint="http://127.0.0.1:1234/v1",
    )


@pytest.fixture()
def store(tmp_path: Path) -> ModelStore:
    db = tmp_path / "gaps.db"
    MigrationRunner(db).apply_all()
    return ModelStore(db)


def test_rerank_family_does_not_promote_embeddings() -> None:
    caps = ModelCapabilities(
        chat=CapabilityState.UNKNOWN,
        embeddings=CapabilityState.UNKNOWN,
        parallel_tool_calls=CapabilityState.SUPPORTED,
    )
    model = _desc("rerank-1", "bge-reranker-base")
    out, _prov = apply_family_capability_inference(caps, model)
    assert out.chat == CapabilityState.UNSUPPORTED
    assert out.embeddings == CapabilityState.UNKNOWN  # NOT coerced to SUPPORTED
    assert out.parallel_tool_calls == CapabilityState.SUPPORTED


def test_embedding_family_still_promotes_embeddings() -> None:
    caps = ModelCapabilities(chat=CapabilityState.UNKNOWN, embeddings=CapabilityState.UNKNOWN)
    model = _desc("emb-1", "nomic-embed-text")
    out, _ = apply_family_capability_inference(caps, model)
    assert out.chat == CapabilityState.UNSUPPORTED
    assert out.embeddings == CapabilityState.SUPPORTED


@pytest.mark.asyncio
async def test_probe_cancel_stops_further_capabilities(store: ModelStore) -> None:
    store.upsert_model(
        {
            "model_id": "m1",
            "display_name": "m1",
            "provider_id": "p",
            "source": "local",
            "capabilities": ModelCapabilities(chat=CapabilityState.UNKNOWN).public_dict(),
            "lifecycle_state": "available",
            "health": "healthy",
        }
    )
    registry = ModelRegistry(store)

    started = asyncio.Event()
    block = asyncio.Event()

    class _Adapter:
        async def test_inference(self, model_id, **kwargs):
            started.set()
            await block.wait()
            return {"ok": True, "latencyMs": 1}

    svc = CapabilityProbeService(store, registry, get_adapter=lambda _pid: _Adapter())

    async def _run():
        return await svc.probe(
            "m1", capabilities=["chat", "streaming", "toolCalling"], timeout_seconds=5.0
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(started.wait(), timeout=2.0)
    assert svc.cancel("m1") is True
    block.set()
    results = await task
    assert len(results) < 3


@pytest.mark.asyncio
async def test_concurrent_probes_single_flight(store: ModelStore) -> None:
    store.upsert_model(
        {
            "model_id": "m1",
            "display_name": "m1",
            "provider_id": "p",
            "source": "local",
            "capabilities": ModelCapabilities().public_dict(),
            "lifecycle_state": "available",
            "health": "healthy",
        }
    )
    registry = ModelRegistry(store)

    gate = asyncio.Event()
    in_flight = 0
    max_in_flight = 0

    class _Adapter:
        async def test_inference(self, model_id, **kwargs):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await gate.wait()
            in_flight -= 1
            return {"ok": True, "latencyMs": 1, "stream": kwargs.get("stream", False)}

    svc = CapabilityProbeService(store, registry, get_adapter=lambda _pid: _Adapter())
    t1 = asyncio.create_task(svc.probe("m1", capabilities=["chat"], timeout_seconds=5.0))
    await asyncio.sleep(0.05)
    t2 = asyncio.create_task(svc.probe("m1", capabilities=["chat"], timeout_seconds=5.0))
    await asyncio.sleep(0.05)
    gate.set()
    await asyncio.gather(t1, t2)
    assert max_in_flight <= 1


def test_sdk_load_timeout_does_not_return_success() -> None:
    with patch("Data.modules.models.lm_studio_sdk.probe_sdk_import", return_value=(True, "1.0")):
        with patch(
            "Data.modules.models.lm_studio_sdk.api_host_from_endpoint",
            return_value="127.0.0.1:1234",
        ):
            with patch.dict("sys.modules", {"lmstudio": MagicMock()}):
                import sys

                fake_lms = sys.modules["lmstudio"]
                fake_lms.LlmLoadModelConfig = MagicMock()
                fake_lms.LlmLoadModelConfig.from_dict = MagicMock(return_value={})
                client = MagicMock()
                client.__enter__ = MagicMock(return_value=client)
                client.__exit__ = MagicMock(return_value=False)

                def _slow_load(*_a, **_k):
                    import time

                    time.sleep(2.0)
                    return MagicMock()

                client.llm.load_new_instance = _slow_load
                fake_lms.Client = MagicMock(return_value=client)

                with pytest.raises(ModelControlError) as exc:
                    sdk_load_model(
                        endpoint="http://127.0.0.1:1234/v1",
                        model_key="m",
                        config={},
                        timeout_seconds=0.2,
                    )
                assert exc.value.code == REQUEST_TIMEOUT
                assert exc.value.details.get("reconcileRequired") is True


@pytest.mark.asyncio
async def test_estimate_status_neither_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "est.db"
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false")
    settings = Settings.from_env()
    MigrationRunner(settings.database_path).apply_all()
    plane = ModelControlPlane(settings)
    plane.bootstrap()
    plane.registry.store.upsert_model(
        {
            "model_id": "m1",
            "display_name": "m1",
            "provider_id": "missing_provider_xyz",
            "source": "local",
            "capabilities": ModelCapabilities().public_dict(),
            "lifecycle_state": "available",
            "health": "healthy",
        }
    )
    plane.resources.estimate = MagicMock(side_effect=RuntimeError("no hw"))  # type: ignore[method-assign]
    result = await plane.estimate_model_load("m1")
    assert result["status"] == "UNAVAILABLE"
    assert result["truth"]["unavailable_when_neither"] is True
    assert result["leviathanStatus"] == "UNAVAILABLE"
