"""Shared module lifecycle error contract — not a per-module patch.

Covers install success, typed operational failures, HTTP status, JobRuntime,
enqueue fallback, and offline smoke of real manifests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.modules import build_modules_router
from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.execution.types import CapabilityDefinition, CapabilityProviderKind
from Data.modules.function_runtime.types import SideEffect
from Data.modules.jobs import JobRuntime, JobState, JobStore, ResourceManager
from Data.modules.module_manager import ModuleContext, ModuleManager, ModuleManagerError, ModuleStatus
from Data.modules.module_manager.errors import scrub_error_text
from Data.modules.module_manager.external.executor import ExternalModuleExecutor
from Data.modules.module_manager.external.install import InstallError
from Data.modules.module_manager.types import ModuleManifest

FACTORY = "Data.modules.module_manager.external.module:create_external_capability_module"
REPO_MODULES = Path(__file__).resolve().parents[2] / "external_capabilities"


class _Obs:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, category: str, name: str, *, payload: dict[str, Any] | None = None, **_: Any) -> None:
        self.events.append((name, dict(payload or {})))

    def names(self) -> list[str]:
        return [name for name, _payload in self.events]


def _write_module(root: Path, module_id: str, external: dict[str, Any]) -> None:
    folder = root / module_id
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        "module_id": module_id,
        "name": module_id,
        "version": "0.0.1",
        "entrypoint": FACTORY,
        "external": external,
    }
    (folder / "module.json").write_text(json.dumps(manifest), encoding="utf-8")


def _manager(tmp: Path, module_id: str, external: dict[str, Any]) -> ModuleManager:
    mods = tmp / "mods"
    _write_module(mods, module_id, external)
    manager = ModuleManager(discovery_roots=(mods,), enabled=True)
    manager.discover()
    manager.initialize(
        module_id,
        ModuleContext(database_path=str(tmp / "control.db"), data_root=str(tmp / "data")),
    )
    return manager


def _client(
    manager: ModuleManager,
    *,
    job_runtime: Any = None,
    approval_service: Any = None,
    obs: _Obs | None = None,
    allow_sync_install_fallback: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_modules_router(
            module_manager=manager,
            observability=obs or _Obs(),
            job_runtime=job_runtime,
            approval_service=approval_service,
            allow_sync_install_fallback=allow_sync_install_fallback,
        )
    )
    return TestClient(app, raise_server_exceptions=False)


def _pip_path(root: Path) -> Path:
    rel = "Scripts/pip.exe" if os.name == "nt" else "bin/pip"
    return root / ".venv" / rel


class ModuleLifecycleErrorTests(unittest.TestCase):
    def test_successful_generic_install_registers_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            tool = tmp / "src"
            tool.mkdir()
            (tool / "README.md").write_text("ok\n", encoding="utf-8")
            manager = _manager(
                tmp,
                "fixture-cli",
                {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool),
                    "install": {"strategy": "NONE"},
                    "runtime": {"command": [sys.executable, "-c", "print(1)"]},
                },
            )
            result = manager.ensure_installed("fixture-cli")
            managed = manager.get("fixture-cli")
            assert managed is not None
            self.assertEqual(managed.status, ModuleStatus.INSTALLED)
            self.assertIsNone(managed.error)
            self.assertEqual(result.get("status"), "INSTALLED")
            versions = manager.list_versions("fixture-cli")
            self.assertGreaterEqual(len(versions), 1)
            self.assertEqual(int(manager.telemetry.get("install_completed", 0)), 1)

    def test_dependency_missing_is_typed_and_truthful(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = _manager(
                tmp,
                "fixture-dep",
                {
                    "adapter": "CLI",
                    "source_type": "git",
                    "source": "https://example.invalid/fixture.git",
                    "ref": "main",
                    "install": {
                        "strategy": ["GIT_CHECKOUT"],
                        "dependencies": ["definitely-missing-binary-leviathan-xyz"],
                    },
                },
            )
            with self.assertRaises(ModuleManagerError) as caught:
                manager.ensure_installed("fixture-dep")
            err = caught.exception
            self.assertNotIsInstance(err, InstallError)
            self.assertIsInstance(err.__cause__, InstallError)
            self.assertEqual(err.code, "DEPENDENCY_MISSING")
            self.assertIn("definitely-missing-binary-leviathan-xyz", err.detail)
            self.assertEqual(err.module_id, "fixture-dep")
            self.assertEqual(err.action, "install")
            managed = manager.get("fixture-dep")
            assert managed is not None
            self.assertEqual(managed.status, ModuleStatus.FAILED)
            self.assertNotEqual(managed.status, ModuleStatus.INSTALLED)
            self.assertIn("DEPENDENCY_MISSING", managed.error or "")

            obs = _Obs()
            client = _client(manager, obs=obs)
            response = client.post("/api/modules/fixture-dep/install", json={})
            self.assertNotEqual(response.status_code, 500)
            self.assertEqual(response.status_code, 424)
            detail = response.json()["detail"]
            self.assertEqual(detail["code"], "DEPENDENCY_MISSING")
            self.assertIn("missing dependencies", detail["message"])
            self.assertEqual(detail["module_id"], "fixture-dep")
            self.assertEqual(detail["action"], "install")
            listed = client.get("/api/modules").json()
            row = next(item for item in listed["modules"] if item["manifest"]["module_id"] == "fixture-dep")
            self.assertEqual(row["status"], "FAILED")
            self.assertIn("DEPENDENCY_MISSING", row["error"] or "")
            self.assertIn("module.install.failed", obs.names())

    def test_git_failure_is_bounded_and_not_installed(self) -> None:
        secret = "token=super-secret-value"
        noisy = secret + " " + ("log-line " * 400)

        def _which(name: str, path: str | None = None) -> str | None:
            if name == "git":
                return "/usr/bin/git"
            return None

        def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(list(cmd), 128, "", noisy)

        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = _manager(
                tmp,
                "fixture-git",
                {
                    "adapter": "CLI",
                    "source_type": "git",
                    "source": "https://example.invalid/fixture.git",
                    "ref": "main",
                    "install": {"strategy": ["GIT_CHECKOUT"]},
                },
            )
            with (
                patch("Data.modules.module_manager.external.install.shutil.which", side_effect=_which),
                patch("Data.modules.module_manager.external.dependencies.shutil.which", side_effect=_which),
                patch("Data.modules.module_manager.external.install.subprocess.run", side_effect=_run),
            ):
                with self.assertRaises(ModuleManagerError) as caught:
                    manager.ensure_installed("fixture-git")
                response = _client(manager).post("/api/modules/fixture-git/install", json={})
            err = caught.exception
            self.assertEqual(err.code, "INSTALL_FAILED")
            self.assertIn("git clone failed", err.detail)
            self.assertNotIn("super-secret-value", err.detail)
            self.assertNotIn("super-secret-value", str(err))
            self.assertLess(len(err.detail), 500)
            managed = manager.get("fixture-git")
            assert managed is not None
            self.assertEqual(managed.status, ModuleStatus.FAILED)
            self.assertEqual(response.status_code, 409)
            self.assertNotEqual(response.status_code, 500)
            body = response.json()["detail"]["message"]
            self.assertIn("git clone failed", body)
            self.assertNotIn("super-secret-value", body)
            self.assertNotIn(secret, json.dumps(response.json()))

    def test_venv_pip_failure_uses_same_contract(self) -> None:
        def _git(self: Any, _url: str, _ref: str, dest: Path) -> str:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "requirements.txt").write_text("not-a-real-distribution\n", encoding="utf-8")
            pip = _pip_path(dest)
            pip.parent.mkdir(parents=True, exist_ok=True)
            pip.write_text("", encoding="utf-8")
            return "abc123"

        def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            # Dependency probes and venv creation must succeed; only pip install fails.
            if not cmd:
                return subprocess.CompletedProcess([], 0, "", "")
            joined = " ".join(str(x) for x in cmd)
            if "sudo" in cmd[0] and "-n" in cmd:
                return subprocess.CompletedProcess(list(cmd), 0, "", "")
            if "--version" in cmd:
                return subprocess.CompletedProcess(list(cmd), 0, "1.0.0\n", "")
            if "-m" in cmd and "venv" in cmd:
                # Create probe/real venv directories when a path argument is present.
                for arg in cmd:
                    text = str(arg)
                    if text.endswith("probe-venv") or text.endswith(".venv") or "/venv" in text or text.endswith("venv"):
                        Path(text).mkdir(parents=True, exist_ok=True)
                        bin_dir = Path(text) / ("Scripts" if os.name == "nt" else "bin")
                        bin_dir.mkdir(parents=True, exist_ok=True)
                        py_name = "python.exe" if os.name == "nt" else "python"
                        pip_name = "pip.exe" if os.name == "nt" else "pip"
                        (bin_dir / py_name).write_text("", encoding="utf-8")
                        (bin_dir / pip_name).write_text("", encoding="utf-8")
                return subprocess.CompletedProcess(list(cmd), 0, "", "")
            if "install" in cmd and ("-r" in cmd or any(str(x).endswith("requirements.txt") for x in cmd)):
                return subprocess.CompletedProcess(list(cmd), 1, "", "No matching distribution for nope")
            if "install" in joined:
                return subprocess.CompletedProcess(list(cmd), 1, "", "No matching distribution for nope")
            return subprocess.CompletedProcess(list(cmd), 0, "", "")

        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = _manager(
                tmp,
                "fixture-pip",
                {
                    "adapter": "CLI",
                    "source_type": "git",
                    "source": "https://example.invalid/fixture.git",
                    "ref": "main",
                    "install": {"strategy": ["GIT_CHECKOUT", "PYTHON_VENV"], "requirements_file": "requirements.txt"},
                },
            )
            with (
                patch("Data.modules.module_manager.external.install.InstallationService._git_checkout", _git),
                patch("Data.modules.module_manager.external.install.subprocess.run", side_effect=_run),
            ):
                with self.assertRaises(ModuleManagerError) as caught:
                    manager.ensure_installed("fixture-pip")
                response = _client(manager).post("/api/modules/fixture-pip/install", json={})
            self.assertEqual(caught.exception.code, "INSTALL_FAILED")
            self.assertIn("pip -r failed", caught.exception.detail)
            managed = manager.get("fixture-pip")
            assert managed is not None
            self.assertEqual(managed.status, ModuleStatus.FAILED)
            self.assertEqual(response.status_code, 409)
            self.assertIn("pip -r failed", response.json()["detail"]["message"])

    def test_npm_and_pnpm_failures_name_the_tool(self) -> None:
        for tool in ("npm", "pnpm"):
            strategy = "NODE_NPM" if tool == "npm" else "NODE_PNPM"

            def _git(self: Any, _url: str, _ref: str, dest: Path) -> str:
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "package.json").write_text('{"name":"fixture"}', encoding="utf-8")
                return "abc123"

            def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(list(cmd), 1, "", f"{tool} ERR! install exploded")

            with tempfile.TemporaryDirectory() as tmp_s:
                tmp = Path(tmp_s)
                manager = _manager(
                    tmp,
                    f"fixture-{tool}",
                    {
                        "adapter": "CLI",
                        "source_type": "git",
                        "source": "https://example.invalid/fixture.git",
                        "ref": "main",
                        "install": {"strategy": ["GIT_CHECKOUT", strategy]},
                    },
                )
                with (
                    patch("Data.modules.module_manager.external.install.InstallationService._git_checkout", _git),
                    patch(
                        "Data.modules.module_manager.external.install._resolve_node_tool",
                        return_value=f"/usr/bin/{tool}",
                    ),
                    patch("Data.modules.module_manager.external.install.subprocess.run", side_effect=_run),
                ):
                    with self.assertRaises(ModuleManagerError) as caught:
                        manager.ensure_installed(f"fixture-{tool}")
                self.assertEqual(caught.exception.code, "INSTALL_FAILED")
                self.assertIn(f"{tool} failed", caught.exception.detail)
                self.assertEqual(manager.get(f"fixture-{tool}").status, ModuleStatus.FAILED)  # type: ignore[union-attr]

    def test_unknown_module_is_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            manager = ModuleManager(discovery_roots=(Path(tmp_s),), enabled=True)
            client = _client(manager)
            response = client.post("/api/modules/missing-mod/install", json={})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["code"], "UNKNOWN_MODULE")
            with self.assertRaises(ModuleManagerError) as caught:
                manager.ensure_installed("missing-mod")
            self.assertEqual(caught.exception.code, "UNKNOWN_MODULE")

    def test_unexpected_defect_stays_500(self) -> None:
        class Boom:
            def __init__(self) -> None:
                self.manifest = ModuleManifest(
                    module_id="boom",
                    name="Boom",
                    version="0",
                    entrypoint="tests:boom",
                )

            def ensure_installed(self, **_kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("programmer bug")

        with tempfile.TemporaryDirectory() as tmp_s:
            manager = ModuleManager(discovery_roots=(Path(tmp_s),), enabled=True)
            manager.register_instance(Boom(), ready=False)  # type: ignore[arg-type]
            client = _client(manager)
            response = client.post("/api/modules/boom/install", json={})
            self.assertEqual(response.status_code, 500)
            managed = manager.get("boom")
            assert managed is not None
            self.assertEqual(managed.status, ModuleStatus.FAILED)
            self.assertNotEqual(managed.status, ModuleStatus.INSTALLED)
            self.assertIn("RuntimeError", managed.error or "")

    def test_enqueue_failure_falls_back_and_is_observable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            tool = tmp / "src"
            tool.mkdir()
            manager = _manager(
                tmp,
                "fixture-queue",
                {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool),
                    "install": {"strategy": "NONE"},
                },
            )

            class _Gateway:
                def get_capability(self, _capability_id: str) -> Any:
                    return SimpleNamespace(side_effects=(SideEffect.READ,))

            class _Jobs:
                def __init__(self) -> None:
                    self.gateway = _Gateway()
                    self.calls = 0

                def enqueue(self, **_kwargs: Any) -> Any:
                    self.calls += 1
                    raise RuntimeError("queue offline")

            jobs = _Jobs()
            obs = _Obs()
            # Production: fail closed — no silent sync fallback.
            prod = _client(
                manager,
                job_runtime=jobs,
                obs=obs,
                allow_sync_install_fallback=False,
            ).post("/api/modules/fixture-queue/install", json={})
            self.assertEqual(prod.status_code, 503)
            self.assertEqual(prod.json()["detail"]["code"], "INSTALL_QUEUE_FAILED")
            self.assertEqual(jobs.calls, 1)
            self.assertIn("module.install.enqueue_failed", obs.names())
            failed = next(payload for name, payload in obs.events if name == "module.install.enqueue_failed")
            self.assertEqual(failed["module_id"], "fixture-queue")
            self.assertEqual(failed["action"], "install")
            self.assertEqual(failed["error_class"], "RuntimeError")
            self.assertIn("queue offline", failed["error"])

            # Dev flag: sync fallback remains observable and marked as non-production.
            jobs2 = _Jobs()
            obs2 = _Obs()
            ok = _client(
                manager,
                job_runtime=jobs2,
                obs=obs2,
                allow_sync_install_fallback=True,
            ).post("/api/modules/fixture-queue/install", json={})
            self.assertEqual(ok.status_code, 200)
            body = ok.json()
            self.assertEqual(body.get("executed_via"), "sync_dev_fallback")
            self.assertEqual(body.get("truth", {}).get("production_worker_path"), False)
            self.assertIn("result", body)
            self.assertEqual(manager.get("fixture-queue").status, ModuleStatus.INSTALLED)  # type: ignore[union-attr]
            self.assertEqual(jobs2.calls, 1)
            self.assertIn("module.install.enqueue_failed", obs2.names())
            self.assertIn("module.install.sync_dev_fallback", obs2.names())

            manager_fail = _manager(
                tmp,
                "fixture-queue-fail",
                {
                    "adapter": "CLI",
                    "source_type": "git",
                    "source": "https://example.invalid/fixture.git",
                    "ref": "main",
                    "install": {
                        "strategy": ["GIT_CHECKOUT"],
                    },
                },
            )

            def _which(name: str, path: str | None = None) -> str | None:
                if name == "git":
                    return "/usr/bin/git"
                return None

            def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
                if cmd and "--version" in cmd:
                    return subprocess.CompletedProcess(list(cmd), 0, "git version 2.0\n", "")
                if cmd and "sudo" in str(cmd[0]) and "-n" in cmd:
                    return subprocess.CompletedProcess(list(cmd), 0, "", "")
                return subprocess.CompletedProcess(list(cmd), 128, "", "fatal: repository not found")

            obs_fail = _Obs()
            # Production fail-closed on enqueue — never reaches sync install.
            with (
                patch("Data.modules.module_manager.external.install.shutil.which", side_effect=_which),
                patch("Data.modules.module_manager.external.dependencies.shutil.which", side_effect=_which),
                patch("Data.modules.module_manager.external.install.subprocess.run", side_effect=_run),
            ):
                bad_prod = _client(
                    manager_fail,
                    job_runtime=_Jobs(),
                    obs=obs_fail,
                    allow_sync_install_fallback=False,
                ).post(
                    "/api/modules/fixture-queue-fail/install",
                    json={},
                )
            self.assertEqual(bad_prod.status_code, 503)
            self.assertEqual(bad_prod.json()["detail"]["code"], "INSTALL_QUEUE_FAILED")
            self.assertIn("module.install.enqueue_failed", obs_fail.names())

            obs_fail2 = _Obs()
            with (
                patch("Data.modules.module_manager.external.install.shutil.which", side_effect=_which),
                patch("Data.modules.module_manager.external.dependencies.shutil.which", side_effect=_which),
                patch("Data.modules.module_manager.external.install.subprocess.run", side_effect=_run),
            ):
                bad = _client(
                    manager_fail,
                    job_runtime=_Jobs(),
                    obs=obs_fail2,
                    allow_sync_install_fallback=True,
                ).post(
                    "/api/modules/fixture-queue-fail/install",
                    json={},
                )
            self.assertEqual(bad.status_code, 409)
            self.assertEqual(bad.json()["detail"]["code"], "INSTALL_FAILED")
            self.assertIn("module.install.enqueue_failed", obs_fail2.names())
            self.assertEqual(manager_fail.get("fixture-queue-fail").status, ModuleStatus.FAILED)  # type: ignore[union-attr]

    def test_queue_response_is_not_a_completed_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            tool = tmp / "src"
            tool.mkdir()
            manager = _manager(
                tmp,
                "fixture-queued",
                {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool),
                    "install": {"strategy": "NONE"},
                },
            )

            class _Gateway:
                def get_capability(self, _capability_id: str) -> Any:
                    return SimpleNamespace(side_effects=("READ",))

            class _Jobs:
                def __init__(self) -> None:
                    self.gateway = _Gateway()

                def enqueue(self, **_kwargs: Any) -> Any:
                    return SimpleNamespace(job_id="job-queued", run_id="run-1", state="QUEUED")

            obs = _Obs()
            response = _client(manager, job_runtime=_Jobs(), obs=obs).post("/api/modules/fixture-queued/install", json={})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["status"], "QUEUED")
            self.assertEqual(body["job_id"], "job-queued")
            self.assertNotIn("result", body)
            self.assertEqual(manager.get("fixture-queued").status, ModuleStatus.DISCOVERED)  # type: ignore[union-attr]
            self.assertIn("module.install.queued", obs.names())

    def test_install_version_failure_matches_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = _manager(
                tmp,
                "fixture-ver",
                {
                    "adapter": "CLI",
                    "source_type": "git",
                    "source": "https://example.invalid/fixture.git",
                    "ref": "main",
                    "install": {
                        "strategy": ["GIT_CHECKOUT"],
                        "dependencies": ["definitely-missing-binary-leviathan-xyz"],
                    },
                },
            )
            client = _client(manager)
            response = client.post("/api/modules/fixture-ver/install-version", json={"ref": "v9", "activate": True})
            self.assertEqual(response.status_code, 424)
            detail = response.json()["detail"]
            self.assertEqual(detail["code"], "DEPENDENCY_MISSING")
            self.assertEqual(detail["action"], "install_version")
            self.assertEqual(detail["module_id"], "fixture-ver")
            self.assertEqual(manager.get("fixture-ver").status, ModuleStatus.FAILED)  # type: ignore[union-attr]
            self.assertNotEqual(manager.get("fixture-ver").status, ModuleStatus.INSTALLED)  # type: ignore[union-attr]

    def test_cancel_does_not_mark_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            tool = tmp / "src"
            tool.mkdir()
            manager = _manager(
                tmp,
                "fixture-cancel",
                {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool),
                    "install": {"strategy": "NONE"},
                },
            )
            with self.assertRaises(ModuleManagerError) as caught:
                manager.ensure_installed("fixture-cancel", cancel_check=lambda: True)
            self.assertEqual(caught.exception.code, "CANCELLED")
            self.assertEqual(manager.get("fixture-cancel").status, ModuleStatus.FAILED)  # type: ignore[union-attr]

    def test_scrub_bounds_process_text(self) -> None:
        text = scrub_error_text("token=abc " + ("x" * 2000), limit=100)
        self.assertNotIn("abc", text)
        self.assertLessEqual(len(text), 100)


class JobRuntimeInstallTests(unittest.TestCase):
    def _runtime(self, manager: ModuleManager, tmp: Path) -> tuple[JobRuntime, list[tuple[float, str, str]]]:
        catalog = CapabilityCatalog()
        catalog.register(
            CapabilityDefinition(
                id="external.module.install",
                name="Install",
                description="test install",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.MODULE,
                provider_ref="external.install",
                input_schema={"type": "object", "additionalProperties": True},
                output_schema={"type": "object", "additionalProperties": True},
                metadata={"execution_class": "INLINE_SAFE"},
            )
        )
        gateway = ExecutionGateway(catalog=catalog)
        gateway.module_executor = ExternalModuleExecutor(manager)
        progress: list[tuple[float, str, str]] = []

        def _progress(job_id: str, pct: float, phase: str, message: str) -> None:
            progress.append((pct, phase, message))

        gateway._job_progress = _progress  # type: ignore[attr-defined]
        gateway._job_cancel_check = lambda _job_id: False  # type: ignore[attr-defined]
        store = JobStore(tmp / "jobs.db")
        store.initialize()
        runtime = JobRuntime(store, gateway, ResourceManager(max_job_concurrency=2))
        return runtime, progress

    def test_jobruntime_success_then_failure_keeps_worker_alive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            tool = tmp / "src"
            tool.mkdir()
            (tool / "marker.txt").write_text("ok", encoding="utf-8")
            mods = tmp / "mods"
            _write_module(
                mods,
                "job-ok",
                {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool),
                    "install": {"strategy": "NONE"},
                },
            )
            _write_module(
                mods,
                "job-fail",
                {
                    "adapter": "CLI",
                    "source_type": "git",
                    "source": "https://example.invalid/fixture.git",
                    "install": {
                        "strategy": ["GIT_CHECKOUT"],
                        "dependencies": ["definitely-missing-binary-leviathan-xyz"],
                    },
                },
            )
            manager = ModuleManager(discovery_roots=(mods,), enabled=True)
            manager.discover()
            ctx = ModuleContext(database_path=str(tmp / "control.db"), data_root=str(tmp / "data"))
            manager.initialize("job-ok", ctx)
            manager.initialize("job-fail", ctx)
            runtime, progress = self._runtime(manager, tmp)

            failed = runtime.enqueue(
                capability_id="external.module.install",
                arguments={"module_id": "job-fail"},
                requested_by="test",
                idempotency_key="fail-1",
            )
            self.assertEqual(failed.state, JobState.QUEUED)
            done_fail = runtime.process_next()
            assert done_fail is not None
            self.assertEqual(done_fail.state, JobState.FAILED)
            self.assertIn("DEPENDENCY_MISSING", done_fail.error or "")
            self.assertEqual(done_fail.error_code, "DEPENDENCY_MISSING")
            self.assertEqual(manager.active_jobs("job-fail"), [])
            self.assertEqual(manager.get("job-fail").status, ModuleStatus.FAILED)  # type: ignore[union-attr]
            self.assertNotEqual(manager.get("job-fail").status, ModuleStatus.INSTALLED)  # type: ignore[union-attr]

            ok = runtime.enqueue(
                capability_id="external.module.install",
                arguments={"module_id": "job-ok"},
                requested_by="test",
                idempotency_key="ok-1",
            )
            self.assertEqual(ok.state, JobState.QUEUED)
            done_ok = runtime.process_next()
            assert done_ok is not None
            self.assertEqual(done_ok.state, JobState.COMPLETED)
            self.assertEqual(manager.get("job-ok").status, ModuleStatus.INSTALLED)  # type: ignore[union-attr]
            self.assertIsNone(manager.get("job-ok").error)  # type: ignore[union-attr]
            self.assertEqual(manager.active_jobs("job-ok"), [])
            self.assertTrue(progress)
            self.assertIsNone(runtime.process_next())


class RealManifestSmokeTests(unittest.TestCase):
    def test_real_manifests_fail_closed_without_network(self) -> None:
        self.assertTrue((REPO_MODULES / "ghosttrack" / "module.json").is_file())
        self.assertTrue((REPO_MODULES / "agent-reach" / "module.json").is_file())
        self.assertTrue((REPO_MODULES / "desktop-commander-mcp" / "module.json").is_file())

        def _which(name: str, path: str | None = None) -> str | None:
            if name in {"git", "python3", "python", "curl", "pip", "pip3"}:
                return f"/usr/bin/{name}"
            return None

        def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            if not cmd:
                return subprocess.CompletedProcess([], 0, "", "")
            if cmd and "sudo" in str(cmd[0]):
                return subprocess.CompletedProcess(list(cmd), 0, "", "")
            if "--version" in cmd or "-V" in cmd:
                return subprocess.CompletedProcess(list(cmd), 0, "1.0.0\n", "")
            if "-m" in cmd and "venv" in cmd:
                for arg in cmd:
                    text = str(arg)
                    if "venv" in text:
                        Path(text).mkdir(parents=True, exist_ok=True)
                        bin_dir = Path(text) / ("Scripts" if os.name == "nt" else "bin")
                        bin_dir.mkdir(parents=True, exist_ok=True)
                        (bin_dir / ("python.exe" if os.name == "nt" else "python")).write_text("", encoding="utf-8")
                        (bin_dir / ("pip.exe" if os.name == "nt" else "pip")).write_text("", encoding="utf-8")
                return subprocess.CompletedProcess(list(cmd), 0, "", "")
            if cmd and str(cmd[0]).endswith("git") or (cmd and cmd[0] == "git"):
                return subprocess.CompletedProcess(list(cmd), 128, "", "fatal: repository not found")
            raise AssertionError(f"unexpected subprocess {cmd}")

        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = ModuleManager(discovery_roots=(REPO_MODULES,), enabled=True)
            discovered = {item.module_id for item in manager.discover()}
            self.assertIn("ghosttrack", discovered)
            self.assertIn("agent-reach", discovered)
            self.assertIn("desktop-commander-mcp", discovered)
            ctx = ModuleContext(database_path=str(tmp / "control.db"), data_root=str(tmp / "data"))
            for module_id in ("ghosttrack", "agent-reach", "desktop-commander-mcp"):
                manager.initialize(module_id, ctx)

            with (
                patch("Data.modules.module_manager.external.install.shutil.which", side_effect=_which),
                patch("Data.modules.module_manager.external.dependencies.shutil.which", side_effect=_which),
                patch("Data.modules.module_manager.external.install.subprocess.run", side_effect=_run),
            ):
                with self.assertRaises(ModuleManagerError) as ghost:
                    manager.ensure_installed("ghosttrack")
                self.assertEqual(ghost.exception.code, "INSTALL_FAILED")
                self.assertIn("git clone failed", ghost.exception.detail)
                self.assertEqual(manager.get("ghosttrack").status, ModuleStatus.FAILED)  # type: ignore[union-attr]

                with self.assertRaises(ModuleManagerError) as reach:
                    manager.ensure_installed("agent-reach")
                self.assertEqual(reach.exception.code, "INSTALL_FAILED")
                self.assertEqual(manager.get("agent-reach").status, ModuleStatus.FAILED)  # type: ignore[union-attr]

            with self.assertRaises(ModuleManagerError) as mcp:
                manager.ensure_installed("desktop-commander-mcp")
            self.assertEqual(mcp.exception.code, "PROTOCOL_ERROR")
            self.assertIn("mcp_bridge", mcp.exception.detail)
            self.assertEqual(manager.get("desktop-commander-mcp").status, ModuleStatus.FAILED)  # type: ignore[union-attr]
            self.assertNotEqual(manager.get("desktop-commander-mcp").status, ModuleStatus.INSTALLED)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
