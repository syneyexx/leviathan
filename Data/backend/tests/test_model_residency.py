"""Model residency + canonical inference session tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.models import ModelControlError, ModelControlPlane
from Data.modules.models.contracts import (
    CapabilityState,
    LoadOptions,
    ModelCapabilities,
    ModelDescriptor,
    ModelLifecycleState,
    ModelSource,
    ResidencyPolicyKind,
    ResidencyState,
)
from Data.modules.models.runtime_binding import (
    assess_transformers_snapshot,
    build_runtime_binding,
)
from Data.modules.model_runtime.llama_cpp_command import build_llama_cpp_command
from Data.modules.model_runtime.port_allocator import PortAllocator
from Data.modules.model_runtime.process_control import terminate_owned_process


@pytest.fixture()
def plane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelControlPlane:
    db_path = tmp_path / "residency.db"
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false")
    monkeypatch.setenv("LEVIATHAN_ALLOW_INPROC_MODEL_FIXTURE", "true")
    settings = Settings.from_env()
    MigrationRunner(settings.database_path).apply_all()
    control = ModelControlPlane(settings)
    control.bootstrap()
    return control


def _register_model(plane: ModelControlPlane, model_id: str, *, provider_id: str = "lm_studio") -> ModelDescriptor:
    descriptor = ModelDescriptor(
        id=model_id,
        display_name=model_id,
        provider_id=provider_id,
        source=ModelSource.LOCAL,
        capabilities=ModelCapabilities(chat=CapabilityState.SUPPORTED),
        lifecycle_state=ModelLifecycleState.AVAILABLE,
        context_window=8192,
        metadata={"provider_model_id": model_id},
    )
    plane.store.upsert_model(
        {
            "model_id": descriptor.id,
            "display_name": descriptor.display_name,
            "provider_id": descriptor.provider_id,
            "source": descriptor.source.value,
            "capabilities": descriptor.capabilities.public_dict(),
            "lifecycle_state": descriptor.lifecycle_state.value,
            "context_window": descriptor.context_window,
            "metadata": descriptor.metadata,
        }
    )
    return plane.registry.get(model_id)


class _FakeRuntime:
    def __init__(self) -> None:
        self.loads = 0
        self.unloads = 0
        self.loaded: set[str] = set()
        self._events: dict[str, asyncio.Event] = {}

    async def load(self, model_id: str, options: Any = None, *, confirm_oom: bool = False) -> dict:
        self.loads += 1
        ev = self._events.setdefault(model_id, asyncio.Event())
        await asyncio.sleep(0.05)
        self.loaded.add(model_id)
        ev.set()
        return {
            "providerResult": {
                "worker": {
                    "worker_id": f"w-{model_id}",
                    "pid": None,
                    "endpoint": f"inproc://{model_id}",
                    "state": "READY",
                }
            }
        }

    async def unload(self, model_id: str) -> dict:
        self.unloads += 1
        self.loaded.discard(model_id)
        return {"unloaded": True}


@pytest.mark.asyncio
async def test_same_model_sharing_leases(plane: ModelControlPlane) -> None:
    _register_model(plane, "model-x")
    fake = _FakeRuntime()
    plane.residency.runtime = fake
    plane.router.save_config(
        {"roleModelOverrides": {"chat": "model-x", "coding": "model-x"}, "fallbackOrder": []}
    )

    a = await plane.residency.acquire_lease(
        "model-x", consumer="chat", domain="chat", model_role="chat", managed=True, ensure_ready=True
    )
    b = await plane.residency.acquire_lease(
        "model-x", consumer="coding", domain="coding", model_role="coding", managed=True, ensure_ready=True
    )
    snap = plane.residency.snapshot("model-x")
    assert snap.active_lease_count == 2
    assert fake.loads == 1
    assert sorted(snap.consumers) == ["chat", "coding"]

    await plane.residency.release_lease(b.lease_id, model_id="model-x")
    snap = plane.residency.snapshot("model-x")
    assert snap.active_lease_count == 1
    assert fake.unloads == 0

    await plane.residency.release_lease(a.lease_id, model_id="model-x")
    snap = plane.residency.snapshot("model-x")
    assert snap.active_lease_count == 0
    assert snap.state == ResidencyState.IDLE


@pytest.mark.asyncio
async def test_cold_start_single_flight(plane: ModelControlPlane) -> None:
    _register_model(plane, "model-x")
    fake = _FakeRuntime()
    plane.residency.runtime = fake

    async def one() -> None:
        await plane.residency.acquire_lease(
            "model-x", consumer="chat", managed=True, ensure_ready=True
        )

    await asyncio.gather(one(), one())
    assert fake.loads == 1
    assert plane.residency.snapshot("model-x").active_lease_count == 2


@pytest.mark.asyncio
async def test_idle_unload_and_cancellation(plane: ModelControlPlane) -> None:
    _register_model(plane, "model-x")
    fake = _FakeRuntime()
    plane.residency.runtime = fake
    plane.residency.set_policy(
        "model-x", {"policy": "IDLE_UNLOAD", "idleUnloadSeconds": 0.05}
    )

    lease = await plane.residency.acquire_lease(
        "model-x", consumer="chat", managed=True, ensure_ready=True
    )
    await plane.residency.release_lease(lease.lease_id, model_id="model-x")
    assert plane.residency.snapshot("model-x").state == ResidencyState.IDLE

    # Cancel unload by acquiring again quickly
    lease2 = await plane.residency.acquire_lease(
        "model-x", consumer="chat", managed=True, ensure_ready=True
    )
    await asyncio.sleep(0.12)
    assert fake.unloads == 0
    assert plane.residency.snapshot("model-x").active_lease_count == 1
    await plane.residency.release_lease(lease2.lease_id, model_id="model-x")
    await asyncio.sleep(0.12)
    assert fake.unloads == 1
    assert plane.residency.snapshot("model-x").state == ResidencyState.UNLOADED


@pytest.mark.asyncio
async def test_keep_hot(plane: ModelControlPlane) -> None:
    _register_model(plane, "model-x")
    fake = _FakeRuntime()
    plane.residency.runtime = fake
    plane.residency.set_policy("model-x", {"policy": "KEEP_HOT", "idleUnloadSeconds": 0.01})
    lease = await plane.residency.acquire_lease(
        "model-x", consumer="chat", managed=True, ensure_ready=True
    )
    await plane.residency.release_lease(lease.lease_id, model_id="model-x")
    await asyncio.sleep(0.05)
    assert fake.unloads == 0
    assert plane.residency.snapshot("model-x").state == ResidencyState.IDLE


@pytest.mark.asyncio
async def test_warm_then_unload_unsupported(plane: ModelControlPlane) -> None:
    _register_model(plane, "model-x")
    with pytest.raises(ModelControlError) as exc:
        plane.residency.set_policy("model-x", {"policy": "WARM_THEN_UNLOAD"})
    assert exc.value.code == "UNSUPPORTED_RESIDENCY_POLICY"


@pytest.mark.asyncio
async def test_active_lease_blocks_manual_unload(plane: ModelControlPlane) -> None:
    _register_model(plane, "model-x")
    fake = _FakeRuntime()
    plane.residency.runtime = fake
    await plane.residency.acquire_lease(
        "model-x", consumer="chat", managed=True, ensure_ready=True
    )
    with pytest.raises(ModelControlError) as exc:
        await plane.residency.manual_unload("model-x")
    assert exc.value.code == "MODEL_ACTIVE_LEASES"
    assert fake.unloads == 0


@pytest.mark.asyncio
async def test_external_provider_no_owned_worker(plane: ModelControlPlane) -> None:
    _register_model(plane, "lms-model", provider_id="lm_studio")
    lease = await plane.residency.acquire_lease(
        "lms-model",
        consumer="chat",
        managed=False,
        external=True,
        ensure_ready=False,
        endpoint="http://127.0.0.1:1234/v1",
    )
    snap = plane.residency.snapshot("lms-model")
    assert snap.state == ResidencyState.EXTERNAL
    assert snap.pid is None
    assert snap.managed is False
    await plane.residency.release_lease(lease.lease_id, model_id="lms-model")
    with pytest.raises(ModelControlError) as exc:
        await plane.residency.manual_unload("lms-model")
    assert exc.value.code == "MODEL_RUNTIME_UNAVAILABLE"


@pytest.mark.asyncio
async def test_startup_clears_leases_not_ready(plane: ModelControlPlane) -> None:
    _register_model(plane, "model-x")
    fake = _FakeRuntime()
    plane.residency.runtime = fake
    await plane.residency.acquire_lease(
        "model-x", consumer="chat", managed=True, ensure_ready=True
    )
    plane.residency.clear_live_leases_on_startup()
    assert plane.residency.snapshot("model-x").active_lease_count == 0


@pytest.mark.asyncio
async def test_gateway_and_lease_cleanup_on_error(plane: ModelControlPlane) -> None:
    _register_model(plane, "model-x")
    fake = _FakeRuntime()
    plane.residency.runtime = fake

    class BoomLLM:
        async def complete_messages(self, *args: Any, **kwargs: Any) -> dict:
            raise RuntimeError("boom")

    plane.bind_llm(BoomLLM())
    plane.router.save_config({"roleModelOverrides": {"chat": "model-x"}, "fallbackOrder": []})
    target = plane.resolve_target(preferred_role="chat")
    # Force managed=false so we don't depend on fake worker pid checks in session path
    target.managed = False
    if target.runtime_binding:
        target.runtime_binding.managed = False

    with pytest.raises(RuntimeError):
        async with plane.inference_session(target, consumer="chat", domain="chat") as session:
            await session.complete_messages([{"role": "user", "content": "hi"}])

    assert plane.gateway.snapshot().active_calls == 0
    assert plane.residency.snapshot("model-x").active_lease_count == 0


def test_router_role_mapping(plane: ModelControlPlane) -> None:
    _register_model(plane, "g")
    _register_model(plane, "c")
    _register_model(plane, "r")
    plane.router.save_config(
        {
            "roleModelOverrides": {"chat": "g", "coding": "c", "research": "r"},
            "fallbackOrder": [],
        }
    )
    assert plane.resolve_target(preferred_role="chat").model.id == "g"
    assert plane.resolve_target(preferred_role="general").model.id == "g"
    assert plane.resolve_target(preferred_role="coding").model.id == "c"
    assert plane.resolve_target(preferred_role="research").model.id == "r"
    assert plane.resolve_target(explicit_model_id="c", preferred_role="chat").model.id == "c"


def test_explicit_wins_over_role(plane: ModelControlPlane) -> None:
    _register_model(plane, "a")
    _register_model(plane, "b")
    plane.router.save_config({"roleModelOverrides": {"coding": "a"}, "fallbackOrder": []})
    target = plane.resolve_target(explicit_model_id="b", preferred_role="coding")
    assert target.model.id == "b"
    assert target.explicit_selection is True


def test_llama_cpp_command_args() -> None:
    cmd = build_llama_cpp_command(
        executable="/usr/bin/llama-server",
        model_path="/models/x.gguf",
        host="127.0.0.1",
        port=29111,
        options=LoadOptions(context_length=4096, gpu_offload_layers=20, cpu_threads=4, batch_size=512, flash_attention=True),
    )
    assert cmd[0] == "/usr/bin/llama-server"
    assert "-m" in cmd and "/models/x.gguf" in cmd
    assert "--host" in cmd and "127.0.0.1" in cmd
    assert "--port" in cmd and "29111" in cmd
    assert "-c" in cmd and "4096" in cmd
    assert "-ngl" in cmd and "20" in cmd
    assert "-t" in cmd and "4" in cmd
    assert "-b" in cmd and "512" in cmd
    assert "-fa" in cmd
    assert all(isinstance(x, str) for x in cmd)


def test_incomplete_safetensors_not_servable(tmp_path: Path) -> None:
    lone = tmp_path / "model.safetensors"
    lone.write_bytes(b"x")
    state, reason = assess_transformers_snapshot(str(lone))
    assert state.value == "UNAVAILABLE"
    assert reason and "config.json" in reason


def test_port_allocator_no_collision() -> None:
    alloc = PortAllocator(host="127.0.0.1", port_start=30100, port_end=30110)
    ports = {alloc.allocate() for _ in range(5)}
    assert len(ports) == 5
    for p in ports:
        alloc.release(p)


def test_telemetry_unknown_vram_not_zero(plane: ModelControlPlane) -> None:
    plane.resources.set_telemetry_provider(
        lambda: {
            "measured": True,
            "memory": {"totalBytes": 8_000_000_000, "availableBytes": 4_000_000_000},
            "gpu": {"available": False, "devices": []},
            "notes": ["nvidia-smi not found"],
        }
    )
    model = _register_model(plane, "m1")
    estimate = plane.resources.estimate(model)
    assert estimate.vram_available_bytes is None
    assert estimate.vram_available_provenance.value == "UNKNOWN"


def test_migration_36_preserves_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "mig.db"
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(db))
    settings = Settings.from_env()
    # Apply through 35 then 36
    runner = MigrationRunner(settings.database_path)
    applied = runner.apply_all()
    assert 36 in applied or runner.current_version(
        __import__("sqlite3").connect(settings.database_path)
    ) >= 36
    plane = ModelControlPlane(settings)
    plane.bootstrap()
    _register_model(plane, "kept")
    assert plane.registry.get("kept").id == "kept"
    plane.store.upsert_runtime_binding(
        {
            "model_id": "kept",
            "runtime_kind": "lm_studio",
            "managed": False,
            "servability_state": "SERVABLE",
        }
    )
    assert plane.store.get_runtime_binding("kept")["runtime_kind"] == "lm_studio"


def test_windows_terminate_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProc:
        pid = 4242
        returncode = 0

        def poll(self):
            return None

        def terminate(self):
            self._term = True

        def kill(self):
            self._kill = True

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    monkeypatch.setattr("Data.modules.model_runtime.process_control.os.name", "nt")
    result = terminate_owned_process(FakeProc(), graceful_timeout_seconds=0.1)
    assert result["forced"] is False or result["returncode"] == 0


def test_local_import_is_not_runtime() -> None:
    model = ModelDescriptor(
        id="imported:x.gguf",
        display_name="x.gguf",
        provider_id="local_import",
        source=ModelSource.IMPORTED,
        format="gguf",
        local_path="/tmp/x.gguf",
        capabilities=ModelCapabilities(),
    )
    binding = build_runtime_binding(
        model,
        provider_type="local_import",
        managed_serving_enabled=False,
    )
    assert binding.runtime_kind == "llama_cpp"
    assert binding.managed is False


@pytest.mark.asyncio
async def test_settings_external_fallback_uses_residency_and_gateway(
    plane: ModelControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ROUTER_EXHAUSTED soft path must still acquire EXTERNAL lease + Gateway."""
    monkeypatch.setenv("LEVIATHAN_LLM_MODEL", "local-test-model")
    # Settings object is frozen — rebuild plane with model configured.
    db_path = plane.settings.database_path
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false")
    settings = Settings.from_env()
    plane = ModelControlPlane(settings)
    plane.bootstrap()

    routed = plane.resolve_settings_external_fallback(
        preferred_role="chat",
        router_error_code="ROUTER_EXHAUSTED",
    )
    assert routed["model"].id.startswith("settings:external:")
    assert routed["provider_id"] == "settings_external"
    assert routed["endpoint"].startswith("http")
    assert routed["resolved"].managed is False
    assert routed["decision"].reason == "legacy_settings_fallback"

    model_id = routed["model"].id
    lease = await plane.residency.acquire_lease(
        model_id,
        consumer="chat",
        domain="chat",
        model_role="chat",
        managed=False,
        ensure_ready=False,
        external=True,
        endpoint=routed["endpoint"],
    )
    call_id = plane.gateway.acquire(
        model_id=model_id,
        provider_id=routed["provider_id"],
        timeout_seconds=1.0,
    )
    snap = plane.residency.snapshot(model_id)
    assert snap.state == ResidencyState.EXTERNAL
    assert snap.active_lease_count == 1
    assert snap.pid is None
    assert snap.managed is False
    assert plane.gateway.snapshot().active_calls == 1

    plane.gateway.release(model_id=model_id, provider_id=routed["provider_id"])
    await plane.residency.release_lease(lease.lease_id, model_id=model_id)
    assert plane.gateway.snapshot().active_calls == 0
    assert plane.residency.snapshot(model_id).active_lease_count == 0
    # External unload remains unavailable (no owned worker).
    with pytest.raises(ModelControlError) as exc:
        await plane.residency.manual_unload(model_id)
    assert exc.value.code in {"MODEL_RUNTIME_UNAVAILABLE", "MODEL_RESIDENCY_UNAVAILABLE"}
    _ = call_id


def test_settings_external_fallback_fails_closed_without_settings(
    plane: ModelControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LEVIATHAN_LLM_MODEL", raising=False)
    monkeypatch.setenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(plane.settings.database_path))
    monkeypatch.setenv("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false")
    settings = Settings.from_env()
    plane = ModelControlPlane(settings)
    with pytest.raises(ModelControlError) as exc:
        plane.resolve_settings_external_fallback(router_error_code="ROUTER_EXHAUSTED")
    assert exc.value.code == "ROUTER_EXHAUSTED"