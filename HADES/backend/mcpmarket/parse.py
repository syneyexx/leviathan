"""Parse MCPMarket public page HTML/JSON-LD. Unknown fields stay unknown."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

_JSON_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_DESC = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_OG_DESC = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_BYLINE = re.compile(r"\bby\s+([A-Za-z0-9._-]{2,80})", re.I)
_GITHUB = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

INJECTION_MARKERS = (
    "ignore previous",
    "ignore all instructions",
    "you are now",
    "system prompt",
    "override policy",
    "grant approval",
    "disable trust",
    "jailbreak",
)


def _strip(html: str) -> str:
    text = unescape(_TAG.sub(" ", html or ""))
    return _WS.sub(" ", text).strip()


def _contains_injection(text: str) -> bool:
    sample = (text or "").lower()
    return any(marker in sample for marker in INJECTION_MARKERS)


def _load_json_ld(html: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for match in _JSON_LD.finditer(html or ""):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            found.append(data)
        elif isinstance(data, list):
            found.extend(item for item in data if isinstance(item, dict))
    return found


def parse_listing_page(html: str, *, url: str, kind_hint: str = "mcp_server") -> dict[str, Any]:
    """Deterministic parser. Does not invent transport/auth/install semantics."""
    json_ld = _load_json_ld(html)
    title_html = _H1.search(html or "")
    title_tag = _TITLE.search(html or "")
    name = _strip(title_html.group(1) if title_html else "") or _strip(title_tag.group(1) if title_tag else "")
    description = ""
    meta = _META_DESC.search(html or "") or _OG_DESC.search(html or "")
    if meta:
        description = unescape(meta.group(1)).strip()
    if not description:
        text = _strip(html)
        # First long sentence-ish block after the name.
        for chunk in re.split(r"(?<=[.!?])\s+", text):
            if name and chunk.lower().startswith(name.lower()):
                continue
            if len(chunk) > 40:
                description = chunk[:800]
                break
    publisher = ""
    byline = _BYLINE.search(_strip(html)[:500])
    if byline:
        publisher = byline.group(1)
    github = sorted(set(_GITHUB.findall(html or "")))
    ld_name = ""
    ld_desc = ""
    ld_extra: dict[str, Any] = {}
    for block in json_ld:
        ld_name = ld_name or str(block.get("name") or "")
        ld_desc = ld_desc or str(block.get("description") or "")
        if "codeRepository" in block:
            github.append(str(block["codeRepository"]))
        unknown_keys = [key for key in block.keys() if key not in {"@context", "@type", "name", "description", "url", "author", "codeRepository"}]
        if unknown_keys:
            ld_extra["unknown_jsonld_keys"] = unknown_keys
            ld_extra["jsonld_type"] = block.get("@type")
    name = name or ld_name or url.rstrip("/").split("/")[-1]
    description = description or ld_desc
    injection = _contains_injection(f"{name} {description} {html[:2000]}")
    toolkit = bool(re.search(r"\btoolkit\b", html or "", re.I)) and bool(
        re.search(r'"tools"\s*:|contained tools|tool group', html or "", re.I)
    )
    return {
        "source": "mcpmarket",
        "source_url": url,
        "kind_hint": kind_hint,
        "name": name[:200],
        "description": description[:2000],
        "publisher": publisher,
        "github": github[:8],
        "json_ld": json_ld,
        "json_ld_extras": ld_extra,
        "injection_flagged": injection,
        "toolkit_shaped": toolkit,
        "raw_preserved": True,
        "untrusted": True,
        "instruction_authority": False,
    }


def parse_skill_page(html: str, *, url: str) -> dict[str, Any]:
    listing = parse_listing_page(html, url=url, kind_hint="skill")
    listing["executable"] = bool(re.search(r"executable code|scripts that Claude loads|bundled resources", html or "", re.I))
    listing["skill_format"] = "agent_skill"
    listing["system_authority"] = False
    return listing


def extract_named_cards(html: str) -> list[dict[str, str]]:
    """Best-effort featured-name harvest from a directory page. Names only."""
    text = _strip(html)
    # Headings that look like catalog cards: keep short title-case tokens.
    names: list[dict[str, str]] = []
    for match in re.finditer(r"(?:<h[1-3][^>]*>)([^<]{2,80})(?:</h[1-3]>)", html or "", re.I):
        name = _strip(match.group(1))
        if name and name.lower() not in {"mcp market", "frequently asked questions", "key features", "use cases"}:
            names.append({"name": name, "slug": slugify(name)})
    if not names:
        for line in text.split(" "):
            pass
    return names[:80]


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return text[:80] or "unknown"
