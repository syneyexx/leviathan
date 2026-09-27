"""Host-compatible stdio — Windows CREATE_NO_WINDOW / Errno 22 resilience."""

from __future__ import annotations

import io
import unittest

from Data.modules.common.process_stdio import (
    DiscardTextIO,
    install_host_compatible_stdio,
    safe_write_line,
    stdio_inheritance_kwargs,
)
from Data.modules.workers.console import print_startup_banner


class _BrokenFlushStream(io.StringIO):
    """Simulates Windows host-capture flush → OSError [Errno 22]."""

    def flush(self) -> None:
        raise OSError(22, "Invalid argument")


class _BrokenWriteStream(io.StringIO):
    def write(self, s: str) -> int:  # type: ignore[override]
        raise OSError(22, "Invalid argument")


class ProcessStdioHostCompatTests(unittest.TestCase):
    def test_safe_write_line_survives_errno_22_flush(self) -> None:
        stream = _BrokenFlushStream()
        self.assertFalse(safe_write_line(stream, "LEVIA THAN banner"))
        # write still happened before flush failure
        self.assertIn("banner", stream.getvalue())

    def test_safe_write_line_survives_errno_22_write(self) -> None:
        stream = _BrokenWriteStream()
        self.assertFalse(safe_write_line(stream, "should not crash"))

    def test_console_banner_does_not_raise_on_broken_stream(self) -> None:
        from pathlib import Path

        stream = _BrokenFlushStream()
        # Must not propagate OSError — this is the NORMAL-mode crash site.
        print_startup_banner(
            install_root=Path("/tmp/leviathan"),
            database_path=Path("/tmp/control.db"),
            stream=stream,
        )
        self.assertIn("LEVIATHAN EXTERNAL EXECUTION FABRIC", stream.getvalue())

    def test_harden_stream_write_flush_in_place(self) -> None:
        stream = _BrokenFlushStream()
        # Use install path via temporary assignment.
        import sys

        old_out = sys.stdout
        try:
            sys.stdout = stream  # type: ignore[assignment]
            info = install_host_compatible_stdio()
            self.assertTrue(info["installed"])
            # Hardened flush must swallow Errno 22.
            sys.stdout.write("hello-host\n")
            sys.stdout.flush()
        finally:
            sys.stdout = old_out

    def test_discard_stand_in(self) -> None:
        d = DiscardTextIO()
        self.assertEqual(d.write("x"), 1)
        d.flush()

    def test_stdio_inheritance_kwargs_shape(self) -> None:
        kwargs = stdio_inheritance_kwargs()
        self.assertIn("stdin", kwargs)
        # stdout/stderr present when current process has real filenos.
        self.assertTrue(isinstance(kwargs, dict))


if __name__ == "__main__":
    unittest.main()
