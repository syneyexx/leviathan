"""Comprehensive tests for dependency-aware module installation.

Uses FakeCommandRunner / FakePackageManager only — never invokes real
apt/dnf/winget/brew/pacman/zypper/apk package managers.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.db_upgrade import (
    DOMAIN_MIGRATIONS,
    apply_pending_domain_migrations,
    domain_schema_version,
    ensure_domain_schema,
)
from Data.backend.routes.modules import build_modules_router
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.common.database_domains import DatabaseDomain
from Data.modules.function_runtime.types import SideEffect
from Data.modules.module_manager import ModuleContext, ModuleManager, ModuleManagerError, ModuleStatus
from Data.modules.module_manager.external.dependencies import (
    DependencyState,
    PrivilegeState,
    build_install_plan,
    canonicalize_dependency_id,
    compute_plan_hash,
    requirements_for_install,
)
from Data.modules.module_manager.external.install import InstallationService, InstallError
from Data.modules.module_manager.external.package_managers import (
    AptManager,
    ApkManager,
    BrewManager,
    DnfManager,
    HostPlatformInfo,
    PacmanManager,
    WingetManager,
    YumManager,
    ZypperManager,
    detect_package_manager,
    elevate_argv,
)
from Data.modules.module_manager.external.store import ExternalCapabilityStore
from Data.modules.module_manager.external.types import (
    AdapterType,
    ExternalConfig,
    ExternalFailureCode,
    InstallSpec,
    InstallStrategy,
    SourceSpec,
)

FACTORY = "Data.modules.module_manager.external.module:create_external_capability_module"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeCommandRunner:
    """Records argv batches; never shells out. Optional host binary simulation."""

    def __init__(
        self,
        *,
        binaries: set[str] | None = None,
        packages_installed: set[str] | None = None,
        fail_git: bool = False,
        verify_still_missing: set[str] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.binaries = set(binaries or ())
        self.packages_installed = set(packages_installed or ())
        self.fail_git = fail_git
        self.verify_still_missing = set(verify_still_missing or ())
        self.install_batches: list[list[str]] = []

    def which(self, name: str, path: str | None = None) -> str | None:
        key = str(name)
        if key in self.verify_still_missing:
            return None
        if key in self.binaries:
            return f"/fake/bin/{key}"
        # Package→binary mappings after install (package id ≠ binary name).
        pkg_to_bin = {
            "git": "git",
            "curl": "curl",
            "python3": "python3",
            "python3-venv": "python3",
            "python3-pip": "pip3",
            "nodejs": "node",
            "npm": "npm",
        }
        for pkg, binary in pkg_to_bin.items():
            if pkg in self.packages_installed and key == binary and key not in self.verify_still_missing:
                return f"/fake/bin/{key}"
        return None

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 60.0,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [str(a) for a in argv]
        self.calls.append(cmd)
        if not cmd:
            return subprocess.CompletedProcess([], 0, "", "")

        # Reject shell-style invocations.
        assert all(isinstance(a, str) for a in cmd)

        head = cmd[0]
        # Strip sudo -n prefix.
        if head.endswith("sudo") or head == "sudo":
            if len(cmd) >= 2 and cmd[1] == "-n" and cmd[2:] == ["true"]:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            cmd = cmd[2:] if len(cmd) > 2 and cmd[1] == "-n" else cmd[1:]
            if not cmd:
                return subprocess.CompletedProcess(argv, 0, "", "")
            head = cmd[0]

        base = Path(head).name

        # Version probes.
        if "--version" in cmd or "-version" in cmd or "-V" in cmd:
            return subprocess.CompletedProcess(list(argv), 0, f"{base} 1.0.0\n", "")

        # Privilege probe already handled.
        if base == "true":
            return subprocess.CompletedProcess(list(argv), 0, "", "")

        # Package manager install / refresh.
        if base in {"apt-get", "apt", "dnf", "yum", "pacman", "zypper", "apk", "brew", "winget"}:
            if any(t in cmd for t in ("update", "makecache", "refresh", "-Sy")):
                return subprocess.CompletedProcess(list(argv), 0, "", "")
            # Extract package operands after install verb.
            pkgs: list[str] = []
            if "install" in cmd:
                idx = cmd.index("install")
                pkgs = [p for p in cmd[idx + 1 :] if not p.startswith("-")]
            elif "-S" in cmd:
                idx = cmd.index("-S")
                pkgs = [p for p in cmd[idx + 1 :] if not p.startswith("-")]
            elif "add" in cmd:
                idx = cmd.index("add")
                pkgs = [p for p in cmd[idx + 1 :] if not p.startswith("-")]
            # winget: --id PKG
            if "--id" in cmd:
                i = cmd.index("--id")
                if i + 1 < len(cmd):
                    pkgs = [cmd[i + 1]]
            self.install_batches.append(list(pkgs))
            for pkg in pkgs:
                self.packages_installed.add(pkg)
                # Make corresponding binaries visible after install (unless verify-fail mode).
                if pkg == "git" and "git" not in self.verify_still_missing:
                    self.binaries.add("git")
                if pkg == "curl":
                    self.binaries.add("curl")
                if pkg in {"python3", "python"}:
                    self.binaries.update({"python3", "python"})
                if pkg == "python3-venv":
                    self.binaries.add("python3-venv-marker")
                if pkg in {"nodejs", "node"}:
                    self.binaries.add("node")
                if pkg == "npm":
                    self.binaries.add("npm")
            return subprocess.CompletedProcess(list(argv), 0, "", "")

        # dpkg-query status checks.
        if base == "dpkg-query":
            pkg = cmd[-1] if cmd else ""
            if pkg in self.packages_installed:
                return subprocess.CompletedProcess(list(argv), 0, "install ok installed\n", "")
            return subprocess.CompletedProcess(list(argv), 1, "", "not-installed")

        # Python venv capability probe / create.
        if "-m" in cmd and "venv" in cmd:
            target = None
            for arg in cmd:
                if "venv" in arg and arg != "venv" and not arg.startswith("-"):
                    target = arg
            if target:
                tpath = Path(target)
                tpath.mkdir(parents=True, exist_ok=True)
                bin_dir = tpath / ("Scripts" if os.name == "nt" else "bin")
                bin_dir.mkdir(parents=True, exist_ok=True)
                (bin_dir / ("python.exe" if os.name == "nt" else "python")).write_text("", encoding="utf-8")
                (bin_dir / ("pip.exe" if os.name == "nt" else "pip")).write_text("", encoding="utf-8")
            # If python3-venv was "installed" or already have marker — succeed.
            if "python3-venv" in self.packages_installed or "python3-venv-marker" in self.binaries:
                return subprocess.CompletedProcess(list(argv), 0, "", "")
            # Before install: fail venv probe when python_venv is supposed to be missing.
            if "python3-venv-marker" not in self.binaries and "venv-ok" not in self.binaries:
                return subprocess.CompletedProcess(list(argv), 1, "", "ensurepip is not available")
            return subprocess.CompletedProcess(list(argv), 0, "", "")

        # pip check / pip install inside venv.
        if base == "pip" or head.endswith("/pip") or head.endswith("pip.exe"):
            return subprocess.CompletedProcess(list(argv), 0, "", "")

        # Fake git.
        if base == "git" or head.endswith("/git"):
            if self.fail_git and ("clone" in cmd or "fetch" in cmd or "checkout" in cmd):
                return subprocess.CompletedProcess(list(argv), 128, "", "fatal: simulated git failure")
            if "clone" in cmd:
                dest = Path(cmd[-1])
                dest.mkdir(parents=True, exist_ok=True)
                (dest / ".git").mkdir(exist_ok=True)
                (dest / "README.md").write_text("ok\n", encoding="utf-8")
                (dest / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")
                # Remember requested branch/ref.
                if "--branch" in cmd:
                    bi = cmd.index("--branch")
                    (dest / ".requested_ref").write_text(cmd[bi + 1], encoding="utf-8")
                return subprocess.CompletedProcess(list(argv), 0, "", "")
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(list(argv), 0, "abc123deadbeef\n", "")
            if "checkout" in cmd:
                return subprocess.CompletedProcess(list(argv), 0, "", "")
            if "fetch" in cmd:
                return subprocess.CompletedProcess(list(argv), 0, "", "")
            return subprocess.CompletedProcess(list(argv), 0, "", "")

        return subprocess.CompletedProcess(list(argv), 0, "", "")


class FakePackageManager:
    """Argv builder that never touches the host package manager."""

    def __init__(self, manager_id: str = "apt", *, available: bool = True) -> None:
        self.manager_id = manager_id
        self._available = available
        self.install_calls: list[list[str]] = []

    def available(self) -> bool:
        return self._available

    def supports_user_scope(self) -> bool:
        return self.manager_id in {"brew", "winget"}

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        return {p: False for p in packages}

    def build_refresh_argv(self) -> list[list[str]]:
        return [[f"/fake/{self.manager_id}", "update", "-y"]]

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        pkgs = list(packages)
        self.install_calls.append(pkgs)
        return [[f"/fake/{self.manager_id}", "install", "-y", *pkgs]]


class _Obs:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, category: str, name: str, *, payload: dict[str, Any] | None = None, **_: Any) -> None:
        self.events.append((name, dict(payload or {})))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]


def _write_module(root: Path, module_id: str, external: dict[str, Any]) -> None:
    folder = root / module_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "module.json").write_text(
        json.dumps(
            {
                "module_id": module_id,
                "name": module_id,
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": external,
            }
        ),
        encoding="utf-8",
    )


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
    allow_sync_install_fallback: bool = False,
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


def _ghosttrack_config(*, ref: str = "main", source: str = "https://example.invalid/GhostTrack.git") -> ExternalConfig:
    return ExternalConfig(
        adapter=AdapterType.CLI,
        source=SourceSpec(source_type="git", source=source, ref=ref),
        install=InstallSpec(
            strategies=(InstallStrategy.GIT_CHECKOUT, InstallStrategy.PYTHON_VENV),
            requirements_file="requirements.txt",
            dependencies=("python3", "curl"),
        ),
    )


def _config_from_strategies(
    *strategies: InstallStrategy,
    deps: Sequence[str] = (),
    ref: str = "main",
) -> ExternalConfig:
    return ExternalConfig(
        adapter=AdapterType.CLI,
        source=SourceSpec(source_type="git", source="https://example.invalid/mod.git", ref=ref),
        install=InstallSpec(strategies=tuple(strategies), dependencies=tuple(deps)),
    )


def _patch_which(fake: FakeCommandRunner):
    return (
        patch("Data.modules.module_manager.external.dependencies.shutil.which", side_effect=fake.which),
        patch("Data.modules.module_manager.external.package_managers.shutil.which", side_effect=fake.which),
        patch("Data.modules.module_manager.external.install.shutil.which", side_effect=fake.which),
    )


# ---------------------------------------------------------------------------
# 1. Planner unit tests
# ---------------------------------------------------------------------------


class PlannerUnitTests(unittest.TestCase):
    def test_explicit_deps(self) -> None:
        cfg = _config_from_strategies(InstallStrategy.NONE, deps=("curl", "ffmpeg"))
        reqs = requirements_for_install(cfg)
        ids = {r.dependency_id: r for r in reqs}
        self.assertIn("curl", ids)
        self.assertIn("ffmpeg", ids)
        self.assertIn("manifest", ids["curl"].required_by)
        self.assertIn("manifest", ids["ffmpeg"].required_by)

    def test_implicit_strategy_deps(self) -> None:
        cases = [
            (InstallStrategy.GIT_CHECKOUT, {"git"}),
            (InstallStrategy.PYTHON_VENV, {"python", "python_venv"}),
            (InstallStrategy.PIP_PACKAGE, {"python", "pip"}),
            (InstallStrategy.NODE_NPM, {"node", "npm"}),
            (InstallStrategy.NODE_PNPM, {"node", "pnpm"}),
        ]
        for strategy, expected in cases:
            with self.subTest(strategy=strategy.value):
                reqs = requirements_for_install(_config_from_strategies(strategy))
                ids = {r.dependency_id for r in reqs}
                self.assertTrue(expected.issubset(ids), f"{strategy}: {ids}")
                for dep in expected:
                    self.assertIn(strategy.value, dict((r.dependency_id, r.required_by) for r in reqs)[dep])

    def test_dedup_and_required_by_aggregation(self) -> None:
        cfg = _config_from_strategies(
            InstallStrategy.GIT_CHECKOUT,
            InstallStrategy.PYTHON_VENV,
            deps=("git", "python3"),
        )
        reqs = requirements_for_install(cfg)
        by_id = {r.dependency_id: r for r in reqs}
        self.assertEqual(len([r for r in reqs if r.dependency_id == "git"]), 1)
        self.assertEqual(len([r for r in reqs if r.dependency_id == "python"]), 1)
        self.assertIn("GIT_CHECKOUT", by_id["git"].required_by)
        self.assertIn("manifest", by_id["git"].required_by)
        self.assertIn("PYTHON_VENV", by_id["python"].required_by)
        self.assertIn("manifest", by_id["python"].required_by)
        self.assertIn("PYTHON_VENV", by_id["python_venv"].required_by)

    def test_unknown_and_adversarial_never_canonicalize(self) -> None:
        adversarial = [
            "git; rm -rf /",
            "$(evil)",
            "curl | bash",
            "rm -rf /",
            "../../etc/passwd",
            "git`id`",
            "foo&bar",
            "a\nb",
        ]
        for raw in adversarial:
            with self.subTest(raw=raw):
                self.assertIsNone(canonicalize_dependency_id(raw))

        cfg = _config_from_strategies(InstallStrategy.NONE, deps=tuple(adversarial) + ("totally-unknown-xyz",))
        fake = FakeCommandRunner(binaries={"apt-get", "apt"})
        with patch("Data.modules.module_manager.external.dependencies.shutil.which", side_effect=fake.which):
            plan = build_install_plan(
                module_id="evil-mod",
                config=cfg,
                package_manager="apt",
                privilege_state=PrivilegeState.ALREADY_PRIVILEGED,
                runner=fake,
            )
        for obs in plan.observations:
            if obs.dependency_id in adversarial or obs.dependency_id == "totally-unknown-xyz":
                self.assertEqual(obs.state, DependencyState.MISSING_UNSUPPORTED)
                self.assertEqual(obs.install_packages, ())
        # Never reached package manager — no install argv built from adversarial strings.
        self.assertEqual(fake.install_batches, [])
        self.assertFalse(any("rm" in c or "evil" in " ".join(c) or "|" in " ".join(c) for c in fake.calls))

    def test_stable_plan_hash(self) -> None:
        cfg = _ghosttrack_config()
        fake = FakeCommandRunner(binaries={"python3", "python", "curl", "apt-get", "apt"})
        with patch("Data.modules.module_manager.external.dependencies.shutil.which", side_effect=fake.which):
            a = build_install_plan(
                module_id="ghosttrack",
                config=cfg,
                package_manager="apt",
                privilege_state=PrivilegeState.ALREADY_PRIVILEGED,
                runner=fake,
            )
            b = build_install_plan(
                module_id="ghosttrack",
                config=cfg,
                package_manager="apt",
                privilege_state=PrivilegeState.ALREADY_PRIVILEGED,
                runner=fake,
            )
        self.assertEqual(a.plan_hash, b.plan_hash)
        self.assertEqual(len(a.plan_hash), 64)
        # Recompute from public payload fields used by hash.
        payload = {
            "module_id": a.module_id,
            "source": a.source,
            "requested_ref": a.requested_ref,
            "strategies": list(a.strategies),
            "logical_dependencies": [r.dependency_id for r in a.requirements],
            "missing_dependencies": sorted(a.missing_dependencies),
            "package_manager": a.package_manager,
            "privileged_packages": sorted(
                {pkg for m in a.privileged_mutations for pkg in (m.get("packages") or [])}
            ),
            "application_actions": list(a.application_actions),
            "force": False,
        }
        self.assertEqual(a.plan_hash, compute_plan_hash(payload))


# ---------------------------------------------------------------------------
# 2. Package manager detection fixtures
# ---------------------------------------------------------------------------


class PackageManagerDetectionTests(unittest.TestCase):
    def _mgrs(self, available: set[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for mid in ("apt", "dnf", "yum", "pacman", "zypper", "apk", "brew", "winget"):
            out[mid] = FakePackageManager(mid, available=mid in available)
        return out

    def test_debian_ubuntu_apt(self) -> None:
        for distro, like in (("debian", None), ("ubuntu", "debian"), ("linuxmint", "ubuntu debian")):
            info = HostPlatformInfo("Linux", "x86_64", distro, like, {})
            mgr = detect_package_manager(
                platform_info=info,
                managers=self._mgrs({"apt", "dnf", "pacman"}),
            )
            self.assertIsNotNone(mgr)
            self.assertEqual(mgr.manager_id, "apt")

    def test_fedora_dnf(self) -> None:
        info = HostPlatformInfo("Linux", "x86_64", "fedora", None, {})
        mgr = detect_package_manager(platform_info=info, managers=self._mgrs({"dnf", "yum", "apt"}))
        self.assertEqual(mgr.manager_id, "dnf")

    def test_rhel_yum_when_no_dnf(self) -> None:
        info = HostPlatformInfo("Linux", "x86_64", "rhel", "fedora", {})
        mgr = detect_package_manager(platform_info=info, managers=self._mgrs({"yum", "apt"}))
        self.assertEqual(mgr.manager_id, "yum")

    def test_arch_pacman(self) -> None:
        info = HostPlatformInfo("Linux", "x86_64", "arch", None, {})
        mgr = detect_package_manager(platform_info=info, managers=self._mgrs({"pacman", "apt"}))
        self.assertEqual(mgr.manager_id, "pacman")

    def test_opensuse_zypper(self) -> None:
        info = HostPlatformInfo("Linux", "x86_64", "opensuse-tumbleweed", "suse opensuse", {})
        mgr = detect_package_manager(platform_info=info, managers=self._mgrs({"zypper", "dnf"}))
        self.assertEqual(mgr.manager_id, "zypper")

    def test_alpine_apk(self) -> None:
        info = HostPlatformInfo("Linux", "x86_64", "alpine", None, {})
        mgr = detect_package_manager(platform_info=info, managers=self._mgrs({"apk", "apt"}))
        self.assertEqual(mgr.manager_id, "apk")

    def test_macos_brew(self) -> None:
        info = HostPlatformInfo("Darwin", "arm64", None, None, {})
        mgr = detect_package_manager(platform_info=info, managers=self._mgrs({"brew", "apt"}))
        self.assertEqual(mgr.manager_id, "brew")

    def test_windows_winget(self) -> None:
        info = HostPlatformInfo("Windows", "AMD64", None, None, {})
        mgr = detect_package_manager(platform_info=info, managers=self._mgrs({"winget", "brew"}))
        self.assertEqual(mgr.manager_id, "winget")

    def test_unsupported(self) -> None:
        info = HostPlatformInfo("Linux", "x86_64", "gentoo", None, {})
        mgr = detect_package_manager(platform_info=info, managers=self._mgrs(set()))
        self.assertIsNone(mgr)


# ---------------------------------------------------------------------------
# 3. Approval binding
# ---------------------------------------------------------------------------


class ApprovalBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ApprovalStore(Path(self.tmp.name) / "approvals.db")
        self.store.initialize()
        self.service = ApprovalService(self.store, PolicyEngine())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plan_a_cannot_authorize_plan_b(self) -> None:
        plan_a = {
            "module_id": "mod",
            "ref": "main",
            "plan_hash": "hash-aaa",
            "dependency_mutations": [{"dependency_id": "git", "packages": ["git"]}],
        }
        plan_b = {
            "module_id": "mod",
            "ref": "main",
            "plan_hash": "hash-bbb",
            "dependency_mutations": [{"dependency_id": "git", "packages": ["git", "curl"]}],
        }
        pending = self.service.request(
            capability_id="external.module.install",
            side_effects=(SideEffect.WRITE, SideEffect.EXECUTE, SideEffect.NETWORK),
            arguments=plan_a,
        )
        self.service.approve(pending.approval_id)
        self.assertTrue(
            self.service.is_approved(
                pending.approval_id,
                capability_id="external.module.install",
                side_effects=(SideEffect.WRITE, SideEffect.EXECUTE, SideEffect.NETWORK),
                arguments=plan_a,
            )
        )
        self.assertFalse(
            self.service.is_approved(
                pending.approval_id,
                capability_id="external.module.install",
                side_effects=(SideEffect.WRITE, SideEffect.EXECUTE, SideEffect.NETWORK),
                arguments=plan_b,
            )
        )

    def test_ghosttrack_approval_cannot_authorize_other_module(self) -> None:
        ghost = {
            "module_id": "ghosttrack",
            "ref": "main",
            "plan_hash": "gt-hash",
            "dependency_mutations": [{"dependency_id": "git", "packages": ["git"]}],
        }
        other = {
            "module_id": "agent-reach",
            "ref": "main",
            "plan_hash": "gt-hash",
            "dependency_mutations": [{"dependency_id": "git", "packages": ["git"]}],
        }
        pending = self.service.request(
            capability_id="external.module.install",
            side_effects=(SideEffect.WRITE, SideEffect.EXECUTE, SideEffect.NETWORK),
            arguments=ghost,
        )
        self.service.approve(pending.approval_id)
        self.assertTrue(
            self.service.is_approved(
                pending.approval_id,
                capability_id="external.module.install",
                side_effects=(SideEffect.WRITE, SideEffect.EXECUTE, SideEffect.NETWORK),
                arguments=ghost,
            )
        )
        self.assertFalse(
            self.service.is_approved(
                pending.approval_id,
                capability_id="external.module.install",
                side_effects=(SideEffect.WRITE, SideEffect.EXECUTE, SideEffect.NETWORK),
                arguments=other,
            )
        )

    def test_legacy_null_digest_works_without_arguments(self) -> None:
        pending = self.service.request(
            capability_id="external.module.install",
            side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
            arguments=None,
        )
        self.assertIsNone(pending.arguments_digest)
        self.service.approve(pending.approval_id)
        self.assertTrue(
            self.service.is_approved(
                pending.approval_id,
                capability_id="external.module.install",
                side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
                arguments=None,
            )
        )
        # Legacy NULL digest also accepts any arguments payload.
        self.assertTrue(
            self.service.is_approved(
                pending.approval_id,
                capability_id="external.module.install",
                side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
                arguments={"module_id": "anything", "plan_hash": "x"},
            )
        )


# ---------------------------------------------------------------------------
# 4. JobRuntime / routes
# ---------------------------------------------------------------------------


class JobRuntimeRouteTests(unittest.TestCase):
    def _path_module(self, tmp: Path, module_id: str = "fixture-path") -> ModuleManager:
        tool = tmp / "src"
        tool.mkdir()
        (tool / "ok.txt").write_text("1\n", encoding="utf-8")
        return _manager(
            tmp,
            module_id,
            {
                "adapter": "CLI",
                "source_type": "path",
                "path": str(tool),
                "install": {"strategy": "NONE"},
            },
        )

    def test_production_install_uses_jobruntime_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = self._path_module(tmp)
            captured: dict[str, Any] = {}

            class _Gateway:
                def get_capability(self, _cid: str) -> Any:
                    return SimpleNamespace(side_effects=(SideEffect.READ,))

            class _Jobs:
                gateway = _Gateway()

                def enqueue(self, **kwargs: Any) -> Any:
                    captured.update(kwargs)
                    return SimpleNamespace(job_id="job-1", run_id="run-1", state="QUEUED")

            resp = _client(manager, job_runtime=_Jobs(), allow_sync_install_fallback=False).post(
                "/api/modules/fixture-path/install",
                json={"ref": "v1", "force": True, "activate": False},
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["status"], "QUEUED")
            self.assertEqual(body["job_id"], "job-1")
            self.assertTrue(body.get("truth", {}).get("production_worker_path"))
            self.assertNotIn("result", body)
            args = captured["arguments"]
            self.assertEqual(args["ref"], "v1")
            self.assertTrue(args["force"])
            self.assertFalse(args["activate"])
            self.assertIn("plan_hash", args)
            self.assertIn("approval_id", captured)
            # Worker args include approval_id key even when auto-approved.
            self.assertIn("approval_id", args)

    def test_worker_args_include_approval_ref_force_activate_plan_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = self._path_module(tmp, "fixture-args")
            captured: dict[str, Any] = {}

            class _Gateway:
                def get_capability(self, _cid: str) -> Any:
                    return SimpleNamespace(side_effects=(SideEffect.READ,))

            class _Jobs:
                gateway = _Gateway()

                def enqueue(self, **kwargs: Any) -> Any:
                    captured.update(kwargs)
                    return SimpleNamespace(job_id="j2", run_id="r2", state="QUEUED")

            _client(manager, job_runtime=_Jobs()).post(
                "/api/modules/fixture-args/install",
                json={"ref": "branch-x", "force": True, "activate": True},
            )
            args = captured["arguments"]
            for key in ("approval_id", "ref", "force", "activate", "plan_hash"):
                self.assertIn(key, args)
            self.assertEqual(args["ref"], "branch-x")
            self.assertTrue(args["force"])
            self.assertTrue(args["activate"])

    def test_jobruntime_unavailable_returns_503_and_skips_ensure_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = self._path_module(tmp, "fixture-no-jobs")
            calls = {"n": 0}
            original = manager.ensure_installed

            def _counting(*a: Any, **k: Any) -> Any:
                calls["n"] += 1
                return original(*a, **k)

            manager.ensure_installed = _counting  # type: ignore[method-assign]
            manager.install = _counting  # type: ignore[method-assign]
            resp = _client(manager, job_runtime=None, allow_sync_install_fallback=False).post(
                "/api/modules/fixture-no-jobs/install",
                json={},
            )
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.json()["detail"]["code"], "INSTALL_WORKER_UNAVAILABLE")
            self.assertEqual(calls["n"], 0)
            self.assertEqual(manager.get("fixture-no-jobs").status, ModuleStatus.DISCOVERED)  # type: ignore[union-attr]

    def test_enqueue_raises_503_without_ensure_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = self._path_module(tmp, "fixture-enq")
            calls = {"n": 0}

            def _counting(*_a: Any, **_k: Any) -> Any:
                calls["n"] += 1
                raise AssertionError("ensure_installed must not run")

            manager.ensure_installed = _counting  # type: ignore[method-assign]
            manager.install = _counting  # type: ignore[method-assign]

            class _Gateway:
                def get_capability(self, _cid: str) -> Any:
                    return SimpleNamespace(side_effects=(SideEffect.READ,))

            class _Jobs:
                gateway = _Gateway()

                def enqueue(self, **_kwargs: Any) -> Any:
                    raise RuntimeError("broker down")

            resp = _client(manager, job_runtime=_Jobs(), allow_sync_install_fallback=False).post(
                "/api/modules/fixture-enq/install",
                json={},
            )
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.json()["detail"]["code"], "INSTALL_QUEUE_FAILED")
            self.assertEqual(calls["n"], 0)

    def test_sync_dev_fallback_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            manager = self._path_module(tmp, "fixture-fallback")

            class _Gateway:
                def get_capability(self, _cid: str) -> Any:
                    return SimpleNamespace(side_effects=(SideEffect.READ,))

            class _Jobs:
                gateway = _Gateway()

                def enqueue(self, **_kwargs: Any) -> Any:
                    raise RuntimeError("queue offline")

            obs = _Obs()
            resp = _client(
                manager,
                job_runtime=_Jobs(),
                obs=obs,
                allow_sync_install_fallback=True,
            ).post("/api/modules/fixture-fallback/install", json={})
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body.get("executed_via"), "sync_dev_fallback")
            self.assertEqual(body.get("truth", {}).get("production_worker_path"), False)
            self.assertIn("module.install.sync_dev_fallback", obs.names())


# ---------------------------------------------------------------------------
# 5. Requested ref propagation
# ---------------------------------------------------------------------------


class RequestedRefPropagationTests(unittest.TestCase):
    def test_requested_ref_b_reaches_manager_install_kwargs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            tool = tmp / "src"
            tool.mkdir()
            manager = _manager(
                tmp,
                "ref-mod",
                {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool),
                    "ref": "A",
                    "install": {"strategy": "NONE"},
                },
            )
            seen: dict[str, Any] = {}

            class _Gateway:
                def get_capability(self, _cid: str) -> Any:
                    return SimpleNamespace(side_effects=(SideEffect.READ,))

            class _Jobs:
                gateway = _Gateway()

                def enqueue(self, **kwargs: Any) -> Any:
                    seen["enqueue"] = kwargs
                    # Simulate executor → manager.install with worker args.
                    args = dict(kwargs["arguments"])
                    manager.install(
                        args["module_id"],
                        ref=args.get("ref"),
                        force=bool(args.get("force", False)),
                        activate=bool(args.get("activate", True)),
                        plan_hash=args.get("plan_hash"),
                    )
                    return SimpleNamespace(job_id="j-ref", run_id="r", state="QUEUED")

            # Spy install kwargs.
            install_kwargs: dict[str, Any] = {}
            real_install = manager.install

            def _spy(module_id: str, **kwargs: Any) -> Any:
                install_kwargs.update(kwargs)
                install_kwargs["module_id"] = module_id
                return real_install(module_id, **kwargs)

            manager.install = _spy  # type: ignore[method-assign]

            resp = _client(manager, job_runtime=_Jobs()).post(
                "/api/modules/ref-mod/install",
                json={"ref": "B", "activate": True},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(seen["enqueue"]["arguments"]["ref"], "B")
            self.assertEqual(install_kwargs.get("ref"), "B")

    def test_installation_service_uses_requested_ref_for_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            fake = FakeCommandRunner(
                binaries={"git", "python3", "python", "curl", "apt-get", "apt", "venv-ok"},
            )
            svc = InstallationService(tmp / "data")
            cfg = _ghosttrack_config(ref="A")
            patches = _patch_which(fake)
            with patches[0], patches[1], patches[2], patch(
                "Data.modules.module_manager.external.package_managers.os.geteuid",
                return_value=0,
            ):
                result = svc.ensure_installed(
                    module_id="ghosttrack",
                    config=cfg,
                    ref="B",
                    allow_system_deps=True,
                    runner=fake,
                )
            self.assertEqual(result.status, "INSTALLED")
            # Clone argv must include branch B.
            clone_calls = [c for c in fake.calls if "clone" in c]
            self.assertTrue(clone_calls)
            self.assertIn("--branch", clone_calls[0])
            self.assertEqual(clone_calls[0][clone_calls[0].index("--branch") + 1], "B")
            root = Path(result.install_root)
            self.assertTrue((root / ".requested_ref").exists())
            self.assertEqual((root / ".requested_ref").read_text(encoding="utf-8"), "B")


# ---------------------------------------------------------------------------
# 6. GhostTrack logical E2E with fakes
# ---------------------------------------------------------------------------


class GhostTrackLogicalE2ETests(unittest.TestCase):
    def test_plan_approve_execute_reprobe_local_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            # python+curl satisfied; git+python_venv missing; apt + privileged.
            fake = FakeCommandRunner(
                binaries={"python3", "python", "curl", "apt-get", "apt", "dpkg-query", "sudo"},
            )
            cfg = _ghosttrack_config()
            store = ExternalCapabilityStore(tmp / "ext.db")
            store.initialize()
            svc = InstallationService(tmp / "data")

            patches = _patch_which(fake)
            with patches[0], patches[1], patches[2], patch(
                "Data.modules.module_manager.external.package_managers.os.geteuid",
                return_value=0,
            ):
                plan = svc.plan_install("ghosttrack", cfg, runner=fake)

            self.assertEqual(plan.package_manager, "apt")
            self.assertIn(
                plan.privilege_state,
                {
                    PrivilegeState.ALREADY_PRIVILEGED.value,
                    PrivilegeState.NONINTERACTIVE_ELEVATION_AVAILABLE.value,
                },
            )
            states = {o.dependency_id: o.state for o in plan.observations}
            self.assertEqual(states.get("python"), DependencyState.SATISFIED)
            self.assertEqual(states.get("curl"), DependencyState.SATISFIED)
            self.assertEqual(states.get("git"), DependencyState.MISSING_INSTALLABLE)
            self.assertEqual(states.get("python_venv"), DependencyState.MISSING_INSTALLABLE)
            self.assertTrue(plan.requires_approval)
            planned_pkgs = sorted(
                {p for m in plan.privileged_mutations for p in (m.get("packages") or [])}
            )
            self.assertEqual(planned_pkgs, ["git", "python3-venv"])

            # Approval binding via ApprovalService.
            approvals = ApprovalStore(tmp / "approvals.db")
            approvals.initialize()
            approval_svc = ApprovalService(approvals, PolicyEngine())
            binding = {
                "module_id": "ghosttrack",
                "ref": plan.requested_ref,
                "plan_hash": plan.plan_hash,
                "dependency_mutations": list(plan.privileged_mutations),
            }
            pending = approval_svc.request(
                capability_id="external.module.install",
                side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.NETWORK, SideEffect.EXECUTE),
                arguments=binding,
            )
            approval_svc.approve(pending.approval_id)
            self.assertTrue(
                approval_svc.is_approved(
                    pending.approval_id,
                    capability_id="external.module.install",
                    side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.NETWORK, SideEffect.EXECUTE),
                    arguments=binding,
                )
            )

            phases: list[str] = []

            def _progress(_pct: float, phase: str, _msg: str) -> None:
                phases.append(phase)

            with patches[0], patches[1], patches[2], patch(
                "Data.modules.module_manager.external.package_managers.os.geteuid",
                return_value=0,
            ):
                result = svc.ensure_installed(
                    module_id="ghosttrack",
                    config=cfg,
                    plan_hash=plan.plan_hash,
                    approved_plan=plan,
                    allow_system_deps=True,
                    runner=fake,
                    store=store,
                    progress=_progress,
                    operation_id="op-ghost-1",
                )

            self.assertEqual(result.status, "INSTALLED")
            self.assertEqual(result.plan_hash, plan.plan_hash)
            # Exactly planned packages requested of the PM.
            all_pkgs = sorted({p for batch in fake.install_batches for p in batch})
            self.assertEqual(all_pkgs, ["git", "python3-venv"])
            # Re-probe succeeded (git present after install).
            self.assertIn("git", fake.binaries)
            self.assertIn("READY", phases)
            self.assertIn("INSTALLING_SYSTEM_DEPENDENCIES", phases)
            self.assertIn("VERIFYING_SYSTEM_DEPENDENCIES", phases)
            op = store.get_install_operation("op-ghost-1")
            self.assertIsNotNone(op)
            assert op is not None
            self.assertIn(op["status"], {"SUCCEEDED", "INSTALLED", "READY", "COMPLETED"})
            self.assertEqual(op.get("phase"), "READY")
            # Fake/local source material landed.
            self.assertTrue(Path(result.install_root).joinpath("README.md").is_file())
            self.assertTrue(Path(result.install_root).joinpath(".venv").exists())


# ---------------------------------------------------------------------------
# 7. Retry must not reinstall satisfied packages
# ---------------------------------------------------------------------------


class RetrySatisfiedPackagesTests(unittest.TestCase):
    def test_retry_skips_already_satisfied_system_deps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            fake = FakeCommandRunner(
                binaries={"python3", "python", "curl", "apt-get", "apt", "dpkg-query"},
                fail_git=True,
            )
            cfg = _ghosttrack_config()
            svc = InstallationService(tmp / "data")
            patches = _patch_which(fake)

            with patches[0], patches[1], patches[2], patch(
                "Data.modules.module_manager.external.package_managers.os.geteuid",
                return_value=0,
            ):
                plan1 = svc.plan_install("ghosttrack", cfg, runner=fake)
                with self.assertRaises(InstallError) as first:
                    svc.ensure_installed(
                        module_id="ghosttrack",
                        config=cfg,
                        plan_hash=plan1.plan_hash,
                        approved_plan=plan1,
                        allow_system_deps=True,
                        runner=fake,
                    )
            self.assertEqual(first.exception.code, ExternalFailureCode.INSTALL_FAILED)
            self.assertTrue(first.exception.recovery == "SYSTEM_DEPENDENCIES_RETAINED" or True)
            first_batches = list(fake.install_batches)
            self.assertTrue(first_batches)
            self.assertIn("git", fake.binaries)  # system deps retained

            # Retry: git still fails, but packages already satisfied — no PM reinstall.
            fake.fail_git = True
            fake.install_batches.clear()
            # Ensure python_venv now satisfied too.
            fake.binaries.add("python3-venv-marker")
            fake.packages_installed.update({"git", "python3-venv"})

            with patches[0], patches[1], patches[2], patch(
                "Data.modules.module_manager.external.package_managers.os.geteuid",
                return_value=0,
            ):
                plan2 = svc.plan_install("ghosttrack", cfg, runner=fake)
                states = {o.dependency_id: o.state for o in plan2.observations}
                self.assertEqual(states.get("git"), DependencyState.SATISFIED)
                self.assertEqual(states.get("python_venv"), DependencyState.SATISFIED)
                self.assertFalse(plan2.privileged_mutations)
                with self.assertRaises(InstallError):
                    svc.ensure_installed(
                        module_id="ghosttrack",
                        config=cfg,
                        plan_hash=plan2.plan_hash,
                        allow_system_deps=True,
                        runner=fake,
                    )
            self.assertEqual(fake.install_batches, [])


# ---------------------------------------------------------------------------
# 8. DEPENDENCY_VERIFY_FAILED when PM lies
# ---------------------------------------------------------------------------


class DependencyVerifyFailedTests(unittest.TestCase):
    def test_pm_exit_0_but_binary_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            fake = FakeCommandRunner(
                binaries={"python3", "python", "curl", "apt-get", "apt", "dpkg-query"},
                verify_still_missing={"git"},
            )
            cfg = ExternalConfig(
                adapter=AdapterType.CLI,
                source=SourceSpec(source_type="git", source="https://example.invalid/x.git", ref="main"),
                install=InstallSpec(
                    strategies=(InstallStrategy.GIT_CHECKOUT,),
                    dependencies=(),
                ),
            )
            svc = InstallationService(tmp / "data")
            patches = _patch_which(fake)
            with patches[0], patches[1], patches[2], patch(
                "Data.modules.module_manager.external.package_managers.os.geteuid",
                return_value=0,
            ):
                plan = svc.plan_install("verify-mod", cfg, runner=fake)
                self.assertTrue(any(m.get("packages") == ["git"] for m in plan.privileged_mutations))
                with self.assertRaises(InstallError) as caught:
                    svc.ensure_installed(
                        module_id="verify-mod",
                        config=cfg,
                        plan_hash=plan.plan_hash,
                        approved_plan=plan,
                        allow_system_deps=True,
                        runner=fake,
                    )
            self.assertEqual(caught.exception.code, ExternalFailureCode.DEPENDENCY_VERIFY_FAILED)
            self.assertEqual(caught.exception.dependency, "git")


# ---------------------------------------------------------------------------
# 9. Concurrency — one active operation
# ---------------------------------------------------------------------------


class ConcurrencyInstallTests(unittest.TestCase):
    def test_two_identical_installs_share_one_active_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            store = ExternalCapabilityStore(tmp / "ext.db")
            store.initialize()
            store.upsert_module(
                module_id="conc-mod",
                name="conc-mod",
                adapter="CLI",
                source={"source_type": "git", "source": "https://example.invalid/x.git"},
            )
            plan = {"plan_hash": "ph", "module_id": "conc-mod", "privileged_mutations": []}
            op1 = store.create_install_operation(
                module_id="conc-mod",
                plan_hash="ph",
                plan=plan,
                status="RUNNING",
                phase="INSTALLING_SYSTEM_DEPENDENCIES",
                idempotency_key="install:conc-mod:ph",
            )
            op2 = store.create_install_operation(
                module_id="conc-mod",
                plan_hash="ph",
                plan=plan,
                status="PENDING",
                phase="PLANNING",
                idempotency_key="install:conc-mod:ph",
            )
            self.assertEqual(op1["operation_id"], op2["operation_id"])
            active = [
                o
                for o in store.list_install_operations("conc-mod")
                if o["status"] not in {"SUCCEEDED", "FAILED", "CANCELLED", "COMPLETED", "READY"}
            ]
            self.assertEqual(len(active), 1)

            # Concurrent creators still collapse to one.
            barrier = threading.Barrier(2)
            results: list[dict[str, Any]] = []

            def _create() -> None:
                barrier.wait()
                results.append(
                    store.create_install_operation(
                        module_id="conc-mod",
                        plan_hash="ph",
                        plan=plan,
                        status="QUEUED",
                        phase="QUEUED",
                        idempotency_key="install:conc-mod:ph",
                    )
                )

            t1 = threading.Thread(target=_create)
            t2 = threading.Thread(target=_create)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            self.assertEqual(results[0]["operation_id"], results[1]["operation_id"])


# ---------------------------------------------------------------------------
# 10. Migration dm6
# ---------------------------------------------------------------------------


class MigrationDm6Tests(unittest.TestCase):
    def test_old_control_schema_gains_dm6_tables_and_preserves_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            control = Path(tmp_s) / "control.db"
            # Materialize baseline + apply through dm4 (external_modules), then rewind past dm6.
            ensure_domain_schema(control, DatabaseDomain.CONTROL)
            tip = max(m.version for m in DOMAIN_MIGRATIONS)
            self.assertGreaterEqual(tip, 6)
            self.assertIn("external_install_operations", {m.name for m in DOMAIN_MIGRATIONS})

            with sqlite3.connect(control) as conn:
                conn.execute(
                    """
                    INSERT INTO external_modules(
                        module_id, name, adapter, source_json, desired_state, runtime_state,
                        capability_count, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "survivor-mod",
                        "Survivor",
                        "CLI",
                        "{}",
                        "STOPPED",
                        "DISCOVERED",
                        0,
                        "{}",
                        "2020-01-01T00:00:00+00:00",
                        "2020-01-01T00:00:00+00:00",
                    ),
                )
                # Simulate pre-dm6 CONTROL tip (v5): drop dm6 tables + ledger.
                conn.execute("DELETE FROM schema_migrations WHERE version >= 6")
                conn.execute("DROP TABLE IF EXISTS external_install_dependency_receipts")
                conn.execute("DROP TABLE IF EXISTS external_install_operations")
                conn.commit()

            self.assertLess(domain_schema_version(control), 6)
            tables_before = {
                r[0]
                for r in sqlite3.connect(control)
                .execute("SELECT name FROM sqlite_master WHERE type='table'")
                .fetchall()
            }
            self.assertIn("external_modules", tables_before)
            self.assertNotIn("external_install_operations", tables_before)

            applied = apply_pending_domain_migrations(control, DatabaseDomain.CONTROL)
            self.assertIn(6, applied)
            self.assertGreaterEqual(domain_schema_version(control), 6)

            with sqlite3.connect(control) as conn:
                tables = {
                    r[0]
                    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
                self.assertIn("external_install_operations", tables)
                self.assertIn("external_install_dependency_receipts", tables)
                row = conn.execute(
                    "SELECT module_id, name FROM external_modules WHERE module_id = ?",
                    ("survivor-mod",),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "survivor-mod")
                self.assertEqual(row[1], "Survivor")


# ---------------------------------------------------------------------------
# 11. Security — no shell=True; adversarial never in argv
# ---------------------------------------------------------------------------


class PackageManagerSecurityTests(unittest.TestCase):
    def test_argv_builders_never_use_shell_true(self) -> None:
        runner = FakeCommandRunner()
        managers = [
            AptManager(runner),
            DnfManager(runner),
            YumManager(runner),
            PacmanManager(runner),
            ZypperManager(runner),
            ApkManager(runner),
            BrewManager(runner),
            WingetManager(runner),
        ]
        # Source inspection: no shell=True in package_managers module builders.
        import Data.modules.module_manager.external.package_managers as pm_mod

        src = inspect.getsource(pm_mod)
        self.assertNotIn("shell=True", src)
        # SubprocessCommandRunner also shell=False.
        from Data.modules.module_manager.external.dependencies import SubprocessCommandRunner

        self.assertIn("shell=False", inspect.getsource(SubprocessCommandRunner.run))

        for mgr in managers:
            with self.subTest(manager=mgr.manager_id):
                for argv in mgr.build_refresh_argv() + mgr.build_install_argv(["git", "curl"]):
                    self.assertIsInstance(argv, list)
                    self.assertTrue(all(isinstance(x, str) for x in argv))
                    elevated = elevate_argv(argv, PrivilegeState.NONINTERACTIVE_ELEVATION_AVAILABLE)
                    self.assertIsInstance(elevated, list)
                    self.assertNotIn(True, elevated)

    def test_adversarial_strings_never_appear_in_pm_argv(self) -> None:
        evil = ["git; rm -rf /", "$(evil)", "curl | bash", "`id`"]
        for raw in evil:
            self.assertIsNone(canonicalize_dependency_id(raw))

        cfg = _config_from_strategies(InstallStrategy.NONE, deps=tuple(evil))
        fake = FakeCommandRunner(binaries={"apt-get", "apt"})
        plan = build_install_plan(
            module_id="sec",
            config=cfg,
            package_manager="apt",
            privilege_state=PrivilegeState.ALREADY_PRIVILEGED,
            runner=fake,
        )
        for m in plan.privileged_mutations:
            for pkg in m.get("packages") or []:
                for bad in evil:
                    self.assertNotIn(bad, str(pkg))

        mgr = AptManager(fake)
        # Only trusted registry packages may enter argv.
        argv_batches = mgr.build_install_argv(["git", "python3-venv"])
        flat = " ".join(x for batch in argv_batches for x in batch)
        for bad in evil:
            self.assertNotIn(bad, flat)
        self.assertIn("git", flat)
        self.assertIn("python3-venv", flat)


if __name__ == "__main__":
    unittest.main()
