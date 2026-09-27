"""Host-compatible process stdio for launcher-owned Python children.

``run_leviathan.exe`` starts ``leviathan.py`` with piped stdout/stderr and
Windows ``CREATE_NO_WINDOW``. Under that capture path, unguarded
``print(..., flush=True)`` / ``TextIO.flush()`` can raise::

    OSError: [Errno 22] Invalid argument

and tear down the Worker Supervisor (and any sibling bootstrap child) before
the fabric becomes healthy.

This module is the owner of that resilience:

1. Prefer UTF-8 with ``errors=replace`` so operator banners with Unicode reach
   the host GUI pipe instead of raising encode errors.
2. Harden ``write`` / ``flush`` so I/O failures never crash the runtime.
3. Keep successful writes flowing to the same host-captured handles.

It does **not** own paper-trading deployments, MarketSim, or trading lifecycle.
"""

from __future__ import annotations

import io
import sys
from typing import Any, TextIO

_HARDENED_FLAG = "_leviathan_host_stdio_hardened"
_INSTALLED = False


class DiscardTextIO(io.TextIOBase):
    """Stand-in when a stdio handle is missing (e.g. ``pythonw``)."""

    encoding = "utf-8"
    errors = "replace"
    name = "<leviathan-discard>"

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:  # type: ignore[override]
        if not isinstance(s, str):
            s = str(s)
        return len(s)

    def flush(self) -> None:
        return None


def safe_write_line(stream: TextIO[str] | Any | None, line: str = "") -> bool:
    """Write one operator line + flush. Never raises on broken host pipes.

    Returns True when the write+flush succeeded, False when the stream was
    missing or I/O failed (Errno 22 / broken pipe / closed handle).
    """
    if stream is None:
        return False
    if line == "":
        text = "\n"
    elif line.endswith("\n"):
        text = line
    else:
        text = f"{line}\n"
    try:
        stream.write(text)
        stream.flush()
        return True
    except (OSError, ValueError, BrokenPipeError):
        return False
    except Exception:  # noqa: BLE001 — never crash the fabric on log I/O
        return False


def _reconfigure_utf8(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError, AttributeError, TypeError):
        # Some wraps / closed streams reject reconfigure; write hardening still applies.
        return


def _harden_stream(stream: Any) -> Any:
    """Patch write/flush in place so fileno()/inheritance stay intact."""
    if stream is None:
        return DiscardTextIO()
    if getattr(stream, _HARDENED_FLAG, False):
        return stream

    _reconfigure_utf8(stream)

    orig_write = stream.write
    orig_flush = stream.flush

    def write(data: Any, *args: Any, **kwargs: Any) -> int:
        try:
            result = orig_write(data, *args, **kwargs)
            return int(result) if result is not None else 0
        except (OSError, ValueError, BrokenPipeError):
            try:
                return len(data) if hasattr(data, "__len__") else 0
            except Exception:  # noqa: BLE001
                return 0
        except Exception:  # noqa: BLE001
            return 0

    def flush(*args: Any, **kwargs: Any) -> None:
        try:
            orig_flush(*args, **kwargs)
        except (OSError, ValueError, BrokenPipeError):
            return None
        except Exception:  # noqa: BLE001
            return None

    try:
        stream.write = write  # type: ignore[method-assign]
        stream.flush = flush  # type: ignore[method-assign]
        setattr(stream, _HARDENED_FLAG, True)
    except Exception:  # noqa: BLE001 — immutable stream; callers still use safe_write_line
        return stream
    return stream


def install_host_compatible_stdio() -> dict[str, Any]:
    """Idempotent: harden ``sys.stdout`` / ``sys.stderr`` for host capture.

    Safe to call from ``leviathan.py``, bootstrap entry, and tests.
    """
    global _INSTALLED
    if getattr(sys, "stdout", None) is None:
        sys.stdout = DiscardTextIO()  # type: ignore[assignment]
    else:
        _harden_stream(sys.stdout)

    if getattr(sys, "stderr", None) is None:
        sys.stderr = DiscardTextIO()  # type: ignore[assignment]
    else:
        _harden_stream(sys.stderr)

    _INSTALLED = True
    return {
        "installed": True,
        "stdoutHardened": bool(getattr(sys.stdout, _HARDENED_FLAG, False))
        or isinstance(sys.stdout, DiscardTextIO),
        "stderrHardened": bool(getattr(sys.stderr, _HARDENED_FLAG, False))
        or isinstance(sys.stderr, DiscardTextIO),
        "encoding": getattr(sys.stdout, "encoding", None),
    }


def stdio_inheritance_kwargs() -> dict[str, Any]:
    """Popen kwargs so bootstrap siblings inherit the host-captured pipes.

    Passing explicit filenos avoids Windows CreateProcess inventing broken
    default handles when the parent was started under ``CREATE_NO_WINDOW``.
    """
    kwargs: dict[str, Any] = {"stdin": __import__("subprocess").DEVNULL}
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        target = getattr(stream, "buffer", stream)
        try:
            kwargs[name] = target.fileno()
        except (OSError, ValueError, AttributeError, io.UnsupportedOperation):
            # Leave unspecified → OS default inherit of the (possibly wrapped) handle.
            continue
    return kwargs


def host_stdio_installed() -> bool:
    return bool(_INSTALLED)
