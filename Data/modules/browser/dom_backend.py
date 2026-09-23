"""Local DOM browser backend — real HTML pages without Chromium (Round 7).

Operates on file://, data:, and http(s) documents parsed into a live DOM.
Supports navigation, a11y/DOM observation, click, type, forms, downloads,
uploads (where permitted), HTML screenshots, and explicit state verification.

A successful click is NOT task completion — callers must VERIFY_STATE.
FixtureBrowserBackend remains test-only; this backend is the default real path.
"""

from __future__ import annotations

import hashlib
import html
import io
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .worker import (
    BrowserAction,
    BrowserBackendKind,
    BrowserObservation,
    BrowserSession,
    _utc_now,
)


@dataclass
class _DomNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_DomNode | str] = field(default_factory=list)
    parent: _DomNode | None = None

    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                parts.append(child.text())
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def find_all(self, predicate) -> list[_DomNode]:
        out: list[_DomNode] = []
        if predicate(self):
            out.append(self)
        for child in self.children:
            if isinstance(child, _DomNode):
                out.extend(child.find_all(predicate))
        return out

    def serialize(self, indent: int = 0) -> str:
        attrs = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in self.attrs.items())
        pad = "  " * indent
        void = self.tag in {"img", "br", "hr", "input", "meta", "link"}
        if void:
            return f"{pad}<{self.tag}{attrs} />\n"
        inner = ""
        for child in self.children:
            if isinstance(child, str):
                inner += f"{pad}  {html.escape(child)}\n"
            else:
                inner += child.serialize(indent + 1)
        return f"{pad}<{self.tag}{attrs}>\n{inner}{pad}</{self.tag}>\n"


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _DomNode(tag="document")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _DomNode(
            tag=tag.lower(),
            attrs={k: (v or "") for k, v in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)
        if tag.lower() not in {"img", "br", "hr", "input", "meta", "link", "area", "base", "col", "embed", "source", "wbr"}:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                self._stack = self._stack[:i]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._stack[-1].children.append(data)


def _parse_html(source: str) -> _DomNode:
    builder = _TreeBuilder()
    builder.feed(source)
    builder.close()
    return builder.root


def _match_selector(node: _DomNode, selector: str) -> bool:
    selector = selector.strip()
    if not selector:
        return False
    if selector.startswith("#"):
        return node.attrs.get("id") == selector[1:]
    if selector.startswith("."):
        classes = set((node.attrs.get("class") or "").split())
        return selector[1:] in classes
    if "[" in selector and selector.endswith("]"):
        tag, _, rest = selector.partition("[")
        key, _, val = rest[:-1].partition("=")
        key = key.strip()
        val = val.strip().strip("\"'")
        if tag and node.tag != tag.lower():
            return False
        return node.attrs.get(key) == val
    if selector.startswith("text="):
        needle = selector[5:].strip().strip("\"'")
        return needle.lower() in node.text().lower()
    return node.tag == selector.lower() or node.attrs.get("name") == selector or node.attrs.get("id") == selector


def _a11y_tree(root: _DomNode) -> str:
    lines: list[str] = ["document"]
    interesting = {
        "h1", "h2", "h3", "h4", "button", "a", "input", "textarea", "select",
        "label", "form", "table", "th", "td", "p", "img", "nav",
    }

    def walk(node: _DomNode, depth: int) -> None:
        if node.tag in interesting:
            role = node.tag
            name = (
                node.attrs.get("aria-label")
                or node.attrs.get("name")
                or node.attrs.get("alt")
                or node.attrs.get("placeholder")
                or node.text()[:80]
            )
            extra = ""
            if node.tag == "input":
                extra = f" type={node.attrs.get('type', 'text')} value={node.attrs.get('value', '')!r}"
            lines.append(f"{'  ' * depth}{role}: {name}{extra}")
        for child in node.children:
            if isinstance(child, _DomNode):
                walk(child, depth + (1 if node.tag in interesting else 0))

    walk(root, 1)
    return "\n".join(lines)


class LocalDomBrowserBackend:
    """Real local HTML DOM browser — not a fixture, not Chromium."""

    kind = BrowserBackendKind.LOCAL_DOM

    def __init__(
        self,
        *,
        allow_network: bool = False,
        allow_uploads: bool = True,
        filesystem_root: str | Path | None = None,
    ) -> None:
        self.allow_network = allow_network
        self.allow_uploads = allow_uploads
        self.filesystem_root = Path(filesystem_root) if filesystem_root else None
        self._dom_by_session: dict[str, _DomNode] = {}
        self._html_by_session: dict[str, str] = {}
        self._downloads: dict[str, list[dict[str, Any]]] = {}
        self._uploads: dict[str, list[dict[str, Any]]] = {}

    def apply(
        self,
        session: BrowserSession,
        *,
        action: BrowserAction,
        arguments: dict[str, Any],
    ) -> tuple[BrowserSession, BrowserObservation, dict[str, Any]]:
        meta: dict[str, Any] = {
            "backend": self.kind.value,
            "implemented": True,
            "fixture_is_not_chromium": False,
            "local_dom_is_real_html": True,
            "click_is_not_task_completion": True,
        }

        if action == BrowserAction.NAVIGATE:
            url = str(arguments.get("url") or "").strip()
            if not url:
                raise ValueError("NAVIGATE requires url")
            html_source, final_url = self._load(url)
            root = _parse_html(html_source)
            self._dom_by_session[session.session_id] = root
            self._html_by_session[session.session_id] = html_source
            title = self._title(root) or final_url
            session.url = final_url
            session.title = title
            session.dom_text = root.text()
            session.accessibility_tree = _a11y_tree(root)
            session.last_action = action.value
            session.updated_at = _utc_now()
            session.metadata["navigations"] = int(session.metadata.get("navigations", 0)) + 1
            session.metadata["backend"] = self.kind.value
            obs = BrowserObservation(
                url=final_url,
                title=title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        if session.url is None and action not in {BrowserAction.WAIT}:
            raise ValueError("Browser session has no page; NAVIGATE first")

        root = self._dom_by_session.get(session.session_id)
        if root is None and action not in {BrowserAction.WAIT}:
            raise ValueError("DOM missing for session — NAVIGATE first")

        if action == BrowserAction.EXTRACT_TEXT:
            assert root is not None
            session.dom_text = root.text()
            session.accessibility_tree = _a11y_tree(root)
            session.last_action = action.value
            session.updated_at = _utc_now()
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        if action == BrowserAction.SCREENSHOT:
            assert root is not None
            # Honest HTML snapshot — not a framebuffer, labeled as such.
            snapshot = root.serialize()
            meta["screenshot_html"] = snapshot
            meta["screenshot_svg"] = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">'
                f'<foreignObject width="100%" height="100%">'
                f'<div xmlns="http://www.w3.org/1999/xhtml">{html.escape(session.title)}</div>'
                f"</foreignObject></svg>"
            )
            meta["screenshot_sha256"] = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
            meta["screenshot_kind"] = "html_dom_snapshot"
            session.last_action = action.value
            session.updated_at = _utc_now()
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
                mode="dom_snapshot",
            )
            return session, obs, meta

        if action == BrowserAction.CLICK:
            assert root is not None
            target = str(arguments.get("selector") or arguments.get("target") or "")
            nodes = root.find_all(lambda n: _match_selector(n, target)) if target else []
            if not nodes:
                raise ValueError(f"CLICK target not found: {target!r}")
            node = nodes[0]
            # Side effects under DOM mutation — still NOT task completion.
            node.attrs["data-clicked"] = "true"
            if node.tag == "a" and node.attrs.get("href"):
                href = urllib.parse.urljoin(session.url or "", node.attrs["href"])
                meta["navigation_candidate"] = href
            if node.tag == "button" or node.attrs.get("type") == "submit":
                form = self._nearest_form(node)
                if form is not None:
                    meta["form_submit_candidate"] = form.attrs.get("id") or form.attrs.get("name") or "form"
                    form.attrs["data-submitted"] = "true"
            session.dom_text = root.text()
            session.accessibility_tree = _a11y_tree(root)
            session.last_action = action.value
            session.updated_at = _utc_now()
            session.metadata["clicks"] = int(session.metadata.get("clicks", 0)) + 1
            meta["target"] = target
            meta["state_verified"] = False
            meta["requires_verify_state"] = True
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        if action == BrowserAction.TYPE:
            assert root is not None
            text = str(arguments.get("text") or "")
            selector = str(arguments.get("selector") or "input")
            nodes = root.find_all(lambda n: _match_selector(n, selector))
            if not nodes:
                raise ValueError(f"TYPE target not found: {selector!r}")
            node = nodes[0]
            if node.tag in {"input", "textarea"}:
                node.attrs["value"] = text
            else:
                node.children = [text]
            session.dom_text = root.text()
            session.accessibility_tree = _a11y_tree(root)
            session.last_action = action.value
            session.updated_at = _utc_now()
            meta["selector"] = selector
            meta["text_len"] = len(text)
            meta["state_verified"] = False
            meta["requires_verify_state"] = True
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        if action == BrowserAction.FORM_FILL:
            assert root is not None
            fields = dict(arguments.get("fields") or {})
            filled: list[str] = []
            for name, value in fields.items():
                nodes = root.find_all(
                    lambda n, nm=name: n.tag in {"input", "textarea", "select"}
                    and (n.attrs.get("name") == nm or n.attrs.get("id") == nm)
                )
                if not nodes:
                    raise ValueError(f"FORM_FILL field not found: {name!r}")
                nodes[0].attrs["value"] = str(value)
                filled.append(name)
            session.dom_text = root.text()
            session.accessibility_tree = _a11y_tree(root)
            session.last_action = action.value
            session.updated_at = _utc_now()
            meta["filled_fields"] = filled
            meta["requires_verify_state"] = True
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        if action == BrowserAction.DOWNLOAD:
            assert root is not None
            selector = str(arguments.get("selector") or "a[download]")
            nodes = root.find_all(lambda n: _match_selector(n, selector) or (
                n.tag == "a" and ("download" in n.attrs or (n.attrs.get("href") or "").endswith((".pdf", ".csv", ".txt", ".zip")))
            ))
            if not nodes:
                raise ValueError(f"DOWNLOAD target not found: {selector!r}")
            href = nodes[0].attrs.get("href") or ""
            name = nodes[0].attrs.get("download") or Path(urllib.parse.urlparse(href).path).name or "download.bin"
            content, resolved = self._load(urllib.parse.urljoin(session.url or "", href))
            record = {
                "filename": name,
                "url": resolved,
                "bytes": len(content.encode("utf-8")),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            self._downloads.setdefault(session.session_id, []).append(record)
            session.metadata["downloads"] = list(self._downloads[session.session_id])
            session.last_action = action.value
            session.updated_at = _utc_now()
            meta["download"] = record
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        if action == BrowserAction.UPLOAD:
            if not self.allow_uploads:
                raise PermissionError("Uploads not permitted by policy")
            assert root is not None
            selector = str(arguments.get("selector") or "input[type=file]")
            path = str(arguments.get("path") or "")
            if not path:
                raise ValueError("UPLOAD requires path")
            target = Path(path).expanduser()
            if not target.is_file():
                raise FileNotFoundError(f"Upload file not found: {target}")
            nodes = root.find_all(
                lambda n: n.tag == "input" and n.attrs.get("type") == "file" and (
                    not selector or _match_selector(n, selector)
                )
            )
            if not nodes:
                raise ValueError(f"UPLOAD input not found: {selector!r}")
            data = target.read_bytes()
            nodes[0].attrs["value"] = target.name
            nodes[0].attrs["data-uploaded"] = "true"
            record = {
                "filename": target.name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            self._uploads.setdefault(session.session_id, []).append(record)
            session.metadata["uploads"] = list(self._uploads[session.session_id])
            session.dom_text = root.text()
            session.accessibility_tree = _a11y_tree(root)
            session.last_action = action.value
            session.updated_at = _utc_now()
            meta["upload"] = record
            meta["requires_verify_state"] = True
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        if action == BrowserAction.VERIFY_STATE:
            assert root is not None
            predicates = list(arguments.get("predicates") or [])
            # Also accept flat keys: contains_text, selector_exists, attribute_equals
            if arguments.get("contains_text"):
                predicates.append({"contains_text": arguments["contains_text"]})
            if arguments.get("selector_exists"):
                predicates.append({"selector_exists": arguments["selector_exists"]})
            if arguments.get("attribute_equals"):
                predicates.append({"attribute_equals": arguments["attribute_equals"]})
            results: list[dict[str, Any]] = []
            all_ok = True
            for pred in predicates:
                ok, detail = self._check_predicate(root, pred)
                results.append({"predicate": pred, "ok": ok, "detail": detail})
                all_ok = all_ok and ok
            session.last_action = action.value
            session.updated_at = _utc_now()
            session.dom_text = root.text()
            session.accessibility_tree = _a11y_tree(root)
            meta["state_verified"] = True
            meta["verification_passed"] = all_ok
            meta["verification_results"] = results
            if not all_ok:
                meta["verification_failed"] = True
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        if action in {BrowserAction.SCROLL, BrowserAction.WAIT, BrowserAction.KEYPRESS}:
            session.last_action = action.value
            session.updated_at = _utc_now()
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            return session, obs, meta

        raise ValueError(f"Unsupported browser action: {action}")

    def _load(self, url: str) -> tuple[str, str]:
        if url.startswith("data:text/html"):
            # data:text/html,payload or data:text/html;base64,...
            header, _, payload = url.partition(",")
            if ";base64" in header:
                import base64

                return base64.b64decode(payload).decode("utf-8", errors="replace"), url
            return urllib.parse.unquote(payload), url
        if url.startswith("file:"):
            path = Path(urllib.request.url2pathname(urllib.parse.urlparse(url).path))
            path = self._confine_local_path(path)
            return path.read_text(encoding="utf-8", errors="replace"), path.resolve().as_uri()
        # bare path
        path = Path(url)
        if path.exists() and path.is_file():
            path = self._confine_local_path(path)
            return path.read_text(encoding="utf-8", errors="replace"), path.resolve().as_uri()
        if url.startswith("http://") or url.startswith("https://"):
            if not self.allow_network:
                raise PermissionError("Network navigation not permitted (allow_network=False)")
            with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310 — gated by policy
                return resp.read().decode("utf-8", errors="replace"), url
        raise ValueError(f"Unsupported URL for LocalDom backend: {url}")

    def _confine_local_path(self, path: Path) -> Path:
        """Refuse host FS escape when filesystem_root is set (Round 8)."""
        if self.filesystem_root is None:
            return path
        from Data.modules.coding.workspace import confine
        from Data.modules.common.paths import PathEscapeError

        try:
            return confine(self.filesystem_root, path)
        except PathEscapeError as exc:
            raise PermissionError(
                f"file:// path outside filesystem_root refused: {path}"
            ) from exc

    @staticmethod
    def _title(root: _DomNode) -> str:
        titles = root.find_all(lambda n: n.tag == "title")
        if titles:
            return titles[0].text()
        headings = root.find_all(lambda n: n.tag in {"h1", "h2"})
        if headings:
            return headings[0].text()
        return ""

    @staticmethod
    def _nearest_form(node: _DomNode) -> _DomNode | None:
        cur: _DomNode | None = node
        while cur is not None:
            if cur.tag == "form":
                return cur
            cur = cur.parent
        return None

    @staticmethod
    def _check_predicate(root: _DomNode, pred: dict[str, Any]) -> tuple[bool, str]:
        if "contains_text" in pred:
            needle = str(pred["contains_text"])
            ok = needle.lower() in root.text().lower()
            return ok, f"contains_text={needle!r} -> {ok}"
        if "selector_exists" in pred:
            sel = str(pred["selector_exists"])
            found = bool(root.find_all(lambda n: _match_selector(n, sel)))
            return found, f"selector_exists={sel!r} -> {found}"
        if "attribute_equals" in pred:
            spec = pred["attribute_equals"]
            sel = str(spec.get("selector") or "")
            attr = str(spec.get("attr") or "")
            expected = str(spec.get("value") or "")
            nodes = root.find_all(lambda n: _match_selector(n, sel))
            if not nodes:
                return False, f"attribute_equals selector missing: {sel}"
            actual = nodes[0].attrs.get(attr, "")
            ok = actual == expected
            return ok, f"{sel}@{attr}={actual!r} expected {expected!r} -> {ok}"
        if "form_submitted" in pred:
            forms = root.find_all(lambda n: n.tag == "form" and n.attrs.get("data-submitted") == "true")
            ok = bool(forms)
            return ok, f"form_submitted -> {ok}"
        return False, f"unknown predicate: {pred}"
