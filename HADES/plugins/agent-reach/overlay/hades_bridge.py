#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shutil
import subprocess


def _bin() -> str:
    return shutil.which("agent-reach") or shutil.which("agent-reach.exe") or "agent-reach"


def run(args: list[str], timeout: int = 600) -> dict:
    command = [_bin(), *args]
    process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=False)
    return {
        "command": command,
        "exit_code": process.returncode,
        "stdout": (process.stdout or "")[-50_000:],
        "stderr": (process.stderr or "")[-50_000:],
    }


def doctor() -> dict:
    import cli_bridge
    payload = cli_bridge.doctor(["agent_reach"], ["agent-reach"])
    payload["cli"] = run(["doctor"], timeout=180)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    install = sub.add_parser("install_check")
    install.add_argument("--env", default="auto", choices=["auto", "local", "server"])
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
        nested = int((payload.get("cli") or {}).get("exit_code") or 0)
        if nested != 0:
            payload = {
                **payload,
                "ok": False,
                "error": payload.get("error") or f"agent-reach doctor exit {nested}",
                "exit_code": nested,
            }
        elif payload.get("ok") is False:
            payload = {
                **payload,
                "exit_code": int(payload.get("exit_code") or 2),
            }
        else:
            payload = {**payload, "ok": True, "exit_code": 0}
    else:
        # Safe check-only install path (no --system).
        payload = run(["install", f"--env={args.env}", "--safe", "--dry-run"], timeout=300)
        nested = int(payload.get("exit_code") or 0)
        stdout = str(payload.get("stdout") or "").strip()
        if nested != 0:
            payload = {
                **payload,
                "ok": False,
                "error": payload.get("error") or f"agent-reach install_check exit {nested}",
            }
        elif not stdout:
            payload = {
                **payload,
                "ok": False,
                "error": "agent-reach install_check produced empty output",
                "exit_code": 2,
            }
        else:
            payload = {**payload, "ok": True, "exit_code": 0}
    if payload.get("ok") is False and int(payload.get("exit_code") or 0) == 0:
        payload = {**payload, "exit_code": 2}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    ok = payload.get("ok", True) is not False
    code = int(payload.get("exit_code") or 0)
    return 0 if ok and code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
