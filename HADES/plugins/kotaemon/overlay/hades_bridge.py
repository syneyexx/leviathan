#!/usr/bin/env python3
"""HADES helpers for Kotaemon (doctor honesty)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def doctor() -> dict:
    app_py = (ROOT / "app.py").is_file()
    pyproject = (ROOT / "pyproject.toml").is_file()
    gradio_ok = False
    try:
        import importlib.util

        gradio_ok = importlib.util.find_spec("gradio") is not None
    except Exception:
        gradio_ok = False
    ok = bool(app_py and gradio_ok)
    payload = {
        "ok": ok,
        "app_py": app_py,
        "pyproject": pyproject,
        "gradio": gradio_ok,
        "ui": "http://127.0.0.1:7860",
        "notes": [
            "Dependency install uses upstream pyproject/libs.",
            "Configure local LLM providers inside the Kotaemon UI after start.",
        ],
    }
    if not app_py:
        payload["error"] = "app.py missing; Kotaemon layout is incomplete"
    elif not gradio_ok:
        payload["error"] = "gradio_not_importable"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    args = parser.parse_args()
    payload = doctor() if args.cmd == "doctor" else {}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
