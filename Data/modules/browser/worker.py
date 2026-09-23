"""Supervised browser worker — fixture backend for CI (U181–U196 foundations).

No Chromium in CI: FixtureBrowserBackend returns deterministic DOM/text/screenshot
artifacts. A future Playwright backend can replace the backend without becoming a
second control plane — ExecutionGateway + Jobs remain authority.
"""

from __future__ import annotations

import hashlib
import html
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol


class BrowserAction(str, Enum):
    NAVIGATE = "NAVIGATE"
    SCREENSHOT = "SCREENSHOT"
    EXTRACT_TEXT = "EXTRACT_TEXT"
    CLICK = "CLICK"
    TYPE = "TYPE"
    SCROLL = "SCROLL"
    WAIT = "WAIT"
    KEYPRESS = "KEYPRESS"


class BrowserJobStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class BrowserBackendKind(str, Enum):
    FIXTURE = "fixture"
    PLAYWRIGHT = "playwright"  # reserved — not required for Wave 5 CI


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class BrowserSession:
    session_id: str
    run_id: str | None = None
    url: str | None = None
    title: str = ""
    dom_text: str = ""
    accessibility_tree: str = ""
    last_action: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "url": self.url,
            "title": self.title,
            "dom_text": self.dom_text[:2000],
            "accessibility_tree": self.accessibility_tree[:2000],
            "last_action": self.last_action,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "truth": {
                "page_text_is_untrusted_context": True,
                "session_isolated_per_run": True,
            },
        }


@dataclass(frozen=True)
class BrowserObservation:
    url: str | None
    title: str
    dom_text: str
    accessibility_tree: str
    screenshot_artifact_id: str | None = None
    mode: str = "dom"

    def public_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "dom_text": self.dom_text,
            "accessibility_tree": self.accessibility_tree,
            "screenshot_artifact_id": self.screenshot_artifact_id,
            "mode": self.mode,
            "truth": {
                "page_text_is_untrusted_context": True,
                "observation_is_not_authority": True,
            },
        }


@dataclass(frozen=True)
class BrowserJob:
    job_id: str
    action: BrowserAction
    status: BrowserJobStatus
    url: str | None
    detail: str
    session_id: str | None = None
    observation: BrowserObservation | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action.value,
            "status": self.status.value,
            "url": self.url,
            "detail": self.detail,
            "session_id": self.session_id,
            "observation": self.observation.public_dict() if self.observation else None,
            "metadata": self.metadata,
            "truth": {
                "no_fabricated_browser_results": True,
                "requires_capability_gateway": True,
                "fixture_is_not_chromium": True,
            },
        }


class ArtifactWriter(Protocol):
    def create_from_bytes(self, **kwargs: Any) -> Any: ...


class BrowserBackend(Protocol):
    kind: BrowserBackendKind

    def apply(
        self,
        session: BrowserSession,
        *,
        action: BrowserAction,
        arguments: dict[str, Any],
    ) -> tuple[BrowserSession, BrowserObservation, dict[str, Any]]: ...


