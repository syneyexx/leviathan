#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess

def doctor() -> dict:
    import cli_bridge
    payload = cli_bridge.doctor(["composio"], ["composio"])
    payload["has_api_key"] = bool(os.environ.get("COMPOSIO_API_KEY"))
    # Do not force ok=True — inherit module/binary honesty from cli_bridge.doctor.
    return payload

def list_toolkits(query: str = "", limit: int = 30) -> dict:
    # Prefer CLI when present; fall back to SDK listing hints.
    binary = shutil.which("composio") or shutil.which("composio.exe")
    if binary:
        process = subprocess.run([binary, "apps"], capture_output=True, text=True, timeout=120, shell=False)
        text = (process.stdout or "") + "\n" + (process.stderr or "")
        lines = [line for line in text.splitlines() if line.strip()]
        if query:
            q = query.lower()
            lines = [line for line in lines if q in line.lower()]
        if process.returncode != 0:
            return {
                "ok": False,
                "source": "cli",
                "exit_code": process.returncode,
                "items": lines[:limit],
                "error": f"composio apps exit {process.returncode}",
            }
        if not lines:
            return {
                "ok": False,
                "source": "cli",
                "exit_code": 0,
                "items": [],
                "error": "composio apps returned empty toolkit list",
            }
        return {"ok": True, "source": "cli", "exit_code": 0, "items": lines[:limit]}
    try:
        from composio import Composio  # type: ignore  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "source": "sdk",
            "error": str(exc),
            "items": [],
            "hint": "Set COMPOSIO_API_KEY and reinstall plugin deps.",
        }
    # CLI missing and SDK import alone cannot list toolkits here.
    return {
        "ok": False,
        "source": "sdk",
        "items": [],
        "error": "CLI unavailable; configure COMPOSIO_API_KEY and use Composio dashboard/docs for toolkit IDs.",
        "has_api_key": bool(os.environ.get("COMPOSIO_API_KEY")),
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    lst = sub.add_parser("list_toolkits")
    lst.add_argument("--query", default="")
    lst.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok", True) else 2
    payload = list_toolkits(args.query, args.limit)
    print(json.dumps(payload, indent=2))
    if payload.get("ok") is False:
        return 1
    return 0 if int(payload.get("exit_code") or 0) == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
