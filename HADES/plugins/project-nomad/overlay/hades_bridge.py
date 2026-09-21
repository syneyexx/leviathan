#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def doctor() -> dict:
    compose = ROOT / "docker-compose.yml"
    alt = ROOT / "docker_compose.yaml"
    compose_present = compose.exists() or alt.exists()
    payload = {
        "ok": compose_present,
        "compose_present": compose_present,
        "compose_path": str(compose if compose.exists() else alt if alt.exists() else ""),
        "docs": [p.name for p in ROOT.glob("*.md")][:20],
        "warning": (
            "Full NOMAD install uses a privileged installer; HADES only packages docs/helpers — "
            "do not run sudo install from autonomous tools."
        ),
    }
    if not compose_present:
        payload["error"] = "docker-compose missing; plugin package is docs/helpers only"
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
