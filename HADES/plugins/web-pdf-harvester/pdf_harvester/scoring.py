"""Link relevance scoring and safe navigation classification."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

HIGH_TERMS = (
    "pdf", "download", "view book", "view pdf", "download pdf", "download book",
    "ebook", "e-book", "full text", "fulltext", "lecture notes", "lecture note",
    "read online", "read book", "document", "publication", "paper", "manual",
    "get book", "view document", "open pdf", "notes", "textbook", "whitepaper",
    "datasheet", "report", "thesis", "dissertation",
)
MEDIUM_TERMS = (
    "book", "view", "read", "open", "continue", "next", "resource", "files",
    "library", "archive", "chapter", "preview", "free",
)
LOW_TERMS = (
    "home", "about", "contact", "privacy", "advertising", "advertise", "login",
    "account", "cart", "wishlist", "share", "facebook", "twitter", "linkedin",
    "instagram", "cookie", "terms", "faq", "help", "sitemap", "newsletter",
)
DANGEROUS_TERMS = (
    "login", "sign in", "signin", "sign-up", "signup", "register", "create account",
    "purchase", "buy now", "buy ", "checkout", "subscribe", "upload", "delete",
    "remove", "payment", "paywall", "subscription", "add to cart", "credit card",
    "password", "captcha",
)
SAFE_CLICK_TERMS = (
    "download", "view", "read", "open", "continue", "next", "pdf", "ebook",
    "e-book", "book", "document", "full text", "lecture", "notes", "get book",
)


@dataclass(frozen=True)
class ScoredLink:
    url: str
    anchor_text: str
    score: float
    reason: str
    attrs: dict[str, str]


def _contains_any(text: str, terms: tuple[str, ...]) -> list[str]:
    hits = [t for t in terms if t in text]
    return hits


def score_link(
    *,
    url: str,
    anchor_text: str = "",
    surrounding_text: str = "",
    page_title: str = "",
    heading_text: str = "",
    parent_score: float = 0.0,
    attrs: dict[str, str] | None = None,
) -> ScoredLink:
    attrs = attrs or {}
    blob = " ".join(
        part.lower()
        for part in (anchor_text, surrounding_text, page_title, heading_text, url, " ".join(attrs.values()))
        if part
    )
    score = 0.0
    reasons: list[str] = []

    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith(".pdf") or ".pdf?" in url.lower() or "/pdf/" in path:
        score += 40
        reasons.append("url_pdf")

    high = _contains_any(blob, HIGH_TERMS)
    if high:
        score += 18 + min(12, 2 * len(high))
        reasons.append("high:" + ",".join(high[:4]))
    medium = _contains_any(blob, MEDIUM_TERMS)
    if medium:
        score += 6 + min(6, len(medium))
        reasons.append("medium:" + ",".join(medium[:3]))
    low = _contains_any(blob, LOW_TERMS)
    if low:
        score -= 12 + min(10, 2 * len(low))
        reasons.append("low:" + ",".join(low[:3]))
    danger = _contains_any(blob, DANGEROUS_TERMS)
    if danger:
        score -= 40
        reasons.append("danger:" + ",".join(danger[:3]))

    # Inherit half of parent relevance (capped)
    if parent_score > 0:
        inherit = min(15.0, parent_score * 0.35)
        score += inherit
        reasons.append("parent_boost")

    # Download-ish HTML attributes
    for key in ("download", "data-download", "data-file", "type"):
        val = (attrs.get(key) or "").lower()
        if "pdf" in val or key == "download":
            score += 10
            reasons.append(f"attr:{key}")

    return ScoredLink(
        url=url,
        anchor_text=(anchor_text or "").strip()[:300],
        score=score,
        reason=";".join(reasons) or "neutral",
        attrs=attrs,
    )


def is_safe_automatic_click(label: str, *, href: str = "", role: str = "") -> bool:
    """Return True only for apparently read-only resource navigation."""
    text = f"{label} {href} {role}".lower().strip()
    if not text:
        return False
    if _contains_any(text, DANGEROUS_TERMS):
        return False
    return bool(_contains_any(text, SAFE_CLICK_TERMS)) or href.lower().endswith(".pdf")


def classify_barrier(page_text: str, status_code: int | None = None) -> str | None:
    blob = (page_text or "").lower()
    if status_code in {401, 403}:
        return "AUTH_REQUIRED"
    if any(term in blob for term in ("captcha", "recaptcha", "hcaptcha", "cf-challenge", "attention required")):
        return "CAPTCHA_BLOCKED"
    if any(term in blob for term in ("paywall", "subscribe to continue", "purchase to download", "members only")):
        return "PAYWALL_BLOCKED"
    if any(term in blob for term in ("sign in to continue", "please log in", "create an account to")):
        return "AUTH_REQUIRED"
    return None


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)


def rough_title(html: str) -> str | None:
    match = _TITLE_RE.search(html or "")
    if not match:
        match = _H1_RE.search(html or "")
    if not match:
        return None
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300] or None