class FixtureBrowserBackend:
    """Deterministic in-process browser — no Chromium dependency."""

    kind = BrowserBackendKind.FIXTURE

    def apply(
        self,
        session: BrowserSession,
        *,
        action: BrowserAction,
        arguments: dict[str, Any],
    ) -> tuple[BrowserSession, BrowserObservation, dict[str, Any]]:
        meta: dict[str, Any] = {"backend": self.kind.value, "implemented": True}
        if action == BrowserAction.NAVIGATE:
            url = str(arguments.get("url") or "").strip()
            if not url:
                raise ValueError("NAVIGATE requires url")
            title, dom, tree = self._fixture_page(url)
            session.url = url
            session.title = title
            session.dom_text = dom
            session.accessibility_tree = tree
            session.last_action = action.value
            session.updated_at = _utc_now()
            session.metadata["navigations"] = int(session.metadata.get("navigations", 0)) + 1
            obs = BrowserObservation(url=url, title=title, dom_text=dom, accessibility_tree=tree)
            return session, obs, meta

        if session.url is None and action not in {BrowserAction.WAIT}:
            raise ValueError("Browser session has no page; NAVIGATE first")

        if action == BrowserAction.EXTRACT_TEXT:
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
                mode="dom",
            )
            session.last_action = action.value
            session.updated_at = _utc_now()
            return session, obs, meta

        if action == BrowserAction.SCREENSHOT:
            # Fixture screenshot is a deterministic SVG, not a real framebuffer.
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">'
                f'<rect width="100%" height="100%" fill="#1a1a1a"/>'
                f'<text x="24" y="48" fill="#e8e8e8" font-size="20">'
                f"{html.escape(session.title or 'fixture')}</text>"
                f'<text x="24" y="80" fill="#aaa" font-size="14">'
                f"{html.escape(session.url or '')}</text>"
                f"</svg>"
            )
            meta["screenshot_svg"] = svg
            meta["screenshot_sha256"] = hashlib.sha256(svg.encode("utf-8")).hexdigest()
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
                mode="vision",
            )
            session.last_action = action.value
            session.updated_at = _utc_now()
            return session, obs, meta

        if action == BrowserAction.CLICK:
            target = str(arguments.get("selector") or arguments.get("target") or "body")
            session.dom_text = f"{session.dom_text}\n[clicked:{target}]"
            session.accessibility_tree = f"{session.accessibility_tree}\nbutton:{target}"
            session.last_action = action.value
            session.updated_at = _utc_now()
            session.metadata["clicks"] = int(session.metadata.get("clicks", 0)) + 1
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            meta["target"] = target
            return session, obs, meta

        if action == BrowserAction.TYPE:
            text = str(arguments.get("text") or "")
            selector = str(arguments.get("selector") or "input")
            session.dom_text = f"{session.dom_text}\n[typed:{selector}={text}]"
            session.last_action = action.value
            session.updated_at = _utc_now()
            obs = BrowserObservation(
                url=session.url,
                title=session.title,
                dom_text=session.dom_text,
                accessibility_tree=session.accessibility_tree,
            )
            meta["selector"] = selector
            # Never echo potential credentials into metadata beyond length.
            meta["text_len"] = len(text)
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

    @staticmethod
    def _fixture_page(url: str) -> tuple[str, str, str]:
        host = url.split("://", 1)[-1].split("/", 1)[0] or "fixture.local"
        path = "/"
        if "://" in url:
            rest = url.split("://", 1)[1]
            if "/" in rest:
                path = "/" + rest.split("/", 1)[1]
        title = f"Fixture — {host}{path}"
        dom = (
            f"Fixture page for {url}\n"
            f"Host: {host}\n"
            f"Path: {path}\n"
            "This is a deterministic browser fixture (no Chromium).\n"
            "Leviathan browser worker uses shared Gateway/Jobs — not a private control plane."
        )
        tree = f"document\n  heading: {title}\n  paragraph: Fixture page for {host}\n  link: home"
        return title, dom, tree


