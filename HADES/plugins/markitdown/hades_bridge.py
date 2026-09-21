#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

def convert(path: str, output: str | None) -> dict:
    from markitdown import MarkItDown
    source = Path(path)
    if not source.is_file():
        raise SystemExit(f"input file not found: {path}")
    md = MarkItDown()
    result = md.convert(str(source))
    text = result.text_content or ""
    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return {"input": str(source), "output": output, "chars": len(text), "markdown": text[:20000], "truncated": len(text) > 20000}

def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--path", required=True)
    c.add_argument("--output", default="")
    d = sub.add_parser("doctor")
    args = parser.parse_args()
    if args.cmd == "doctor":
        import cli_bridge
        payload = cli_bridge.doctor(["markitdown"], ["markitdown"])
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok", True) else 2
    payload = convert(args.path, args.output or None)
    if not str(payload.get("markdown") or "").strip() and int(payload.get("chars") or 0) == 0:
        payload = {**payload, "ok": False, "error": "conversion produced empty markdown"}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

