"""Playwright Chromium browser backend (GI8).

READY only when: playwright installed AND Chromium executable exists AND
launch succeeds AND a page can navigate AND a bounded observation is returned.
Package presence alone is never treated as READY.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .worker import (
    BrowserAction,
    BrowserBackendKind,
    BrowserObservation,
    BrowserSession,
    _utc_now,
)

# Observation bounds — page content is untrusted context.
_MAX_DOM_TEXT = 8000
_MAX_A11Y = 8000
_MAX_DOM_SUMMARY = 2000
_MAX_INTERACTIVE = 80
_MAX_CONSOLE = 40
_MAX_NETWORK = 40


class PlaywrightUnavailable(Exception):
    """Honest UNAVAILABLE — never claim READY without a measured Chromium path."""

    unavailable = True


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…[truncated]"


def _probe_playwright_import() -> tuple[bool, str]:
    try:
        import playwright  # noqa: F401

        return True, getattr(playwright, "__version__", "installed")
    except ImportError:
        return False, "playwright package not installed"


def chromium_executable_exists() -> tuple[bool, str | None]:
    """Return (exists, path) for the Playwright-managed Chromium binary if resolvable."""
    ok, _ = _probe_playwright_import()
    if not ok:
        return False, None
    try:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        try:
            path = pw.chromium.executable_path
            exists = bool(path and Path(path).is_file())
            return exists, path
        finally:
            pw.stop()
    except Exception:  # noqa: BLE001
        return False, None


class PlaywrightBrowserBackend:
    """Real Chromium path — one browser per backend, context per group, page per session."""

    kind = BrowserBackendKind.PLAYWRIGHT

    def __init__(
        self,
        *,
        allow_uploads: bool = True,
        headless: bool = True,
        default_timeout_ms: int = 15000,
        extra_http_headers: dict[str, str] | None = None,
    ) -> None:
        self.allow_uploads = allow_uploads
        self.headless = headless
        self.default_timeout_ms = default_timeout_ms
        self.extra_http_headers = dict(extra_http_headers or {})
        self._pkg_ok, self._pkg_detail = _probe_playwright_import()
        self._playwright: Any = None
        self._browser: Any = None
        self._contexts: dict[str, Any] = {}
        self._pages: dict[str, Any] = {}
        self._console: dict[str, list[str]] = {}
        self._network_errors: dict[str, list[str]] = {}
        self._downloads: dict[str, list[dict[str, Any]]] = {}
        self._ready: bool | None = None
        self._readiness: dict[str, Any] = {
            "status": "UNKNOWN",
            "package_installed": self._pkg_ok,
            "package_detail": self._pkg_detail,
            "chromium_executable": None,
            "chromium_exists": False,
            "launch_ok": False,
            "navigate_ok": False,
            "observation_ok": False,
            "ready": False,
            "detail": "not probed",
            "truth": {
                "package_alone_is_not_ready": True,
                "unavailable_is_not_ready": True,
            },
        }

    # ------------------------------------------------------------------ readiness

    def readiness(self, *, force: bool = False) -> dict[str, Any]:
        """Probe and cache readiness. Never marks READY on package alone."""
        if self._ready is not None and not force:
            return dict(self._readiness)
        if not self._pkg_ok:
            self._ready = False
            self._readiness.update(
                {
                    "status": "UNAVAILABLE",
                    "ready": False,
                    "detail": (
                        "Playwright is not installed — browser backend UNAVAILABLE "
                        "(not READY). Use LEVIATHAN_BROWSER_BACKEND=local_dom or install playwright."
                    ),
                }
            )
            return dict(self._readiness)
        try:
            self._ensure_runtime()
            # Prove navigate + observation on a data URL (no network required).
            page = self._browser.new_page()
            try:
                page.set_default_timeout(self.default_timeout_ms)
                page.goto(
                    "data:text/html,<html><head><title>ready</title></head>"
                    "<body><p>leviathan-playwright-ready</p></body></html>",
                    wait_until="domcontentloaded",
                )
                title = page.title() or ""
                body = page.inner_text("body") if page.query_selector("body") else ""
                nav_ok = "leviathan-playwright-ready" in body and "ready" in title.lower()
                obs_ok = bool(title or body)
                self._ready = bool(nav_ok and obs_ok)
                self._readiness.update(
                    {
                        "status": "READY" if self._ready else "UNAVAILABLE",
                        "launch_ok": True,
                        "navigate_ok": nav_ok,
                        "observation_ok": obs_ok,
                        "ready": bool(self._ready),
                        "detail": (
                            "Playwright Chromium READY"
                            if self._ready
                            else "Launch succeeded but navigate/observation probe failed"
                        ),
                    }
                )
            finally:
                page.close()
        except PlaywrightUnavailable as exc:
            self._ready = False
            self._readiness.update(
                {
                    "status": "UNAVAILABLE",
                    "ready": False,
                    "detail": str(exc),
                }
            )
            self._teardown_runtime()
        except Exception as exc:  # noqa: BLE001
            self._ready = False
            self._readiness.update(
                {
                    "status": "UNAVAILABLE",
                    "ready": False,
                    "launch_ok": False,
                    "detail": f"Playwright readiness probe failed: {exc}",
                }
            )
            self._teardown_runtime()
        return dict(self._readiness)

    def _ensure_ready(self) -> None:
        info = self.readiness()
        if not info.get("ready"):
            raise PlaywrightUnavailable(
                str(info.get("detail") or "Playwright Chromium UNAVAILABLE (not READY)")
            )

    def _ensure_runtime(self) -> None:
        if self._browser is not None:
            return
        if not self._pkg_ok:
            raise PlaywrightUnavailable(
                "Playwright is not installed — browser backend UNAVAILABLE "
                "(not READY). Use LEVIATHAN_BROWSER_BACKEND=local_dom or install playwright."
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise PlaywrightUnavailable(
                "Playwright is not installed — browser backend UNAVAILABLE (not READY)."
            ) from exc
        try:
            self._playwright = sync_playwright().start()
            exe = self._playwright.chromium.executable_path
            self._readiness["chromium_executable"] = exe
            exists = bool(exe and Path(exe).is_file())
            self._readiness["chromium_exists"] = exists
            if not exists:
                raise PlaywrightUnavailable(
                    "Playwright package present but Chromium executable missing — "
                    "UNAVAILABLE (not READY). Run `playwright install chromium`."
                )
            self._browser = self._playwright.chromium.launch(headless=self.headless)
            self._readiness["launch_ok"] = True
        except PlaywrightUnavailable:
            self._teardown_runtime()
            raise
        except Exception as exc:  # noqa: BLE001
            self._teardown_runtime()
            raise PlaywrightUnavailable(
                f"Playwright Chromium launch failed — UNAVAILABLE (not READY): {exc}"
            ) from exc

    def _teardown_runtime(self) -> None:
        for page in list(self._pages.values()):
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
        self._pages.clear()
        for ctx in list(self._contexts.values()):
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
        self._contexts.clear()
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None

    def close(self) -> None:
        self._teardown_runtime()
        self._ready = None

    # ------------------------------------------------------------------ sessions

    def _group_key(self, session: BrowserSession) -> str:
        return str(session.run_id or session.session_id)

    def _get_context(self, session: BrowserSession) -> Any:
        key = self._group_key(session)
        ctx = self._contexts.get(key)
        if ctx is not None:
            return ctx
        assert self._browser is not None
        headers = dict(self.extra_http_headers)
        ctx = self._browser.new_context(
            accept_downloads=True,
            extra_http_headers=headers or None,
        )
        self._contexts[key] = ctx
        return ctx

    def _get_page(self, session: BrowserSession) -> Any:
        page = self._pages.get(session.session_id)
        if page is not None:
            return page
        ctx = self._get_context(session)
        page = ctx.new_page()
        page.set_default_timeout(self.default_timeout_ms)
        sid = session.session_id
        self._console.setdefault(sid, [])
        self._network_errors.setdefault(sid, [])

        def _on_console(msg: Any) -> None:
            try:
                if msg.type in {"error", "warning"}:
                    line = f"{msg.type}: {msg.text}"
                    bucket = self._console[sid]
                    if line not in bucket and len(bucket) < _MAX_CONSOLE:
                        bucket.append(line)
            except Exception:  # noqa: BLE001
                pass

        def _on_page_error(exc: Any) -> None:
            try:
                line = f"pageerror: {exc}"
                bucket = self._console[sid]
                if line not in bucket and len(bucket) < _MAX_CONSOLE:
                    bucket.append(line)
            except Exception:  # noqa: BLE001
                pass

        def _on_request_failed(req: Any) -> None:
            try:
                failure = req.failure
                line = f"{req.method} {req.url} failed: {failure}"
                bucket = self._network_errors[sid]
                if line not in bucket and len(bucket) < _MAX_NETWORK:
                    bucket.append(line)
            except Exception:  # noqa: BLE001
                pass

        page.on("console", _on_console)
        page.on("pageerror", _on_page_error)
        page.on("requestfailed", _on_request_failed)
        self._pages[sid] = page
        return page

    # ------------------------------------------------------------------ locators

    def _locator(self, page: Any, arguments: dict[str, Any], *, for_type: bool = False):
        """Resolve CSS / text / ARIA role / name / label / placeholder / test-id."""
        role = arguments.get("role")
        name = arguments.get("name") or arguments.get("accessible_name")
        if role:
            kwargs: dict[str, Any] = {}
            if name:
                kwargs["name"] = str(name)
            return page.get_by_role(str(role), **kwargs)
        if arguments.get("label"):
            return page.get_by_label(str(arguments["label"]))
        if arguments.get("placeholder"):
            return page.get_by_placeholder(str(arguments["placeholder"]))
        test_id = arguments.get("test_id") or arguments.get("testid") or arguments.get("data_testid")
        if test_id:
            return page.get_by_test_id(str(test_id))
        # TYPE uses arguments["text"] as input value — do not treat as locator.
        if not for_type and arguments.get("text") and not arguments.get("selector"):
            return page.get_by_text(str(arguments["text"]), exact=False)
        selector = str(
            arguments.get("selector")
            or arguments.get("target")
            or arguments.get("locator")
            or ""
        ).strip()
        if not selector:
            raise ValueError("Locator required (selector/role/label/placeholder/test_id/text)")
        if selector.startswith("text="):
            return page.get_by_text(selector[5:].strip().strip("\"'"), exact=False)
        if selector.startswith("role="):
            # role=button[name=Submit] or role=button
            rest = selector[5:]
            role_name, _, name_part = rest.partition("[")
            kwargs = {}
            if name_part:
                m = re.search(r"name\s*=\s*['\"]?([^\]'\"]+)", name_part)
                if m:
                    kwargs["name"] = m.group(1)
            return page.get_by_role(role_name.strip(), **kwargs)
        if selector.startswith("label="):
            return page.get_by_label(selector[6:].strip().strip("\"'"))
        if selector.startswith("placeholder="):
            return page.get_by_placeholder(selector[12:].strip().strip("\"'"))
        if selector.startswith("testid=") or selector.startswith("test_id="):
            val = selector.split("=", 1)[1].strip().strip("\"'")
            return page.get_by_test_id(val)
        return page.locator(selector)

    # ------------------------------------------------------------------ observe

    def _observe(self, session: BrowserSession, page: Any, *, mode: str = "dom") -> BrowserObservation:
        url = page.url
        title = ""
        try:
            title = page.title() or ""
        except Exception:  # noqa: BLE001
            title = ""
        dom_text = ""
        try:
            dom_text = page.inner_text("body") if page.query_selector("body") else page.content()
        except Exception:  # noqa: BLE001
            try:
                dom_text = page.content()
            except Exception:  # noqa: BLE001
                dom_text = ""
        a11y = self._a11y_snapshot(page)
        interactive = self._interactive_elements(page)
        viewport = page.viewport_size or {}
        try:
            vp_metrics = page.evaluate(
                """() => ({
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    scrollX: window.scrollX,
                    scrollY: window.scrollY,
                    devicePixelRatio: window.devicePixelRatio
                })"""
            )
            if isinstance(vp_metrics, dict):
                viewport = {**viewport, **vp_metrics}
        except Exception:  # noqa: BLE001
            pass
        dom_summary = _truncate(
            f"title={title!r} url={url!r} interactive={len(interactive)} "
            f"text_chars={len(dom_text)}",
            _MAX_DOM_SUMMARY,
        )
        console_errors = list(self._console.get(session.session_id, []))[-_MAX_CONSOLE:]
        network_errors = list(self._network_errors.get(session.session_id, []))[-_MAX_NETWORK:]
        session.url = url
        session.title = title
        session.dom_text = _truncate(dom_text, _MAX_DOM_TEXT)
        session.accessibility_tree = _truncate(a11y, _MAX_A11Y)
        session.updated_at = _utc_now()
        session.metadata["backend"] = self.kind.value
        session.metadata["viewport"] = viewport
        session.metadata["interactive_count"] = len(interactive)
        session.metadata["console_errors"] = console_errors
        session.metadata["network_errors"] = network_errors
        return BrowserObservation(
            url=url,
            title=title,
            dom_text=session.dom_text,
            accessibility_tree=session.accessibility_tree,
            mode=mode,
            dom_summary=dom_summary,
            interactive_elements=tuple(interactive[:_MAX_INTERACTIVE]),
            viewport=viewport,
            console_errors=tuple(console_errors),
            network_errors=tuple(network_errors),
        )

    def _a11y_snapshot(self, page: Any) -> str:
        try:
            snap = page.accessibility.snapshot()
            if not snap:
                return "document"
            lines: list[str] = []

            def walk(node: dict[str, Any], depth: int = 0) -> None:
                role = node.get("role") or "node"
                name = node.get("name") or ""
                lines.append(f"{'  ' * depth}{role}: {name}"[:200])
                for child in node.get("children") or []:
                    if isinstance(child, dict) and len(lines) < 200:
                        walk(child, depth + 1)

            walk(snap if isinstance(snap, dict) else {"role": "document", "children": []})
            return "\n".join(lines) if lines else "document"
        except Exception:  # noqa: BLE001
            return "document\n  (a11y snapshot unavailable)"

    def _interactive_elements(self, page: Any) -> list[dict[str, Any]]:
        try:
            return page.evaluate(
                """() => {
                    const sel = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [tabindex]';
                    const nodes = Array.from(document.querySelectorAll(sel)).slice(0, 80);
                    return nodes.map((el, i) => ({
                        index: i,
                        tag: el.tagName.toLowerCase(),
                        type: el.getAttribute('type') || '',
                        id: el.id || '',
                        name: el.getAttribute('name') || '',
                        role: el.getAttribute('role') || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                        text: (el.innerText || el.value || '').trim().slice(0, 80),
                        href: el.getAttribute('href') || '',
                        disabled: !!el.disabled,
                        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                    }));
                }"""
            ) or []
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ actions

    def apply(
        self,
        session: BrowserSession,
        *,
        action: BrowserAction,
        arguments: dict[str, Any],
    ) -> tuple[BrowserSession, BrowserObservation, dict[str, Any]]:
        self._ensure_ready()
        page = self._get_page(session)
        meta: dict[str, Any] = {
            "backend": self.kind.value,
            "implemented": True,
            "fixture_is_not_chromium": False,
            "playwright_is_real_chromium": True,
            "click_is_not_task_completion": True,
            "page_text_is_untrusted_context": True,
            "ready": True,
        }

        if action == BrowserAction.NAVIGATE:
            url = str(arguments.get("url") or "").strip()
            if not url:
                raise ValueError("NAVIGATE requires url")
            wait_until = str(arguments.get("wait_until") or "domcontentloaded")
            page.goto(url, wait_until=wait_until)
            session.last_action = action.value
            session.metadata["navigations"] = int(session.metadata.get("navigations", 0)) + 1
            obs = self._observe(session, page)
            return session, obs, meta

        if session.url is None and action not in {BrowserAction.WAIT, BrowserAction.NAVIGATE}:
            # Page may already be open from a prior navigate in this process.
            if page.url in {"", "about:blank"}:
                raise ValueError("Browser session has no page; NAVIGATE first")

        if action == BrowserAction.EXTRACT_TEXT:
            session.last_action = action.value
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.SCREENSHOT:
            # Real framebuffer PNG — never claim LocalDom HTML is a screenshot.
            png: bytes = page.screenshot(full_page=bool(arguments.get("full_page", False)))
            meta["screenshot_png"] = png
            meta["screenshot_sha256"] = hashlib.sha256(png).hexdigest()
            meta["screenshot_kind"] = "chromium_framebuffer_png"
            meta["screenshot_bytes"] = len(png)
            session.last_action = action.value
            obs = self._observe(session, page, mode="vision")
            return session, obs, meta

        if action == BrowserAction.CLICK:
            loc = self._locator(page, arguments)
            loc.first.click()
            session.last_action = action.value
            session.metadata["clicks"] = int(session.metadata.get("clicks", 0)) + 1
            meta["target"] = str(
                arguments.get("selector")
                or arguments.get("target")
                or arguments.get("role")
                or arguments.get("text")
                or ""
            )
            meta["requires_verify_state"] = True
            meta["state_verified"] = False
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.TYPE:
            text = str(arguments.get("text") or "")
            loc = self._locator(page, arguments, for_type=True)
            clear = bool(arguments.get("clear", True))
            if clear:
                loc.first.fill(text)
            else:
                loc.first.type(text)
            session.last_action = action.value
            meta["selector"] = str(arguments.get("selector") or arguments.get("label") or "")
            meta["text_len"] = len(text)
            meta["requires_verify_state"] = True
            meta["state_verified"] = False
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.SCROLL:
            direction = str(arguments.get("direction") or "down").lower()
            amount = int(arguments.get("amount") or arguments.get("pixels") or 600)
            delta = amount if direction in {"down", "right"} else -amount
            if direction in {"left", "right"}:
                page.mouse.wheel(delta, 0)
            else:
                page.mouse.wheel(0, delta)
            session.last_action = action.value
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.WAIT:
            ms = int(arguments.get("ms") or arguments.get("timeout_ms") or 250)
            selector = arguments.get("selector") or arguments.get("wait_for")
            if selector:
                page.wait_for_selector(str(selector), timeout=ms)
            else:
                page.wait_for_timeout(max(0, min(ms, 60_000)))
            session.last_action = action.value
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.KEYPRESS:
            key = str(arguments.get("key") or arguments.get("keys") or "Enter")
            selector = arguments.get("selector")
            if selector or arguments.get("role") or arguments.get("label"):
                loc = self._locator(page, arguments, for_type=True)
                loc.first.press(key)
            else:
                page.keyboard.press(key)
            session.last_action = action.value
            meta["key"] = key
            meta["requires_verify_state"] = True
            meta["state_verified"] = False
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.FORM_FILL:
            fields = dict(arguments.get("fields") or {})
            filled: list[str] = []
            for name, value in fields.items():
                # Prefer name=, then id=, then label=
                locator = page.locator(
                    f'input[name="{name}"], textarea[name="{name}"], select[name="{name}"], '
                    f'#{name}'
                )
                if locator.count() == 0:
                    locator = page.get_by_label(str(name), exact=False)
                if locator.count() == 0:
                    raise ValueError(f"FORM_FILL field not found: {name!r}")
                tag = locator.first.evaluate("el => el.tagName.toLowerCase()")
                input_type = locator.first.evaluate("el => (el.getAttribute('type')||'').toLowerCase()")
                if tag == "select":
                    locator.first.select_option(str(value))
                elif input_type in {"checkbox", "radio"}:
                    if value in (True, "true", "1", "on", "yes"):
                        locator.first.check()
                    else:
                        locator.first.uncheck()
                else:
                    locator.first.fill(str(value))
                filled.append(name)
            session.last_action = action.value
            meta["filled_fields"] = filled
            meta["requires_verify_state"] = True
            meta["state_verified"] = False
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.DOWNLOAD:
            selector = str(arguments.get("selector") or "a[download], a[href]")
            loc = page.locator(selector).first
            with page.expect_download(timeout=self.default_timeout_ms) as dl_info:
                loc.click()
            download = dl_info.value
            suggested = download.suggested_filename or "download.bin"
            # Read bytes via temporary path Playwright provides.
            path = download.path()
            data = Path(path).read_bytes() if path else b""
            if not data:
                # Fallback: stream to failure-safe empty marker
                try:
                    failure = download.failure()
                except Exception:  # noqa: BLE001
                    failure = None
                if failure:
                    raise RuntimeError(f"DOWNLOAD failed: {failure}")
            record = {
                "filename": suggested,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest() if data else None,
                "url": download.url,
            }
            self._downloads.setdefault(session.session_id, []).append(record)
            session.metadata["downloads"] = list(self._downloads[session.session_id])
            session.last_action = action.value
            meta["download"] = record
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.UPLOAD:
            if not self.allow_uploads:
                raise PermissionError("Uploads not permitted by policy")
            path = str(arguments.get("path") or "")
            if not path:
                raise ValueError("UPLOAD requires path")
            target = Path(path).expanduser()
            if not target.is_file():
                raise FileNotFoundError(f"Upload file not found: {target}")
            loc = self._locator(
                page,
                {
                    **arguments,
                    "selector": arguments.get("selector") or 'input[type="file"]',
                },
                for_type=True,
            )
            loc.first.set_input_files(str(target))
            data = target.read_bytes()
            record = {
                "filename": target.name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            session.metadata.setdefault("uploads", []).append(record)
            session.last_action = action.value
            meta["upload"] = record
            meta["requires_verify_state"] = True
            meta["state_verified"] = False
            obs = self._observe(session, page)
            return session, obs, meta

        if action == BrowserAction.VERIFY_STATE:
            predicates = list(arguments.get("predicates") or [])
            if arguments.get("contains_text"):
                predicates.append({"contains_text": arguments["contains_text"]})
            if arguments.get("selector_exists"):
                predicates.append({"selector_exists": arguments["selector_exists"]})
            if arguments.get("attribute_equals"):
                predicates.append({"attribute_equals": arguments["attribute_equals"]})
            if arguments.get("url_contains"):
                predicates.append({"url_contains": arguments["url_contains"]})
            if arguments.get("title_contains"):
                predicates.append({"title_contains": arguments["title_contains"]})
            results: list[dict[str, Any]] = []
            all_ok = True
            for pred in predicates:
                ok, detail = self._check_predicate(page, pred)
                results.append({"predicate": pred, "ok": ok, "detail": detail})
                all_ok = all_ok and ok
            session.last_action = action.value
            meta["state_verified"] = True
            meta["verification_passed"] = all_ok
            meta["verification_results"] = results
            if not all_ok:
                meta["verification_failed"] = True
            obs = self._observe(session, page)
            return session, obs, meta

        raise ValueError(f"Unsupported browser action: {action}")

    def _check_predicate(self, page: Any, pred: dict[str, Any]) -> tuple[bool, str]:
        if "contains_text" in pred:
            needle = str(pred["contains_text"])
            try:
                body = page.inner_text("body")
            except Exception:  # noqa: BLE001
                body = ""
            ok = needle.lower() in body.lower()
            return ok, f"contains_text={needle!r} -> {ok}"
        if "selector_exists" in pred:
            sel = str(pred["selector_exists"])
            try:
                found = page.locator(sel).count() > 0
            except Exception as exc:  # noqa: BLE001
                return False, f"selector_exists error: {exc}"
            return found, f"selector_exists={sel!r} -> {found}"
        if "attribute_equals" in pred:
            spec = pred["attribute_equals"]
            sel = str(spec.get("selector") or "")
            attr = str(spec.get("attr") or "")
            expected = str(spec.get("value") or "")
            try:
                loc = page.locator(sel).first
                if attr in {"value", "checked"}:
                    actual = loc.input_value() if attr == "value" else str(loc.is_checked())
                else:
                    actual = loc.get_attribute(attr) or ""
            except Exception as exc:  # noqa: BLE001
                return False, f"attribute_equals error: {exc}"
            ok = actual == expected
            return ok, f"{sel}@{attr}={actual!r} expected {expected!r} -> {ok}"
        if "url_contains" in pred:
            needle = str(pred["url_contains"])
            ok = needle in (page.url or "")
            return ok, f"url_contains={needle!r} -> {ok}"
        if "title_contains" in pred:
            needle = str(pred["title_contains"])
            try:
                title = page.title() or ""
            except Exception:  # noqa: BLE001
                title = ""
            ok = needle.lower() in title.lower()
            return ok, f"title_contains={needle!r} -> {ok}"
        if "form_submitted" in pred:
            # Best-effort: look for thank-you / success markers or data attribute.
            try:
                ok = page.locator("[data-submitted='true'], .form-success, #form-success").count() > 0
            except Exception:  # noqa: BLE001
                ok = False
            return ok, f"form_submitted -> {ok}"
        return False, f"unknown predicate: {pred}"
