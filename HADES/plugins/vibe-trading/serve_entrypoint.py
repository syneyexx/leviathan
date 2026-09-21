#!/usr/bin/env python3
"""Managed service entry for Vibe-Trading web UI (plugin venv)."""
from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("LANGCHAIN_PROVIDER", "openai")
    os.environ.setdefault(
        "LANGCHAIN_BASE_URL",
        os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
    )
    os.environ.setdefault("LANGCHAIN_API_KEY", os.environ.get("OPENAI_API_KEY", "lm-studio"))
    # Prefer console script module path from the installed package.
    from cli import main as vibe_main

    sys.argv = ["vibe-trading", "serve", "--host", "127.0.0.1", "--port", "8899"]
    result = vibe_main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())

