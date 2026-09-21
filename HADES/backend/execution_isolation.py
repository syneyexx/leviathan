"""Technically enforced execution isolation for untrusted autonomous code.

Secured mode requires a working OS isolation adapter that restricts:
- filesystem (read/write roots)
- network (default deny)
- environment variable passthrough
- credential leakage

Adapters:
- linux_userns_mount: user+mount(+optional net) namespaces via ``unshare``
- windows_job: Job Object process limits only — NOT full FS/network isolation;
  secured mode must NOT claim FS isolation from Job Objects alone.

Fail-closed: if secured isolation cannot be enforced, raise IsolationUnavailable
instead of falling back to an unbounded subprocess.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


class IsolationError(RuntimeError):
    """Base isolation failure."""


class IsolationUnavailable(IsolationError):
    """Required isolation cannot be enforced on this host."""


class IsolationViolation(IsolationError):
    """Child attempted or would require an out-of-policy action."""


TRUSTED_MODE = "trusted"
SECURED_MODE = "secured"

ADAPTER_LINUX_USERNS = "linux_userns_mount"
ADAPTER_WINDOWS_JOB = "windows_job"
ADAPTER_NONE = "none"


@dataclass
class IsolationPolicy:
    """Explicit roots and capability bounds for one execution."""

    read_roots: list[Path] = field(default_factory=list)
    write_roots: list[Path] = field(default_factory=list)
    allow_network: bool = False
    env_allowlist: list[str] = field(
        default_factory=lambda: [
            "PATH",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "WINDIR",
            "TEMP",
            "TMP",
            "TMPDIR",
            "HOME",
            "USERPROFILE",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "PYTHONIOENCODING",
            "PYTHONUTF8",
            "PYTHONUNBUFFERED",
            "PATHEXT",
            "COMSPEC",
        ]
    )
    inherit_python_exe: bool = True
    mode: str = SECURED_MODE  # trusted | secured


@dataclass
class IsolationResult:
    ok: bool
    adapter: str
    mode: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    pid: int | None = None
    isolation_enforced: bool = False
    fs_isolation: bool = False
    network_isolation: bool = False
    env_filtered: bool = False
    reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "adapter": self.adapter,
            "mode": self.mode,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "pid": self.pid,
            "isolation_enforced": self.isolation_enforced,
            "fs_isolation": self.fs_isolation,
            "network_isolation": self.network_isolation,
            "env_filtered": self.env_filtered,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def _resolve_roots(paths: Sequence[Path | str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser().resolve(strict=False)
        out.append(path)
    return out


def filter_environment(
    source: Mapping[str, str] | None,
    *,
    allowlist: Sequence[str],
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Pass only allowlisted names; never copy secrets by default."""
    src = dict(source or {})
    allowed = {str(name).upper() for name in allowlist}
    filtered: dict[str, str] = {}
    for key, value in src.items():
        if key.upper() in allowed:
            # Skip obvious credential-shaped values even if allowlisted by mistake.
            upper = key.upper()
            if any(tok in upper for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY")):
                if upper not in {"PATHEXT"}:  # PATHEXT is safe Windows metadata
                    continue
            filtered[key] = value
    filtered["PYTHONUNBUFFERED"] = "1"
    if extra:
        filtered.update({str(k): str(v) for k, v in extra.items()})
    return filtered


def detect_isolation_capabilities() -> dict[str, Any]:
    """Honest host probe — never sets operationally_tested from import alone."""
    is_windows = os.name == "nt" or sys.platform.startswith("win")
    unshare = shutil.which("unshare")
    linux_userns = False
    linux_userns_reason = "not_linux"
    if not is_windows and unshare:
        try:
            probe = subprocess.run(
                [unshare, "--user", "--map-root-user", "--mount", "true"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            linux_userns = probe.returncode == 0
            linux_userns_reason = "ok" if linux_userns else (probe.stderr or probe.stdout or "unshare_failed")[:200]
        except Exception as exc:  # pragma: no cover - host dependent
            linux_userns_reason = f"probe_error:{exc}"
    job_api = False
    if is_windows:
        try:
            from gen2.sandbox_job import job_object_api_present

            job_api = bool(job_object_api_present())
        except Exception:
            job_api = False
    return {
        "platform": sys.platform,
        "is_windows": is_windows,
        "unshare_path": unshare,
        "linux_userns_mount_available": linux_userns,
        "linux_userns_reason": linux_userns_reason,
        "windows_job_object_api": job_api,
        # Job Objects alone are NOT FS/network isolation.
        "windows_fs_isolation_available": False,
        "secured_fs_isolation_available": bool(linux_userns),
        "operationally_tested": False,
    }


def build_filtered_env(policy: IsolationPolicy, *, source: Mapping[str, str] | None = None) -> dict[str, str]:
    return filter_environment(source or os.environ, allowlist=policy.env_allowlist)


def _linux_helper_script() -> str:
    """Inner helper executed inside the user+mount namespace."""
    return textwrap.dedent(
        r"""
        import json
        import os
        import shutil
        import subprocess
        import sys
        from pathlib import Path

        cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        jail = Path(cfg["jail_dir"])
        new_root = jail / "root"
        if new_root.exists():
            shutil.rmtree(new_root)
        new_root.mkdir(parents=True)

        def ensure_mount(src: str, dst: Path, *, read_only: bool) -> None:
            src_path = Path(src)
            if not src_path.exists():
                return
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src_path.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    dst.touch()
            flags = ["--bind"]
            subprocess.run(["mount", *flags, str(src_path), str(dst)], check=True)
            if read_only:
                subprocess.run(["mount", "-o", "remount,ro,bind", str(dst)], check=False)

        # Minimal userspace (read-only).
        for essential in ("/usr", "/bin", "/lib", "/lib64", "/sbin", "/etc"):
            ensure_mount(essential, new_root / essential.lstrip("/"), read_only=True)

        # Device/proc stubs.
        (new_root / "proc").mkdir(parents=True, exist_ok=True)
        (new_root / "dev").mkdir(parents=True, exist_ok=True)
        (new_root / "tmp").mkdir(parents=True, exist_ok=True)
        subprocess.run(["mount", "-t", "proc", "proc", str(new_root / "proc")], check=False)
        for node in ("null", "zero", "urandom", "random", "tty"):
            ensure_mount(f"/dev/{node}", new_root / "dev" / node, read_only=False)

        # Allowed roots.
        for root in cfg.get("read_roots") or []:
            target = new_root / Path(root).resolve().as_posix().lstrip("/")
            ensure_mount(root, target, read_only=True)
        for root in cfg.get("write_roots") or []:
            target = new_root / Path(root).resolve().as_posix().lstrip("/")
            ensure_mount(root, target, read_only=False)

        # Workdir inside jail must exist.
        workdir = Path(cfg["cwd"]).resolve()
        work_in_jail = new_root / workdir.as_posix().lstrip("/")
        work_in_jail.mkdir(parents=True, exist_ok=True)

        os.chroot(str(new_root))
        os.chdir(str(workdir))
        env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}
        argv = list(cfg["argv"])
        timeout = cfg.get("timeout_seconds")
        try:
            completed = subprocess.run(
                argv,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=None if timeout is None else float(timeout),
                shell=False,
                env=env,
                check=False,
            )
            payload = {
                "ok": True,
                "exit_code": int(completed.returncode),
                "stdout": completed.stdout or "",
                "stderr": completed.stderr or "",
                "pid": os.getpid(),
            }
        except subprocess.TimeoutExpired as exc:
            payload = {
                "ok": False,
                "exit_code": 124,
                "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "timeout",
                "pid": os.getpid(),
                "reason": "timeout",
            }
        except Exception as exc:
            payload = {
                "ok": False,
                "exit_code": 1,
                "stdout": "",
                "stderr": f"isolation_helper_error:{exc}",
                "pid": os.getpid(),
                "reason": "helper_error",
            }
        Path(cfg["result_path"]).write_text(json.dumps(payload), encoding="utf-8")
        """
    ).strip()


def run_linux_userns_isolated(
    argv: Sequence[str],
    *,
    cwd: Path,
    policy: IsolationPolicy,
    timeout_seconds: float | None = 30.0,
    env: Mapping[str, str] | None = None,
) -> IsolationResult:
    caps = detect_isolation_capabilities()
    if not caps.get("linux_userns_mount_available"):
        raise IsolationUnavailable(
            f"linux_userns_mount unavailable: {caps.get('linux_userns_reason')}"
        )
    unshare = caps.get("unshare_path") or shutil.which("unshare")
    if not unshare:
        raise IsolationUnavailable("unshare binary not found")

    read_roots = _resolve_roots([*policy.read_roots, *policy.write_roots, cwd])
    write_roots = _resolve_roots([*policy.write_roots, cwd])
    # Always allow the interpreter binary directory as read-only when using Python.
    # Resolve symlinks (venv python → /usr/bin/python3.X) so chroot argv is reachable.
    normalized_argv = [str(x) for x in argv]
    exe = Path(argv[0]).resolve(strict=False) if argv else None
    if exe and exe.exists():
        read_roots.append(exe.parent if exe.is_file() else exe)
        normalized_argv[0] = str(exe)
        # Also allow realpath of python shared libs via /usr already.

    filtered_env = filter_environment(env or os.environ, allowlist=policy.env_allowlist)

    with tempfile.TemporaryDirectory(prefix="hades-iso-") as tmp:
        jail = Path(tmp)
        cfg_path = jail / "cfg.json"
        result_path = jail / "result.json"
        helper_path = jail / "helper.py"
        helper_path.write_text(_linux_helper_script() + "\n", encoding="utf-8")
        # Result file must be writable from inside chroot — keep jail dir itself mounted RW.
        write_roots = list({*write_roots, jail})
        helper_python = Path(sys.executable).resolve()
        read_roots = list({*read_roots, jail, helper_python.parent})
        cfg = {
            "jail_dir": str(jail),
            "argv": normalized_argv,
            "cwd": str(Path(cwd).resolve()),
            "read_roots": [str(p) for p in read_roots],
            "write_roots": [str(p) for p in write_roots],
            "env": filtered_env,
            "timeout_seconds": timeout_seconds,
            "result_path": str(result_path),
        }
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

        unshare_argv = [str(unshare), "--user", "--map-root-user", "--mount"]
        if not policy.allow_network:
            unshare_argv.append("--net")
        # Outer helper must also use a realpath that survives mounts (not a broken venv symlink view).
        unshare_argv.extend([str(helper_python), str(helper_path), str(cfg_path)])

        started = time.perf_counter()
        outer = subprocess.run(
            unshare_argv,
            capture_output=True,
            text=True,
            timeout=(None if timeout_seconds is None else float(timeout_seconds) + 10.0),
            shell=False,
            check=False,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        if not result_path.is_file():
            raise IsolationUnavailable(
                "isolation helper did not produce a result "
                f"(exit={outer.returncode}, stderr={(outer.stderr or '')[:400]})"
            )
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        return IsolationResult(
            ok=bool(payload.get("ok")) and int(payload.get("exit_code") or 1) == 0,
            adapter=ADAPTER_LINUX_USERNS,
            mode=SECURED_MODE,
            exit_code=int(payload.get("exit_code") if payload.get("exit_code") is not None else 1),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or outer.stderr or ""),
            duration_ms=duration_ms,
            pid=payload.get("pid"),
            isolation_enforced=True,
            fs_isolation=True,
            network_isolation=not policy.allow_network,
            env_filtered=True,
            reason=payload.get("reason"),
            evidence={
                "allow_network": policy.allow_network,
                "read_roots": [str(p) for p in read_roots],
                "write_roots": [str(p) for p in write_roots],
                "outer_exit": outer.returncode,
            },
        )


def run_trusted_subprocess(
    argv: Sequence[str],
    *,
    cwd: Path,
    policy: IsolationPolicy,
    timeout_seconds: float | None = 30.0,
    env: Mapping[str, str] | None = None,
) -> IsolationResult:
    """Explicit trusted mode — filtered env optional, no FS jail.

    Callers must label this distinctly from secured isolation.
    """
    filtered = filter_environment(env or os.environ, allowlist=policy.env_allowlist)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(x) for x in argv],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=None if timeout_seconds is None else float(timeout_seconds),
            shell=False,
            env=filtered,
            check=False,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return IsolationResult(
            ok=completed.returncode == 0,
            adapter=ADAPTER_NONE,
            mode=TRUSTED_MODE,
            exit_code=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_ms=duration_ms,
            isolation_enforced=False,
            fs_isolation=False,
            network_isolation=False,
            env_filtered=True,
            reason="trusted_mode_no_fs_isolation",
            evidence={"warning": "trusted_mode_allows_host_filesystem"},
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return IsolationResult(
            ok=False,
            adapter=ADAPTER_NONE,
            mode=TRUSTED_MODE,
            exit_code=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "timeout",
            duration_ms=duration_ms,
            isolation_enforced=False,
            fs_isolation=False,
            network_isolation=False,
            env_filtered=True,
            reason="timeout",
        )


def run_isolated(
    argv: Sequence[str],
    *,
    cwd: Path | str,
    policy: IsolationPolicy | None = None,
    timeout_seconds: float | None = 30.0,
    env: Mapping[str, str] | None = None,
) -> IsolationResult:
    """Run argv under the requested policy. Secured mode fails closed."""
    pol = policy or IsolationPolicy()
    workdir = Path(cwd).expanduser().resolve(strict=False)
    mode = (pol.mode or SECURED_MODE).strip().lower()
    if mode == TRUSTED_MODE:
        return run_trusted_subprocess(
            argv, cwd=workdir, policy=pol, timeout_seconds=timeout_seconds, env=env
        )
    if mode != SECURED_MODE:
        raise IsolationError(f"Unknown isolation mode: {mode}")

    caps = detect_isolation_capabilities()
    if caps.get("secured_fs_isolation_available"):
        return run_linux_userns_isolated(
            argv, cwd=workdir, policy=pol, timeout_seconds=timeout_seconds, env=env
        )
    if caps.get("is_windows"):
        # Job Objects are process limits only — do not pretend they are FS isolation.
        raise IsolationUnavailable(
            "Secured filesystem isolation is unavailable on this Windows host. "
            "Job Objects alone are not FS/network isolation. "
            "Use mode=trusted explicitly if unbounded host FS access is intentional, "
            "or provide an AppContainer/FS-jail adapter. "
            "Status: UNVERIFIED_ON_HOST for Windows FS isolation."
        )
    raise IsolationUnavailable(
        f"Secured isolation unavailable on this host "
        f"(linux_userns={caps.get('linux_userns_reason')})."
    )


def default_policy_for_data_root(
    data_root: Path | str,
    *,
    extra_read: Sequence[Path | str] | None = None,
    extra_write: Sequence[Path | str] | None = None,
    allow_network: bool = False,
    mode: str = SECURED_MODE,
) -> IsolationPolicy:
    root = Path(data_root).expanduser().resolve(strict=False)
    return IsolationPolicy(
        read_roots=[root, *([Path(p) for p in extra_read] if extra_read else [])],
        write_roots=[root, *([Path(p) for p in extra_write] if extra_write else [])],
        allow_network=allow_network,
        mode=mode,
    )
