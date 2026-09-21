#!/usr/bin/env python3
"""Apply no-AI-slop / ELI5 / diagram helpers locally for HADES."""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path

SLOP_REPLACEMENTS = [
    (re.compile(r"\bdelve(?:s|d|ing)? into\b", re.I), "look at"),
    (re.compile(r"\bin the (?:ever-)?evolving (?:landscape|world) of\b", re.I), "in"),
    (re.compile(r"\bit(?:'s| is) important to note that\b", re.I), ""),
    (re.compile(r"\bin conclusion,\s*", re.I), ""),
    (re.compile(r"\bfurthermore,\s*", re.I), ""),
    (re.compile(r"\bmoreover,\s*", re.I), ""),
    (re.compile(r"\bunlock(?:s|ing)? the potential of\b", re.I), "use"),
    (re.compile(r"\ba tapestry of\b", re.I), "a mix of"),
    (re.compile(r"\brealm of\b", re.I), "area of"),
    (re.compile(r"\bcut(?:ting)?-edge\b", re.I), "current"),
    (re.compile(r"\brobust(?:ness)?\b", re.I), "solid"),
    (re.compile(r"\bleverage\b", re.I), "use"),
    (re.compile(r"\butilize\b", re.I), "use"),
    (re.compile(r"\bcommence\b", re.I), "start"),
    (re.compile(r"\bendeavor\b", re.I), "effort"),
    (re.compile(r"\bparadigm shift\b", re.I), "change"),
    (re.compile(r"\bsynerg(?:y|ies|istic)\b", re.I), "combined"),
    (re.compile(r"\bgame-?changer\b", re.I), "important change"),
    (re.compile(r"\bat the end of the day,?\s*", re.I), ""),
    (re.compile(r"\bin today's (?:fast-paced|digital) world,?\s*", re.I), ""),
    (re.compile(r"\bI hope this (?:helps|email finds you well)[^.]*\.?", re.I), ""),
    (re.compile(r"[ \t]{2,}", re.I), " "),
]


def clean_slop(text: str) -> dict:
    original = text
    updated = text
    hits = []
    for pattern, repl in SLOP_REPLACEMENTS:
        if pattern.search(updated):
            hits.append(pattern.pattern)
            updated = pattern.sub(repl, updated)
    updated = re.sub(r"\n{3,}", "\n\n", updated).strip()
    return {
        "ok": True,
        "changed": updated != original.strip(),
        "patterns_hit": hits,
        "text": updated,
    }


def eli5(topic: str, audience: str) -> dict:
    audience = (audience or "curious adult").strip()
    topic = topic.strip()
    if not topic:
        return {"ok": False, "error": "topic_required"}
    analog = {
        "kid": "like explaining with toys and food",
        "manager": "like a one-slide status update",
        "engineer": "like a precise but jargon-light design note",
        "parent": "like a calm kitchen-table explanation",
    }.get(audience.lower(), "like a clear conversation")
    return {
        "ok": True,
        "topic": topic,
        "audience": audience,
        "guidance": [
            f"Explain {topic} {analog}.",
            "Start with what it is in one sentence.",
            "Give one concrete example from daily life.",
            "Name one limitation so it stays honest.",
            "Avoid fake certainty and marketing adjectives.",
        ],
        "template": (
            f"{topic} is ___. Imagine ___. That matters because ___. "
            f"Watch out for ___."
        ),
        "note": "This tool returns an explanation scaffold HADES can fill. Optional LM Studio rewrite is not required.",
    }


def diagram(kind: str, title: str, items: str) -> dict:
    kind = (kind or "boxes").strip().lower()
    title = title.strip() or "Diagram"
    parts = [item.strip() for item in re.split(r"[;\n]+", items) if item.strip()]
    if not parts:
        return {"ok": False, "error": "items_required"}
    boxes = []
    width, x, y = 180, 24, 64
    for index, part in enumerate(parts[:12]):
        boxes.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="56" fill="none" stroke="#222" stroke-width="2"/>'
            f'<text x="{x + width/2}" y="{y + 34}" text-anchor="middle" font-family="Georgia, serif" font-size="14">{escape(part[:40])}</text>'
        )
        if index < min(len(parts), 12) - 1:
            boxes.append(
                f'<line x1="{x + width}" y1="{y + 28}" x2="{x + width + 36}" y2="{y + 28}" stroke="#222" stroke-width="2"/>'
            )
        x += width + 36
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{max(x, 400)}" height="140" viewBox="0 0 {max(x, 400)} 140">'
        f'<rect width="100%" height="100%" fill="#fff"/>'
        f'<text x="24" y="32" font-family="Georgia, serif" font-size="20">{escape(title)}</text>'
        f"{''.join(boxes)}</svg>"
    )
    html = f"<!doctype html><meta charset='utf-8'><title>{escape(title)}</title>{svg}"
    out = Path("diagram.html")
    out.write_text(html, encoding="utf-8")
    return {
        "ok": True,
        "kind": kind,
        "title": title,
        "items": parts[:12],
        "output": str(out.resolve()),
        "svg": svg,
        "note": "Editorial boxes, no drop shadows, no Mermaid.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES writing/design helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clean")
    c.add_argument("--text", required=True)
    e = sub.add_parser("eli5")
    e.add_argument("--topic", required=True)
    e.add_argument("--audience", default="curious adult")
    d = sub.add_parser("diagram")
    d.add_argument("--kind", default="boxes")
    d.add_argument("--title", default="Diagram")
    d.add_argument("--items", required=True)
    args = parser.parse_args()
    if args.cmd == "clean":
        payload = clean_slop(args.text)
    elif args.cmd == "eli5":
        payload = eli5(args.topic, args.audience)
    else:
        payload = diagram(args.kind, args.title, args.items)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
