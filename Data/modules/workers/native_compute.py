"""Allowlisted subprocess runner for the Rust native data-plane binary.

Invokes ``leviathan-data-plane`` with argv lists only (shell=False), bounded
stdout/stderr, timeouts, cancellation, and receipt validation.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

PROTOCOL_VERSION = 1
BINARY_NAME = "leviathan-data-plane"
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_STDOUT_LIMIT = 2 * 1024 * 1024
DEFAULT_STDERR_LIMIT = 2 * 1024 * 1024
# Soft RSS watchdog: terminate when child RSS exceeds memoryBytes * grace.
MEMORY_RSS_GRACE_FACTOR = 1.25
MEMORY_ENFORCEMENT_SOFT = "SOFT_ENFORCED"

SUPPORTED_OPERATIONS = frozenset(
    {
        "dataset.validate",
        "dataset.hash",
        "dataset.transform",
        "dataset.split",
        "dataset.export",
        "dataset.dedupe",
        "dataset.parquet_validate",
        "dataset.parquet_hash",
        "dataset.parquet_to_jsonl",
        "market.ohlcv_validate",
    }
)

PARQUET_OPERATIONS = frozenset(
    {
        "dataset.parquet_validate",
        "dataset.parquet_hash",
        "dataset.parquet_to_jsonl",
    }
)

MARKET_OPERATIONS = frozenset(
    {
        "market.ohlcv_validate",
    }
)


class NativeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    DISABLED = "DISABLED"
    BUILD_MISSING = "BUILD_MISSING"
    FAILED_HEALTHCHECK = "FAILED_HEALTHCHECK"


@dataclass
class NativeCapabilities:
    status: NativeStatus
    protocol_version: int | None = None
    operations: list[str] = field(default_factory=list)
    backend: dict[str, Any] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    binary_path: str | None = None
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "protocolVersion": self.protocol_version,
            "operations": list(self.operations),
            "backend": dict(self.backend),
            "features": dict(self.features),
            "binaryPath": self.binary_path,
            "detail": self.detail,
        }

    @property
    def available(self) -> bool:
        return self.status == NativeStatus.AVAILABLE


@dataclass
class NativeRunResult:
    ok: bool
    receipt: dict[str, Any] | None
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None
    memory_enforcement: str | None = None
    peak_rss_bytes: int | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "receipt": self.receipt,
            "status": self.status,
            "exitCode": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "durationMs": self.duration_ms,
            "errorCode": self.error_code,
            "errorMessage": self.error_message,
            "memoryEnforcement": self.memory_enforcement,
            "peakRssBytes": self.peak_rss_bytes,
        }


def _repo_data_root() -> Path:
    # Data/modules/workers/native_compute.py → Data/
    return Path(__file__).resolve().parents[2]


def default_binary_candidates() -> list[Path]:
    root = _repo_data_root()
    names = [BINARY_NAME, f"{BINARY_NAME}.exe"]
    out: list[Path] = []
    for name in names:
        out.append(root / "native" / "bin" / name)
        out.append(root / "native" / "target" / "release" / name)
        out.append(root / "native" / "target" / "debug" / name)
    return out


def resolve_native_binary(
    *,
    explicit: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Path | None:
    """Resolve an allowlisted binary path only — never shell PATH lookup of arbitrary names."""
    environ = env if env is not None else os.environ
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    override = (environ.get("LEVIATHAN_NATIVE_DATA_PLANE_BIN") or "").strip()
    if override:
        candidates.append(Path(override))
    candidates.extend(default_binary_candidates())

    allow_roots = [
        (_repo_data_root() / "native").resolve(),
    ]
    extra_root = (environ.get("LEVIATHAN_NATIVE_BIN_ROOT") or "").strip()
    if extra_root:
        allow_roots.append(Path(extra_root).resolve())

    seen: set[Path] = set()
    for raw in candidates:
        path = Path(raw).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if not _is_under_allow_roots(resolved, allow_roots):
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def _is_under_allow_roots(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _bounded_read(stream: Any, limit: int, chunks: list[bytes], overflow: list[bool]) -> None:
    total = 0
    try:
        while True:
            data = stream.read(64 * 1024)
            if not data:
                break
            if total >= limit:
                overflow[0] = True
                continue
            take = min(len(data), limit - total)
            chunks.append(data[:take])
            total += take
            if take < len(data):
                overflow[0] = True
    except OSError:
        pass


def _decode_bounded(chunks: list[bytes], overflow: bool) -> str:
    text = b"".join(chunks).decode("utf-8", errors="replace")
    if overflow:
        return text + "\n…[truncated]"
    return text


def probe_capabilities(
    *,
    binary: Path | None = None,
    timeout_seconds: float = 15.0,
    disabled: bool | None = None,
) -> NativeCapabilities:
    if disabled is None:
        disabled = (os.getenv("LEVIATHAN_NATIVE_COMPUTE_DISABLED") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if disabled:
        return NativeCapabilities(status=NativeStatus.DISABLED, detail="native compute disabled by settings")

    path = binary or resolve_native_binary()
    if path is None:
        return NativeCapabilities(
            status=NativeStatus.BUILD_MISSING,
            detail="leviathan-data-plane binary not found under allowlisted roots",
        )

    argv = [str(path), "--capabilities", "--json"]
    try:
        proc = subprocess.run(  # noqa: S603 — argv list, shell=False, allowlisted binary
            argv,
            shell=False,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return NativeCapabilities(
            status=NativeStatus.FAILED_HEALTHCHECK,
            binary_path=str(path),
            detail="capabilities probe timed out",
        )
    except OSError as exc:
        return NativeCapabilities(
            status=NativeStatus.UNAVAILABLE,
            binary_path=str(path),
            detail=f"failed to spawn binary: {exc}",
        )

    stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        return NativeCapabilities(
            status=NativeStatus.FAILED_HEALTHCHECK,
            binary_path=str(path),
            detail=f"capabilities exit={proc.returncode}: {stdout[:500]}",
        )
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        return NativeCapabilities(
            status=NativeStatus.INCOMPATIBLE,
            binary_path=str(path),
            detail="capabilities output was not JSON",
        )

    protocol = doc.get("protocolVersion")
    try:
        protocol_i = int(protocol)
    except (TypeError, ValueError):
        return NativeCapabilities(
            status=NativeStatus.INCOMPATIBLE,
            binary_path=str(path),
            detail="missing protocolVersion in capabilities",
        )
    if protocol_i != PROTOCOL_VERSION:
        return NativeCapabilities(
            status=NativeStatus.INCOMPATIBLE,
            protocol_version=protocol_i,
            binary_path=str(path),
            detail=f"protocol mismatch: got {protocol_i}, expected {PROTOCOL_VERSION}",
        )

    ops = [str(x) for x in (doc.get("operations") or [])]
    missing = sorted(SUPPORTED_OPERATIONS - set(ops))
    if missing:
        return NativeCapabilities(
            status=NativeStatus.INCOMPATIBLE,
            protocol_version=protocol_i,
            operations=ops,
            backend=dict(doc.get("backend") or {}),
            features=dict(doc.get("features") or {}),
            binary_path=str(path),
            detail=f"missing operations: {', '.join(missing)}",
        )

    return NativeCapabilities(
        status=NativeStatus.AVAILABLE,
        protocol_version=protocol_i,
        operations=ops,
        backend=dict(doc.get("backend") or {}),
        features=dict(doc.get("features") or {}),
        binary_path=str(path),
        detail="ok",
    )


def validate_receipt(receipt: dict[str, Any], *, task_id: str, operation: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(receipt, dict):
        return ["receipt is not an object"]
    try:
        if int(receipt.get("protocolVersion")) != PROTOCOL_VERSION:
            errors.append("protocolVersion mismatch")
    except (TypeError, ValueError):
        errors.append("protocolVersion missing")
    if str(receipt.get("taskId") or "") != task_id:
        errors.append("taskId mismatch")
    if str(receipt.get("operation") or "") != operation:
        errors.append("operation mismatch")
    if str(receipt.get("status") or "") not in {"ok", "error"}:
        errors.append("status must be ok|error")
    backend = receipt.get("backend")
    if not isinstance(backend, dict) or not backend.get("name"):
        errors.append("backend info missing")
    for key in ("recordsIn", "recordsOut", "durationMs", "peakRssBytes", "spillBytes"):
        if key not in receipt:
            errors.append(f"missing {key}")
    return errors


def build_task_document(
    *,
    task_id: str,
    operation: str,
    input_path: str | Path,
    temporary_path: str | Path,
    limits: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    content_hash: str | None = None,
    allowed_roots: list[str] | None = None,
    input_format: str = "jsonl",
) -> dict[str, Any]:
    lim = dict(limits or {})
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "taskId": task_id,
        "operation": operation,
        "input": {
            "path": str(input_path),
            "format": input_format,
            "contentHash": content_hash,
        },
        "output": {"temporaryPath": str(temporary_path)},
        "limits": {
            "memoryBytes": int(lim.get("memoryBytes", lim.get("memory_bytes", 512 * 1024 * 1024))),
            "batchRows": int(lim.get("batchRows", lim.get("batch_rows", 16384))),
            "maxRecordBytes": int(lim.get("maxRecordBytes", lim.get("max_record_bytes", 16 * 1024 * 1024))),
            "threads": int(lim.get("threads", 4)),
            "spillBytes": int(lim.get("spillBytes", lim.get("spill_bytes", 20 * 1024 * 1024 * 1024))),
        },
        "options": dict(options or {}),
        "allowedRoots": list(allowed_roots or []),
    }


def read_process_rss_bytes(pid: int) -> int | None:
    """Best-effort child RSS in bytes (psutil → /proc → Windows WorkingSet)."""
    if pid <= 0:
        return None
    try:
        import psutil  # type: ignore[import-untyped]

        return int(psutil.Process(pid).memory_info().rss)
    except Exception:  # noqa: BLE001
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            GetProcessMemoryInfo = ctypes.windll.psapi.GetProcessMemoryInfo  # type: ignore[attr-defined]
            OpenProcess = ctypes.windll.kernel32.OpenProcess  # type: ignore[attr-defined]
            CloseHandle = ctypes.windll.kernel32.CloseHandle  # type: ignore[attr-defined]
            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010
            handle = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
            if not handle:
                return None
            try:
                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                if GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    return int(counters.WorkingSetSize)
            finally:
                CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return None
        return None
    # Linux /proc/<pid>/status VmRSS (kB)
    try:
        status_path = Path(f"/proc/{int(pid)}/status")
        for line in status_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def run_native_task(
    task: dict[str, Any],
    *,
    binary: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    stdout_limit: int = DEFAULT_STDOUT_LIMIT,
    stderr_limit: int = DEFAULT_STDERR_LIMIT,
    cancel_event: threading.Event | None = None,
    work_dir: Path | None = None,
    rss_reader: Callable[[int], int | None] | None = None,
    memory_grace_factor: float = MEMORY_RSS_GRACE_FACTOR,
) -> NativeRunResult:
    """Execute one native task via JSON file protocol.

    Soft memory watchdog (SOFT_ENFORCED): poll child RSS vs limits.memoryBytes
    * grace; on exceed terminate the child and return NATIVE_MEMORY_BUDGET_EXCEEDED.
    This is not OS hard cgroup enforcement.
    """
    started = time.monotonic()
    operation = str(task.get("operation") or "")
    task_id = str(task.get("taskId") or "")
    # Reject unsupported operations before binary resolution so honesty does not
    # depend on whether the native binary happens to be built in this environment.
    if operation not in SUPPORTED_OPERATIONS:
        return NativeRunResult(
            ok=False,
            receipt=None,
            status="error",
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=0,
            error_code="NATIVE_UNSUPPORTED_OPERATION",
            error_message=f"unsupported operation: {operation}",
            memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
        )

    path = binary or resolve_native_binary()
    if path is None:
        return NativeRunResult(
            ok=False,
            receipt=None,
            status="BUILD_MISSING",
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=0,
            error_code="NATIVE_BINARY_MISSING",
            error_message="allowlisted binary not found",
            memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
        )

    limits = task.get("limits") if isinstance(task.get("limits"), dict) else {}
    memory_budget = int(limits.get("memoryBytes") or limits.get("memory_bytes") or 0)
    rss_limit = (
        int(memory_budget * float(memory_grace_factor)) if memory_budget > 0 else 0
    )
    read_rss = rss_reader or read_process_rss_bytes

    tmp_ctx = None
    if work_dir is None:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="leviathan-native-")
        work = Path(tmp_ctx.name)
    else:
        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)

    try:
        task_path = work / "task.json"
        receipt_path = work / "receipt.json"
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        argv = [str(path), "--task", str(task_path), "--receipt", str(receipt_path)]

        proc = subprocess.Popen(  # noqa: S603
            argv,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []
        out_overflow = [False]
        err_overflow = [False]
        t_out = threading.Thread(
            target=_bounded_read, args=(proc.stdout, stdout_limit, out_chunks, out_overflow), daemon=True
        )
        t_err = threading.Thread(
            target=_bounded_read, args=(proc.stderr, stderr_limit, err_chunks, err_overflow), daemon=True
        )
        t_out.start()
        t_err.start()

        deadline = time.monotonic() + float(timeout_seconds)
        cancelled = False
        timed_out = False
        memory_exceeded = False
        peak_rss: int | None = None
        while True:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _terminate(proc)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate(proc)
                break
            if rss_limit > 0 and proc.pid:
                try:
                    rss = read_rss(int(proc.pid))
                except Exception:  # noqa: BLE001
                    rss = None
                if rss is not None:
                    peak_rss = rss if peak_rss is None else max(peak_rss, rss)
                    if rss > rss_limit:
                        memory_exceeded = True
                        _terminate(proc)
                        break
            if proc.poll() is not None:
                break
            time.sleep(0.05)

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate(proc, force=True)
            proc.wait(timeout=5)

        t_out.join(timeout=2)
        t_err.join(timeout=2)
        stdout = _decode_bounded(out_chunks, out_overflow[0])
        stderr = _decode_bounded(err_chunks, err_overflow[0])
        duration_ms = int((time.monotonic() - started) * 1000)

        if cancelled:
            return NativeRunResult(
                ok=False,
                receipt=None,
                status="error",
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                error_code="NATIVE_CANCELLED",
                error_message="native task cancelled",
                memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
                peak_rss_bytes=peak_rss,
            )
        if memory_exceeded:
            receipt = {
                "protocolVersion": PROTOCOL_VERSION,
                "taskId": task_id,
                "operation": operation,
                "status": "error",
                "memoryEnforcement": MEMORY_ENFORCEMENT_SOFT,
                "peakRssBytes": peak_rss,
                "memoryBudgetBytes": memory_budget,
                "memoryLimitBytes": rss_limit,
                "error": {
                    "code": "NATIVE_MEMORY_BUDGET_EXCEEDED",
                    "message": (
                        f"child RSS {peak_rss} exceeded soft limit "
                        f"{rss_limit} (budget {memory_budget} × {memory_grace_factor})"
                    ),
                },
                "backend": {"name": "rust_native", "memoryEnforcement": MEMORY_ENFORCEMENT_SOFT},
                "recordsIn": 0,
                "recordsOut": 0,
                "bytesIn": 0,
                "bytesOut": 0,
                "durationMs": duration_ms,
                "spillBytes": 0,
            }
            return NativeRunResult(
                ok=False,
                receipt=receipt,
                status="error",
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                error_code="NATIVE_MEMORY_BUDGET_EXCEEDED",
                error_message=str(receipt["error"]["message"]),
                memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
                peak_rss_bytes=peak_rss,
            )
        if timed_out:
            return NativeRunResult(
                ok=False,
                receipt=None,
                status="error",
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                error_code="NATIVE_TIMEOUT",
                error_message=f"native task exceeded {timeout_seconds}s",
                memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
                peak_rss_bytes=peak_rss,
            )

        receipt: dict[str, Any] | None = None
        if receipt_path.is_file():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                receipt = None
        if receipt is None and stdout.strip():
            # Fallback: last JSON object on stdout
            for line in reversed(stdout.strip().splitlines()):
                try:
                    receipt = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        if not isinstance(receipt, dict):
            return NativeRunResult(
                ok=False,
                receipt=None,
                status="error",
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                error_code="NATIVE_RECEIPT_MISSING",
                error_message="receipt JSON missing or invalid",
                memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
                peak_rss_bytes=peak_rss,
            )

        issues = validate_receipt(receipt, task_id=task_id, operation=operation)
        if issues:
            return NativeRunResult(
                ok=False,
                receipt=receipt,
                status="error",
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                error_code="NATIVE_RECEIPT_INVALID",
                error_message="; ".join(issues),
                memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
                peak_rss_bytes=peak_rss,
            )

        ok = str(receipt.get("status")) == "ok" and proc.returncode == 0
        err = receipt.get("error") if isinstance(receipt.get("error"), dict) else {}
        # Annotate soft enforcement honesty on successful/error receipts.
        if "memoryEnforcement" not in receipt:
            receipt = {**receipt, "memoryEnforcement": MEMORY_ENFORCEMENT_SOFT}
        return NativeRunResult(
            ok=ok,
            receipt=receipt,
            status=str(receipt.get("status") or "error"),
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            error_code=str(err.get("code")) if err else None,
            error_message=str(err.get("message")) if err else None,
            memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
            peak_rss_bytes=peak_rss
            if peak_rss is not None
            else (int(receipt["peakRssBytes"]) if receipt.get("peakRssBytes") is not None else None),
        )
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def _terminate(proc: subprocess.Popen[Any], *, force: bool = False) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
    except OSError:
        pass
    if force:
        time.sleep(0.2)
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass


class NativeComputeRunner:
    """Allowlisted native data-plane runner used by DatasetService handlers.

    Python always verifies the receipt and content hash before atomic publish.
    Callers must not mark a derived version READY until metadata is committed.
    """

    def __init__(
        self,
        *,
        binary: Path | None = None,
        capabilities: NativeCapabilities | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.binary = binary
        self._capabilities = capabilities
        self.timeout_seconds = float(timeout_seconds)

    @property
    def available(self) -> bool:
        caps = self.capabilities()
        return caps.status == NativeStatus.AVAILABLE

    def capabilities(self) -> NativeCapabilities:
        if self._capabilities is None:
            self._capabilities = probe_capabilities(binary=self.binary)
        return self._capabilities

    def probe(self) -> dict[str, Any]:
        """Bounded Worker Fabric summary: status, binaryVersion, operations."""
        caps = self.capabilities()
        backend = caps.backend if isinstance(caps.backend, dict) else {}
        version = backend.get("version")
        return {
            "status": caps.status.value,
            "binaryVersion": str(version) if version is not None else None,
            "operations": list(caps.operations)[:64],
            "protocolVersion": caps.protocol_version,
            "detail": (caps.detail or "")[:500],
            "binaryPath": caps.binary_path,
        }

    def run(
        self,
        *,
        task_id: str,
        operation: str,
        input_path: str | Path,
        temporary_path: str | Path,
        limits: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        content_hash: str | None = None,
        allowed_roots: list[str] | None = None,
        input_format: str = "jsonl",
        cancel_event: threading.Event | None = None,
        work_dir: Path | None = None,
        rss_reader: Callable[[int], int | None] | None = None,
        memory_grace_factor: float = MEMORY_RSS_GRACE_FACTOR,
    ) -> NativeRunResult:
        task = build_task_document(
            task_id=task_id,
            operation=operation,
            input_path=input_path,
            temporary_path=temporary_path,
            limits=limits,
            options=options,
            content_hash=content_hash,
            allowed_roots=allowed_roots,
            input_format=input_format,
        )
        return run_native_task(
            task,
            binary=self.binary,
            timeout_seconds=self.timeout_seconds,
            cancel_event=cancel_event,
            work_dir=work_dir,
            rss_reader=rss_reader,
            memory_grace_factor=memory_grace_factor,
        )

    def verify_output(
        self,
        result: NativeRunResult,
        *,
        temporary_path: str | Path,
        expected_hash: str | None = None,
    ) -> dict[str, Any]:
        """Validate receipt + optional content hash of native temporary output."""
        from Data.modules.common.hashing import sha256_file

        if not result.ok or not isinstance(result.receipt, dict):
            return {
                "ok": False,
                "errorCode": result.error_code or "NATIVE_FAILED",
                "errorMessage": result.error_message or "native task failed",
            }
        path = Path(temporary_path)
        if not path.is_file():
            return {
                "ok": False,
                "errorCode": "NATIVE_OUTPUT_MISSING",
                "errorMessage": f"native temporary output missing: {path}",
            }
        digest = sha256_file(path)
        receipt_hash = result.receipt.get("contentHash") or result.receipt.get("outputContentHash")
        if receipt_hash and str(receipt_hash) != digest:
            return {
                "ok": False,
                "errorCode": "NATIVE_OUTPUT_HASH_MISMATCH",
                "errorMessage": "receipt contentHash does not match output file",
                "expected": str(receipt_hash),
                "actual": digest,
            }
        if expected_hash and expected_hash != digest:
            return {
                "ok": False,
                "errorCode": "NATIVE_OUTPUT_HASH_MISMATCH",
                "errorMessage": "expected content hash mismatch",
                "expected": expected_hash,
                "actual": digest,
            }
        return {
            "ok": True,
            "contentHash": digest,
            "byteSize": path.stat().st_size,
            "recordsOut": result.receipt.get("recordsOut"),
            "receipt": result.receipt,
        }


__all__ = [
    "BINARY_NAME",
    "MEMORY_ENFORCEMENT_SOFT",
    "MEMORY_RSS_GRACE_FACTOR",
    "PROTOCOL_VERSION",
    "PARQUET_OPERATIONS",
    "MARKET_OPERATIONS",
    "SUPPORTED_OPERATIONS",
    "NativeCapabilities",
    "NativeComputeRunner",
    "NativeRunResult",
    "NativeStatus",
    "build_task_document",
    "default_binary_candidates",
    "probe_capabilities",
    "read_process_rss_bytes",
    "resolve_native_binary",
    "run_native_task",
    "validate_receipt",
]
