#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

def _graphrag_bin() -> str:
    return shutil.which("graphrag") or "graphrag"

def run(args: list[str], timeout: int = 600) -> dict:
    command = [_graphrag_bin(), *args]
    process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=False)
    return {
        "command": command,
        "exit_code": process.returncode,
        "stdout": (process.stdout or "")[-50_000:],
        "stderr": (process.stderr or "")[-50_000:],
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    init = sub.add_parser("init")
    init.add_argument("--root", required=True)
    index = sub.add_parser("index")
    index.add_argument("--root", required=True)
    query = sub.add_parser("query")
    query.add_argument("--root", required=True)
    query.add_argument("--method", default="local")
    query.add_argument("--query", required=True)
    args = parser.parse_args()
    if args.cmd == "doctor":
        import cli_bridge
        payload = cli_bridge.doctor(["graphrag"], ["graphrag"])
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok", True) else 2
    if args.cmd == "init":
        Path(args.root).mkdir(parents=True, exist_ok=True)
        payload = run(["init", "--root", args.root])
    elif args.cmd == "index":
        payload = run(["index", "--root", args.root], timeout=3600)
    else:
        payload = run(["query", "--root", args.root, "--method", args.method, "--query", args.query], timeout=600)
    nested = int(payload.get("exit_code") or 0)
    stdout = str(payload.get("stdout") or "")
    if nested != 0:
        payload = {**payload, "ok": False, "error": f"graphrag exit {nested}"}
    elif not stdout.strip():
        # Empty stdout with exit 0 is not proof of successful init/index/query work.
        payload = {
            **payload,
            "ok": False,
            "error": f"empty graphrag {args.cmd} result",
            "exit_code": 2,
        }
        nested = 2
    else:
        payload = {**payload, "ok": True}
    print(json.dumps(payload, indent=2))
    return 0 if nested == 0 else (2 if nested == 2 else 1)

if __name__ == "__main__":
    raise SystemExit(main())
