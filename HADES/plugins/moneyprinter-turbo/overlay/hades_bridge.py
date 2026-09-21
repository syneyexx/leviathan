#!/usr/bin/env python3
"""HADES helpers for MoneyPrinterTurbo (doctor + LM Studio config seed)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def doctor() -> dict:
    main_py = (ROOT / "main.py").is_file()
    webui = (ROOT / "webui" / "Main.py").is_file()
    config_example = (ROOT / "config.example.toml").is_file()
    ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    layout_ok = main_py and webui and config_example
    ok = bool(layout_ok and ffmpeg)
    payload = {
        "ok": ok,
        "root": str(ROOT),
        "main_py": main_py,
        "webui": webui,
        "cli": (ROOT / "cli.py").is_file(),
        "config_example": config_example,
        "config_toml": (ROOT / "config.toml").is_file(),
        "ffmpeg": bool(ffmpeg),
        "ui": "http://127.0.0.1:8501",
        "api_docs": "http://127.0.0.1:8080/docs",
        "notes": [
            "Prefer seed_lm_studio before start so script generation uses local models.",
            "Video generation still needs FFmpeg and a material source (pexels/local/etc).",
            "Network may be required for stock footage unless you use local materials.",
        ],
    }
    if not layout_ok:
        missing = [name for name, present in (("main.py", main_py), ("webui/Main.py", webui), ("config.example.toml", config_example)) if not present]
        payload["error"] = "missing_required_layout:" + ",".join(missing)
    elif not ffmpeg:
        payload["error"] = "ffmpeg_not_found"
    return payload


def seed_lm_studio(base_url: str, model: str, api_key: str) -> dict:
    """Create/update config.toml openai_* fields for LM Studio without wiping other keys."""
    model_name = (model or "").strip()
    base = (base_url or "").strip().rstrip("/")
    if not model_name:
        return {"ok": False, "error": "model_required"}
    if not base:
        return {"ok": False, "error": "base_url_required"}
    example = ROOT / "config.example.toml"
    target = ROOT / "config.toml"
    if not target.is_file():
        if not example.is_file():
            return {"ok": False, "error": "config.example.toml missing"}
        target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    text = target.read_text(encoding="utf-8")
    replacements = {
        "llm_provider": "openai",
        "openai_api_key": api_key or "lm-studio",
        "openai_base_url": base,
        "openai_model_name": model_name,
        "listen_host": "127.0.0.1",
    }
    lines = text.splitlines()
    out: list[str] = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in replacements:
            out.append(f'{key} = "{replacements[key]}"')
            seen.add(key)
        else:
            out.append(line)
    for key, value in replacements.items():
        if key not in seen:
            out.append(f'{key} = "{value}"')
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    written = target.read_text(encoding="utf-8")
    missing = [
        key
        for key, value in replacements.items()
        if f'{key} = "{value}"' not in written and f"{key} = '{value}'" not in written
    ]
    if missing:
        return {"ok": False, "error": "config_write_unverified:" + ",".join(missing), "config": str(target)}
    return {
        "ok": True,
        "config": str(target),
        "llm_provider": "openai",
        "openai_base_url": replacements["openai_base_url"],
        "openai_model_name": model_name,
        "listen_host": "127.0.0.1",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    s = sub.add_parser("seed_lm_studio")
    s.add_argument("--base-url", default=os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"))
    s.add_argument("--model", required=True)
    s.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "lm-studio"))
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    else:
        payload = seed_lm_studio(args.base_url, args.model, args.api_key)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
