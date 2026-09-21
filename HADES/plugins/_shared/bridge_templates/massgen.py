#!/usr/bin/env python3
"""Local multi-agent committee via LM Studio (MassGen-inspired). Fail closed without a model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    import lm_client
except ImportError:
    lm_client = None  # type: ignore

DEFAULT_ROLES = ["planner", "critic", "synthesizer"]


def doctor() -> dict:
    return {
        "ok": True,
        "python": sys.executable,
        "lm_client": lm_client is not None,
        "default_roles": DEFAULT_ROLES,
        "notes": [
            "Runs sequential local agents against LM Studio.",
            "Does not start the upstream MassGen TUI or cloud providers.",
        ],
    }


def run_committee(prompt: str, model: str, base_url: str, api_key: str, agents: str) -> dict:
    roles = [item.strip() for item in (agents or "").split(",") if item.strip()] or list(DEFAULT_ROLES)
    if lm_client is None:
        return {"ok": False, "error": "lm_client_missing"}
    transcript = []
    for role in roles:
        prior = "\n".join(f"{row['role']}: {row['content']}" for row in transcript)
        result = lm_client.chat(
            [
                {
                    "role": "system",
                    "content": f"You are the {role} in a local HADES committee. Be concrete. Do not claim tools you did not run.",
                },
                {"role": "user", "content": f"Task:\n{prompt}\n\nPrior committee notes:\n{prior or '(none)'}"},
            ],
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=90.0,
            max_tokens=900,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error"),
                "detail": result.get("detail") or result.get("hint"),
                "partial": transcript,
            }
        transcript.append({"role": role, "content": result["content"]})
    return {"ok": True, "model": model, "roles": roles, "transcript": transcript, "answer": transcript[-1]["content"] if transcript else ""}


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES MassGen-style committee")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    r = sub.add_parser("run_committee")
    r.add_argument("--prompt", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--base-url", default="")
    r.add_argument("--api-key", default="")
    r.add_argument("--agents", default="planner,critic,synthesizer")
    args = parser.parse_args()
    payload = doctor() if args.cmd == "doctor" else run_committee(
        args.prompt, args.model, args.base_url, args.api_key, args.agents
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
