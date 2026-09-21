#!/usr/bin/env python3
"""Static + optional LM Studio code review for HADES (Alibaba OpenCodeReview-inspired)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    import lm_client
except ImportError:
    lm_client = None  # type: ignore

LONG_LINE = 140
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
SECRET_RE = re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]+", re.I)
EVAL_RE = re.compile(r"\beval\s*\(|\bexec\s*\(|pickle\.loads\s*\(")
BARE_EXCEPT = re.compile(r"except\s*:")


def _read(path: str, max_chars: int) -> tuple[Path, str] | dict:
    source = Path(path).expanduser()
    if not source.is_file():
        return {"ok": False, "error": "file_not_found", "path": str(source)}
    text = source.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    return source, text[:max_chars] + ("\n… [truncated]" if truncated else "")


def review_static(path: str, max_chars: int) -> dict:
    loaded = _read(path, max_chars)
    if isinstance(loaded, dict):
        return loaded
    source, text = loaded
    findings = []
    for index, line in enumerate(text.splitlines(), start=1):
        if len(line) > LONG_LINE:
            findings.append({"line": index, "severity": "info", "rule": "long_line", "message": f"Line length {len(line)} > {LONG_LINE}."})
        if TODO_RE.search(line):
            findings.append({"line": index, "severity": "info", "rule": "todo", "message": line.strip()[:200]})
        if SECRET_RE.search(line):
            findings.append({"line": index, "severity": "high", "rule": "possible_secret", "message": "Possible credential assignment."})
        if EVAL_RE.search(line):
            findings.append({"line": index, "severity": "high", "rule": "dangerous_eval", "message": line.strip()[:200]})
        if BARE_EXCEPT.search(line):
            findings.append({"line": index, "severity": "medium", "rule": "bare_except", "message": "Bare except swallows errors."})
    return {
        "ok": True,
        "path": str(source),
        "mode": "static",
        "findings": findings[:80],
        "count": len(findings),
        "note": "Deterministic heuristics only. Not a substitute for a full LLM review.",
    }


def review_with_model(path: str, model: str, base_url: str, api_key: str, max_chars: int) -> dict:
    static = review_static(path, max_chars)
    if not static.get("ok"):
        return static
    if lm_client is None:
        return {**static, "ok": False, "error": "lm_client_missing"}
    source, text = _read(path, max_chars)  # type: ignore[misc]
    prompt = (
        "You are a code reviewer for a local HADES workspace. Return JSON with keys "
        "summary (string) and comments (array of {line, severity, message}). "
        "Be specific. Do not invent files. Static findings follow.\n\n"
        f"STATIC_FINDINGS:\n{json.dumps(static['findings'][:20])}\n\nCODE:\n{text}"
    )
    result = lm_client.chat(
        [
            {"role": "system", "content": "Review code. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout=90.0,
        max_tokens=1600,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error"),
            "detail": result.get("detail") or result.get("hint"),
            "static": static,
            "hint": "Static findings are still available via review_file. LM Studio is optional.",
        }
    return {
        "ok": True,
        "path": static["path"],
        "mode": "model+static",
        "model": model,
        "static_findings": static["findings"],
        "model_review": result.get("content"),
    }


def doctor() -> dict:
    return {
        "ok": True,
        "python": sys.executable,
        "lm_client": lm_client is not None,
        "notes": [
            "review_file always works offline.",
            "review_with_model needs a running LM Studio (or compatible) endpoint and a model id.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES code review")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    s = sub.add_parser("review_file")
    s.add_argument("--path", required=True)
    s.add_argument("--max-chars", type=int, default=24000)
    m = sub.add_parser("review_with_model")
    m.add_argument("--path", required=True)
    m.add_argument("--model", required=True)
    m.add_argument("--base-url", default="")
    m.add_argument("--api-key", default="")
    m.add_argument("--max-chars", type=int, default=24000)
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "review_file":
        payload = review_static(args.path, args.max_chars)
    else:
        payload = review_with_model(args.path, args.model, args.base_url, args.api_key, args.max_chars)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
