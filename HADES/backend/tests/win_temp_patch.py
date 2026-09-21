"""Windows-safe TemporaryDirectory defaults for backend unittest discovery."""

from __future__ import annotations

import os
import tempfile

_OrigTemporaryDirectory = tempfile.TemporaryDirectory


class WindowsSafeTemporaryDirectory(_OrigTemporaryDirectory):
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if os.name == "nt":
            kwargs.setdefault("ignore_cleanup_errors", True)
        super().__init__(*args, **kwargs)


def install() -> None:
    tempfile.TemporaryDirectory = WindowsSafeTemporaryDirectory  # type: ignore[misc, assignment]


install()
