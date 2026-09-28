"""Worker crash forensics — bounded log tails, classification, retention.

Does not invent a second logging subsystem. Operates on per-generation worker
log files owned by ``process.spawn_worker_process``.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Bound memory: never read megabytes of crash logs into the supervisor.
_MAX_TAIL_BYTES = 16_384
_MAX_TAIL_LINES = 80
_MAX_SUMMARY_LEN = 240
_DEFAULT_MAX_FILES_PER_POOL = 40
_DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 3600
_DEFAULT_MAX_FILE_BYTES = 8 * 1024 * 1024

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(password\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(connection[_-]?string\s*[:=]\s*)\S+"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+"),
)

_EXCEPTION_LINE = re.compile(
    r"^([A-Za-z_][\w.]*(?:Error|Exception|Timeout|Interrupt|Failure))\s*:\s*(.*)$"
)
_TRACEBACK_FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+), in (.+)$')
_PHASE_MARKER = re.compile(r"(?i)\[?\s*phase\s*[:=]\s*([A-Z][A-Z0-9_]+)\]?")


@dataclass(frozen=True)
class CrashEvidence:
    error_code: str
    error_summary: str
    exception_type: str | None = None
    exception_message: str | None = None
    last_frame: str | None = None
    startup_phase: str | None = None
    startup_or_runtime: str = "runtime"
    crash_log_path: str | None = None
    tail_lines: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "error_summary": self.error_summary,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "last_frame": self.last_frame,
            "startup_phase": self.startup_phase,
            "startup_or_runtime": self.startup_or_runtime,
            "crash_log_path": self.crash_log_path,
        }


def redact_crash_text(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(r"\1***", out)
    return out


def generation_log_filename(
    *,
    pool_id: str,
    slot: int,
    worker_id: str,
    pid: int,
    started_at: float | None = None,
) -> str:
    """Unique immutable log identity for one worker process generation."""
    ts = datetime.fromtimestamp(
        started_at if started_at is not None else time.time(),
        tz=timezone.utc,
    ).strftime("%Y%m%dT%H%M%S")
    # Prefer the random suffix from worker_id (pool-slot-suffix).
    suffix = worker_id
    parts = worker_id.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) >= 6:
        suffix = f"{pool_id}-{slot}-{parts[1]}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", suffix)
    return f"{safe}-pid{int(pid)}-{ts}.log"


def retain_pool_logs(
    pool_dir: Path,
    *,
    max_files: int = _DEFAULT_MAX_FILES_PER_POOL,
    max_age_seconds: float = _DEFAULT_MAX_AGE_SECONDS,
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> list[str]:
    """Bounded retention per pool directory. Returns deleted paths."""
    if not pool_dir.is_dir():
        return []
    deleted: list[str] = []
    now = time.time()
    files = sorted(
        (p for p in pool_dir.iterdir() if p.is_file() and p.suffix == ".log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for idx, path in enumerate(files):
        try:
            st = path.stat()
        except OSError:
            continue
        too_old = (now - st.st_mtime) > float(max_age_seconds)
        too_many = idx >= int(max_files)
        too_big = st.st_size > int(max_file_bytes) and idx > 0
        if too_old or too_many or too_big:
            try:
                path.unlink(missing_ok=True)
                deleted.append(str(path))
            except OSError:
                pass
    return deleted


def read_crash_tail(log_path: Path | str | None, *, max_bytes: int = _MAX_TAIL_BYTES) -> str:
    if not log_path:
        return ""
    path = Path(log_path)
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(max(0, size - max_bytes))
            raw = handle.read(max_bytes)
        text = raw.decode("utf-8", errors="replace")
        # Drop partial first line after seek.
        if size > max_bytes and "\n" in text:
            text = text.split("\n", 1)[1]
        return redact_crash_text(text)
    except OSError:
        return ""


def classify_crash_text(
    text: str,
    *,
    exit_code: int | None = None,
    default_phase: str | None = None,
) -> CrashEvidence:
    """Deterministic classification from evidence only — never invent SQLITE from exit=1."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()][-_MAX_TAIL_LINES:]
    exception_type: str | None = None
    exception_message: str | None = None
    last_frame: str | None = None
    phase = default_phase

    for line in lines:
        frame = _TRACEBACK_FRAME.match(line)
        if frame:
            last_frame = f"{frame.group(1)}:{frame.group(2)} in {frame.group(3)}"
            continue
        phase_m = _PHASE_MARKER.search(line)
        if phase_m:
            phase = phase_m.group(1)
            continue
        exc = _EXCEPTION_LINE.match(line.strip())
        if exc:
            exception_type = exc.group(1)
            exception_message = redact_crash_text(exc.group(2).strip())[:_MAX_SUMMARY_LEN]

    # Also scan joined text for common fingerprints when traceback formatting differs.
    lowered = text.lower()
    error_code = "UNCLASSIFIED_EXIT"
    if exception_type:
        et = exception_type.rsplit(".", 1)[-1]
        msg = (exception_message or "").lower()
        if et in {"ImportError", "ModuleNotFoundError"} or "no module named" in msg:
            error_code = "IMPORT_ERROR"
        elif et in {"OperationalError"} and ("locked" in msg or "busy" in msg):
            error_code = "DATABASE_LOCKED"
        elif et in {"OperationalError", "DatabaseError"} and (
            "no such table" in msg or "schema" in msg or "migrate" in msg
        ):
            error_code = "DATABASE_SCHEMA_ERROR"
        elif et in {"OperationalError"} and ("locked" in lowered or "busy" in lowered):
            error_code = "DATABASE_LOCKED"
        elif et in {"ConfigError", "ValueError", "TypeError"} and "config" in msg:
            error_code = "CONFIG_ERROR"
        elif "protocol" in msg or "incompatible" in msg:
            error_code = "PROTOCOL_ERROR"
        elif et in {"FileNotFoundError", "PermissionError"}:
            error_code = "DEPENDENCY_ERROR"
        else:
            error_code = "UNHANDLED_EXCEPTION"
    elif exit_code not in (None, 0):
        if "importerror" in lowered or "modulenotfounderror" in lowered:
            error_code = "IMPORT_ERROR"
        elif "database is locked" in lowered or "database table is locked" in lowered:
            error_code = "DATABASE_LOCKED"
        elif "no such table" in lowered:
            error_code = "DATABASE_SCHEMA_ERROR"
        else:
            error_code = "PROCESS_EXIT_NONZERO"

    summary_parts: list[str] = []
    if exception_type:
        summary_parts.append(exception_type)
    if exception_message:
        summary_parts.append(exception_message)
    if not summary_parts:
        if exit_code not in (None, 0):
            summary_parts.append(f"exit={exit_code}")
        else:
            summary_parts.append("no crash detail captured")
    error_summary = sanitize_summary(" — ".join(summary_parts))

    startup_markers = (
        "BOOTSTRAP",
        "LOADING_CONFIG",
        "OPENING_CONTROL_DB",
        "INITIALIZING_",
        "REGISTERING",
        "PROCESS_SPAWNED",
    )
    startup_or_runtime = "runtime"
    if phase and any(phase.startswith(m) or m in phase for m in startup_markers):
        startup_or_runtime = "startup"
    elif any(m.lower() in lowered for m in ("during worker bootstrap", "startup phase")):
        startup_or_runtime = "startup"

    return CrashEvidence(
        error_code=error_code,
        error_summary=error_summary,
        exception_type=exception_type,
        exception_message=exception_message,
        last_frame=last_frame,
        startup_phase=phase,
        startup_or_runtime=startup_or_runtime,
        tail_lines=tuple(lines[-12:]),
    )


def analyze_worker_crash(
    *,
    log_path: Path | str | None,
    exit_code: int | None,
    default_phase: str | None = None,
) -> CrashEvidence:
    text = read_crash_tail(log_path)
    evidence = classify_crash_text(
        text,
        exit_code=exit_code,
        default_phase=default_phase,
    )
    return CrashEvidence(
        error_code=evidence.error_code,
        error_summary=evidence.error_summary,
        exception_type=evidence.exception_type,
        exception_message=evidence.exception_message,
        last_frame=evidence.last_frame,
        startup_phase=evidence.startup_phase,
        startup_or_runtime=evidence.startup_or_runtime,
        crash_log_path=str(log_path) if log_path else None,
        tail_lines=evidence.tail_lines,
    )


def sanitize_summary(value: str, *, max_len: int = _MAX_SUMMARY_LEN) -> str:
    text = redact_crash_text(" ".join(str(value).split()))
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text
