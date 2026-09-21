#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import mcp_bridge


def server_command() -> list[str]:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("npx not found on PATH")
    return [npx, *["-y", "@wonderwhy-er/desktop-commander"]]


def doctor() -> dict:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    node = shutil.which("node") or shutil.which("node.exe")
    pkg = Path(__file__).resolve().parent / "package.json"
    ok = bool(npx) and bool(node)
    payload = {
        "ok": ok,
        "npx": npx,
        "node": node,
        "package_json": pkg.is_file(),
        "mcp_package": "@wonderwhy-er/desktop-commander",
        "notes": [
            "Requires Node.js + npx on PATH.",
            "Powerful host terminal/filesystem access — autonomous disabled in HADES.",
            "Live MCP session quality is UNVERIFIED_ON_HOST without Node network allowlist.",
        ],
    }
    if not ok:
        missing = [name for name, present in (("npx", npx), ("node", node)) if not present]
        payload["error"] = "missing_required:" + ",".join(missing)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=["doctor", "list_tools", "call_tool"])
    parser.add_argument("--tool", default="")
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    if args.action == "doctor":
        payload = doctor()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 2
    payload = mcp_bridge.run_session(
        server_command(),
        args.action,
        args.tool or None,
        args.arguments or None,
        args.timeout,
    )
    is_error = bool(payload.get("isError")) or bool(payload.get("error"))
    if args.action == "list_tools" and not (payload.get("tools") or []):
        payload = {**payload, "ok": False, "error": payload.get("error") or "empty_tools_list"}
        is_error = True
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if is_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
