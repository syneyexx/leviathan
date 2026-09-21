#!/usr/bin/env python3
"""Small CLI helpers shared by slim HADES plugin wrappers."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path


def which_many(names: list[str]) -> dict[str, str | None]:
    return {name: shutil.which(name) or shutil.which(name + ".cmd") for name in names}


def module_status(module_name: str) -> dict:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return {"module": module_name, "available": False}
    try:
        mod = importlib.import_module(module_name)
        version = getattr(mod, "__version__", None)
    except Exception as exc:  # noqa: BLE001 - report import failures to the operator
        return {"module": module_name, "available": False, "error": str(exc)}
    return {"module": module_name, "available": True, "version": version, "file": getattr(mod, "__file__", None)}




def doctor(modules: list[str], binaries: list[str]) -> dict:
    module_rows = [module_status(name) for name in modules]
    binary_rows = which_many(binaries)
    missing_modules = [row["module"] for row in module_rows if not row.get("available")]
    # Binaries are advisory when listed as alternatives (e.g. python/python3); only fail when
    # every requested binary is absent.
    missing_all_binaries = bool(binaries) and not any(binary_rows.values())
    ok = not missing_modules and not missing_all_binaries
    payload = {
        "ok": ok,
        "python": sys.executable,
        "platform": sys.platform,
        "modules": module_rows,
        "binaries": binary_rows,
        "cwd": str(Path.cwd()),
        "env_hints": {
            "COMPOSIO_API_KEY": bool(os.environ.get("COMPOSIO_API_KEY")),
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
        },
    }
    if missing_modules:
        payload["error"] = "missing_modules:" + ",".join(missing_modules)
    elif missing_all_binaries:
        payload["error"] = "missing_binaries:" + ",".join(binaries)
    return payload



def main() -> int:
    parser = argparse.ArgumentParser(description="HADES CLI bridge helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor")
    p_doctor.add_argument("--modules", default="")
    p_doctor.add_argument("--binaries", default="")

    p_module = sub.add_parser("module-status")
    p_module.add_argument("--name", required=True)

    args = parser.parse_args()
    if args.cmd == "doctor":
        modules = [item.strip() for item in args.modules.split(",") if item.strip()]
        binaries = [item.strip() for item in args.binaries.split(",") if item.strip()]
        payload = doctor(modules, binaries)
    else:
        payload = module_status(args.name)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.cmd == "doctor":
        return 0 if payload.get("ok", True) else 2
    return 0 if payload.get("available", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
