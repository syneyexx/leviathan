#!/usr/bin/env python3
"""Honest RuView helper: parse local CSI dumps. Does not fake WiFi sensing without hardware."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path


def doctor() -> dict:
    return {
        "ok": True,
        "python": sys.executable,
        "hardware_required": True,
        "notes": [
            "RuView needs WiFi CSI / ESP32 (or similar) hardware.",
            "Without a local CSI dump this plugin cannot invent presence or vital signs.",
            "Use parse_csi on a CSV/JSON capture exported from the device.",
        ],
    }


def parse_csi(path: str, max_rows: int) -> dict:
    source = Path(path).expanduser()
    if not source.is_file():
        return {"ok": False, "error": "file_not_found", "path": str(source), "hint": "Pass a local CSI CSV/JSON dump."}
    suffix = source.suffix.lower()
    rows: list[dict] = []
    if suffix == ".json":
        data = json.loads(source.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, list):
            rows = [item for item in data if isinstance(item, dict)][:max_rows]
        elif isinstance(data, dict) and isinstance(data.get("samples"), list):
            rows = [item for item in data["samples"] if isinstance(item, dict)][:max_rows]
        else:
            return {"ok": False, "error": "unsupported_json_shape"}
    else:
        with source.open(encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return {"ok": False, "error": "no_header"}
            for index, row in enumerate(reader):
                if index >= max_rows:
                    break
                rows.append(dict(row))
    numeric_cols = {}
    if rows:
        for key in rows[0]:
            values = []
            for row in rows:
                try:
                    values.append(float(str(row.get(key, "")).replace(",", "")))
                except ValueError:
                    values = []
                    break
            if values:
                numeric_cols[key] = {
                    "min": min(values),
                    "max": max(values),
                    "mean": statistics.fmean(values),
                    "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
                }
    return {
        "ok": True,
        "path": str(source.resolve()),
        "samples": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "numeric": numeric_cols,
        "preview": rows[:5],
        "note": "Statistics only. No vital-sign or presence claim is made from this parse.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES RuView helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("parse_csi")
    p.add_argument("--path", required=True)
    p.add_argument("--max-rows", type=int, default=2000)
    args = parser.parse_args()
    payload = doctor() if args.cmd == "doctor" else parse_csi(args.path, args.max_rows)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
