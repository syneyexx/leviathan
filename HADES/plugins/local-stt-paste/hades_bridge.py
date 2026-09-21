#!/usr/bin/env python3
"""Local STT paste bridge — validates pasted transcript and proposes a HADES task.

Does not perform speech recognition. Use an offline STT tool locally, paste the
text here (or call HADES POST /api/voice/to-task) to turn transcript → task draft.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


MIN_TRANSCRIPT_LEN = 3
MAX_TRANSCRIPT_LEN = 20_000

PRIORITY_HINTS = {
    "high": ("urgent", "asap", "hoog", "kritiek", "critical", "nu"),
    "low": ("later", "laag", "whenever", "ooit"),
}


def _suggest_task(transcript: str) -> dict[str, Any]:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    title = lines[0][:120] if lines else "Spraaktaak"
    if title.lower().startswith(("maak ", "create ", "start ", "doe ")):
        title = title.split(" ", 1)[-1][:120].strip().capitalize() or title

    lower = transcript.lower()
    priority = "normal"
    for level, hints in PRIORITY_HINTS.items():
        if any(hint in lower for hint in hints):
            priority = level
            break

    acceptance: list[str] = []
    for match in re.finditer(r"(?:accepteer|acceptance|done when|klaar als)[:\s]+(.+)", transcript, re.I):
        acceptance.append(match.group(1).strip()[:300])
    if not acceptance:
        acceptance = ["Het gevraagde resultaat is lokaal geleverd of eerlijk als incompleet gemeld."]

    agent = "auto"
    for hint, mapped in (
        ("code", "builder"),
        ("bouw", "builder"),
        ("onderzoek", "research_worker"),
        ("research", "research_worker"),
        ("review", "critic"),
        ("verifieer", "critic"),
    ):
        if hint in lower:
            agent = mapped
            break

    return {
        "title": title,
        "prompt": transcript,
        "agent": agent,
        "priority": priority,
        "acceptance_criteria": acceptance,
        "source": "local_stt_paste",
        "auto_start_recommended": False,
        "note": "Concept uit transcriptie - controleer voor starten. Geen cloud-STT en geen ingebouwde ASR; alleen geplakte lokale tekst (local-stt-paste).",
        "next_step": "POST /api/voice/to-task met create=true (optioneel auto_start=true) of Taken -> Spraak -> taak.",
    }


def transcribe_paste(transcript: str) -> dict[str, Any]:
    text = (transcript or "").strip()
    if len(text) < MIN_TRANSCRIPT_LEN:
        return {
            "ok": False,
            "error": f"Transcript te kort (minimaal {MIN_TRANSCRIPT_LEN} tekens).",
            "transcript": text,
            "suggestion": None,
        }
    if len(text) > MAX_TRANSCRIPT_LEN:
        return {
            "ok": False,
            "error": f"Transcript te lang (maximaal {MAX_TRANSCRIPT_LEN} tekens).",
            "transcript": text[:200],
            "suggestion": None,
        }
    return {
        "ok": True,
        "transcript": text,
        "suggestion": _suggest_task(text),
    }


def doctor() -> dict[str, Any]:
    return {
        "ok": True,
        "plugin": "local-stt-paste",
        "stt": False,
        "offline": True,
        "ready_to_paste": True,
        "notes": [
            "Geen spraakherkenning in deze plugin — plak transcript van een lokale STT-tool.",
            "Gebruik transcribe_paste of HADES POST /api/voice/to-task (Taken → Spraak → taak).",
            "VoiceStudio is optionele externe ASR/TTS; plak resultaat hier — geen cloud-STT.",
            "ok=true means the paste bridge is present; stt=false means no onboard recognizer.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES local STT paste bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor")

    paste = sub.add_parser("transcribe_paste")
    paste.add_argument("--transcript", default="")
    paste.add_argument("--stdin-json", action="store_true", help="Lees JSON {transcript} van stdin")

    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    else:
        raw = args.transcript
        if args.stdin_json or not raw:
            try:
                blob = sys.stdin.read()
                parsed = json.loads(blob or "{}")
            except json.JSONDecodeError as exc:
                payload = {"ok": False, "error": f"Ongeldige JSON op stdin: {exc.msg}", "transcript": "", "suggestion": None}
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 1
            if isinstance(parsed, dict):
                raw = str(parsed.get("transcript") or "")
            else:
                raw = str(parsed)
        payload = transcribe_paste(raw)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    # Windows CI/default consoles are often cp1252; force UTF-8 for JSON with accents.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
