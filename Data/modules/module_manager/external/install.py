"""Generic installation path for external capabilities.

Installations land under data_root/external_capabilities/<module-id>/versions/<ref>.
Installation itself is intended to run as a JobRuntime task (caller enqueues).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .types import ExternalConfig, ExternalFailureCode, InstallStrategy


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class InstallError(RuntimeError):
    def __init__(self, code: ExternalFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


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

    def public_dict(self) -> dict[str, Any]:
        return {
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


ProgressCb = Callable[[float, str, str], None]


class InstallationService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)
        self.base = self.data_root / "external_capabilities"

    def install_root_for(self, module_id: str, ref_key: str) -> Path:
        safe_mod = "".join(c if c.isalnum() or c in "._-" else "_" for c in module_id)
        safe_ref = "".join(c if c.isalnum() or c in "._-" else "_" for c in ref_key)[:80] or "default"
        return self.base / safe_mod / "versions" / safe_ref

    def ensure_installed(
        self,
        *,
        module_id: str,
        config: ExternalConfig,
        progress: ProgressCb | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> InstallResult:
        def _prog(p: float, phase: str, msg: str) -> None:
            if progress:
                progress(p, phase, msg)

        if cancel_check and cancel_check():
            raise InstallError(ExternalFailureCode.CANCELLED, "install cancelled")

        # Local path source without install strategies.
        if config.source.source_type == "path" and config.source.path:
            root = Path(config.source.path).expanduser().resolve()
            if not root.exists():
                raise InstallError(ExternalFailureCode.NOT_INSTALLED, f"path missing: {root}")
            # Include ref so install_version/activate can distinguish pinned path snapshots.
            ref_key = config.source.ref or "local"
            version_id = f"{module_id}:path:{_hash_text(f'{root}:{ref_key}')[:12]}"
            _prog(1.0, "installed", "local path ready")
            return InstallResult(
                version_id=version_id,
                module_id=module_id,
                install_root=str(root),
                source_ref=config.source.ref or ref_key,
                resolved_commit=None,
                content_hash=_dir_fingerprint(root),
                strategies=["NONE"],
                dependency_versions={},
                installed_at=utc_now(),
            )

        if config.source.source_type == "none" or (
            InstallStrategy.NONE in config.install.strategies
            and len(config.install.strategies) == 1
            and not config.source.source
        ):
            # Manifest-only / skill-only — no checkout required.
            root = self.install_root_for(module_id, config.source.ref or "none")
            root.mkdir(parents=True, exist_ok=True)
            version_id = f"{module_id}:none:{_hash_text(module_id)[:12]}"
            return InstallResult(
                version_id=version_id,
                module_id=module_id,
                install_root=str(root),
                source_ref=config.source.ref,
                resolved_commit=None,
                content_hash=None,
                strategies=["NONE"],
                dependency_versions={},
                installed_at=utc_now(),
            )

        ref_key = config.source.ref or "main"
        root = self.install_root_for(module_id, ref_key)
        applied: list[str] = []
        dep_versions: dict[str, Any] = {}
        resolved_commit: str | None = None

        # Missing binary dependencies — report, do not silently install OS packages.
        missing = _missing_binaries(config.install.dependencies)
        if missing:
            raise InstallError(
                ExternalFailureCode.DEPENDENCY_MISSING,
                f"missing dependencies: {', '.join(missing)}",
            )

        for strategy in config.install.strategies:
            if cancel_check and cancel_check():
                raise InstallError(ExternalFailureCode.CANCELLED, "install cancelled")
            if strategy == InstallStrategy.NONE:
                applied.append(strategy.value)
                continue
            if strategy == InstallStrategy.GIT_CHECKOUT:
                _prog(0.1, "git", f"checkout {config.source.source}@{ref_key}")
                resolved_commit = self._git_checkout(config.source.source, ref_key, root)
                applied.append(strategy.value)
                _prog(0.4, "git", f"resolved {resolved_commit}")
            elif strategy == InstallStrategy.PYTHON_VENV:
                _prog(0.5, "venv", "create/update python venv")
                venv_info = self._python_venv(root, config)
                dep_versions.update(venv_info)
                applied.append(strategy.value)
            elif strategy == InstallStrategy.PIP_PACKAGE:
                _prog(0.6, "pip", "pip install packages")
                pip_info = self._pip_packages(root, config)
                dep_versions.update(pip_info)
                applied.append(strategy.value)
            elif strategy == InstallStrategy.NODE_NPM:
                _prog(0.6, "npm", "npm install")
                npm_info = self._node_install(root, config, tool="npm")
                dep_versions.update(npm_info)
                applied.append(strategy.value)
            elif strategy == InstallStrategy.NODE_PNPM:
                _prog(0.6, "pnpm", "pnpm install")
                npm_info = self._node_install(root, config, tool="pnpm")
                dep_versions.update(npm_info)
                applied.append(strategy.value)
            elif strategy == InstallStrategy.NODE_SCRIPT:
                applied.append(strategy.value)
            elif strategy == InstallStrategy.BINARY:
                # Binary strategy expects the binary already present or provided by checkout.
                applied.append(strategy.value)
            else:
                raise InstallError(ExternalFailureCode.INSTALL_FAILED, f"unsupported strategy {strategy}")

        post_env = os.environ.copy()
        node_dir = _preferred_node_bin_dir()
        if node_dir:
            post_env["PATH"] = f"{node_dir}{os.pathsep}{post_env.get('PATH', '')}"
        for cmd in config.install.post_install:
            if cancel_check and cancel_check():
                raise InstallError(ExternalFailureCode.CANCELLED, "install cancelled")
            _prog(0.85, "post_install", " ".join(cmd))
            argv = list(cmd)
            # Resolve npm/pnpm/node through preferred toolchain when listed bare.
            if argv and argv[0] in {"npm", "pnpm", "node"}:
                resolved = _resolve_node_tool(argv[0])
                if resolved:
                    argv[0] = resolved
            completed = subprocess.run(
                argv,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
                shell=False,
                env=post_env,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()[:800]
                raise InstallError(
                    ExternalFailureCode.INSTALL_FAILED,
                    f"post_install failed ({completed.returncode}): {detail}",
                )

        content_hash = _dir_fingerprint(root) if root.exists() else None
        version_id = f"{module_id}:{resolved_commit or ref_key}:{ (content_hash or uuid.uuid4().hex)[:12]}"
        _prog(1.0, "installed", str(root))
        return InstallResult(
            version_id=version_id,
            module_id=module_id,
            install_root=str(root),
            source_ref=config.source.ref,
            resolved_commit=resolved_commit,
            content_hash=content_hash,
            strategies=applied,
            dependency_versions=dep_versions,
            installed_at=utc_now(),
        )

    def _git_checkout(self, url: str, ref: str, dest: Path) -> str:
        if not shutil.which("git"):
            raise InstallError(ExternalFailureCode.DEPENDENCY_MISSING, "git not available")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if (dest / ".git").exists():
            cmds = [
                ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", ref],
                ["git", "-C", str(dest), "checkout", "--force", "FETCH_HEAD"],
            ]
        else:
            if dest.exists():
                shutil.rmtree(dest)
            cmds = [["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)]]
        for cmd in cmds:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False, shell=False)
            # Fallback: clone without --branch when ref is a commit or default branch differs.
            if completed.returncode != 0 and cmd[0:2] == ["git", "clone"]:
                completed = subprocess.run(
                    ["git", "clone", "--depth", "1", url, str(dest)],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    check=False,
                    shell=False,
                )
                if completed.returncode == 0 and ref:
                    subprocess.run(
                        ["git", "-C", str(dest), "checkout", ref],
                        capture_output=True,
                        text=True,
                        timeout=120,
                        check=False,
                        shell=False,
                    )
            if completed.returncode != 0:
                raise InstallError(
                    ExternalFailureCode.INSTALL_FAILED,
                    f"git failed: {completed.stderr[:800] or completed.stdout[:800]}",
                )
        rev = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
        )
        return (rev.stdout or "").strip() or ref

    def _python_venv(self, root: Path, config: ExternalConfig) -> dict[str, Any]:
        venv = root / ".venv"
        py = shutil.which("python3") or shutil.which("python")
        if not py:
            raise InstallError(ExternalFailureCode.DEPENDENCY_MISSING, "python not available")
        if not venv.exists():
            completed = subprocess.run(
                [py, "-m", "venv", str(venv)],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()[:800]
                raise InstallError(
                    ExternalFailureCode.INSTALL_FAILED,
                    f"venv failed: {detail or 'unknown (is python3-venv installed?)'}",
                )
        pip = venv / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
        if not pip.exists():
            raise InstallError(ExternalFailureCode.INSTALL_FAILED, "pip missing in venv")
        req = config.install.requirements_file
        # Ignore editable flags mistakenly listed as package names; handled below.
        packages = [p for p in config.install.python_packages if p not in {"-e", "--editable", "."}]
        if req:
            req_path = root / req
            if req_path.exists():
                completed = subprocess.run(
                    [str(pip), "install", "-r", str(req_path)],
                    capture_output=True,
                    text=True,
                    timeout=900,
                    check=False,
                    shell=False,
                )
                if completed.returncode != 0:
                    detail = (completed.stderr or completed.stdout or "").strip()[:500]
                    raise InstallError(ExternalFailureCode.INSTALL_FAILED, f"pip -r failed: {detail}")
        if packages:
            completed = subprocess.run(
                [str(pip), "install", *packages],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()[:500]
                raise InstallError(ExternalFailureCode.INSTALL_FAILED, f"pip install failed: {detail}")
        # Also install editable package if pyproject/setup present.
        if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
            editable = subprocess.run(
                [str(pip), "install", "-e", str(root)],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
                shell=False,
            )
            if editable.returncode != 0:
                detail = (editable.stderr or editable.stdout or "").strip()[:500]
                raise InstallError(ExternalFailureCode.INSTALL_FAILED, f"pip editable failed: {detail}")
        return {"python": py, "venv": str(venv)}

    def _pip_packages(self, root: Path, config: ExternalConfig) -> dict[str, Any]:
        # Prefer venv pip when present.
        pip = root / ".venv" / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
        if not pip.exists():
            pip_bin = shutil.which("pip3") or shutil.which("pip")
            if not pip_bin:
                raise InstallError(ExternalFailureCode.DEPENDENCY_MISSING, "pip not available")
            pip = Path(pip_bin)
        raw = list(config.install.python_packages)
        # Treat "-e ." / "--editable ." as editable install of the checkout root.
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
        completed = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:500]
            raise InstallError(ExternalFailureCode.INSTALL_FAILED, f"pip failed: {detail}")
        return {"pip_packages": packages, "editable": editable, "cwd": str(root)}

    def _node_install(self, root: Path, config: ExternalConfig, *, tool: str) -> dict[str, Any]:
        tool_path = _resolve_node_tool(tool)
        if not tool_path:
            raise InstallError(ExternalFailureCode.DEPENDENCY_MISSING, f"{tool} not available")
        pkg = root / (config.install.package_json or "package.json")
        if not pkg.exists() and not config.install.npm_packages:
            return {tool: "skipped_no_package_json"}
        cmd = [tool_path, "install"]
        if config.install.npm_packages:
            cmd = [tool_path, "install", *config.install.npm_packages]
        env = os.environ.copy()
        # Prefer a Node that satisfies modern engines (e.g. >=22.22) when available via nvm.
        node_dir = _preferred_node_bin_dir()
        if node_dir:
            env["PATH"] = f"{node_dir}{os.pathsep}{env.get('PATH', '')}"
        completed = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
            shell=False,
            env=env,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:800]
            raise InstallError(ExternalFailureCode.INSTALL_FAILED, f"{tool} failed: {detail}")
        return {tool: "ok", "tool_path": tool_path, "node_bin_dir": node_dir}


def _missing_binaries(names: tuple[str, ...]) -> list[str]:
    """Return missing binaries, with common language-runtime aliases."""
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
        candidates = aliases.get(name, (name,))
        if not any(shutil.which(c) for c in candidates):
            # Also accept preferred nvm node/npm/pnpm.
            if name in {"node", "npm", "pnpm"} and _resolve_node_tool(name):
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
    # Prefer any >= 22.22 when present; otherwise newest found.
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
        # Skip bulky/irrelevant dirs.
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
