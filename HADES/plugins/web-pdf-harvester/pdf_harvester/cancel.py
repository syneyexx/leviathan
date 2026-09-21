"""Cooperative cancellation for long crawls/downloads."""

from __future__ import annotations

import signal
import threading
from pathlib import Path


class CancelToken:
    def __init__(self, flag_path: Path | None = None) -> None:
        self._event = threading.Event()
        self.flag_path = flag_path
        self._installed = False

    def cancel(self, reason: str = "cancelled") -> None:
        self._reason = reason
        self._event.set()
        if self.flag_path is not None:
            try:
                self.flag_path.parent.mkdir(parents=True, exist_ok=True)
                self.flag_path.write_text(reason, encoding="utf-8")
            except OSError:
                pass

    @property
    def reason(self) -> str:
        return getattr(self, "_reason", "cancelled")

    def is_cancelled(self) -> bool:
        if self._event.is_set():
            return True
        if self.flag_path is not None and self.flag_path.exists():
            self._event.set()
            try:
                self._reason = self.flag_path.read_text(encoding="utf-8").strip() or "cancelled"
            except OSError:
                self._reason = "cancelled"
            return True
        return False

    def clear(self) -> None:
        self._event.clear()
        if self.flag_path is not None and self.flag_path.exists():
            try:
                self.flag_path.unlink()
            except OSError:
                pass

    def install_signal_handlers(self) -> None:
        if self._installed:
            return

        def _handler(signum, frame) -> None:  # noqa: ANN001
            self.cancel(f"signal:{signum}")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                # Not in main thread or unsupported
                pass
        self._installed = True
