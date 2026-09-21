"""Resolve how the HADES Windows launcher should serve the frontend."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_frontend_mode(root: Path) -> str:
    """Return ``dev`` or ``production`` for the local frontend process."""

    explicit = os.environ.get("HADES_FRONTEND_MODE", "").strip().lower()
    if explicit == "dev":
        return "dev"
    if explicit == "production":
        return "production"
    dist_index = root / "dist" / "index.html"
    return "production" if dist_index.is_file() else "dev"


def frontend_shell_command(root: Path) -> list[str]:
    """Windows ``cmd /k`` command list to start the frontend on port 3000."""

    mode = resolve_frontend_mode(root)
    if mode == "production":
        return ["cmd", "/k", "npm run start"]
    return ["cmd", "/k", "npm run dev -- --host 127.0.0.1 --port 3000"]
