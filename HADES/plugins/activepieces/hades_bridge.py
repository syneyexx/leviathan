#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def doctor() -> dict:
    docker = shutil.which("docker") or shutil.which("docker.exe")
    compose = ROOT / "docker-compose.yml"
    compose_present = compose.is_file()
    ok = bool(docker) and compose_present
    payload = {
        "ok": ok,
        "docker": docker,
        "compose_file": "docker-compose.yml",
        "compose_present": compose_present,
        "compose_path": str(compose) if compose_present else "",
        "hint": (
            "Prefer official Activepieces docker compose; HADES start uses docker compose up "
            "when Docker is available."
        ),
    }
    if not ok:
        missing = []
        if not docker:
            missing.append("docker")
        if not compose_present:
            missing.append("docker-compose.yml")
        payload["error"] = "missing_required:" + ",".join(missing)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    args = parser.parse_args()
    payload = doctor() if args.cmd == "doctor" else {}
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
