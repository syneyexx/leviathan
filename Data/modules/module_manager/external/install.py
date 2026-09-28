"""Generic installation path for external capabilities.

Installations land under data_root/external_capabilities/<module-id>/versions/<ref>.
Installation itself is intended to run as a JobRuntime task (caller enqueues).

System package installation is privilege-scoped and approval-gated. Application
dependency installation (venv/pip/npm/post_install) always runs unprivileged
argv lists (shell=False) and never inherits elevation used for host packages.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..errors import bounded_process_output
from .dependencies import (
    CommandRunner,
    DependencyState,
    InstallPhase,
    InstallPlan,
    PrivilegeState,
    SubprocessCommandRunner,
    build_install_plan,
    canonicalize_dependency_id,
    observe_dependency,
    plan_allows_execution,
    privileged_packages_from_plan,
    progress_for_phase,
    requirements_for_install,
)
from .package_managers import (
    detect_package_manager,
    discover_privilege_state,
    elevate_argv,
    fingerprint_argv,
    windows_extra_search_dirs,
)
from .types import ExternalConfig, ExternalFailureCode, InstallStrategy


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class InstallError(RuntimeError):
    def __init__(
        self,
        code: ExternalFailureCode,
        message: str,
        *,
        phase: str | InstallPhase | None = None,
        dependency: str | None = None,
        package_manager: str | None = None,
        retryable: bool | None = None,
        recovery: str | None = None,
    ) -> None:
        code_value = code.value if hasattr(code, "value") else str(code)
        super().__init__(f"{code_value}: {message}")
        self.code = code
        self.message = message
        if isinstance(phase, InstallPhase):
            self.phase = phase.value
        else:
            self.phase = phase
        self.dependency = dependency
        self.package_manager = package_manager
        self.retryable = retryable
        self.recovery = recovery


@dataclass
class InstallResult:
    version_id: str
    module_id: str
    install_root: str
    source_ref: str | None
    resolved_commit: str | None
    content_hash: str | None
    strategies: list[str]
    dependency_versions: dict[str, Any]
    installed_at: str
    status: str = "INSTALLED"
    plan_hash: str | None = None
    operation_id: str | None = None
    system_dependencies_retained: bool = False

    def public_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "version_id": self.version_id,
            "module_id": self.module_id,
            "install_root": self.install_root,
            "source_ref": self.source_ref,
            "resolved_commit": self.resolved_commit,
            "content_hash": self.content_hash,
            "strategies": list(self.strategies),
            "dependency_versions": dict(self.dependency_versions),
            "installed_at": self.installed_at,
            "status": self.status,
        }
        if self.plan_hash is not None:
            body["plan_hash"] = self.plan_hash
        if self.operation_id is not None:
            body["operation_id"] = self.operation_id
        if self.system_dependencies_retained:
            body["system_dependencies_retained"] = True
            body["recovery"] = "SYSTEM_DEPENDENCIES_RETAINED"
        return body


ProgressCb = Callable[[float, str, str], None]


@dataclass
class _InstallContext:
    module_id: str
    config: ExternalConfig
    ref_key: str
    operation_id: str
    force: bool
    auto_resolve_dependencies: bool
    approved_plan: InstallPlan | None
    allow_system_deps: bool
    expected_plan_hash: str | None
    runner: CommandRunner | None
    store: Any | None
    progress: ProgressCb | None
    cancel_check: Callable[[], bool] | None
    system_deps_installed: bool = False
    cancel_pending: bool = False
    plan: InstallPlan | None = None
    privilege_state: PrivilegeState = PrivilegeState.UNSUPPORTED
    package_manager_id: str | None = None
    dep_provenance: dict[str, Any] = field(default_factory=dict)


class InstallationService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)
        self.base = self.data_root / "external_capabilities"

    def install_root_for(self, module_id: str, ref_key: str) -> Path:
        safe_mod = "".join(c if c.isalnum() or c in "._-" else "_" for c in module_id)
        safe_ref = "".join(c if c.isalnum() or c in "._-" else "_" for c in ref_key)[:80] or "default"
        return self.base / safe_mod / "versions" / safe_ref

    def module_base_for(self, module_id: str) -> Path:
        safe_mod = "".join(c if c.isalnum() or c in "._-" else "_" for c in module_id)
        return self.base / safe_mod

    def staging_root_for(self, module_id: str, operation_id: str) -> Path:
        safe_op = "".join(c if c.isalnum() or c in "._-" else "_" for c in operation_id)[:80] or "op"
        return self.module_base_for(module_id) / "staging" / safe_op

    def plan_install(
        self,
        module_id: str,
        config: ExternalConfig,
        *,
        ref: str | None = None,
        force: bool = False,
        runner: CommandRunner | None = None,
    ) -> InstallPlan:
        """Read-only preflight: detect package manager, privilege, and build InstallPlan."""
        cmd_runner = runner or SubprocessCommandRunner()
        manager = detect_package_manager(runner=cmd_runner)
        privilege = discover_privilege_state(manager=manager, runner=cmd_runner)
        return build_install_plan(
            module_id=module_id,
            config=config,
            requested_ref=ref or config.source.ref or "main",
            package_manager=manager.manager_id if manager else None,
            privilege_state=privilege,
            runner=cmd_runner,
            extra_path_dirs=windows_extra_search_dirs(),
            force=force,
        )

    def ensure_installed(
        self,
        *,
        module_id: str,
        config: ExternalConfig,
        progress: ProgressCb | None = None,
        cancel_check: Callable[[], bool] | None = None,
        ref: str | None = None,
        force: bool = False,
        activate: bool = False,  # noqa: ARG002 — activation owned by caller/adapters
        plan_hash: str | None = None,
        operation_id: str | None = None,
        auto_resolve_dependencies: bool = True,
        approved_plan: InstallPlan | None = None,
        allow_system_deps: bool = False,
        runner: CommandRunner | None = None,
        store: Any | None = None,
    ) -> InstallResult:
        """Plan and execute installation. ``force`` rebuilds/re-fetches; never skips approval/deps/health."""
        ctx = _InstallContext(
            module_id=module_id,
            config=config,
            ref_key=ref or config.source.ref or "main",
            operation_id=operation_id or uuid.uuid4().hex,
            force=bool(force),
            auto_resolve_dependencies=bool(auto_resolve_dependencies),
            approved_plan=approved_plan,
            allow_system_deps=bool(allow_system_deps),
            expected_plan_hash=plan_hash,
            runner=runner,
            store=store,
            progress=progress,
            cancel_check=cancel_check,
        )
        self._raise_if_cancelled(ctx, phase=InstallPhase.PLANNING)

        # Local path source without checkout — preserve prior early-return contract.
        if config.source.source_type == "path" and config.source.path:
            return self._install_path_source(ctx)

        if config.source.source_type == "none" or (
            InstallStrategy.NONE in config.install.strategies
            and len(config.install.strategies) == 1
            and not config.source.source
        ):
            return self._install_none_source(ctx)

        plan = self.plan_install(
            module_id,
            config,
            ref=ctx.ref_key,
            force=ctx.force,
            runner=ctx.runner,
        )
        return self.execute_install_plan(
            module_id=module_id,
            config=config,
            plan=plan,
            progress=progress,
            cancel_check=cancel_check,
            force=force,
            activate=activate,
            plan_hash=plan_hash,
            operation_id=ctx.operation_id,
            auto_resolve_dependencies=auto_resolve_dependencies,
            approved_plan=approved_plan,
            allow_system_deps=allow_system_deps,
            runner=runner,
            store=store,
        )

    def execute_install_plan(
        self,
        *,
        module_id: str,
        config: ExternalConfig,
        plan: InstallPlan,
        progress: ProgressCb | None = None,
        cancel_check: Callable[[], bool] | None = None,
        force: bool = False,
        activate: bool = False,  # noqa: ARG002
        plan_hash: str | None = None,
        operation_id: str | None = None,
        auto_resolve_dependencies: bool = True,
        approved_plan: InstallPlan | None = None,
        allow_system_deps: bool = False,
        runner: CommandRunner | None = None,
        store: Any | None = None,
    ) -> InstallResult:
        ctx = _InstallContext(
            module_id=module_id,
            config=config,
            ref_key=plan.requested_ref or config.source.ref or "main",
            operation_id=operation_id or uuid.uuid4().hex,
            force=bool(force),
            auto_resolve_dependencies=bool(auto_resolve_dependencies),
            approved_plan=approved_plan,
            allow_system_deps=bool(allow_system_deps),
            expected_plan_hash=plan_hash,
            runner=runner,
            store=store,
            progress=progress,
            cancel_check=cancel_check,
            plan=plan,
            privilege_state=PrivilegeState(plan.privilege_state)
            if plan.privilege_state in PrivilegeState._value2member_map_
            else PrivilegeState.UNSUPPORTED,
            package_manager_id=plan.package_manager,
        )
        return self._execute(ctx)

    # ------------------------------------------------------------------
    # Execution pipeline
    # ------------------------------------------------------------------

    def _execute(self, ctx: _InstallContext) -> InstallResult:
        previous_runner = getattr(self, "_active_runner", None)
        self._active_runner = ctx.runner
        try:
            return self._execute_inner(ctx)
        finally:
            self._active_runner = previous_runner

    def _execute_inner(self, ctx: _InstallContext) -> InstallResult:
        self._emit(ctx, InstallPhase.PLANNING, "building install plan")
        plan = ctx.plan or self.plan_install(
            ctx.module_id,
            ctx.config,
            ref=ctx.ref_key,
            force=ctx.force,
            runner=ctx.runner,
        )
        ctx.plan = plan
        ctx.ref_key = plan.requested_ref or ctx.ref_key
        ctx.package_manager_id = plan.package_manager
        try:
            ctx.privilege_state = PrivilegeState(plan.privilege_state)
        except ValueError:
            ctx.privilege_state = PrivilegeState.UNSUPPORTED

        if ctx.expected_plan_hash and ctx.expected_plan_hash != plan.plan_hash:
            raise InstallError(
                ExternalFailureCode.PLAN_STALE_REAPPROVAL_REQUIRED,
                "provided plan_hash does not match current install plan",
                phase=InstallPhase.PLANNING,
                retryable=True,
                recovery="replan_and_reapprove",
            )

        self._persist_operation(ctx, phase=InstallPhase.PLANNING.value, status="RUNNING")
        self._raise_if_cancelled(ctx, phase=InstallPhase.PLANNING)

        dest = self.install_root_for(ctx.module_id, ctx.ref_key)
        if not ctx.force and dest.exists() and any(dest.iterdir()):
            # Reuse existing tree only when host deps are already satisfied.
            missing_now = [
                o.dependency_id
                for o in plan.observations
                if o.state != DependencyState.SATISFIED
            ]
            if not missing_now and not plan.privileged_mutations:
                return self._result_from_existing(ctx, dest, plan)

        try:
            self._resolve_system_dependencies(ctx)
            self._raise_if_cancelled(ctx, phase=InstallPhase.VERIFYING_SYSTEM_DEPENDENCIES)

            staging = self.staging_root_for(ctx.module_id, ctx.operation_id)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)

            applied: list[str] = []
            dep_versions: dict[str, Any] = dict(ctx.dep_provenance)
            resolved_commit: str | None = None

            for strategy in ctx.config.install.strategies:
                self._raise_if_cancelled(ctx, phase=InstallPhase.FETCHING_SOURCE)
                if strategy == InstallStrategy.NONE:
                    applied.append(strategy.value)
                    continue
                if strategy == InstallStrategy.GIT_CHECKOUT:
                    self._emit(ctx, InstallPhase.FETCHING_SOURCE, f"checkout {ctx.config.source.source}@{ctx.ref_key}")
                    # Positional-only call keeps monkeypatches that replace _git_checkout compatible.
                    resolved_commit = self._git_checkout(
                        ctx.config.source.source,
                        ctx.ref_key,
                        staging,
                    )
                    applied.append(strategy.value)
                    self._emit(ctx, InstallPhase.FETCHING_SOURCE, f"resolved {resolved_commit}")
                elif strategy == InstallStrategy.PYTHON_VENV:
                    self._emit(ctx, InstallPhase.PREPARING_RUNTIME, "create/update python venv")
                    venv_info = self._python_venv(staging, ctx.config)
                    dep_versions.update(venv_info)
                    applied.append(strategy.value)
                elif strategy == InstallStrategy.PIP_PACKAGE:
                    self._emit(ctx, InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES, "pip install packages")
                    pip_info = self._pip_packages(staging, ctx.config)
                    dep_versions.update(pip_info)
                    applied.append(strategy.value)
                elif strategy == InstallStrategy.NODE_NPM:
                    self._emit(ctx, InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES, "npm install")
                    npm_info = self._node_install(staging, ctx.config, tool="npm")
                    dep_versions.update(npm_info)
                    applied.append(strategy.value)
                elif strategy == InstallStrategy.NODE_PNPM:
                    self._emit(ctx, InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES, "pnpm install")
                    npm_info = self._node_install(staging, ctx.config, tool="pnpm")
                    dep_versions.update(npm_info)
                    applied.append(strategy.value)
                elif strategy == InstallStrategy.NODE_SCRIPT:
                    applied.append(strategy.value)
                elif strategy == InstallStrategy.BINARY:
                    applied.append(strategy.value)
                else:
                    raise InstallError(
                        ExternalFailureCode.INSTALL_FAILED,
                        f"unsupported strategy {strategy}",
                        phase=InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES,
                    )

            self._run_post_install(ctx, staging)
            self._verify_installation(ctx, staging, applied, dep_versions)

            final_root = self._promote_staging(staging, dest)
            content_hash = _dir_fingerprint(final_root) if final_root.exists() else None
            version_id = (
                f"{ctx.module_id}:{resolved_commit or ctx.ref_key}:"
                f"{(content_hash or uuid.uuid4().hex)[:12]}"
            )
            dep_versions = self._enrich_dependency_versions(ctx, plan, dep_versions)
            self._emit(ctx, InstallPhase.READY, str(final_root))
            result = InstallResult(
                version_id=version_id,
                module_id=ctx.module_id,
                install_root=str(final_root),
                source_ref=ctx.config.source.ref or ctx.ref_key,
                resolved_commit=resolved_commit,
                content_hash=content_hash,
                strategies=applied,
                dependency_versions=dep_versions,
                installed_at=utc_now(),
                plan_hash=plan.plan_hash,
                operation_id=ctx.operation_id,
                system_dependencies_retained=ctx.system_deps_installed,
            )
            self._persist_operation(ctx, phase=InstallPhase.READY.value, status="INSTALLED", result=result)
            return result
        except InstallError as exc:
            self._cleanup_failure(ctx, exc)
            if ctx.system_deps_installed and exc.recovery is None:
                exc.recovery = "SYSTEM_DEPENDENCIES_RETAINED"
            raise
        except Exception as exc:  # noqa: BLE001
            wrapped = InstallError(
                ExternalFailureCode.INSTALL_FAILED,
                str(exc)[:400],
                phase=InstallPhase.FAILED,
                recovery="SYSTEM_DEPENDENCIES_RETAINED" if ctx.system_deps_installed else None,
            )
            self._cleanup_failure(ctx, wrapped)
            raise wrapped from exc

    def _resolve_system_dependencies(self, ctx: _InstallContext) -> None:
        plan = ctx.plan
        assert plan is not None

        installable_missing = [
            o
            for o in plan.observations
            if o.state
            in {
                DependencyState.MISSING_INSTALLABLE,
                DependencyState.VERSION_MISMATCH_INSTALLABLE,
            }
        ]
        blocked = [o for o in plan.observations if o.state == DependencyState.BLOCKED_PRIVILEGE]
        unsupported = [
            o
            for o in plan.observations
            if o.state
            in {
                DependencyState.MISSING_UNSUPPORTED,
                DependencyState.VERSION_MISMATCH_UNSUPPORTED,
            }
        ]

        if unsupported:
            # Unknown manifest binaries keep the legacy DEPENDENCY_MISSING contract;
            # known logical deps without a trusted package mapping use UNSUPPORTED.
            from .dependencies import LOGICAL_DEPENDENCY_REGISTRY

            known_unsupported = [
                o for o in unsupported if o.dependency_id in LOGICAL_DEPENDENCY_REGISTRY
            ]
            unknown = [o for o in unsupported if o.dependency_id not in LOGICAL_DEPENDENCY_REGISTRY]
            if known_unsupported:
                raise InstallError(
                    ExternalFailureCode.DEPENDENCY_UNSUPPORTED,
                    f"unsupported dependencies: {', '.join(o.dependency_id for o in known_unsupported)}",
                    phase=InstallPhase.PLANNING,
                    dependency=known_unsupported[0].dependency_id,
                    retryable=False,
                )
            if unknown:
                raise InstallError(
                    ExternalFailureCode.DEPENDENCY_MISSING,
                    f"missing dependencies: {', '.join(o.dependency_id for o in unknown)}",
                    phase=InstallPhase.PLANNING,
                    dependency=unknown[0].dependency_id,
                    retryable=False,
                )

        if blocked and not ctx.auto_resolve_dependencies:
            raise InstallError(
                ExternalFailureCode.PRIVILEGE_REQUIRED,
                f"missing dependencies require privilege: {', '.join(o.dependency_id for o in blocked)}",
                phase=InstallPhase.APPROVAL_REQUIRED,
                dependency=blocked[0].dependency_id,
                package_manager=plan.package_manager,
                retryable=True,
                recovery="elevate_or_install_manually",
            )

        if not installable_missing and not blocked:
            # Legacy pure detection gate for any remaining missing names.
            missing = _missing_binaries(ctx.config.install.dependencies)
            if missing and not plan.missing_dependencies:
                raise InstallError(
                    ExternalFailureCode.DEPENDENCY_MISSING,
                    f"missing dependencies: {', '.join(missing)}",
                    phase=InstallPhase.PLANNING,
                    dependency=missing[0],
                )
            return

        if not ctx.auto_resolve_dependencies:
            ids = [o.dependency_id for o in installable_missing or blocked]
            raise InstallError(
                ExternalFailureCode.DEPENDENCY_MISSING,
                f"missing dependencies: {', '.join(ids)}",
                phase=InstallPhase.PLANNING,
                dependency=ids[0] if ids else None,
                package_manager=plan.package_manager,
            )

        if not plan.installable and blocked:
            raise InstallError(
                ExternalFailureCode.PRIVILEGE_REQUIRED,
                "non-interactive elevation unavailable for system package installation",
                phase=InstallPhase.APPROVAL_REQUIRED,
                package_manager=plan.package_manager,
                retryable=True,
                recovery="configure_passwordless_sudo_or_run_as_root",
            )

        if plan.requires_approval or plan.privileged_mutations:
            self._assert_system_dep_approval(ctx, plan)

        if not plan.package_manager:
            raise InstallError(
                ExternalFailureCode.PACKAGE_MANAGER_UNAVAILABLE,
                "no supported host package manager detected",
                phase=InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES,
            )

        packages = privileged_packages_from_plan(plan)
        if not packages:
            return

        self._install_system_packages(ctx, packages)
        self._verify_system_dependencies(ctx)

    def _assert_system_dep_approval(self, ctx: _InstallContext, plan: InstallPlan) -> None:
        if ctx.allow_system_deps:
            return
        if ctx.approved_plan is None:
            raise InstallError(
                ExternalFailureCode.APPROVAL_REQUIRED,
                "system dependency installation requires an approved plan",
                phase=InstallPhase.APPROVAL_REQUIRED,
                package_manager=plan.package_manager,
                retryable=True,
                recovery="approve_install_plan",
            )
        ok, reason = plan_allows_execution(ctx.approved_plan, plan)
        if not ok:
            raise InstallError(
                ExternalFailureCode.PLAN_STALE_REAPPROVAL_REQUIRED,
                reason or "approved plan no longer covers required packages",
                phase=InstallPhase.APPROVAL_REQUIRED,
                package_manager=plan.package_manager,
                retryable=True,
                recovery="replan_and_reapprove",
            )

    def _install_system_packages(self, ctx: _InstallContext, packages: Sequence[str]) -> None:
        self._emit(
            ctx,
            InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES,
            f"installing {', '.join(packages)} via {ctx.package_manager_id}",
        )
        runner = ctx.runner or SubprocessCommandRunner()
        manager = detect_package_manager(runner=runner)
        if manager is None or (ctx.package_manager_id and manager.manager_id != ctx.package_manager_id):
            # Prefer the planned manager id when available.
            from .package_managers import build_manager_map

            managers = build_manager_map(runner)
            manager = managers.get(ctx.package_manager_id or "") if ctx.package_manager_id else manager
        if manager is None:
            raise InstallError(
                ExternalFailureCode.PACKAGE_MANAGER_UNAVAILABLE,
                "package manager disappeared before install",
                phase=InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES,
                package_manager=ctx.package_manager_id,
            )

        privilege = discover_privilege_state(manager=manager, runner=runner)
        ctx.privilege_state = privilege
        if privilege in {PrivilegeState.PRIVILEGE_REQUIRED, PrivilegeState.UNSUPPORTED}:
            raise InstallError(
                ExternalFailureCode.PRIVILEGE_REQUIRED,
                "cannot install system packages without non-interactive privilege",
                phase=InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES,
                package_manager=manager.manager_id,
                retryable=True,
            )

        argv_batches: list[list[str]] = []
        try:
            argv_batches.extend(manager.build_refresh_argv())
        except Exception as exc:  # noqa: BLE001
            raise InstallError(
                ExternalFailureCode.PACKAGE_METADATA_REFRESH_FAILED,
                f"failed to build refresh argv: {exc}",
                phase=InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES,
                package_manager=manager.manager_id,
                retryable=True,
            ) from exc
        argv_batches.extend(manager.build_install_argv(list(packages)))

        installed_packages: list[str] = []
        command_log: list[dict[str, Any]] = []
        ran_any_pm_command = False
        for argv in argv_batches:
            if ctx.cancel_pending or (ctx.cancel_check and ctx.cancel_check()):
                # Do not interrupt the in-flight package-manager command; mark pending
                # and stop before starting the next argv batch / phase.
                ctx.cancel_pending = True
                self._emit(ctx, InstallPhase.CANCEL_PENDING, "cancel pending after package-manager command")
                break
            elevated = elevate_argv(argv, privilege)
            self._emit(
                ctx,
                InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES,
                f"pm: {' '.join(elevated[:6])}{'…' if len(elevated) > 6 else ''}",
            )
            try:
                completed = self._run(
                    elevated,
                    timeout=1800.0,
                    runner=runner,
                )
            except subprocess.TimeoutExpired as exc:
                raise InstallError(
                    ExternalFailureCode.PACKAGE_INSTALL_FAILED,
                    f"package manager timed out: {bounded_process_output(None, str(exc))}",
                    phase=InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES,
                    package_manager=manager.manager_id,
                    retryable=True,
                ) from exc
            ran_any_pm_command = True
            command_log.append(
                {
                    "argv_fingerprint": fingerprint_argv(elevated),
                    "returncode": completed.returncode,
                    "privileged": elevated != list(argv),
                }
            )
            if completed.returncode != 0:
                detail = bounded_process_output(completed.stderr, completed.stdout)
                is_refresh = any(tok in {"update", "makecache", "refresh", "-Sy"} for tok in argv)
                code = (
                    ExternalFailureCode.PACKAGE_METADATA_REFRESH_FAILED
                    if is_refresh
                    else ExternalFailureCode.PACKAGE_INSTALL_FAILED
                )
                raise InstallError(
                    code,
                    f"package manager failed ({completed.returncode}): {detail}",
                    phase=InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES,
                    package_manager=manager.manager_id,
                    retryable=True,
                )
            installed_packages = list(packages)

        if ran_any_pm_command:
            ctx.system_deps_installed = True
            ctx.dep_provenance["system_packages"] = {
                "package_manager": manager.manager_id,
                "packages": list(packages),
                "privilege_state": privilege.value,
                "commands": command_log,
                "installed_packages": installed_packages,
            }
            self._persist_operation(
                ctx,
                phase=InstallPhase.INSTALLING_SYSTEM_DEPENDENCIES.value,
                status="RUNNING",
                extra={"system_packages": list(packages)},
            )

        if ctx.cancel_pending:
            raise InstallError(
                ExternalFailureCode.CANCELLED,
                "install cancelled after package-manager command"
                if ran_any_pm_command
                else "install cancelled",
                phase=InstallPhase.CANCELLED,
                package_manager=manager.manager_id,
                recovery="SYSTEM_DEPENDENCIES_RETAINED" if ran_any_pm_command else None,
            )

    def _verify_system_dependencies(self, ctx: _InstallContext) -> None:
        """Re-probe logical deps — never trust package-manager exit codes alone."""
        assert ctx.plan is not None
        self._emit(ctx, InstallPhase.VERIFYING_SYSTEM_DEPENDENCIES, "re-probing host dependencies")
        runner = ctx.runner or SubprocessCommandRunner()
        requirements = requirements_for_install(ctx.config)
        observations = tuple(
            observe_dependency(
                req,
                package_manager=ctx.package_manager_id,
                privilege_state=ctx.privilege_state,
                runner=runner,
                extra_path_dirs=windows_extra_search_dirs(),
            )
            for req in requirements
        )
        still_missing = [
            o
            for o in observations
            if o.state
            not in {
                DependencyState.SATISFIED,
                DependencyState.UNMEASURED,
            }
        ]
        ctx.dep_provenance["system_dependency_verification"] = {
            "observations": [o.public_dict() for o in observations],
            "verified_at": utc_now(),
        }
        # Refresh plan observations for provenance without changing plan_hash mid-flight.
        if still_missing:
            first = still_missing[0]
            raise InstallError(
                ExternalFailureCode.DEPENDENCY_VERIFY_FAILED,
                f"dependency still missing after package install: {first.dependency_id}",
                phase=InstallPhase.VERIFYING_SYSTEM_DEPENDENCIES,
                dependency=first.dependency_id,
                package_manager=ctx.package_manager_id,
                retryable=True,
                recovery="SYSTEM_DEPENDENCIES_RETAINED",
            )

    def _run_post_install(self, ctx: _InstallContext, root: Path) -> None:
        if not ctx.config.install.post_install:
            return
        self._emit(ctx, InstallPhase.POST_INSTALL, "running post_install hooks")
        from Data.modules.common.process_control import scrub_child_environment
        post_env = scrub_child_environment()
        node_dir = _preferred_node_bin_dir()
        if node_dir:
            post_env["PATH"] = f"{node_dir}{os.pathsep}{post_env.get('PATH', '')}"
        for cmd in ctx.config.install.post_install:
            self._raise_if_cancelled(ctx, phase=InstallPhase.POST_INSTALL)
            self._emit(ctx, InstallPhase.POST_INSTALL, " ".join(cmd))
            argv = list(cmd)
            if argv and argv[0] in {"npm", "pnpm", "node"}:
                resolved = _resolve_node_tool(argv[0])
                if resolved:
                    argv[0] = resolved
            # Never elevate post_install — always unprivileged argv, shell=False.
            completed = self._run(
                argv,
                timeout=600.0,
                cwd=str(root),
                env=post_env,
                runner=ctx.runner,
            )
            if completed.returncode != 0:
                detail = bounded_process_output(completed.stderr, completed.stdout)
                raise InstallError(
                    ExternalFailureCode.INSTALL_FAILED,
                    f"post_install failed ({completed.returncode}): {detail}",
                    phase=InstallPhase.POST_INSTALL,
                    recovery="SYSTEM_DEPENDENCIES_RETAINED" if ctx.system_deps_installed else None,
                )

    def _verify_installation(
        self,
        ctx: _InstallContext,
        root: Path,
        applied: Sequence[str],
        dep_versions: dict[str, Any],
    ) -> None:
        self._emit(ctx, InstallPhase.VERIFYING_INSTALLATION, "verifying installation")
        if any(s in applied for s in (InstallStrategy.PYTHON_VENV.value, InstallStrategy.PIP_PACKAGE.value)):
            pip = root / ".venv" / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
            if pip.exists():
                completed = self._run(
                    [str(pip), "check"],
                    timeout=120.0,
                    cwd=str(root),
                    runner=ctx.runner,
                )
                dep_versions["pip_check"] = {
                    "returncode": completed.returncode,
                    "detail": bounded_process_output(completed.stderr, completed.stdout)[:240],
                }
                if completed.returncode != 0:
                    raise InstallError(
                        ExternalFailureCode.VERIFY_FAILED,
                        f"pip check failed: {bounded_process_output(completed.stderr, completed.stdout)}",
                        phase=InstallPhase.VERIFYING_INSTALLATION,
                        retryable=True,
                        recovery="SYSTEM_DEPENDENCIES_RETAINED" if ctx.system_deps_installed else None,
                    )
        if InstallStrategy.NODE_NPM.value in applied or InstallStrategy.NODE_PNPM.value in applied:
            tool = "pnpm" if InstallStrategy.NODE_PNPM.value in applied else "npm"
            tool_path = _resolve_node_tool(tool)
            if tool_path and (root / (ctx.config.install.package_json or "package.json")).exists():
                from Data.modules.common.process_control import scrub_child_environment
                env = scrub_child_environment()
                node_dir = _preferred_node_bin_dir()
                if node_dir:
                    env["PATH"] = f"{node_dir}{os.pathsep}{env.get('PATH', '')}"
                completed = self._run(
                    [tool_path, "ls", "--depth", "0"],
                    timeout=180.0,
                    cwd=str(root),
                    env=env,
                    runner=ctx.runner,
                )
                dep_versions[f"{tool}_ls"] = {
                    "returncode": completed.returncode,
                    "detail": bounded_process_output(completed.stderr, completed.stdout)[:240],
                }
                if completed.returncode != 0:
                    raise InstallError(
                        ExternalFailureCode.VERIFY_FAILED,
                        f"{tool} ls failed: {bounded_process_output(completed.stderr, completed.stdout)}",
                        phase=InstallPhase.VERIFYING_INSTALLATION,
                        retryable=True,
                        recovery="SYSTEM_DEPENDENCIES_RETAINED" if ctx.system_deps_installed else None,
                    )

    def _promote_staging(self, staging: Path, dest: Path) -> Path:
        """Atomically replace versions/<ref> with the staging tree (same filesystem rename)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        if dest.exists():
            backup = dest.with_name(f"{dest.name}.bak-{uuid.uuid4().hex[:8]}")
            dest.rename(backup)
        try:
            staging.rename(dest)
        except OSError:
            # Cross-device fallback: copy then remove staging.
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(staging, dest)
            shutil.rmtree(staging, ignore_errors=True)
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        # Best-effort: remove empty staging parent leftovers.
        staging_parent = staging.parent
        if staging_parent.exists() and staging_parent.name == "staging":
            try:
                next(staging_parent.iterdir())
            except StopIteration:
                shutil.rmtree(staging_parent, ignore_errors=True)
            except OSError:
                pass
        return dest

    def _cleanup_failure(self, ctx: _InstallContext, exc: InstallError) -> None:
        staging = self.staging_root_for(ctx.module_id, ctx.operation_id)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        # Previous active/version tree is never deleted on failure.
        phase = exc.phase or InstallPhase.FAILED.value
        status = "CANCELLED" if exc.code == ExternalFailureCode.CANCELLED else "FAILED"
        self._persist_operation(
            ctx,
            phase=phase,
            status=status,
            extra={
                "error": exc.message,
                "code": getattr(exc.code, "value", str(exc.code)),
                "system_dependencies_retained": ctx.system_deps_installed,
            },
        )
        if ctx.store is not None and hasattr(ctx.store, "set_runtime_state"):
            try:
                ctx.store.set_runtime_state(
                    ctx.module_id,
                    "FAILED" if status == "FAILED" else "CANCELLED",
                    last_error=f"{getattr(exc.code, 'value', exc.code)}: {exc.message}",
                )
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Early-return helpers (path / none)
    # ------------------------------------------------------------------

    def _install_path_source(self, ctx: _InstallContext) -> InstallResult:
        root = Path(ctx.config.source.path or "").expanduser().resolve()
        if not root.exists():
            raise InstallError(ExternalFailureCode.NOT_INSTALLED, f"path missing: {root}")
        ref_key = ctx.config.source.ref or ctx.ref_key or "local"
        version_id = f"{ctx.module_id}:path:{_hash_text(f'{root}:{ref_key}')[:12]}"
        self._emit(ctx, InstallPhase.READY, "local path ready")
        return InstallResult(
            version_id=version_id,
            module_id=ctx.module_id,
            install_root=str(root),
            source_ref=ctx.config.source.ref or ref_key,
            resolved_commit=None,
            content_hash=_dir_fingerprint(root),
            strategies=["NONE"],
            dependency_versions={},
            installed_at=utc_now(),
            operation_id=ctx.operation_id,
        )

    def _install_none_source(self, ctx: _InstallContext) -> InstallResult:
        root = self.install_root_for(ctx.module_id, ctx.config.source.ref or "none")
        root.mkdir(parents=True, exist_ok=True)
        version_id = f"{ctx.module_id}:none:{_hash_text(ctx.module_id)[:12]}"
        self._emit(ctx, InstallPhase.READY, "manifest-only install ready")
        return InstallResult(
            version_id=version_id,
            module_id=ctx.module_id,
            install_root=str(root),
            source_ref=ctx.config.source.ref,
            resolved_commit=None,
            content_hash=None,
            strategies=["NONE"],
            dependency_versions={},
            installed_at=utc_now(),
            operation_id=ctx.operation_id,
        )

    def _result_from_existing(
        self,
        ctx: _InstallContext,
        dest: Path,
        plan: InstallPlan,
    ) -> InstallResult:
        content_hash = _dir_fingerprint(dest)
        version_id = f"{ctx.module_id}:{ctx.ref_key}:{(content_hash or uuid.uuid4().hex)[:12]}"
        dep_versions = self._enrich_dependency_versions(ctx, plan, {"reused_existing": True})
        self._emit(ctx, InstallPhase.READY, f"reusing existing install at {dest}")
        return InstallResult(
            version_id=version_id,
            module_id=ctx.module_id,
            install_root=str(dest),
            source_ref=ctx.config.source.ref or ctx.ref_key,
            resolved_commit=None,
            content_hash=content_hash,
            strategies=list(plan.strategies),
            dependency_versions=dep_versions,
            installed_at=utc_now(),
            plan_hash=plan.plan_hash,
            operation_id=ctx.operation_id,
        )

    def _enrich_dependency_versions(
        self,
        ctx: _InstallContext,
        plan: InstallPlan,
        dep_versions: Mapping[str, Any],
    ) -> dict[str, Any]:
        enriched = dict(dep_versions)
        enriched["provenance"] = {
            "plan_hash": plan.plan_hash,
            "package_manager": plan.package_manager,
            "privilege_state": plan.privilege_state,
            "observations": [o.public_dict() for o in plan.observations],
            "privileged_mutations": list(plan.privileged_mutations),
            "missing_dependencies": list(plan.missing_dependencies),
            "force": ctx.force,
            "operation_id": ctx.operation_id,
            "system_dependencies_retained": ctx.system_deps_installed,
        }
        return enriched

    # ------------------------------------------------------------------
    # Progress / cancel / persistence / runner
    # ------------------------------------------------------------------

    def _emit(self, ctx: _InstallContext, phase: InstallPhase | str, message: str) -> None:
        key = phase.value if isinstance(phase, InstallPhase) else str(phase)
        if ctx.progress:
            ctx.progress(progress_for_phase(key), key, message)

    def _raise_if_cancelled(self, ctx: _InstallContext, *, phase: InstallPhase) -> None:
        if ctx.cancel_pending or (ctx.cancel_check and ctx.cancel_check()):
            ctx.cancel_pending = True
            self._emit(ctx, InstallPhase.CANCELLED, "install cancelled")
            raise InstallError(
                ExternalFailureCode.CANCELLED,
                "install cancelled",
                phase=phase,
                recovery="SYSTEM_DEPENDENCIES_RETAINED" if ctx.system_deps_installed else None,
            )

    def _persist_operation(
        self,
        ctx: _InstallContext,
        *,
        phase: str,
        status: str,
        result: InstallResult | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        store = ctx.store
        if store is None:
            return
        # Map install-local statuses onto store terminal vocabulary.
        store_status = status
        if status == "INSTALLED":
            store_status = "SUCCEEDED"
        metadata: dict[str, Any] = dict(extra or {})
        if result is not None:
            metadata["result"] = result.public_dict()
        progress = progress_for_phase(phase)

        try:
            if hasattr(store, "upsert_module"):
                try:
                    store.upsert_module(
                        module_id=ctx.module_id,
                        name=ctx.module_id,
                        adapter=str(getattr(ctx.config.adapter, "value", ctx.config.adapter) or "CLI"),
                        source=ctx.config.source.public_dict(),
                        runtime_state=phase,
                    )
                except Exception:  # noqa: BLE001
                    pass
            existing = None
            if hasattr(store, "get_install_operation"):
                existing = store.get_install_operation(ctx.operation_id)
            if existing is None and hasattr(store, "create_install_operation"):
                plan_payload = ctx.plan.public_dict() if ctx.plan is not None else {}
                store.create_install_operation(
                    module_id=ctx.module_id,
                    plan_hash=(ctx.plan.plan_hash if ctx.plan else "") or "",
                    plan=plan_payload,
                    status=store_status,
                    phase=phase,
                    operation_id=ctx.operation_id,
                    requested_ref=ctx.ref_key,
                    progress=progress,
                    package_manager=ctx.package_manager_id,
                    metadata=metadata,
                )
            elif hasattr(store, "update_install_operation"):
                error_code = metadata.get("code")
                error_detail = metadata.get("error")
                terminal = store_status in {
                    "SUCCEEDED",
                    "FAILED",
                    "CANCELLED",
                    "COMPLETED",
                    "READY",
                }
                store.update_install_operation(
                    ctx.operation_id,
                    status=store_status,
                    phase=phase,
                    progress=progress,
                    package_manager=ctx.package_manager_id,
                    error_code=str(error_code) if error_code else None,
                    error_detail=str(error_detail) if error_detail else None,
                    retryable=bool(metadata.get("retryable")) if "retryable" in metadata else None,
                    rollback_status=(
                        "SYSTEM_DEPENDENCIES_RETAINED"
                        if metadata.get("system_dependencies_retained")
                        else None
                    ),
                    completed_at=utc_now() if terminal else None,
                    metadata=metadata or None,
                )
            elif hasattr(store, "set_runtime_state"):
                runtime = store_status if store_status in {"FAILED", "CANCELLED"} else phase
                store.set_runtime_state(ctx.module_id, runtime)
        except Exception:  # noqa: BLE001
            pass
    def _run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        runner: CommandRunner | None = None,
    ) -> subprocess.CompletedProcess[str]:
        active = runner if runner is not None else getattr(self, "_active_runner", None)
        if active is not None:
            return active.run(list(argv), timeout=timeout, cwd=cwd, env=env)
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

    # ------------------------------------------------------------------
    # Strategy implementations (unprivileged)
    # ------------------------------------------------------------------

    def _git_checkout(
        self,
        url: str,
        ref: str,
        dest: Path,
        runner: CommandRunner | None = None,
    ) -> str:
        if not shutil.which("git"):
            raise InstallError(
                ExternalFailureCode.DEPENDENCY_MISSING,
                "git not available",
                phase=InstallPhase.FETCHING_SOURCE,
                dependency="git",
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        if (dest / ".git").exists():
            cmds = [
                ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", ref],
                ["git", "-C", str(dest), "checkout", "--force", "FETCH_HEAD"],
            ]
        else:
            if dest.exists() and any(dest.iterdir()):
                # Staging should be empty aside from placeholder; clear non-git trees.
                for child in dest.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
            cmds = [["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)]]
        for cmd in cmds:
            completed = self._run(cmd, timeout=600.0, runner=runner)
            # Fallback: clone without --branch when ref is a commit or default branch differs.
            if completed.returncode != 0 and cmd[0:2] == ["git", "clone"]:
                completed = self._run(
                    ["git", "clone", "--depth", "1", url, str(dest)],
                    timeout=600.0,
                    runner=runner,
                )
                if completed.returncode == 0 and ref:
                    checkout = self._run(
                        ["git", "-C", str(dest), "checkout", ref],
                        timeout=120.0,
                        runner=runner,
                    )
                    if checkout.returncode != 0:
                        raise InstallError(
                            ExternalFailureCode.INSTALL_FAILED,
                            f"git checkout failed: {bounded_process_output(checkout.stderr, checkout.stdout)}",
                            phase=InstallPhase.FETCHING_SOURCE,
                        )
            if completed.returncode != 0:
                raise InstallError(
                    ExternalFailureCode.INSTALL_FAILED,
                    f"{_git_stage(cmd)} failed: {bounded_process_output(completed.stderr, completed.stdout)}",
                    phase=InstallPhase.FETCHING_SOURCE,
                )
        rev = self._run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            timeout=30.0,
            runner=runner,
        )
        return (rev.stdout or "").strip() or ref

    def _python_venv(
        self,
        root: Path,
        config: ExternalConfig,
        runner: CommandRunner | None = None,
    ) -> dict[str, Any]:
        venv = root / ".venv"
        py = shutil.which("python3") or shutil.which("python")
        if not py:
            raise InstallError(
                ExternalFailureCode.DEPENDENCY_MISSING,
                "python not available",
                phase=InstallPhase.PREPARING_RUNTIME,
                dependency="python",
            )
        if not venv.exists():
            completed = self._run([py, "-m", "venv", str(venv)], timeout=180.0, runner=runner)
            if completed.returncode != 0:
                detail = bounded_process_output(completed.stderr, completed.stdout)
                raise InstallError(
                    ExternalFailureCode.INSTALL_FAILED,
                    f"venv failed: {detail if detail != 'no output' else 'unknown (is python3-venv installed?)'}",
                    phase=InstallPhase.PREPARING_RUNTIME,
                    dependency="python_venv",
                )
        pip = venv / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
        if not pip.exists():
            raise InstallError(
                ExternalFailureCode.INSTALL_FAILED,
                "pip missing in venv",
                phase=InstallPhase.PREPARING_RUNTIME,
            )
        req = config.install.requirements_file
        packages = [p for p in config.install.python_packages if p not in {"-e", "--editable", "."}]
        if req:
            req_path = root / req
            if req_path.exists():
                completed = self._run(
                    [str(pip), "install", "-r", str(req_path)],
                    timeout=900.0,
                    runner=runner,
                )
                if completed.returncode != 0:
                    detail = bounded_process_output(completed.stderr, completed.stdout)
                    raise InstallError(
                        ExternalFailureCode.INSTALL_FAILED,
                        f"pip -r failed: {detail}",
                        phase=InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES,
                    )
        if packages:
            completed = self._run(
                [str(pip), "install", *packages],
                timeout=900.0,
                runner=runner,
            )
            if completed.returncode != 0:
                detail = bounded_process_output(completed.stderr, completed.stdout)
                raise InstallError(
                    ExternalFailureCode.INSTALL_FAILED,
                    f"pip install failed: {detail}",
                    phase=InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES,
                )
        if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
            editable = self._run(
                [str(pip), "install", "-e", str(root)],
                timeout=900.0,
                runner=runner,
            )
            if editable.returncode != 0:
                detail = bounded_process_output(editable.stderr, editable.stdout)
                raise InstallError(
                    ExternalFailureCode.INSTALL_FAILED,
                    f"pip editable failed: {detail}",
                    phase=InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES,
                )
        return {"python": py, "venv": str(venv), "privileged": False}

    def _pip_packages(
        self,
        root: Path,
        config: ExternalConfig,
        runner: CommandRunner | None = None,
    ) -> dict[str, Any]:
        pip = root / ".venv" / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
        if not pip.exists():
            pip_bin = shutil.which("pip3") or shutil.which("pip")
            if not pip_bin:
                raise InstallError(
                    ExternalFailureCode.DEPENDENCY_MISSING,
                    "pip not available",
                    phase=InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES,
                    dependency="pip",
                )
            pip = Path(pip_bin)
        raw = list(config.install.python_packages)
        editable = False
        packages: list[str] = []
        i = 0
        while i < len(raw):
            tok = raw[i]
            if tok in {"-e", "--editable"}:
                editable = True
                if i + 1 < len(raw) and raw[i + 1] in {".", ""}:
                    i += 2
                    continue
                i += 1
                continue
            if tok == ".":
                editable = True
                i += 1
                continue
            packages.append(tok)
            i += 1
        if not packages and not editable and config.source.source_type == "pip" and config.source.source:
            packages = [config.source.source]
        if not packages and not editable:
            return {}
        cmd = [str(pip), "install"]
        if editable:
            cmd.extend(["-e", str(root)])
        if packages:
            cmd.extend(packages)
        completed = self._run(cmd, timeout=900.0, cwd=str(root), runner=runner)
        if completed.returncode != 0:
            detail = bounded_process_output(completed.stderr, completed.stdout)
            raise InstallError(
                ExternalFailureCode.INSTALL_FAILED,
                f"pip failed: {detail}",
                phase=InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES,
            )
        return {"pip_packages": packages, "editable": editable, "cwd": str(root), "privileged": False}

    def _node_install(
        self,
        root: Path,
        config: ExternalConfig,
        *,
        tool: str,
        runner: CommandRunner | None = None,
    ) -> dict[str, Any]:
        tool_path = _resolve_node_tool(tool)
        if not tool_path:
            raise InstallError(
                ExternalFailureCode.DEPENDENCY_MISSING,
                f"{tool} not available",
                phase=InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES,
                dependency=tool,
            )
        pkg = root / (config.install.package_json or "package.json")
        if not pkg.exists() and not config.install.npm_packages:
            return {tool: "skipped_no_package_json"}
        cmd = [tool_path, "install"]
        if config.install.npm_packages:
            cmd = [tool_path, "install", *config.install.npm_packages]
        from Data.modules.common.process_control import scrub_child_environment
        env = scrub_child_environment()
        node_dir = _preferred_node_bin_dir()
        if node_dir:
            env["PATH"] = f"{node_dir}{os.pathsep}{env.get('PATH', '')}"
        completed = self._run(cmd, timeout=900.0, cwd=str(root), env=env, runner=runner)
        if completed.returncode != 0:
            detail = bounded_process_output(completed.stderr, completed.stdout)
            raise InstallError(
                ExternalFailureCode.INSTALL_FAILED,
                f"{tool} failed: {detail}",
                phase=InstallPhase.INSTALLING_APPLICATION_DEPENDENCIES,
            )
        return {tool: "ok", "tool_path": tool_path, "node_bin_dir": node_dir, "privileged": False}


def _git_stage(cmd: list[str]) -> str:
    verbs = set(cmd)
    if "clone" in verbs:
        return "git clone"
    if "fetch" in verbs:
        return "git fetch"
    if "checkout" in verbs:
        return "git checkout"
    return "git"


def _missing_binaries(names: tuple[str, ...]) -> list[str]:
    """Return missing binaries — pure detection only; never installs packages.

    Prefers the trusted logical registry candidate lists when a name canonicalizes;
    falls back to legacy alias tables. Does not invoke package managers.
    """
    from .dependencies import LOGICAL_DEPENDENCY_REGISTRY

    aliases = {
        "python": ("python3", "python", "python3.12", "python3.11"),
        "python3": ("python3", "python", "python3.12", "python3.11"),
        "pip": ("pip3", "pip"),
        "pip3": ("pip3", "pip"),
        "node": ("node",),
        "npm": ("npm",),
        "pnpm": ("pnpm",),
    }
    missing: list[str] = []
    for name in names:
        canonical = canonicalize_dependency_id(name)
        entry = LOGICAL_DEPENDENCY_REGISTRY.get(canonical) if canonical else None
        if entry and entry.binary_candidates:
            candidates = entry.binary_candidates
        else:
            candidates = aliases.get(name, (name,))
        if not any(shutil.which(c) for c in candidates):
            if name in {"node", "npm", "pnpm"} and _resolve_node_tool(name):
                continue
            if canonical in {"node", "npm", "pnpm"} and _resolve_node_tool(canonical):
                continue
            # Capability-only deps (e.g. python_venv) are observed by the planner, not which().
            if entry and not entry.binary_candidates:
                continue
            missing.append(name)
    return missing


def _preferred_node_bin_dir() -> str | None:
    """Return a bin dir with the newest Node >= 22.22 when discoverable."""
    candidates: list[Path] = []
    nvm_dir = Path(os.environ.get("NVM_DIR") or (Path.home() / ".nvm"))
    versions = nvm_dir / "versions" / "node"
    if versions.is_dir():
        for path in versions.iterdir():
            node = path / "bin" / "node"
            if node.is_file():
                candidates.append(path / "bin")
    which_node = shutil.which("node")
    if which_node:
        candidates.append(Path(which_node).resolve().parent)

    best: tuple[tuple[int, ...], Path] | None = None
    for bin_dir in candidates:
        node = bin_dir / "node"
        if not node.is_file():
            continue
        try:
            completed = subprocess.run(
                [str(node), "-v"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                shell=False,
            )
            ver = (completed.stdout or "").strip().lstrip("v")
            parts = tuple(int(p) for p in ver.split(".")[:3])
        except Exception:  # noqa: BLE001
            continue
        if best is None or parts > best[0]:
            best = (parts, bin_dir)
    if best is None:
        return None
    return str(best[1])


def _resolve_node_tool(tool: str) -> str | None:
    node_dir = _preferred_node_bin_dir()
    if node_dir:
        candidate = Path(node_dir) / tool
        if candidate.is_file():
            return str(candidate)
    return shutil.which(tool)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dir_fingerprint(root: Path, *, limit_files: int = 200) -> str:
    """Bounded content fingerprint — does not hash every file in huge trees."""
    h = hashlib.sha256()
    count = 0
    if not root.exists():
        return h.hexdigest()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = set(path.parts)
        if parts & {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}:
            continue
        try:
            rel = str(path.relative_to(root))
            st = path.stat()
            h.update(rel.encode("utf-8"))
            h.update(str(st.st_size).encode("utf-8"))
            h.update(str(int(st.st_mtime)).encode("utf-8"))
        except OSError:
            continue
        count += 1
        if count >= limit_files:
            break
    return h.hexdigest()
