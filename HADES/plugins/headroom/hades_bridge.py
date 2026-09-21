#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path


def doctor() -> dict:
    import cli_bridge
    payload = cli_bridge.doctor(["headroom"], ["headroom"])
    payload["notes"] = [
        "Use compress for one-shot message compression.",
        "Use start to run the local Headroom proxy (default 127.0.0.1:8787).",
    ]
    return payload


def compress(path: str, model: str, max_chars: int) -> dict:
    from headroom import compress as headroom_compress
    source = Path(path)
    if not source.is_file():
        raise SystemExit(f"input file not found: {path}")
    text = source.read_text(encoding="utf-8", errors="replace")
    messages = [{"role": "user", "content": text}]
    result = headroom_compress(messages, model=model or "gpt-4o")
    empty = result is None or result == {} or result == [] or result == ""
    if isinstance(result, dict):
        payload = result
        # Treat null-only wrappers as empty compressions.
        if set(payload.keys()) == {"result"} and payload.get("result") is None:
            empty = True
    else:
        payload = {"result": result}
    rendered = json.dumps(payload, ensure_ascii=False)
    out = {
        "ok": not empty,
        "input": str(source),
        "model": model or "gpt-4o",
        "input_chars": len(text),
        "output_chars": len(rendered),
        "truncated": len(rendered) > max_chars,
        "compressed": rendered[:max_chars],
    }
    if empty:
        out["error"] = "empty compress result"
    return out


def headroom_bin() -> str:
    return shutil.which("headroom") or shutil.which("headroom.exe") or "headroom"


def cli(args: list[str], timeout: int = 120) -> dict:
    command = [headroom_bin(), *args]
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
    c = sub.add_parser("compress")
    c.add_argument("--path", required=True)
    c.add_argument("--model", default="gpt-4o")
    c.add_argument("--max-chars", type=int, default=20000)
    p = sub.add_parser("proxy")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", default="8787")
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 2
    if args.cmd == "proxy":
        # Exec-style service entry used by the managed start tool.
        command = [headroom_bin(), "proxy", "--host", args.host, "--port", str(args.port)]
        raise SystemExit(subprocess.call(command))
    payload = compress(args.path, args.model, args.max_chars)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # Honor compress() ok flag — "{}" dumps are non-empty strings but still empty results.
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

