"""Trusted logical dependency registry, probes, and install-plan generation.

Manifest dependency strings are logical identifiers — never passed directly
to a package manager. Package names come only from this registry.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .types import ExternalConfig, InstallStrategy


class DependencyKind(str, Enum):
    BINARY = "BINARY"
    RUNTIME = "RUNTIME"
    RUNTIME_CAPABILITY = "RUNTIME_CAPABILITY"
    PACKAGE_MANAGER = "PACKAGE_MANAGER"


class DependencyState(str, Enum):
    SATISFIED = "SATISFIED"
    MISSING_INSTALLABLE = "MISSING_INSTALLABLE"
    MISSING_UNSUPPORTED = "MISSING_UNSUPPORTED"
    VERSION_MISMATCH_INSTALLABLE = "VERSION_MISMATCH_INSTALLABLE"
    VERSION_MISMATCH_UNSUPPORTED = "VERSION_MISMATCH_UNSUPPORTED"
    UNMEASURED = "UNMEASURED"
    BLOCKED_PRIVILEGE = "BLOCKED_PRIVILEGE"


class PrivilegeState(str, Enum):
    ALREADY_PRIVILEGED = "ALREADY_PRIVILEGED"
    NONINTERACTIVE_ELEVATION_AVAILABLE = "NONINTERACTIVE_ELEVATION_AVAILABLE"
    USER_SCOPE_INSTALL_AVAILABLE = "USER_SCOPE_INSTALL_AVAILABLE"
    PRIVILEGE_REQUIRED = "PRIVILEGE_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


class InstallPhase(str, Enum):
    PLANNING = "PLANNING"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    INSTALLING_SYSTEM_DEPENDENCIES = "INSTALLING_SYSTEM_DEPENDENCIES"
    VERIFYING_SYSTEM_DEPENDENCIES = "VERIFYING_SYSTEM_DEPENDENCIES"
    FETCHING_SOURCE = "FETCHING_SOURCE"
    PREPARING_RUNTIME = "PREPARING_RUNTIME"
    INSTALLING_APPLICATION_DEPENDENCIES = "INSTALLING_APPLICATION_DEPENDENCIES"
    POST_INSTALL = "POST_INSTALL"
    VERIFYING_INSTALLATION = "VERIFYING_INSTALLATION"
    ACTIVATING = "ACTIVATING"
    READY = "READY"
    FAILED = "FAILED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"


# Strategy → logical dependency ids (implicit).
_STRATEGY_IMPLICIT: dict[InstallStrategy, tuple[str, ...]] = {
    InstallStrategy.GIT_CHECKOUT: ("git",),
    InstallStrategy.PYTHON_VENV: ("python", "python_venv"),
    InstallStrategy.PIP_PACKAGE: ("python", "pip"),
    InstallStrategy.NODE_NPM: ("node", "npm"),
    InstallStrategy.NODE_PNPM: ("node", "pnpm"),
    InstallStrategy.NODE_SCRIPT: ("node",),
}

# Manifest alias → canonical logical id.
_DEPENDENCY_ALIASES: dict[str, str] = {
    "python3": "python",
    "python": "python",
    "py": "python",
    "pip3": "pip",
    "pip": "pip",
    "python3-venv": "python_venv",
    "python-venv": "python_venv",
    "venv": "python_venv",
    "git": "git",
    "curl": "curl",
    "node": "node",
    "nodejs": "node",
    "npm": "npm",
    "pnpm": "pnpm",
    "bash": "bash",
    "ffmpeg": "ffmpeg",
}


@dataclass(frozen=True)
class PackageCandidate:
    """Trusted package-manager package identifiers for one logical dependency."""

    manager_id: str
    packages: tuple[str, ...]


@dataclass(frozen=True)
class LogicalDependency:
    dependency_id: str
    kind: DependencyKind
    binary_candidates: tuple[str, ...] = ()
    package_candidates: tuple[PackageCandidate, ...] = ()
    version_probe_argv: tuple[str, ...] | None = None  # appended after resolved binary
    capability_probe: str | None = None  # "python_venv" etc.


# Trusted registry — never accept package names from third-party manifests.
LOGICAL_DEPENDENCY_REGISTRY: dict[str, LogicalDependency] = {
    "git": LogicalDependency(
        dependency_id="git",
        kind=DependencyKind.BINARY,
        binary_candidates=("git",),
        package_candidates=(
            PackageCandidate("apt", ("git",)),
            PackageCandidate("dnf", ("git",)),
            PackageCandidate("yum", ("git",)),
            PackageCandidate("pacman", ("git",)),
            PackageCandidate("zypper", ("git",)),
            PackageCandidate("apk", ("git",)),
            PackageCandidate("brew", ("git",)),
            PackageCandidate("winget", ("Git.Git",)),
        ),
        version_probe_argv=("--version",),
    ),
    "curl": LogicalDependency(
        dependency_id="curl",
        kind=DependencyKind.BINARY,
        binary_candidates=("curl",),
        package_candidates=(
            PackageCandidate("apt", ("curl",)),
            PackageCandidate("dnf", ("curl",)),
            PackageCandidate("yum", ("curl",)),
            PackageCandidate("pacman", ("curl",)),
            PackageCandidate("zypper", ("curl",)),
            PackageCandidate("apk", ("curl",)),
            PackageCandidate("brew", ("curl",)),
            PackageCandidate("winget", ("cURL.cURL",)),
        ),
        version_probe_argv=("--version",),
    ),
    "python": LogicalDependency(
        dependency_id="python",
        kind=DependencyKind.RUNTIME,
        binary_candidates=("python3", "python", "py"),
        package_candidates=(
            PackageCandidate("apt", ("python3",)),
            PackageCandidate("dnf", ("python3",)),
            PackageCandidate("yum", ("python3",)),
            PackageCandidate("pacman", ("python",)),
            PackageCandidate("zypper", ("python3",)),
            PackageCandidate("apk", ("python3",)),
            PackageCandidate("brew", ("python"),),
            PackageCandidate("winget", ("Python.Python.3.12",)),
        ),
        version_probe_argv=("--version",),
    ),
    "python_venv": LogicalDependency(
        dependency_id="python_venv",
        kind=DependencyKind.RUNTIME_CAPABILITY,
        binary_candidates=(),
        package_candidates=(
            PackageCandidate("apt", ("python3-venv",)),
            PackageCandidate("dnf", ("python3",)),
            PackageCandidate("yum", ("python3",)),
            PackageCandidate("pacman", ("python",)),
            PackageCandidate("zypper", ("python3-venv",)),
            PackageCandidate("apk", ("python3",)),
            # brew/python includes venv; winget Python includes venv module
            PackageCandidate("brew", ("python",)),
            PackageCandidate("winget", ("Python.Python.3.12",)),
        ),
        capability_probe="python_venv",
    ),
    "pip": LogicalDependency(
        dependency_id="pip",
        kind=DependencyKind.BINARY,
        binary_candidates=("pip3", "pip"),
        package_candidates=(
            PackageCandidate("apt", ("python3-pip",)),
            PackageCandidate("dnf", ("python3-pip",)),
            PackageCandidate("yum", ("python3-pip",)),
            PackageCandidate("pacman", ("python-pip",)),
            PackageCandidate("zypper", ("python3-pip",)),
            PackageCandidate("apk", ("py3-pip",)),
            PackageCandidate("brew", ("python",)),
            PackageCandidate("winget", ("Python.Python.3.12",)),
        ),
        version_probe_argv=("--version",),
    ),
    "node": LogicalDependency(
        dependency_id="node",
        kind=DependencyKind.RUNTIME,
        binary_candidates=("node",),
        package_candidates=(
            PackageCandidate("apt", ("nodejs",)),
            PackageCandidate("dnf", ("nodejs",)),
            PackageCandidate("yum", ("nodejs",)),
            PackageCandidate("pacman", ("nodejs",)),
            PackageCandidate("zypper", ("nodejs",)),
            PackageCandidate("apk", ("nodejs",)),
            PackageCandidate("brew", ("node",)),
            PackageCandidate("winget", ("OpenJS.NodeJS.LTS",)),
        ),
        version_probe_argv=("--version",),
    ),
    "npm": LogicalDependency(
        dependency_id="npm",
        kind=DependencyKind.BINARY,
        binary_candidates=("npm",),
        package_candidates=(
            PackageCandidate("apt", ("npm",)),
            PackageCandidate("dnf", ("npm",)),
            PackageCandidate("yum", ("npm",)),
            PackageCandidate("pacman", ("npm",)),
            PackageCandidate("zypper", ("npm",)),
            PackageCandidate("apk", ("npm",)),
            PackageCandidate("brew", ("node",)),
            PackageCandidate("winget", ("OpenJS.NodeJS.LTS",)),
        ),
        version_probe_argv=("--version",),
    ),
    "pnpm": LogicalDependency(
        dependency_id="pnpm",
        kind=DependencyKind.BINARY,
        binary_candidates=("pnpm",),
        package_candidates=(
            PackageCandidate("brew", ("pnpm",)),
            PackageCandidate("winget", ("pnpm.pnpm",)),
            # Many Linux distros lack a first-party pnpm package — unsupported via apt/etc.
        ),
        version_probe_argv=("--version",),
    ),
    "bash": LogicalDependency(
        dependency_id="bash",
        kind=DependencyKind.BINARY,
        binary_candidates=("bash",),
        package_candidates=(
            PackageCandidate("apt", ("bash",)),
            PackageCandidate("dnf", ("bash",)),
            PackageCandidate("yum", ("bash",)),
            PackageCandidate("pacman", ("bash",)),
            PackageCandidate("zypper", ("bash",)),
            PackageCandidate("apk", ("bash",)),
            PackageCandidate("brew", ("bash",)),
        ),
        version_probe_argv=("--version",),
    ),
    "ffmpeg": LogicalDependency(
        dependency_id="ffmpeg",
        kind=DependencyKind.BINARY,
        binary_candidates=("ffmpeg",),
        package_candidates=(
            PackageCandidate("apt", ("ffmpeg",)),
            PackageCandidate("dnf", ("ffmpeg",)),
            PackageCandidate("yum", ("ffmpeg",)),
            PackageCandidate("pacman", ("ffmpeg",)),
            PackageCandidate("zypper", ("ffmpeg",)),
            PackageCandidate("apk", ("ffmpeg",)),
            PackageCandidate("brew", ("ffmpeg",)),
            PackageCandidate("winget", ("Gyan.FFmpeg",)),
        ),
        version_probe_argv=("-version",),
    ),
}


@dataclass(frozen=True)
class DependencyRequirement:
    dependency_id: str
    kind: DependencyKind
    required_by: tuple[str, ...]
    required: bool = True
    version_constraint: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "kind": self.kind.value,
            "required_by": list(self.required_by),
            "required": self.required,
            "version_constraint": self.version_constraint,
        }


@dataclass(frozen=True)
class DependencyObservation:
    dependency_id: str
    state: DependencyState
    resolved_binary: str | None = None
    observed_version: str | None = None
    package_manager: str | None = None
    install_packages: tuple[str, ...] = ()
    detail: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "state": self.state.value,
            "resolved_binary": self.resolved_binary,
            "observed_version": self.observed_version,
            "package_manager": self.package_manager,
            "install_packages": list(self.install_packages),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class InstallPlan:
    module_id: str
    requested_ref: str
    strategies: tuple[str, ...]
    requirements: tuple[DependencyRequirement, ...]
    observations: tuple[DependencyObservation, ...]
    missing_dependencies: tuple[str, ...]
    privileged_mutations: tuple[dict[str, Any], ...]
    application_actions: tuple[dict[str, Any], ...]
    package_manager: str | None
    privilege_state: str
    requires_approval: bool
    installable: bool
    blockers: tuple[dict[str, Any], ...]
    plan_hash: str
    source: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "requested_ref": self.requested_ref,
            "strategies": list(self.strategies),
            "requirements": [r.public_dict() for r in self.requirements],
            "observations": [o.public_dict() for o in self.observations],
            "missing_dependencies": list(self.missing_dependencies),
            "privileged_mutations": list(self.privileged_mutations),
            "application_actions": list(self.application_actions),
            "package_manager": self.package_manager,
            "privilege_state": self.privilege_state,
            "requires_approval": self.requires_approval,
            "installable": self.installable,
            "blockers": list(self.blockers),
            "plan_hash": self.plan_hash,
            "source": dict(self.source),
        }

    def privileged_dependency_ids(self) -> tuple[str, ...]:
        return tuple(
            str(m.get("dependency_id"))
            for m in self.privileged_mutations
            if m.get("dependency_id")
        )


class CommandRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 60.0,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 60.0,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            cwd=cwd,
            env=dict(env) if env is not None else None,
        )


def canonicalize_dependency_id(raw: str) -> str | None:
    """Map a manifest dependency string to a trusted logical id, or None if unknown."""
    key = str(raw or "").strip().lower()
    if not key:
        return None
    # Reject anything that looks like shell injection / path traversal.
    if any(ch in key for ch in (";", "|", "&", "$", "`", "\n", "\r", "(", ")", "<", ">", "\\", "/", " ")):
        return None
    if ".." in key:
        return None
    return _DEPENDENCY_ALIASES.get(key) or (key if key in LOGICAL_DEPENDENCY_REGISTRY else None)


def requirements_for_install(config: ExternalConfig) -> tuple[DependencyRequirement, ...]:
    """Merge explicit manifest dependencies with strategy-implied ones."""
    by_id: dict[str, list[str]] = {}
    kinds: dict[str, DependencyKind] = {}
    unsupported: list[DependencyRequirement] = []

    for strategy in config.install.strategies:
        for dep_id in _STRATEGY_IMPLICIT.get(strategy, ()):
            by_id.setdefault(dep_id, [])
            tag = strategy.value
            if tag not in by_id[dep_id]:
                by_id[dep_id].append(tag)
            kinds[dep_id] = LOGICAL_DEPENDENCY_REGISTRY[dep_id].kind

    for raw in config.install.dependencies:
        canonical = canonicalize_dependency_id(raw)
        if canonical is None:
            unsupported.append(
                DependencyRequirement(
                    dependency_id=str(raw),
                    kind=DependencyKind.BINARY,
                    required_by=("manifest",),
                    required=True,
                )
            )
            continue
        by_id.setdefault(canonical, [])
        if "manifest" not in by_id[canonical]:
            by_id[canonical].append("manifest")
        if canonical in LOGICAL_DEPENDENCY_REGISTRY:
            kinds[canonical] = LOGICAL_DEPENDENCY_REGISTRY[canonical].kind
        else:
            kinds[canonical] = DependencyKind.BINARY

    out: list[DependencyRequirement] = []
    for dep_id in sorted(by_id.keys()):
        entry = LOGICAL_DEPENDENCY_REGISTRY.get(dep_id)
        out.append(
            DependencyRequirement(
                dependency_id=dep_id,
                kind=kinds.get(dep_id, DependencyKind.BINARY if entry is None else entry.kind),
                required_by=tuple(by_id[dep_id]),
                required=True,
            )
        )
    # Preserve unsupported as requirements with unknown ids for planner blockers.
    out.extend(unsupported)
    return tuple(out)


def _which_candidates(
    candidates: Sequence[str],
    *,
    extra_path_dirs: Sequence[str] | None = None,
) -> str | None:
    search_path = os.environ.get("PATH", "")
    if extra_path_dirs:
        search_path = os.pathsep.join([*extra_path_dirs, search_path])
    for name in candidates:
        found = shutil.which(name, path=search_path)
        if found:
            return found
    return None


def _probe_version(
    binary: str,
    argv_suffix: Sequence[str] | None,
    runner: CommandRunner,
) -> str | None:
    if not argv_suffix:
        return None
    try:
        completed = runner.run([binary, *argv_suffix], timeout=15.0)
    except Exception:  # noqa: BLE001
        return None
    text = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if not text:
        return None
    return text.splitlines()[0][:200]


def probe_python_venv(runner: CommandRunner, *, python_binary: str | None = None) -> tuple[bool, str | None]:
    """Create a bounded temp venv to verify venv capability works."""
    py = python_binary or _which_candidates(("python3", "python", "py"))
    if not py:
        return False, "python interpreter missing"
    tmp: str | None = None
    try:
        tmp = tempfile.mkdtemp(prefix="leviathan-venv-probe-")
        target = str(Path(tmp) / "probe-venv")
        completed = runner.run([py, "-m", "venv", target], timeout=90.0)
        if completed.returncode != 0:
            detail = ((completed.stderr or "") + (completed.stdout or "")).strip()[:240]
            return False, detail or "venv creation failed"
        # Confirm interpreter exists inside venv.
        if os.name == "nt":
            vpy = Path(target) / "Scripts" / "python.exe"
        else:
            vpy = Path(target) / "bin" / "python"
        if not vpy.exists():
            return False, "venv interpreter missing after creation"
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:240]
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def observe_dependency(
    requirement: DependencyRequirement,
    *,
    package_manager: str | None,
    privilege_state: PrivilegeState,
    runner: CommandRunner | None = None,
    extra_path_dirs: Sequence[str] | None = None,
    skip_venv_probe: bool = False,
) -> DependencyObservation:
    runner = runner or SubprocessCommandRunner()
    dep_id = requirement.dependency_id
    entry = LOGICAL_DEPENDENCY_REGISTRY.get(dep_id)

    if entry is None:
        return DependencyObservation(
            dependency_id=dep_id,
            state=DependencyState.MISSING_UNSUPPORTED,
            detail="unknown logical dependency; never passed to package manager",
        )

    packages: tuple[str, ...] = ()
    if package_manager:
        for cand in entry.package_candidates:
            if cand.manager_id == package_manager:
                packages = cand.packages
                break

    if entry.capability_probe == "python_venv":
        if skip_venv_probe:
            return DependencyObservation(
                dependency_id=dep_id,
                state=DependencyState.UNMEASURED,
                package_manager=package_manager,
                install_packages=packages,
                detail="venv probe skipped",
            )
        py = _which_candidates(("python3", "python", "py"), extra_path_dirs=extra_path_dirs)
        ok, detail = probe_python_venv(runner, python_binary=py)
        if ok:
            return DependencyObservation(
                dependency_id=dep_id,
                state=DependencyState.SATISFIED,
                resolved_binary=py,
                package_manager=package_manager,
                install_packages=packages,
                detail="venv capability verified",
            )
        if packages and package_manager:
            state = DependencyState.MISSING_INSTALLABLE
            if privilege_state in {PrivilegeState.PRIVILEGE_REQUIRED, PrivilegeState.UNSUPPORTED}:
                state = DependencyState.BLOCKED_PRIVILEGE
            return DependencyObservation(
                dependency_id=dep_id,
                state=state,
                resolved_binary=py,
                package_manager=package_manager,
                install_packages=packages,
                detail=detail or "python venv capability missing",
            )
        return DependencyObservation(
            dependency_id=dep_id,
            state=DependencyState.MISSING_UNSUPPORTED,
            resolved_binary=py,
            package_manager=package_manager,
            install_packages=(),
            detail=detail or "python venv missing and no supported package mapping",
        )

    binary = _which_candidates(entry.binary_candidates, extra_path_dirs=extra_path_dirs)
    # Node toolchain may live in nvm dirs.
    if binary is None and dep_id in {"node", "npm", "pnpm"}:
        try:
            from .install import _resolve_node_tool

            binary = _resolve_node_tool(dep_id)
        except Exception:  # noqa: BLE001
            binary = None

    if binary:
        version = _probe_version(binary, entry.version_probe_argv, runner)
        return DependencyObservation(
            dependency_id=dep_id,
            state=DependencyState.SATISFIED,
            resolved_binary=binary,
            observed_version=version,
            package_manager=package_manager,
            install_packages=packages,
        )

    if packages and package_manager:
        state = DependencyState.MISSING_INSTALLABLE
        if privilege_state in {PrivilegeState.PRIVILEGE_REQUIRED, PrivilegeState.UNSUPPORTED}:
            state = DependencyState.BLOCKED_PRIVILEGE
        return DependencyObservation(
            dependency_id=dep_id,
            state=state,
            package_manager=package_manager,
            install_packages=packages,
            detail=f"{dep_id} missing; installable via {package_manager}",
        )

    return DependencyObservation(
        dependency_id=dep_id,
        state=DependencyState.MISSING_UNSUPPORTED,
        package_manager=package_manager,
        detail=f"{dep_id} missing; no trusted package mapping for manager={package_manager!r}",
    )


def _application_actions(config: ExternalConfig, *, requested_ref: str) -> tuple[dict[str, Any], ...]:
    actions: list[dict[str, Any]] = []
    for strategy in config.install.strategies:
        if strategy == InstallStrategy.GIT_CHECKOUT:
            actions.append(
                {
                    "action": "git_checkout",
                    "source": config.source.source,
                    "ref": requested_ref,
                }
            )
        elif strategy == InstallStrategy.PYTHON_VENV:
            actions.append({"action": "create_venv", "requirements_file": config.install.requirements_file})
        elif strategy == InstallStrategy.PIP_PACKAGE:
            actions.append({"action": "pip_install", "packages": list(config.install.python_packages)})
        elif strategy == InstallStrategy.NODE_NPM:
            actions.append({"action": "npm_install"})
        elif strategy == InstallStrategy.NODE_PNPM:
            actions.append({"action": "pnpm_install"})
        elif strategy == InstallStrategy.NODE_SCRIPT:
            actions.append({"action": "node_script"})
        elif strategy == InstallStrategy.BINARY:
            actions.append({"action": "binary"})
    for cmd in config.install.post_install:
        actions.append({"action": "post_install", "argv": list(cmd)})
    return tuple(actions)


def compute_plan_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_install_plan(
    *,
    module_id: str,
    config: ExternalConfig,
    requested_ref: str | None = None,
    package_manager: str | None = None,
    privilege_state: PrivilegeState = PrivilegeState.PRIVILEGE_REQUIRED,
    runner: CommandRunner | None = None,
    extra_path_dirs: Sequence[str] | None = None,
    force: bool = False,
    observations_override: Sequence[DependencyObservation] | None = None,
) -> InstallPlan:
    """Read-only preflight: derive requirements, observe host, produce hashed plan."""
    ref = requested_ref or config.source.ref or "main"
    requirements = requirements_for_install(config)
    if observations_override is not None:
        observations = tuple(observations_override)
    else:
        observations = tuple(
            observe_dependency(
                req,
                package_manager=package_manager,
                privilege_state=privilege_state,
                runner=runner,
                extra_path_dirs=extra_path_dirs,
            )
            for req in requirements
        )

    missing: list[str] = []
    privileged: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    installable = True

    for obs in observations:
        if obs.state == DependencyState.SATISFIED:
            continue
        missing.append(obs.dependency_id)
        if obs.state == DependencyState.MISSING_INSTALLABLE:
            privileged.append(
                {
                    "dependency_id": obs.dependency_id,
                    "package_manager": obs.package_manager,
                    "packages": list(obs.install_packages),
                }
            )
        elif obs.state == DependencyState.BLOCKED_PRIVILEGE:
            installable = False
            blockers.append(
                {
                    "code": "PRIVILEGE_REQUIRED",
                    "dependency_id": obs.dependency_id,
                    "package_manager": obs.package_manager,
                    "packages": list(obs.install_packages),
                    "detail": obs.detail,
                }
            )
            # Still record intended mutation for UX honesty.
            if obs.install_packages:
                privileged.append(
                    {
                        "dependency_id": obs.dependency_id,
                        "package_manager": obs.package_manager,
                        "packages": list(obs.install_packages),
                        "blocked": True,
                    }
                )
        elif obs.state in {
            DependencyState.MISSING_UNSUPPORTED,
            DependencyState.VERSION_MISMATCH_UNSUPPORTED,
        }:
            installable = False
            blockers.append(
                {
                    "code": "DEPENDENCY_UNSUPPORTED",
                    "dependency_id": obs.dependency_id,
                    "detail": obs.detail,
                }
            )
        elif obs.state == DependencyState.UNMEASURED:
            blockers.append(
                {
                    "code": "UNMEASURED",
                    "dependency_id": obs.dependency_id,
                    "detail": obs.detail,
                }
            )

    if privileged and package_manager is None:
        installable = False
        blockers.append(
            {
                "code": "PACKAGE_MANAGER_UNAVAILABLE",
                "detail": "No supported host package manager detected",
            }
        )

    if privileged and privilege_state == PrivilegeState.PRIVILEGE_REQUIRED:
        installable = False
        if not any(b.get("code") == "PRIVILEGE_REQUIRED" for b in blockers):
            blockers.append(
                {
                    "code": "PRIVILEGE_REQUIRED",
                    "detail": "Non-interactive elevation is unavailable for system package installation",
                }
            )
    elif privileged and privilege_state == PrivilegeState.UNSUPPORTED:
        installable = False
        if not any(b.get("code") == "PACKAGE_MANAGER_UNAVAILABLE" for b in blockers):
            blockers.append(
                {
                    "code": "PACKAGE_MANAGER_UNAVAILABLE",
                    "detail": "No supported privilege path for package installation",
                }
            )

    # Approval is required whenever privileged host mutations are planned and the
    # plan is otherwise installable (or needs operator visibility of privilege block).
    requires_approval = bool(privileged)

    hard_block_codes = {
        "DEPENDENCY_UNSUPPORTED",
        "PACKAGE_MANAGER_UNAVAILABLE",
        "PRIVILEGE_REQUIRED",
    }
    if any(b.get("code") in hard_block_codes for b in blockers):
        installable = False

    # Satisfied host + no privileged work → installable without approval.
    if not privileged and not any(b.get("code") in hard_block_codes for b in blockers):
        installable = True
        requires_approval = False

    application_actions = _application_actions(config, requested_ref=ref)
    strategies = tuple(s.value for s in config.install.strategies)
    source = config.source.public_dict()

    hash_payload = {
        "module_id": module_id,
        "source": source,
        "requested_ref": ref,
        "strategies": list(strategies),
        "logical_dependencies": [r.dependency_id for r in requirements],
        "missing_dependencies": sorted(missing),
        "package_manager": package_manager,
        "privileged_packages": sorted(
            {
                pkg
                for m in privileged
                for pkg in (m.get("packages") or [])
            }
        ),
        "application_actions": list(application_actions),
        "force": bool(force),
    }
    plan_hash = compute_plan_hash(hash_payload)

    return InstallPlan(
        module_id=module_id,
        requested_ref=ref,
        strategies=strategies,
        requirements=requirements,
        observations=observations,
        missing_dependencies=tuple(missing),
        privileged_mutations=tuple(privileged),
        application_actions=application_actions,
        package_manager=package_manager,
        privilege_state=privilege_state.value,
        requires_approval=requires_approval,
        installable=installable,
        blockers=tuple(blockers),
        plan_hash=plan_hash,
        source=source,
    )


def privileged_packages_from_plan(plan: InstallPlan) -> tuple[str, ...]:
    """Deduplicated trusted package names from privileged mutations."""
    seen: list[str] = []
    for mutation in plan.privileged_mutations:
        for pkg in mutation.get("packages") or []:
            name = str(pkg)
            if name and name not in seen:
                seen.append(name)
    return tuple(seen)


def plan_allows_execution(
    approved_plan: InstallPlan,
    current_plan: InstallPlan,
) -> tuple[bool, str | None]:
    """True when current privileged set is a subset of the approved plan."""
    approved = set(privileged_packages_from_plan(approved_plan))
    current = set(privileged_packages_from_plan(current_plan))
    if current - approved:
        return False, "PLAN_STALE_REAPPROVAL_REQUIRED"
    approved_deps = set(approved_plan.privileged_dependency_ids())
    current_deps = set(current_plan.privileged_dependency_ids())
    if current_deps - approved_deps:
        return False, "PLAN_STALE_REAPPROVAL_REQUIRED"
    return True, None


PHASE_PROGRESS: dict[str, float] = {
    InstallPhase.PLANNING.value: 0.05,
    InstallPhase.APPROVAL_REQUIRED.value: 0.08,
    InstallPhase.QUEUED.value: 0.1,
    InstallPhase.PREPARING.value: 0.12,
    InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES.value: 0.25,
    InstallPhase.VERIFYING_SYSTEM_DEPENDENCIES.value: 0.35,
    InstallPhase.FETCHING_SOURCE.value: 0.5,
    InstallPhase.PREPARING_RUNTIME.value: 0.6,
    InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES.value: 0.75,
    InstallPhase.POST_INSTALL.value: 0.85,
    InstallPhase.VERIFYING_INSTALLATION.value: 0.92,
    InstallPhase.ACTIVATING.value: 0.96,
    InstallPhase.READY.value: 1.0,
    InstallPhase.FAILED.value: 1.0,
    InstallPhase.CANCELLED.value: 1.0,
    InstallPhase.CANCEL_PENDING.value: 0.5,
}


def progress_for_phase(phase: str | InstallPhase) -> float:
    key = phase.value if isinstance(phase, InstallPhase) else str(phase)
    return float(PHASE_PROGRESS.get(key, 0.0))