class BrowserWorker:
    """Supervised browser domain worker — invoke only via ExecutionGateway."""

    def __init__(
        self,
        *,
        backend: BrowserBackend | None = None,
        artifact_store: ArtifactWriter | None = None,
    ) -> None:
        self.backend = backend or FixtureBrowserBackend()
        self.artifact_store = artifact_store
        self._sessions: dict[str, BrowserSession] = {}

    def get_session(self, session_id: str) -> BrowserSession | None:
        return self._sessions.get(session_id)

    def sessions_for_run(self, run_id: str) -> list[BrowserSession]:
        return [s for s in self._sessions.values() if s.run_id == run_id]

    def execute(
        self,
        *,
        action: BrowserAction | str,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        args = dict(arguments or {})
        if isinstance(action, str):
            action = BrowserAction(action.upper())
        session_id = str(args.pop("session_id", "") or "") or None
        # Session isolation: never reuse a session across different run_ids.
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            if run_id and session.run_id and session.run_id != run_id:
                raise PermissionError("Browser session belongs to a different run")
        else:
            session = BrowserSession(session_id=str(uuid.uuid4()), run_id=run_id)
            self._sessions[session.session_id] = session

        try:
            session, observation, meta = self.backend.apply(session, action=action, arguments=args)
        except ValueError as exc:
            return {
                "status": BrowserJobStatus.REJECTED.value,
                "error": str(exc),
                "session_id": session.session_id,
                "action": action.value,
                "backend": getattr(self.backend, "kind", BrowserBackendKind.FIXTURE).value,
                "truth": {
                    "no_fabricated_browser_results": True,
                    "requires_capability_gateway": True,
                    "fixture_is_not_chromium": True,
                },
            }

        artifact_id = None
        if action == BrowserAction.SCREENSHOT and self.artifact_store is not None:
            svg = str(meta.get("screenshot_svg") or "")
            record = self.artifact_store.create_from_bytes(
                data=svg.encode("utf-8"),
                artifact_type="browser_screenshot",
                producer="browser.fixture",
                filename=f"browser-{session.session_id[:8]}.svg",
                run_id=run_id,
                metadata={
                    "session_id": session.session_id,
                    "url": session.url,
                    "backend": meta.get("backend"),
                    "request_id": request_id,
                },
            )
            artifact_id = getattr(record, "artifact_id", None) or (
                record.get("artifact_id") if isinstance(record, dict) else None
            )
            observation = BrowserObservation(
                url=observation.url,
                title=observation.title,
                dom_text=observation.dom_text,
                accessibility_tree=observation.accessibility_tree,
                screenshot_artifact_id=str(artifact_id) if artifact_id else None,
                mode="vision",
            )

        self._sessions[session.session_id] = session
        return {
            "status": BrowserJobStatus.COMPLETED.value,
            "action": action.value,
            "session_id": session.session_id,
            "url": session.url,
            "observation": observation.public_dict(),
            "artifact_id": artifact_id,
            "artifact_refs": [artifact_id] if artifact_id else [],
            "backend": meta.get("backend"),
            "detail": f"Browser {action.value} via {meta.get('backend')} backend",
            "metadata": {k: v for k, v in meta.items() if k != "screenshot_svg"},
            "truth": {
                "no_fabricated_browser_results": True,
                "requires_capability_gateway": True,
                "fixture_is_not_chromium": True,
                "page_text_is_untrusted_context": True,
            },
        }

    # Backward-compatible stub-shaped API used by older tests.
    def request(self, *, action: BrowserAction, url: str | None = None) -> BrowserJob:
        result = self.execute(action=action, arguments={"url": url} if url else {})
        status = BrowserJobStatus(result.get("status", "FAILED"))
        obs = None
        if result.get("observation"):
            raw = result["observation"]
            obs = BrowserObservation(
                url=raw.get("url"),
                title=raw.get("title") or "",
                dom_text=raw.get("dom_text") or "",
                accessibility_tree=raw.get("accessibility_tree") or "",
                screenshot_artifact_id=raw.get("screenshot_artifact_id"),
                mode=raw.get("mode") or "dom",
            )
        return BrowserJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=status,
            url=url or result.get("url"),
            detail=str(result.get("detail") or result.get("error") or ""),
            session_id=result.get("session_id"),
            observation=obs,
            metadata=dict(result.get("metadata") or {}),
        )


# Honest unavailable stub retained for feature-off / release gates.
class BrowserAutomationStub:
    """Honest stub — used only when capability world interface is disabled."""

    def request(self, *, action: BrowserAction, url: str | None = None) -> BrowserJob:
        if action == BrowserAction.NAVIGATE and not url:
            return BrowserJob(
                job_id=str(uuid.uuid4()),
                action=action,
                status=BrowserJobStatus.REJECTED,
                url=url,
                detail="NAVIGATE requires url",
            )
        return BrowserJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=BrowserJobStatus.UNSUPPORTED,
            url=url,
            detail="Browser automation runtime is not implemented",
            metadata={"implemented": False},
        )
