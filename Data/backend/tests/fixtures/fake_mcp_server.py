#!/usr/bin/env python3
"""Deterministic fake MCP server for stdio protocol tests.

Speaks newline-delimited JSON-RPC on stdin/stdout.
Modes via argv:
  --mode=normal|malformed|slow|exit_after_init|flood_stderr|many_tools|echo
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def write(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def read() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--tool-count", type=int, default=2)
    args = parser.parse_args()

    initialized = False
    while True:
        raw = sys.stdin.readline()
        if not raw:
            break
        if args.mode == "malformed" and initialized:
            sys.stdout.write("{not-json\n")
            sys.stdout.flush()
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        req_id = msg.get("id")

        if method == "initialize":
            if args.mode == "exit_after_init":
                write(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "fake-mcp", "version": "0.0.1"},
                        },
                    }
                )
                return 0
            write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {"name": "fake-mcp", "version": "1.0.0"},
                    },
                }
            )
            initialized = True
            continue

        if method == "notifications/initialized":
            if args.mode == "flood_stderr":
                sys.stderr.write("x" * 200_000)
                sys.stderr.flush()
            continue

        if method == "tools/list":
            if args.delay:
                time.sleep(args.delay)
            tools = []
            count = args.tool_count if args.mode == "many_tools" else 2
            for i in range(count):
                tools.append(
                    {
                        "name": f"echo_{i}" if count > 2 else ("echo" if i == 0 else "add"),
                        "description": f"tool {i}",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "a": {"type": "number"},
                                "b": {"type": "number"},
                            },
                        },
                        "annotations": {"readOnlyHint": True} if i == 0 else {},
                    }
                )
            # Inject one invalid tool when normal — should be skipped best-effort.
            if args.mode == "normal":
                tools.append({"description": "missing name"})
            write({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})
            continue

        if method == "tools/call":
            if args.mode == "slow" or args.delay:
                time.sleep(args.delay or 2.0)
            params = msg.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "add":
                value = float(arguments.get("a") or 0) + float(arguments.get("b") or 0)
                content = [{"type": "text", "text": str(value)}]
            else:
                content = [{"type": "text", "text": str(arguments.get("text") or "pong")}]
            write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": content, "isError": False},
                }
            )
            continue

        if req_id is not None:
            write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
