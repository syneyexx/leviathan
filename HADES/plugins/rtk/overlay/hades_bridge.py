#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path


def _candidates() -> list[Path]:
    root = Path(__file__).resolve().parent
    names = ["rtk", "rtk.exe"]
    rows = []
    for name in names:
        rows.extend(
            [
                root / "target" / "release" / name,
                root / "target" / "debug" / name,
            ]
        )
    which = shutil.which("rtk") or shutil.which("rtk.exe")
    if which:
        rows.append(Path(which))
    return rows


def resolve_bin() -> str:
    for path in _candidates():
        if path.is_file():
            return str(path)
    return "rtk"


def run(args: list[str], timeout: int = 120) -> dict:
    command = [resolve_bin(), *args]
    process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=False)
    return {
        "command": command,
        "exit_code": process.returncode,
        "stdout": (process.stdout or "")[-50_000:],
        "stderr": (process.stderr or "")[-50_000:],
    }


def doctor() -> dict:
    binary = resolve_bin()
    exists = Path(binary).is_file() or bool(shutil.which(binary))
    version = run(["--version"]) if exists else {"error": "rtk binary not found; run cargo build during plugin dependency install"}
    return {"binary": binary, "available": exists, "version": version}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("gain")
    r = sub.add_parser("run")
    r.add_argument("--args", nargs="*", default=[])
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
        if not payload.get("available"):
            payload = {**payload, "ok": False, "error": "rtk binary not found", "exit_code": 1}
        else:
            nested = int((payload.get("version") or {}).get("exit_code") or 0)
            if nested != 0:
                payload = {
                    **payload,
                    "ok": False,
                    "error": f"rtk --version exit {nested}",
                    "exit_code": nested,
                }
            else:
                payload = {**payload, "ok": True, "exit_code": 0}
    elif args.cmd == "gain":
        payload = run(["gain"])
        nested = int(payload.get("exit_code") or 0)
        stdout = str(payload.get("stdout") or "").strip()
        if nested != 0:
            payload = {**payload, "ok": False, "error": f"rtk gain exit {nested}"}
        elif not stdout:
            payload = {**payload, "ok": False, "error": "rtk gain produced empty output", "exit_code": 2}
        else:
            payload = {**payload, "ok": True, "exit_code": 0}
    else:
        if not args.args:
            raise SystemExit("provide RTK argv via --args")
        payload = run(list(args.args))
        nested = int(payload.get("exit_code") or 0)
        stdout = str(payload.get("stdout") or "").strip()
        if nested != 0:
            payload = {**payload, "ok": False, "error": f"rtk exit {nested}"}
        elif not stdout:
            payload = {**payload, "ok": False, "error": "rtk produced empty output", "exit_code": 2}
        else:
            payload = {**payload, "ok": True, "exit_code": nested}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("ok") is False:
        return int(payload.get("exit_code") or 2)
    return 0 if int(payload.get("exit_code") or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
