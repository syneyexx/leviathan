"""Central HADES application logging with correlation trace ids (T16/F-33)."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from errors.correlation import get_correlation

_LOG_FORMAT = "%(asctime)s %(levelname)s [trace_id=%(trace_id)s] %(name)s: %(message)s"
_CONFIGURED_FLAG = "_hades_logging_configured"
_DEFAULT_MAX_BYTES = 50 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5


class TraceIdFilter(logging.Filter):
    """Inject the active correlation trace_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_correlation()
        record.trace_id = ctx.trace_id if ctx is not None else "-"
        return True


def hades_log_path(data_root: Path | str) -> Path:
    return Path(data_root).expanduser().resolve() / "logs" / "hades.log"


def configure_hades_logging(
    data_root: Path | str,
    *,
    level: str | int | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
    force: bool = False,
) -> Path:
    """Install root FileHandler + stderr StreamHandler under ``data_root/logs``.

    Idempotent unless ``force=True``. Returns the primary log file path.
    """
    root = logging.getLogger()
    log_path = hades_log_path(data_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if getattr(root, _CONFIGURED_FLAG, False) and not force:
        return log_path

    resolved_level = _resolve_level(level)
    max_bytes = int(max_bytes if max_bytes is not None else _DEFAULT_MAX_BYTES)
    backup_count = int(backup_count if backup_count is not None else _DEFAULT_BACKUP_COUNT)

    formatter = logging.Formatter(_LOG_FORMAT)
    trace_filter = TraceIdFilter()

    # Drop prior HADES-owned handlers when forcing reconfigure (tests).
    if force:
        for handler in list(root.handlers):
            if getattr(handler, "_hades_owned", False):
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max(1024, max_bytes),
        backupCount=max(1, backup_count),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(trace_filter)
    file_handler._hades_owned = True  # type: ignore[attr-defined]

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(trace_filter)
    stream_handler._hades_owned = True  # type: ignore[attr-defined]

    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    root.setLevel(resolved_level)
    setattr(root, _CONFIGURED_FLAG, True)

    logging.getLogger("hades").info("hades_logging_configured path=%s level=%s", log_path, logging.getLevelName(resolved_level))
    return log_path


def _resolve_level(level: str | int | None) -> int:
    if level is None:
        env = os.environ.get("HADES_LOG_LEVEL", "INFO")
        level = env
    if isinstance(level, int):
        return level
    text = str(level).strip().upper()
    return int(getattr(logging, text, logging.INFO))


def find_trace_in_log(log_path: Path | str, trace_id: str, *, max_bytes: int = 2_000_000) -> bool:
    """Return True when ``trace_id`` appears in the log file (post-mortem helper/tests)."""
    path = Path(log_path)
    if not path.is_file() or not trace_id:
        return False
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        data = handle.read().decode("utf-8", errors="replace")
    return str(trace_id) in data


def logging_status(data_root: Path | str | None = None) -> dict[str, Any]:
    root = logging.getLogger()
    path = str(hades_log_path(data_root)) if data_root else None
    return {
        "configured": bool(getattr(root, _CONFIGURED_FLAG, False)),
        "level": logging.getLevelName(root.level),
        "log_path": path,
        "handler_count": len([h for h in root.handlers if getattr(h, "_hades_owned", False)]),
    }
