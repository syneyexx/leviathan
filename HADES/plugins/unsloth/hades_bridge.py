#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import platform
import sys

def doctor() -> dict:
    import cli_bridge
    payload = cli_bridge.doctor(["unsloth", "torch"], ["nvidia-smi"])
    payload["python_version"] = sys.version
    payload["machine"] = platform.machine()
    payload["notes"] = [
        "Unsloth fine-tuning needs a suitable GPU stack on most workloads.",
        "Prefer the official Unsloth Desktop app for interactive training on Windows.",
        "This HADES plugin exposes environment checks and import diagnostics.",
    ]
    return payload

def info() -> dict:
    import cli_bridge
    rows = {
        "unsloth": cli_bridge.module_status("unsloth"),
        "torch": cli_bridge.module_status("torch"),
    }
    ok = all(bool(row.get("available")) for row in rows.values())
    payload = {"ok": ok, **rows}
    if not ok:
        missing = [name for name, row in rows.items() if not row.get("available")]
        payload["error"] = "missing_modules:" + ",".join(missing)
    return payload

def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("info")
    args = parser.parse_args()
    payload = doctor() if args.cmd == "doctor" else info()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok", True) else 2

if __name__ == "__main__":
    raise SystemExit(main())

