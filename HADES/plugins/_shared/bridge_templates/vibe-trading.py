#!/usr/bin/env python3
"""HADES bridge for Vibe-Trading (doctor, research CLI, MCP list/call)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys


def _resolve_binary(names: list[str]) -> str | None:
    for name in names:
        found = shutil.which(name) or shutil.which(name + ".exe")
        if found:
            return found
    return None


def _binary() -> str | None:
    return _resolve_binary(["vibe-trading", "vibe_trading"])


def _mcp_binary() -> str | None:
    return _resolve_binary(["vibe-trading-mcp", "vibe_trading_mcp"])


def doctor() -> dict:
    import cli_bridge

    payload = cli_bridge.doctor(["vibe_trading"], ["vibe-trading", "vibe-trading-mcp"])
    cli = _binary()
    mcp = _mcp_binary()
    module_ok = any(bool(row.get("available")) for row in (payload.get("modules") or []))
    cli_ok = bool(cli)
    ok = bool(module_ok or cli_ok)
    payload["ok"] = ok
    payload["cli"] = cli
    payload["mcp"] = mcp
    payload["cli_present"] = cli_ok
    payload["mcp_present"] = bool(mcp)
    payload["ui"] = "http://127.0.0.1:8899"
    payload["notes"] = [
        "Configure LLM provider for local LM Studio via env before research runs:",
        "  LANGCHAIN_PROVIDER=openai LANGCHAIN_BASE_URL=http://127.0.0.1:1234/v1 LANGCHAIN_API_KEY=lm-studio",
        "  LANGCHAIN_MODEL=<dynamic model id from LM Studio>",
        "start launches the FastAPI web UI; MCP tools are available via list_tools/call_tool (research-only).",
        "No live order placement is exposed through the HADES MCP bridge.",
    ]
    if not ok:
        payload["error"] = "vibe-trading module/CLI missing"
    return payload


def _env() -> dict:
    env = os.environ.copy()
    env.setdefault("LANGCHAIN_PROVIDER", "openai")
    env.setdefault(
        "LANGCHAIN_BASE_URL",
        os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
    )
    env.setdefault("LANGCHAIN_API_KEY", os.environ.get("OPENAI_API_KEY", "lm-studio"))
    return env


def research(prompt: str, timeout: int) -> dict:
    if not prompt.strip():
        raise SystemExit("prompt is required")
    binary = _binary()
    if not binary:
        return {
            "ok": False,
            "error": "vibe-trading CLI not found on PATH",
            "exit_code": 127,
            "stdout": "",
            "stderr": "",
        }
    command = [binary, "run", "-p", prompt]
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        env=_env(),
    )
    return {
        "command": command,
        "exit_code": process.returncode,
        "stdout": (process.stdout or "")[-40_000:],
        "stderr": (process.stderr or "")[-20_000:],
    }


def serve() -> dict:
    """Foreground serve helper used only for doctor diagnostics — managed start uses argv below."""
    binary = _binary()
    if not binary:
        return {"ok": False, "error": "vibe-trading CLI not found on PATH", "cli": None}
    return {"ok": True, "command": [binary, "serve", "--host", "127.0.0.1", "--port", "8899"], "cli": binary}


def mcp_action(action: str, tool: str, arguments: str, timeout: float) -> dict:
    import mcp_bridge

    mcp = _mcp_binary()
    if not mcp:
        return {"ok": False, "isError": True, "error": "vibe-trading-mcp not found on PATH"}
    # Apply local LLM defaults into process env for the MCP child.
    os.environ.update({k: v for k, v in _env().items() if k.startswith("LANGCHAIN_")})
    return mcp_bridge.run_session(
        [mcp],
        action,
        tool or None,
        arguments or None,
        timeout,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("serve")
    r = sub.add_parser("research")
    r.add_argument("--prompt", required=True)
    r.add_argument("--timeout", type=int, default=600)
    m = sub.add_parser("mcp")
    m.add_argument("--action", required=True, choices=["list_tools", "call_tool"])
    m.add_argument("--tool", default="")
    m.add_argument("--arguments", default="{}")
    m.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 2
    if args.cmd == "serve":
        payload = serve()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 2
    if args.cmd == "research":
        payload = research(args.prompt, args.timeout)
        nested = int(payload.get("exit_code") or 0)
        stdout = str(payload.get("stdout") or "")
        if nested != 0:
            payload = {**payload, "ok": False, "error": payload.get("error") or f"vibe-trading exit {nested}"}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 1
        if not stdout.strip():
            payload = {**payload, "ok": False, "error": "empty research stdout"}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    payload = mcp_action(args.action, args.tool, args.arguments, args.timeout)
    is_error = bool(payload.get("isError")) or bool(payload.get("error")) or payload.get("ok") is False
    if args.action == "list_tools" and not (payload.get("tools") or []):
        payload = {**payload, "ok": False, "error": payload.get("error") or "empty_tools_list"}
        is_error = True
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if is_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
