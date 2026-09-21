"""Optional Playwright browser escalation for JS-rendered download paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .scoring import is_safe_automatic_click
from .urls import safe_normalize


@dataclass
class BrowserDiscovery:
    final_url: str
    html: str | None = None
    title: str | None = None
    discovered_urls: list[str] = field(default_factory=list)
    clicked: list[str] = field(default_factory=list)
    error: str | None = None
    error_class: str | None = None
    used_browser: bool = False


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


class BrowserEscalator:
    """Reuses a single browser context. No-op when Playwright is missing."""

    def __init__(self, *, timeout_ms: int = 45000, max_pages: int = 2, allow_private: bool = False) -> None:
        self.timeout_ms = timeout_ms
        self.max_pages = max(1, max_pages)
        self.allow_private = allow_private
        self._playwright = None
        self._browser = None
        self._context = None
        self._enabled = False

    async def start(self) -> bool:
        if not playwright_available():
            return False
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._context = await self._browser.new_context(accept_downloads=True)
            self._enabled = True
            return True
        except Exception:
            await self.close()
            return False

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._browser = None
        self._playwright = None
        self._enabled = False

    async def discover(self, url: str, *, referer: str | None = None) -> BrowserDiscovery:
        if not self._enabled or self._context is None:
            return BrowserDiscovery(final_url=url, error="browser_unavailable", error_class="BROWSER_ERROR")

        page = await self._context.new_page()
        found: list[str] = []
        clicked: list[str] = []

        def _capture(request: Any) -> None:
            try:
                req_url = request.url
                normalized = safe_normalize(req_url, allow_private=self.allow_private)
                if normalized and (
                    normalized.lower().endswith(".pdf")
                    or "application/pdf" in (request.headers.get("content-type") or "").lower()
                    or "download" in normalized.lower()
                ):
                    found.append(normalized)
            except Exception:
                pass

        page.on("request", _capture)

        async def on_response(response: Any) -> None:
            try:
                headers = {k.lower(): v for k, v in response.headers.items()}
                ctype = headers.get("content-type", "")
                normalized = safe_normalize(response.url, allow_private=self.allow_private)
                if normalized and ("application/pdf" in ctype or normalized.lower().endswith(".pdf")):
                    found.append(normalized)
            except Exception:
                pass

        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms, referer=referer)
            # Inspect iframes / embeds
            for frame in page.frames:
                frame_url = safe_normalize(frame.url, allow_private=self.allow_private)
                if frame_url:
                    found.append(frame_url)
            html = await page.content()
            title = await page.title()

            # Safe automatic clicks (bounded)
            selectors = [
                "a", "button", "[role=button]", "input[type=button]", "input[type=submit]",
            ]
            candidates = []
            for sel in selectors:
                try:
                    elements = await page.query_selector_all(sel)
                except Exception:
                    continue
                for el in elements[:40]:
                    try:
                        label = ((await el.inner_text()) or (await el.get_attribute("aria-label")) or "").strip()
                        href = (await el.get_attribute("href")) or ""
                        role = (await el.get_attribute("role")) or ""
                        if is_safe_automatic_click(label, href=href, role=role):
                            candidates.append((el, label or href))
                    except Exception:
                        continue

            for el, label in candidates[:3]:
                try:
                    async with page.expect_download(timeout=2500) as download_info:
                        await el.click(timeout=2500)
                    download = await download_info.value
                    src = download.url
                    normalized = safe_normalize(src, allow_private=self.allow_private)
                    if normalized:
                        found.append(normalized)
                    clicked.append(label)
                    # Cancel actual file write — discovery must not download bodies
                    try:
                        await download.cancel()
                    except Exception:
                        pass
                except Exception:
                    try:
                        async with page.expect_navigation(timeout=2500):
                            await el.click(timeout=2500)
                        clicked.append(label)
                        nav_url = safe_normalize(page.url, allow_private=self.allow_private)
                        if nav_url:
                            found.append(nav_url)
                        html = await page.content()
                    except Exception:
                        continue

            # Dedupe
            uniq: list[str] = []
            seen: set[str] = set()
            for item in found:
                if item not in seen:
                    seen.add(item)
                    uniq.append(item)

            return BrowserDiscovery(
                final_url=safe_normalize(page.url, allow_private=self.allow_private) or url,
                html=html,
                title=title,
                discovered_urls=uniq,
                clicked=clicked,
                used_browser=True,
            )
        except Exception as exc:
            return BrowserDiscovery(
                final_url=url, error=str(exc), error_class="BROWSER_ERROR", used_browser=True,
            )
        finally:
            try:
                await page.close()
            except Exception:
                pass
