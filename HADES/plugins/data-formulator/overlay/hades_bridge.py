#!/usr/bin/env python3
"""Offline CSV → chart/table formulation for HADES (Data Formulator-inspired)."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from html import escape
from pathlib import Path


def _load_csv(path: str, max_rows: int) -> dict:
    source = Path(path).expanduser()
    if not source.is_file():
        return {"ok": False, "error": "file_not_found", "path": str(source)}
    with source.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return {"ok": False, "error": "no_header", "path": str(source)}
        rows = []
        for index, row in enumerate(reader):
            if index >= max_rows:
                break
            rows.append({str(k): ("" if v is None else str(v)) for k, v in row.items()})
    return {"ok": True, "path": str(source.resolve()), "columns": list(reader.fieldnames), "rows": rows, "count": len(rows)}


def _numeric(values: list[str]) -> list[float]:
    out = []
    for item in values:
        try:
            out.append(float(item.replace(",", "")))
        except ValueError:
            continue
    return out


def summarize(path: str, max_rows: int) -> dict:
    loaded = _load_csv(path, max_rows)
    if not loaded.get("ok"):
        return loaded
    columns = []
    for name in loaded["columns"]:
        values = [row.get(name, "") for row in loaded["rows"]]
        nums = _numeric(values)
        info = {"name": name, "filled": sum(1 for v in values if str(v).strip()), "numeric": len(nums)}
        if nums:
            info["min"] = min(nums)
            info["max"] = max(nums)
            info["mean"] = statistics.fmean(nums)
        else:
            info["top"] = Counter(v for v in values if v.strip()).most_common(5)
        columns.append(info)
    return {**loaded, "profile": columns, "rows": loaded["rows"][:8]}


def _bar_svg(labels: list[str], values: list[float], title: str) -> str:
    width, height, pad = 720, 360, 40
    peak = max(values) or 1.0
    bar_w = max(8, (width - 2 * pad) / max(len(values), 1) - 8)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="#111"/>',
        f'<text x="{pad}" y="24" fill="#eee" font-family="sans-serif" font-size="16">{escape(title)}</text>',
    ]
    for index, (label, value) in enumerate(zip(labels, values)):
        x = pad + index * (bar_w + 8)
        h = (value / peak) * (height - 80)
        y = height - 40 - h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="#6cf"/>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 16}" fill="#ccc" font-size="10" text-anchor="middle">{escape(str(label)[:12])}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def chart(path: str, x: str, y: str, chart_type: str, output: str, max_rows: int) -> dict:
    loaded = _load_csv(path, max_rows)
    if not loaded.get("ok"):
        return loaded
    columns = loaded["columns"]
    x_col = x if x in columns else columns[0]
    y_col = y if y in columns else (columns[1] if len(columns) > 1 else columns[0])
    labels = [row.get(x_col, "") for row in loaded["rows"]]
    nums = _numeric([row.get(y_col, "") for row in loaded["rows"]])
    if chart_type not in {"bar", "table"}:
        return {"ok": False, "error": "unsupported_chart", "allowed": ["bar", "table"]}
    if chart_type == "bar" and not nums:
        return {"ok": False, "error": "y_not_numeric", "y": y_col}
    if chart_type == "bar":
        body = _bar_svg(labels[:40], nums[:40], f"{y_col} by {x_col}")
    else:
        head = "".join(f"<th>{escape(col)}</th>" for col in columns)
        body_rows = []
        for row in loaded["rows"][:40]:
            body_rows.append("<tr>" + "".join(f"<td>{escape(row.get(col, ''))}</td>" for col in columns) + "</tr>")
        body = f"<table border='1'><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    html = f"<!doctype html><meta charset='utf-8'><title>HADES chart</title>{body}"
    dest = Path(output).expanduser() if output else Path("chart.html")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    return {
        "ok": True,
        "path": loaded["path"],
        "x": x_col,
        "y": y_col,
        "type": chart_type,
        "output": str(dest.resolve()),
        "rows_used": min(len(loaded["rows"]), 40),
        "note": "Local SVG/HTML only. No Azure OpenAI / Data Formulator UI required.",
    }


def doctor() -> dict:
    return {
        "ok": True,
        "python": sys.executable,
        "notes": ["summarize/chart work fully offline on local CSV files.", "Full Microsoft Data Formulator UI is not started by this plugin."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES data formulator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    s = sub.add_parser("summarize")
    s.add_argument("--path", required=True)
    s.add_argument("--max-rows", type=int, default=500)
    c = sub.add_parser("chart")
    c.add_argument("--path", required=True)
    c.add_argument("--x", default="")
    c.add_argument("--y", default="")
    c.add_argument("--type", default="bar")
    c.add_argument("--output", default="chart.html")
    c.add_argument("--max-rows", type=int, default=500)
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "summarize":
        payload = summarize(args.path, args.max_rows)
    else:
        payload = chart(args.path, args.x, args.y, args.type, args.output, args.max_rows)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
