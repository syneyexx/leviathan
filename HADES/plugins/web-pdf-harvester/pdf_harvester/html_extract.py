"""HTML link extraction including iframes/embeds and scored anchors."""

from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser
from typing import Iterable

from .scoring import ScoredLink, rough_title, score_link
from .urls import safe_normalize

LINK_ATTRS = {
    "href", "src", "data-href", "data-url", "data-src", "data-download",
    "data-file", "action", "poster", "data",
}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, dict[str, str], str]] = []
        self._capture_a = False
        self._a_attrs: dict[str, str] = {}
        self._a_text: list[str] = []
        self.headings: list[str] = []
        self._capture_heading = False
        self._heading_buf: list[str] = []
        self.meta_refresh: list[str] = []
        self.canonical: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = {k.lower(): (v or "") for k, v in attrs if k}
        tag_l = tag.lower()
        if tag_l == "a":
            self._capture_a = True
            self._a_attrs = amap
            self._a_text = []
        elif tag_l in {"h1", "h2", "h3"}:
            self._capture_heading = True
            self._heading_buf = []
        elif tag_l in {"iframe", "embed", "object", "source", "link"}:
            for key in LINK_ATTRS:
                if amap.get(key):
                    self.events.append((tag_l, amap, amap[key]))
            if tag_l == "link" and "canonical" in (amap.get("rel") or "").lower() and amap.get("href"):
                self.canonical = amap["href"]
        elif tag_l == "meta" and (amap.get("http-equiv") or "").lower() == "refresh":
            match = re.search(r"url\s*=\s*['\"]?([^'\";]+)", amap.get("content") or "", flags=re.I)
            if match:
                self.meta_refresh.append(match.group(1).strip())
        else:
            for key in LINK_ATTRS:
                if amap.get(key):
                    self.events.append((tag_l, amap, amap[key]))

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l == "a" and self._capture_a:
            text = re.sub(r"\s+", " ", "".join(self._a_text)).strip()
            href = self._a_attrs.get("href") or self._a_attrs.get("data-href") or ""
            self.events.append(("a", dict(self._a_attrs), href))
            # stash text on attrs for scorer
            self.events[-1][1]["_text"] = text
            self._capture_a = False
        if tag_l in {"h1", "h2", "h3"} and self._capture_heading:
            text = re.sub(r"\s+", " ", "".join(self._heading_buf)).strip()
            if text:
                self.headings.append(text[:200])
            self._capture_heading = False

    def handle_data(self, data: str) -> None:
        if self._capture_a:
            self._a_text.append(data)
        if self._capture_heading:
            self._heading_buf.append(data)


def extract_scored_links(
    html_text: str,
    base_url: str,
    *,
    parent_score: float = 0.0,
    allow_private: bool = False,
    max_urls: int = 200,
) -> tuple[list[ScoredLink], str | None, str | None]:
    parser = _Extractor()
    try:
        parser.feed(html_text or "")
    except Exception:
        pass
    title = rough_title(html_text or "")
    heading_blob = " | ".join(parser.headings[:5])
    canonical = None
    if parser.canonical:
        canonical = safe_normalize(parser.canonical, base=base_url, allow_private=allow_private)

    scored: list[ScoredLink] = []
    seen: set[str] = set()

    def _add(raw: str, anchor: str, attrs: dict[str, str], surrounding: str = "") -> None:
        nonlocal scored
        raw = html_lib.unescape((raw or "").strip())
        if not raw or raw.startswith(("#", "mailto:", "tel:")):
            return
        normalized = safe_normalize(raw, base=base_url, allow_private=allow_private)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        item = score_link(
            url=normalized,
            anchor_text=anchor,
            surrounding_text=surrounding,
            page_title=title or "",
            heading_text=heading_blob,
            parent_score=parent_score,
            attrs=attrs,
        )
        scored.append(item)

    for tag, attrs, raw in parser.events:
        anchor = attrs.pop("_text", "") if tag == "a" else tag
        _add(raw, anchor, attrs, surrounding=heading_blob)
        if len(scored) >= max_urls:
            break

    for raw in parser.meta_refresh:
        _add(raw, "meta-refresh", {"discovery": "meta_refresh"})
        if len(scored) >= max_urls:
            break

    # Absolute URLs embedded in scripts / onclick (JS-generated navigation hints)
    if len(scored) < max_urls:
        for match in re.findall(r"""https?://[^\s\"'<>\\)]+|\.pdf\b|/download[^\"'\s<>]*""", html_text or "", flags=re.I):
            if match.startswith("http") or match.endswith(".pdf") or "/download" in match.lower():
                _add(match if match.startswith("http") else match, "embedded", {"discovery": "embedded"})
            if len(scored) >= max_urls:
                break

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:max_urls], title, canonical


def unique_preserve(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
