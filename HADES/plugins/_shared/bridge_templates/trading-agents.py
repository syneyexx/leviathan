#!/usr/bin/env python3
"""Paper-only multi-agent trading debate for HADES (TradingAgents-inspired). Never places live orders."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    import lm_client
except ImportError:
    lm_client = None  # type: ignore

ROLES = (
    ("market", "Technical market analyst. Describe price structure, not advice."),
    ("news", "News analyst. List only facts present in the brief; otherwise say unknown."),
    ("fundamentals", "Fundamentals analyst. Use only provided notes."),
    ("bull", "Bull researcher. Steelman the long case with explicit uncertainty."),
    ("bear", "Bear researcher. Steelman the short/avoid case."),
    ("trader", "Paper trader. Propose a hypothetical paper action: hold/buy/sell with size 0-1."),
    ("risk", "Risk manager. Veto anything that looks like live trading or unbounded size."),
)
DISCLAIMER = "SIMULATION/PAPER ONLY. This plugin never contacts a broker and never places real orders."


def doctor() -> dict:
    return {
        "ok": True,
        "python": sys.executable,
        "lm_client": lm_client is not None,
        "roles": [name for name, _ in ROLES],
        "disclaimer": DISCLAIMER,
    }


def prepare(ticker: str, notes: str) -> dict:
    symbol = ticker.strip().upper()
    if not symbol:
        return {"ok": False, "error": "ticker_required"}
    return {
        "ok": True,
        "ticker": symbol,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "roles": [{"id": name, "brief": brief} for name, brief in ROLES],
        "disclaimer": DISCLAIMER,
        "next": "Call run_round with a dynamic LM Studio model id, or use the role briefs in Chat.",
    }


def run_round(ticker: str, notes: str, model: str, base_url: str, api_key: str) -> dict:
    prepared = prepare(ticker, notes)
    if not prepared.get("ok"):
        return prepared
    if lm_client is None:
        return {"ok": False, "error": "lm_client_missing", "prepare": prepared}
    transcript = []
    context = f"Ticker: {prepared['ticker']}\nOperator notes:\n{notes or '(none)'}\n{DISCLAIMER}"
    for name, brief in ROLES:
        history = "\n".join(f"{row['role']}: {row['content']}" for row in transcript[-4:])
        result = lm_client.chat(
            [
                {"role": "system", "content": f"{brief} {DISCLAIMER} JSON is allowed but plain text is fine."},
                {"role": "user", "content": f"{context}\nPrior:\n{history or '(start)'}"},
            ],
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=90.0,
            max_tokens=700,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error"),
                "detail": result.get("detail") or result.get("hint"),
                "partial": transcript,
                "disclaimer": DISCLAIMER,
            }
        transcript.append({"role": name, "content": result["content"]})
    out = ROOT / "last_round.json"
    payload = {
        "ok": True,
        "ticker": prepared["ticker"],
        "model": model,
        "transcript": transcript,
        "disclaimer": DISCLAIMER,
        "saved": str(out),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES paper trading agents")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("prepare")
    p.add_argument("--ticker", required=True)
    p.add_argument("--notes", default="")
    r = sub.add_parser("run_round")
    r.add_argument("--ticker", required=True)
    r.add_argument("--notes", default="")
    r.add_argument("--model", required=True)
    r.add_argument("--base-url", default="")
    r.add_argument("--api-key", default="")
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "prepare":
        payload = prepare(args.ticker, args.notes)
    else:
        payload = run_round(args.ticker, args.notes, args.model, args.base_url, args.api_key)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
