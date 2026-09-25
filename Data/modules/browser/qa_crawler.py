"""Localhost human-journey QA crawler — BrowserJourneyCrawler (GI9/GI10).

Runs inside the browser domain using BrowserWorker / Playwright|LocalDom.
JobRuntime owns long runs. No CrawlerRuntime2 / private crawler DB.
"""

from __future__ import annotations

import hashlib
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_report_key(store: dict[str, Any], ref: str) -> str | None:
    """Resolve a run_id or journey_id to the canonical run_id key."""
    if ref in store:
        return ref
    for run_id, report in store.items():
        if getattr(report, "journey_id", None) == ref:
            return run_id
    return None


class JourneyPersona(str, Enum):
    DESKTOP_MOUSE = "DESKTOP_MOUSE"
    KEYBOARD_ONLY = "KEYBOARD_ONLY"
    MOBILE_VIEWPORT = "MOBILE_VIEWPORT"
    RETURNING_USER = "RETURNING_USER"


class CrawlStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    LIMIT_REACHED = "LIMIT_REACHED"


_DESTRUCTIVE_PATTERNS = re.compile(
    r"(delete\s+account|drop\s+database|factory\s+reset|purchase|buy\s+now|"
    r"charge|unsubscribe\s+permanently|wipe|destroy)",
    re.I,
)


@dataclass
class CrawlBudget:
    max_pages: int = 50
    max_actions: int = 200
    max_depth: int = 8
    max_wall_time_seconds: float = 300.0
    max_forms: int = 20
    max_navigation_failures: int = 10
    max_repeat_state: int = 3
    max_console_errors_collected: int = 100
    max_network_events_collected: int = 200


@dataclass
class CrawlIssue:
    issue_id: str
    severity: str  # critical | high | medium | low | info
    kind: str
    message: str
    url: str | None = None
    reproduction: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "severity": self.severity,
            "kind": self.kind,
            "message": self.message,
            "url": self.url,
            "reproduction": list(self.reproduction),
            "artifact_refs": list(self.artifact_refs),
            "metadata": dict(self.metadata),
        }


@dataclass
class StateNode:
    fingerprint: str
    url: str
    depth: int
    visit_count: int = 1


@dataclass
class CrawlReport:
    run_id: str
    journey_id: str
    trace_id: str
    status: CrawlStatus
    start_url: str
    persona: JourneyPersona
    pages_visited: int = 0
    actions_performed: int = 0
    issues: list[CrawlIssue] = field(default_factory=list)
    console_issues: list[dict[str, Any]] = field(default_factory=list)
    network_issues: list[dict[str, Any]] = field(default_factory=list)
    accessibility_observations: list[dict[str, Any]] = field(default_factory=list)
    performance_observations: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    reproduction_journeys: list[list[str]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    seed: int = 0
    created_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None
    error: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "journey_id": self.journey_id,
            "trace_id": self.trace_id,
            "status": self.status.value,
            "start_url": self.start_url,
            "persona": self.persona.value,
            "pages_visited": self.pages_visited,
            "actions_performed": self.actions_performed,
            "issues": [i.public_dict() for i in self.issues],
            "console_issues": list(self.console_issues),
            "network_issues": list(self.network_issues),
            "accessibility_observations": list(self.accessibility_observations),
            "performance_observations": list(self.performance_observations),
            "screenshots": list(self.screenshots),
            "reproduction_journeys": list(self.reproduction_journeys),
            "coverage": dict(self.coverage),
            "seed": self.seed,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "checkpoint": dict(self.checkpoint),
            "truth": {
                "localhost_scoped_by_default": True,
                "no_stealth_evasion": True,
                "no_stealth_anti_bot": True,
                "not_a_second_browser_runtime": True,
                "no_private_crawler_db": True,
                "cancelled_is_not_success": True,
                "page_text_is_untrusted_context": True,
                "a11y_is_observation_not_wcag_certification": True,
                "personas_are_config_not_llm_agents": True,
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
            },
        }

    def markdown(self) -> str:
        lines = [
            f"# QA Crawl Report — {self.journey_id}",
            "",
            f"- Status: **{self.status.value}**",
            f"- Start: `{self.start_url}`",
            f"- Persona: {self.persona.value}",
            f"- Pages: {self.pages_visited}",
            f"- Actions: {self.actions_performed}",
            f"- Issues: {len(self.issues)}",
            f"- Seed: {self.seed}",
            "",
            "## Issues",
        ]
        if not self.issues:
            lines.append("_None detected._")
        for issue in self.issues:
            lines.append(f"### [{issue.severity}] {issue.kind}")
            lines.append(issue.message)
            if issue.reproduction:
                lines.append("Reproduction:")
                for step in issue.reproduction:
                    lines.append(f"1. {step}" if not step[:1].isdigit() else f"- {step}")
            lines.append("")
        return "\n".join(lines)


class HostNotAllowed(Exception):
    error_code = "CRAWLER_TARGET_NOT_ALLOWED"


class BrowserJourneyCrawler:
    """Deterministic localhost user-journey crawler over BrowserWorker actions."""

    def __init__(
        self,
        *,
        browser_worker: Any,
        artifact_store: Any | None = None,
        allowed_hosts: tuple[str, ...] | None = None,
        budget: CrawlBudget | None = None,
        allow_destructive: bool = False,
        allow_form_submit: bool = True,
        observability: Any | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.browser_worker = browser_worker
        self.artifact_store = artifact_store
        self.allowed_hosts = tuple(
            h.lower()
            for h in (
                allowed_hosts
                or ("localhost", "127.0.0.1", "::1")
            )
        )
        self.budget = budget or CrawlBudget()
        self.allow_destructive = bool(allow_destructive)
        self.allow_form_submit = bool(allow_form_submit)
        self.observability = observability
        self._sleep = sleep_fn or time.sleep
        self._runs: dict[str, CrawlReport] = {}
        self._cancel: set[str] = set()

    def assert_host_allowed(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if host not in self.allowed_hosts:
            raise HostNotAllowed(
                f"QA crawler target host not allowed: {host!r} "
                f"(allowed={list(self.allowed_hosts)})"
            )

    def start(
        self,
        *,
        start_url: str,
        persona: JourneyPersona | str = JourneyPersona.DESKTOP_MOUSE,
        seed: int = 42,
        run_id: str | None = None,
        journey_id: str | None = None,
        trace_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> CrawlReport:
        self.assert_host_allowed(start_url)
        persona_e = (
            persona if isinstance(persona, JourneyPersona) else JourneyPersona(str(persona))
        )
        run_id = run_id or f"qa_{uuid.uuid4().hex[:12]}"
        journey_id = journey_id or f"journey_{uuid.uuid4().hex[:10]}"
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:10]}"
        report = CrawlReport(
            run_id=run_id,
            journey_id=journey_id,
            trace_id=trace_id,
            status=CrawlStatus.ACCEPTED,
            start_url=start_url,
            persona=persona_e,
            seed=int(seed),
        )
        self._runs[run_id] = report
        self._emit("crawler.started", {"run_id": run_id, "url": start_url})
        return report

    def cancel(self, run_id: str) -> CrawlReport:
        key = _resolve_report_key(self._runs, run_id)
        if key is None:
            raise KeyError(run_id)
        self._cancel.add(key)
        report = self._runs[key]
        if report.status in {CrawlStatus.ACCEPTED, CrawlStatus.RUNNING}:
            report.status = CrawlStatus.CANCELLED
            report.finished_at = _utc_now()
            self._flush_artifacts(report)
            self._emit("crawler.cancelled", {"run_id": key})
        return report

    def status(self, run_id: str) -> CrawlReport:
        key = _resolve_report_key(self._runs, run_id)
        if key is None:
            raise KeyError(run_id)
        return self._runs[key]

    def run(
        self,
        *,
        start_url: str | None = None,
        run_id: str | None = None,
        persona: JourneyPersona | str = JourneyPersona.DESKTOP_MOUSE,
        seed: int = 42,
        resume_checkpoint: dict[str, Any] | None = None,
    ) -> CrawlReport:
        if run_id and run_id in self._runs:
            report = self._runs[run_id]
        else:
            report = self.start(
                start_url=start_url or (resume_checkpoint or {}).get("url") or "",
                persona=persona,
                seed=seed,
                run_id=run_id,
            )
        if report.status == CrawlStatus.CANCELLED:
            return report
        report.status = CrawlStatus.RUNNING
        rng = random.Random(report.seed)
        started = time.monotonic()
        session_id: str | None = None
        path: list[str] = []
        graph: dict[str, StateNode] = {}
        forms_filled = 0
        nav_failures = 0

        try:
            nav = self._action(
                "NAVIGATE",
                {"url": report.start_url, "headers": self._qa_headers(report)},
                run_id=report.run_id,
            )
            session_id = str((nav.get("session") or {}).get("session_id") or nav.get("session_id") or "")
            path.append(f"Navigate {report.start_url}")
            report.actions_performed += 1
            report.pages_visited = 1
            self._ingest_observation(report, nav, path)

            while True:
                if report.run_id in self._cancel:
                    report.status = CrawlStatus.CANCELLED
                    break
                if report.pages_visited >= self.budget.max_pages:
                    report.status = CrawlStatus.LIMIT_REACHED
                    report.error = "CRAWLER_LIMIT_REACHED:max_pages"
                    break
                if report.actions_performed >= self.budget.max_actions:
                    report.status = CrawlStatus.LIMIT_REACHED
                    report.error = "CRAWLER_LIMIT_REACHED:max_actions"
                    break
                if (time.monotonic() - started) >= self.budget.max_wall_time_seconds:
                    report.status = CrawlStatus.LIMIT_REACHED
                    report.error = "CRAWLER_LIMIT_REACHED:max_wall_time"
                    break

                obs = (nav.get("observation") or nav.get("result") or {})
                url = str(obs.get("url") or report.start_url)
                fp = self._fingerprint(url, obs)
                node = graph.get(fp)
                if node:
                    node.visit_count += 1
                    if node.visit_count > self.budget.max_repeat_state:
                        report.issues.append(
                            CrawlIssue(
                                issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                                severity="medium",
                                kind="infinite_navigation_loop",
                                message=f"Repeated state fingerprint {fp[:12]}…",
                                url=url,
                                reproduction=list(path),
                            )
                        )
                        break
                else:
                    graph[fp] = StateNode(fingerprint=fp, url=url, depth=len(path))

                candidates = self._candidate_actions(
                    obs, persona=report.persona, base_url=url
                )
                if not candidates:
                    break
                action_spec = candidates[rng.randrange(0, len(candidates))]
                if self._is_destructive(action_spec) and not self.allow_destructive:
                    continue
                if action_spec.get("kind") == "FORM_FILL" and forms_filled >= self.budget.max_forms:
                    continue

                # Pre-navigate HTTP probe for link targets (broken/5xx detection).
                target_url = action_spec.get("target_url")
                if target_url:
                    try:
                        self.assert_host_allowed(str(target_url))
                    except HostNotAllowed:
                        report.issues.append(
                            CrawlIssue(
                                issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                                severity="info",
                                kind="scope_blocked",
                                message=f"Blocked non-localhost navigation: {target_url}",
                                url=str(target_url),
                                reproduction=list(path),
                            )
                        )
                        continue
                    probe = self._probe_http(str(target_url), report)
                    code = probe.get("status")
                    if isinstance(code, int) and code >= 400:
                        kind = (
                            "broken_link"
                            if code == 404
                            else (f"http_{code}" if code < 500 else f"http_{code}")
                        )
                        report.issues.append(
                            CrawlIssue(
                                issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                                severity="critical" if code >= 500 else "high",
                                kind=kind,
                                message=f"HTTP {code} for {target_url}",
                                url=str(target_url),
                                reproduction=list(path),
                                metadata=probe,
                            )
                        )
                        self._capture_failure(report, {"error": f"HTTP {code}"}, path, str(target_url))
                        continue
                    if probe.get("error") and probe.get("status") is None:
                        report.issues.append(
                            CrawlIssue(
                                issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                                severity="high",
                                kind="timeout" if "timed out" in str(probe.get("error")).lower() else "broken_link",
                                message=str(probe.get("error")),
                                url=str(target_url),
                                reproduction=list(path),
                                metadata=probe,
                            )
                        )
                        continue

                self._pace(rng)
                try:
                    nav = self._action(
                        action_spec["action"],
                        {**action_spec.get("arguments", {}), "session_id": session_id},
                        run_id=report.run_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    nav_failures += 1
                    report.issues.append(
                        CrawlIssue(
                            issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                            severity="high",
                            kind="action_failed",
                            message=str(exc),
                            url=url,
                            reproduction=list(path) + [action_spec.get("label", "action")],
                        )
                    )
                    if nav_failures >= self.budget.max_navigation_failures:
                        break
                    continue

                report.actions_performed += 1
                path.append(str(action_spec.get("label") or action_spec["action"]))
                if action_spec.get("kind") == "FORM_FILL":
                    forms_filled += 1
                status = str(nav.get("status") or "").upper()
                if status in {"FAILED", "REJECTED"}:
                    nav_failures += 1
                    self._capture_failure(report, nav, path, url)
                else:
                    new_url = str(
                        ((nav.get("observation") or {}).get("url"))
                        or ((nav.get("session") or {}).get("url"))
                        or url
                    )
                    if new_url != url:
                        report.pages_visited += 1
                    self._ingest_observation(report, nav, path)
                    # Mutation verification when required.
                    if bool(nav.get("requires_verify_state")) or status == "APPLIED_UNVERIFIED":
                        verify = self._action(
                            "VERIFY_STATE",
                            {"session_id": session_id},
                            run_id=report.run_id,
                        )
                        report.actions_performed += 1
                        if str(verify.get("status") or "").upper() not in {"COMPLETED", "OK", "PASSED"}:
                            report.issues.append(
                                CrawlIssue(
                                    issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                                    severity="medium",
                                    kind="browser_state_unverified",
                                    message="Mutation applied but VERIFY_STATE did not confirm expected state",
                                    url=new_url,
                                    reproduction=list(path),
                                )
                            )

            if report.status == CrawlStatus.RUNNING:
                report.status = CrawlStatus.COMPLETED
        except HostNotAllowed as exc:
            report.status = CrawlStatus.FAILED
            report.error = f"CRAWLER_TARGET_NOT_ALLOWED: {exc}"
        except Exception as exc:  # noqa: BLE001
            report.status = CrawlStatus.FAILED
            report.error = str(exc)
            self._capture_failure(report, {}, path, report.start_url)
        finally:
            report.finished_at = _utc_now()
            report.coverage = {
                "states": len(graph),
                "pages_visited": report.pages_visited,
                "actions_performed": report.actions_performed,
                "forms_filled": forms_filled,
            }
            report.reproduction_journeys = [path] if path else []
            report.checkpoint = {
                "url": report.start_url,
                "pages_visited": report.pages_visited,
                "actions_performed": report.actions_performed,
                "seed": report.seed,
            }
            self._flush_artifacts(report)
            self._emit(
                "crawler.completed" if report.status == CrawlStatus.COMPLETED else "crawler.issue",
                {"run_id": report.run_id, "status": report.status.value, "issues": len(report.issues)},
            )
        return report

    def replay(self, run_id: str) -> CrawlReport:
        prior = self.status(run_id)
        return self.run(
            start_url=prior.start_url,
            persona=prior.persona,
            seed=prior.seed,
        )

    def report_artifact(self, run_id: str) -> dict[str, Any]:
        report = self.status(run_id)
        payload: dict[str, Any] = {"json": report.public_dict(), "markdown": report.markdown()}
        if self.artifact_store is not None:
            try:
                data = report.markdown().encode("utf-8")
                meta = {"kind": "qa_crawl_report", "run_id": report.run_id}
                if hasattr(self.artifact_store, "create_from_bytes"):
                    art = self.artifact_store.create_from_bytes(
                        data=data,
                        artifact_type="browser_qa_report_md",
                        producer="browser.qa.report",
                        filename=f"qa-report-{report.journey_id}.md",
                        run_id=report.run_id,
                        metadata=meta,
                    )
                    payload["artifact_id"] = getattr(art, "artifact_id", None) or (
                        art.get("artifact_id") if isinstance(art, dict) else str(art)
                    )
                elif hasattr(self.artifact_store, "put_bytes"):
                    art = self.artifact_store.put_bytes(
                        data, media_type="text/markdown", metadata=meta
                    )
                    payload["artifact_id"] = getattr(art, "artifact_id", None) or str(art)
            except Exception:  # noqa: BLE001
                pass
        return payload

    # --- internals ---------------------------------------------------------

    def _qa_headers(self, report: CrawlReport) -> dict[str, str]:
        return {
            "X-Leviathan-QA-Run": report.run_id,
            "X-Leviathan-Trace": report.trace_id,
        }

    def _action(self, action: str, arguments: dict[str, Any], *, run_id: str) -> dict[str, Any]:
        return self.browser_worker.execute(
            action=action,
            arguments=arguments,
            run_id=run_id,
            request_id=f"qa_{uuid.uuid4().hex[:8]}",
        )

    def _pace(self, rng: random.Random) -> None:
        delay = rng.uniform(0.1, 0.7)
        self._sleep(delay)

    def _fingerprint(self, url: str, obs: dict[str, Any]) -> str:
        dom = str(obs.get("dom_text") or obs.get("text") or "")[:2000]
        interactive = str(obs.get("interactive_elements") or obs.get("accessibility_tree") or "")[:1000]
        raw = f"{urlparse(url).path}|{hashlib.sha256(dom.encode()).hexdigest()[:12]}|{hashlib.sha256(interactive.encode()).hexdigest()[:12]}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _candidate_actions(
        self, obs: dict[str, Any], *, persona: JourneyPersona, base_url: str = ""
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        elements = obs.get("interactive_elements") or []
        if isinstance(elements, list):
            for el in elements[:40]:
                if not isinstance(el, dict):
                    continue
                tag = str(el.get("tag") or el.get("role") or "").lower()
                name = str(
                    el.get("name")
                    or el.get("text")
                    or el.get("label")
                    or el.get("ariaLabel")
                    or ""
                )
                el_id = str(el.get("id") or "")
                el_name = str(el.get("name") or "")
                href = str(el.get("href") or "")
                selector = (
                    el.get("selector")
                    or el.get("css")
                    or el.get("test_id")
                    or (f"#{el_id}" if el_id else None)
                    or (f'[name="{el_name}"]' if el_name else None)
                    or (f"text={name}" if name else None)
                )
                if tag in {"a", "link"} or el.get("role") == "link" or href:
                    abs_url = urljoin(base_url, href) if href else None
                    if abs_url and not href.startswith(("#", "javascript:")):
                        out.append(
                            {
                                "action": "NAVIGATE",
                                "arguments": {"url": abs_url},
                                "label": f"Navigate {abs_url}",
                                "kind": "NAV",
                                "target_url": abs_url,
                            }
                        )
                    elif selector:
                        if persona == JourneyPersona.KEYBOARD_ONLY:
                            out.append(
                                {
                                    "action": "KEYPRESS",
                                    "arguments": {"key": "Enter", "selector": selector},
                                    "label": f"Keyboard activate {name or selector}",
                                    "kind": "NAV",
                                }
                            )
                        else:
                            out.append(
                                {
                                    "action": "CLICK",
                                    "arguments": {"selector": selector},
                                    "label": f"Click {name or selector}",
                                    "kind": "NAV",
                                }
                            )
                    continue
                if not selector:
                    continue
                if tag in {"button"} or el.get("role") == "button":
                    if persona == JourneyPersona.KEYBOARD_ONLY:
                        out.append(
                            {
                                "action": "KEYPRESS",
                                "arguments": {"key": "Enter", "selector": selector},
                                "label": f"Keyboard activate {name or selector}",
                                "kind": "NAV",
                            }
                        )
                    else:
                        out.append(
                            {
                                "action": "CLICK",
                                "arguments": {"selector": selector},
                                "label": f"Click {name or selector}",
                                "kind": "NAV",
                            }
                        )
                if tag in {"input", "textarea"} or el.get("role") == "textbox":
                    value = self._synthetic_value(el)
                    out.append(
                        {
                            "action": "TYPE",
                            "arguments": {"selector": selector, "text": value},
                            "label": f"Type into {name or selector}",
                            "kind": "FORM_FILL",
                        }
                    )
        # Always allow a gentle scroll to reveal lazy content.
        out.append(
            {
                "action": "SCROLL",
                "arguments": {"direction": "down", "amount": 400},
                "label": "Scroll down",
                "kind": "SCROLL",
            }
        )
        return out

    def _probe_http(self, url: str, report: CrawlReport) -> dict[str, Any]:
        """Bounded localhost HTTP probe with header redaction."""
        if len(report.network_issues) >= self.budget.max_network_events_collected:
            return {"skipped": True}
        headers = self._qa_headers(report)
        req = Request(url, headers=headers, method="GET")
        t0 = time.perf_counter()
        try:
            with urlopen(req, timeout=5) as resp:  # noqa: S310 — localhost-scoped
                body = resp.read(2048)
                event = {
                    "url": url,
                    "status": getattr(resp, "status", None),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "bytes": len(body),
                }
                report.network_issues.append(event)
                return event
        except HTTPError as exc:
            event = {
                "url": url,
                "status": exc.code,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                "error": str(exc.reason),
            }
            report.network_issues.append(event)
            return event
        except (URLError, TimeoutError, OSError) as exc:
            event = {
                "url": url,
                "status": None,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                "error": str(exc),
            }
            report.network_issues.append(event)
            return event

    def _synthetic_value(self, el: dict[str, Any]) -> str:
        kind = str(el.get("type") or el.get("name") or el.get("label") or el.get("id") or "").lower()
        run = uuid.uuid4().hex[:6]
        if "email" in kind:
            return f"qa+{run}@example.invalid"
        if "phone" in kind or "tel" in kind:
            return "+15550100"
        if "pass" in kind:
            return f"QaTest-{run}-!"
        if "search" in kind:
            return "leviathan qa"
        if "number" in kind:
            return "42"
        if "name" in kind:
            return "Leviathan QA User"
        return f"qa-value-{run}"

    def _is_destructive(self, action_spec: dict[str, Any]) -> bool:
        blob = f"{action_spec.get('label') or ''} {action_spec.get('arguments') or ''}"
        return bool(_DESTRUCTIVE_PATTERNS.search(blob))

    def _ingest_observation(
        self, report: CrawlReport, payload: dict[str, Any], path: list[str]
    ) -> None:
        obs = payload.get("observation") or payload.get("result") or {}
        url = obs.get("url")
        # Console / page errors
        for err in (obs.get("console_errors") or obs.get("page_errors") or [])[:20]:
            entry = err if isinstance(err, dict) else {"message": str(err)}
            key = str(entry.get("message") or entry)
            existing = next((c for c in report.console_issues if c.get("message") == key), None)
            if existing:
                existing["count"] = int(existing.get("count") or 1) + 1
            else:
                if len(report.console_issues) < self.budget.max_console_errors_collected:
                    report.console_issues.append(
                        {
                            "message": key,
                            "count": 1,
                            "url": url,
                            "action": path[-1] if path else None,
                        }
                    )
                    report.issues.append(
                        CrawlIssue(
                            issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                            severity="high",
                            kind="console_error",
                            message=key[:500],
                            url=str(url) if url else None,
                            reproduction=list(path),
                        )
                    )
        for net in (
            list(obs.get("network_failures") or [])
            + list(obs.get("failed_requests") or [])
            + list(obs.get("network_errors") or [])
        )[:20]:
            if len(report.network_issues) >= self.budget.max_network_events_collected:
                break
            entry = net if isinstance(net, dict) else {"url": str(net), "message": str(net)}
            # Redact secrets
            safe = {
                k: v
                for k, v in entry.items()
                if k.lower() not in {"authorization", "cookie", "token", "password"}
            }
            report.network_issues.append(safe)
            status = int(safe.get("status") or 0)
            if status >= 400:
                report.issues.append(
                    CrawlIssue(
                        issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                        severity="critical" if status >= 500 else "high",
                        kind=f"http_{status}",
                        message=f"HTTP {status} for {safe.get('url')}",
                        url=str(safe.get("url") or url or ""),
                        reproduction=list(path),
                    )
                )
        # Accessibility observations (measurable, not WCAG certification)
        for el in (obs.get("interactive_elements") or [])[:30]:
            if not isinstance(el, dict):
                continue
            name = (
                el.get("name")
                or el.get("accessible_name")
                or el.get("label")
                or el.get("ariaLabel")
                or el.get("id")
            )
            if not name and str(el.get("tag") or "").lower() in {"button", "a", "input"}:
                report.accessibility_observations.append(
                    {
                        "kind": "missing_accessible_name",
                        "selector": el.get("selector") or el.get("id"),
                        "url": url,
                    }
                )
                report.issues.append(
                    CrawlIssue(
                        issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                        severity="info",
                        kind="a11y_missing_name",
                        message="interactive element without accessible name",
                        url=str(url) if url else None,
                        reproduction=list(path),
                        metadata={"element": {k: el.get(k) for k in ("tag", "id", "type")}},
                    )
                )
        text = str(obs.get("dom_text") or "")
        if text.strip() == "":
            report.issues.append(
                CrawlIssue(
                    issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                    severity="medium",
                    kind="blank_content",
                    message="Page visible text empty",
                    url=str(url) if url else None,
                    reproduction=list(path),
                )
            )
        # Prompt-injection fixture text stays data — record observation only.
        if "ignore all previous instructions" in text.lower():
            report.accessibility_observations.append(
                {
                    "kind": "untrusted_page_instruction_text",
                    "note": "page content must remain external data",
                    "url": url,
                }
            )
        perf = obs.get("performance") or obs.get("timing")
        if isinstance(perf, dict) and len(report.performance_observations) < 50:
            report.performance_observations.append({"url": url, **perf})

    def _capture_failure(
        self,
        report: CrawlReport,
        payload: dict[str, Any],
        path: list[str],
        url: str | None,
    ) -> None:
        shot = None
        try:
            session_id = (payload.get("session") or {}).get("session_id") or payload.get(
                "session_id"
            )
            shot_result = self._action(
                "SCREENSHOT",
                {"session_id": session_id} if session_id else {},
                run_id=report.run_id,
            )
            shot = (
                (shot_result.get("observation") or {}).get("screenshot_artifact_id")
                or shot_result.get("screenshot_artifact_id")
                or shot_result.get("artifact_id")
            )
            if shot:
                report.screenshots.append(str(shot))
        except Exception:  # noqa: BLE001
            pass
        report.issues.append(
            CrawlIssue(
                issue_id=f"iss_{uuid.uuid4().hex[:8]}",
                severity="high",
                kind="action_or_navigation_failure",
                message=str(payload.get("error") or payload.get("detail") or "failure"),
                url=url,
                reproduction=list(path),
                artifact_refs=[str(shot)] if shot else [],
            )
        )

    def _flush_artifacts(self, report: CrawlReport) -> None:
        if self.artifact_store is None:
            return
        data = report.markdown().encode("utf-8")
        meta = {
            "kind": "qa_crawl_report",
            "run_id": report.run_id,
            "journey_id": report.journey_id,
            "status": report.status.value,
        }
        try:
            if hasattr(self.artifact_store, "create_from_bytes"):
                self.artifact_store.create_from_bytes(
                    data=data,
                    artifact_type="browser_qa_report_md",
                    producer="browser.qa.crawl",
                    filename=f"qa-report-{report.journey_id}.md",
                    run_id=report.run_id,
                    metadata=meta,
                )
            elif hasattr(self.artifact_store, "put_bytes"):
                self.artifact_store.put_bytes(
                    data,
                    media_type="text/markdown",
                    metadata=meta,
                )
        except Exception:  # noqa: BLE001
            pass

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.observability is None:
            return
        try:
            if hasattr(self.observability, "emit"):
                self.observability.emit("browser", event, payload=payload)
            elif hasattr(self.observability, "record"):
                self.observability.record(event, payload)
        except Exception:  # noqa: BLE001
            pass


# Compatibility aliases
LocalUserJourneyCrawler = BrowserJourneyCrawler
CrawlBudgets = CrawlBudget
JourneyReport = CrawlReport


# --- Compatibility surface expected by BrowserWorker._execute_qa (GI9) -----

_DEFAULT_LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass
class CrawlBudgets:
    max_pages: int = 40
    max_actions: int = 120
    max_depth: int = 6
    max_wall_time_s: float = 90.0
    max_forms: int = 12
    jitter_min_ms: int = 100
    jitter_max_ms: int = 700

    def to_budget(self) -> CrawlBudget:
        return CrawlBudget(
            max_pages=self.max_pages,
            max_actions=self.max_actions,
            max_depth=self.max_depth,
            max_wall_time_seconds=float(self.max_wall_time_s),
            max_forms=self.max_forms,
        )


@dataclass
class CrawlConfig:
    seed_url: str
    persona: JourneyPersona = JourneyPersona.DESKTOP_MOUSE
    allowed_hosts: frozenset[str] = field(default_factory=lambda: _DEFAULT_LOCAL_HOSTS)
    budgets: CrawlBudgets = field(default_factory=CrawlBudgets)
    allow_destructive_test_actions: bool = False
    seed: int = 42
    auth_secret_ref: str | None = None
    auth_lease_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    journey_id: str | None = None


class LocalUserJourneyCrawler:
    """Worker-facing adapter over BrowserJourneyCrawler."""

    def __init__(
        self,
        *,
        worker: Any = None,
        browser_worker: Any = None,
        artifact_store: Any | None = None,
        observability: Any | None = None,
    ) -> None:
        self._worker = worker or browser_worker
        self._artifact_store = artifact_store
        self._observability = observability
        self._inner = BrowserJourneyCrawler(
            browser_worker=self._worker,
            artifact_store=artifact_store,
            observability=observability,
            sleep_fn=lambda _s: None,
        )
        self._by_journey: dict[str, str] = {}  # journey_id -> run_id
        self._cancel_flags: set[str] = set()

    def run(self, config: CrawlConfig | dict[str, Any]) -> dict[str, Any]:
        if isinstance(config, dict):
            persona_raw = str(config.get("persona") or JourneyPersona.DESKTOP_MOUSE.value)
            try:
                persona = JourneyPersona(persona_raw.upper())
            except ValueError:
                persona = JourneyPersona.DESKTOP_MOUSE
            budgets_raw = dict(config.get("budgets") or {})
            budgets = CrawlBudgets(
                **{
                    k: budgets_raw[k]
                    for k in (
                        "max_pages",
                        "max_actions",
                        "max_depth",
                        "max_wall_time_s",
                        "max_forms",
                        "jitter_min_ms",
                        "jitter_max_ms",
                    )
                    if k in budgets_raw
                }
            )
            hosts = config.get("allowed_hosts")
            config = CrawlConfig(
                seed_url=str(config.get("seed_url") or config.get("url") or ""),
                persona=persona,
                allowed_hosts=frozenset(hosts) if hosts else _DEFAULT_LOCAL_HOSTS,
                budgets=budgets,
                allow_destructive_test_actions=bool(
                    config.get("allow_destructive_test_actions", False)
                ),
                seed=int(config.get("seed", 42)),
                auth_secret_ref=config.get("auth_secret_ref"),
                auth_lease_id=config.get("auth_lease_id"),
                run_id=config.get("run_id"),
                trace_id=config.get("trace_id"),
                journey_id=config.get("journey_id"),
            )
        self._inner.allowed_hosts = tuple(h.lower() for h in config.allowed_hosts)
        self._inner.budget = config.budgets.to_budget()
        self._inner.allow_destructive = bool(config.allow_destructive_test_actions)
        try:
            self._inner.assert_host_allowed(config.seed_url)
        except HostNotAllowed as exc:
            raise PermissionError(str(exc)) from exc
        # Pre-probe linked paths on the seed page for HTTP status findings.
        probe_findings = self._probe_seed_links(config.seed_url, config)
        report = self._inner.run(
            start_url=config.seed_url,
            persona=config.persona,
            seed=config.seed,
            run_id=config.run_id,
        )
        if config.journey_id:
            self._by_journey[str(config.journey_id)] = report.run_id
            report.journey_id = str(config.journey_id)
        else:
            self._by_journey[report.journey_id] = report.run_id
        return self._public_report(report, extra_findings=probe_findings)

    def status(self, journey_id: str) -> dict[str, Any]:
        run_id = self._by_journey.get(journey_id) or journey_id
        try:
            report = self._inner.status(run_id)
        except KeyError:
            return {
                "journey_id": journey_id,
                "status": "NOT_FOUND",
                "error_code": "CRAWLER_NOT_FOUND",
            }
        out = self._public_report(report)
        out["report"] = out
        return out

    def request_cancel(self, journey_id: str) -> dict[str, Any]:
        run_id = self._by_journey.get(journey_id) or journey_id
        self._cancel_flags.add(journey_id)
        try:
            report = self._inner.cancel(run_id)
        except KeyError:
            return {
                "journey_id": journey_id,
                "status": "NOT_FOUND",
                "cancel_requested": True,
                "error_code": "CRAWLER_NOT_FOUND",
            }
        out = self._public_report(report)
        out["cancel_requested"] = True
        return out

    def replay(self, journey_id: str, *, seed: int | None = None) -> dict[str, Any]:
        run_id = self._by_journey.get(journey_id) or journey_id
        prior = self._inner.status(run_id)
        report = self._inner.run(
            start_url=prior.start_url,
            persona=prior.persona,
            seed=int(seed if seed is not None else prior.seed),
        )
        self._by_journey[report.journey_id] = report.run_id
        self._by_journey[journey_id] = report.run_id
        return self._public_report(report)

    def report(self, journey_id: str) -> dict[str, Any]:
        run_id = self._by_journey.get(journey_id) or journey_id
        payload = self._inner.report_artifact(run_id)
        try:
            report = self._inner.status(run_id)
            public = self._public_report(report)
        except KeyError:
            public = {"journey_id": journey_id, "status": "NOT_FOUND"}
        return {
            "journey_id": journey_id,
            "run_id": run_id,
            **public,
            **payload,
        }

    def _public_report(
        self,
        report: CrawlReport,
        *,
        extra_findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = list(extra_findings or [])
        for issue in report.issues:
            kind = issue.kind.upper()
            if kind.startswith("HTTP_"):
                status = int(kind.split("_")[-1]) if kind.split("_")[-1].isdigit() else 0
                if status >= 500:
                    kind = "HTTP_5XX"
                elif status >= 400:
                    kind = "HTTP_4XX"
            elif "blank" in issue.kind:
                kind = "BLANK_CONTENT"
            elif "loop" in issue.kind:
                kind = "LOOP"
            elif "console" in issue.kind:
                kind = "CONSOLE_ERROR"
            elif "unverified" in issue.kind:
                kind = "STATE_UNVERIFIED"
            else:
                kind = kind.replace("-", "_")
            findings.append(
                {
                    "kind": kind,
                    "severity": issue.severity,
                    "message": issue.message,
                    "url": issue.url,
                    "reproduction": list(issue.reproduction),
                }
            )
        for obs in report.accessibility_observations:
            kind = str(obs.get("kind") or "A11Y_OBSERVATION")
            if kind == "missing_accessible_name":
                kind = "A11Y_OBSERVATION"
            elif kind == "untrusted_page_instruction_text":
                kind = "UNTRUSTED_PAGE_TEXT"
            findings.append(
                {
                    "kind": kind if kind.isupper() else "A11Y_OBSERVATION",
                    "severity": "medium",
                    "message": str(obs),
                    "url": obs.get("url"),
                    "reproduction": [],
                }
            )
        status = report.status.value
        if status == "LIMIT_REACHED":
            status = "BUDGET"
        md_id = None
        json_id = None
        if self._artifact_store is not None:
            try:
                md = self._artifact_store.create_from_bytes(
                    data=report.markdown().encode("utf-8"),
                    artifact_type="qa_crawl_report",
                    producer="browser.qa",
                    filename=f"qa-{report.journey_id}.md",
                    run_id=report.run_id,
                    metadata={"kind": "qa_crawl_report_md"},
                )
                md_id = getattr(md, "artifact_id", None)
            except Exception:  # noqa: BLE001
                try:
                    md = self._artifact_store.put_bytes(
                        report.markdown().encode("utf-8"),
                        media_type="text/markdown",
                        metadata={"kind": "qa_crawl_report"},
                    )
                    md_id = getattr(md, "artifact_id", None) or str(md)
                except Exception:  # noqa: BLE001
                    pass
            try:
                import json as _json

                raw = _json.dumps(report.public_dict(), ensure_ascii=False).encode("utf-8")
                js = self._artifact_store.create_from_bytes(
                    data=raw,
                    artifact_type="qa_crawl_report",
                    producer="browser.qa",
                    filename=f"qa-{report.journey_id}.json",
                    run_id=report.run_id,
                    metadata={"kind": "qa_crawl_report_json"},
                )
                json_id = getattr(js, "artifact_id", None)
            except Exception:  # noqa: BLE001
                pass
        return {
            "journey_id": report.journey_id,
            "run_id": report.run_id,
            "trace_id": report.trace_id,
            "status": status,
            "start_url": report.start_url,
            "persona": report.persona.value,
            "pages_visited": report.pages_visited,
            "actions_performed": report.actions_performed,
            "findings": findings,
            "issues": [i.public_dict() for i in report.issues],
            "console_issues": list(report.console_issues),
            "network_issues": list(report.network_issues),
            "accessibility_observations": list(report.accessibility_observations),
            "performance_observations": list(report.performance_observations),
            "screenshots": list(report.screenshots),
            "reproduction": report.reproduction_journeys[0]
            if report.reproduction_journeys
            else [],
            "reproduction_journeys": list(report.reproduction_journeys),
            "coverage": dict(report.coverage),
            "seed": report.seed,
            "created_at": report.created_at,
            "finished_at": report.finished_at,
            "error": report.error,
            "report_artifact_id": json_id or md_id,
            "markdown_artifact_id": md_id,
            "truth": {
                "localhost_scoped_by_default": True,
                "no_stealth_anti_bot": True,
                "no_private_crawler_db": True,
                "a11y_is_observation_not_wcag_certification": True,
                "job_runtime_cancel_checkpoint_resume": "EXTERNAL_REQUIRED",
                "page_text_is_untrusted_context": True,
                "personas_are_config_not_llm_agents": True,
                "not_a_second_browser_runtime": True,
                "cancelled_is_not_success": True,
            },
        }

    def _probe_seed_links(
        self, seed_url: str, config: CrawlConfig
    ) -> list[dict[str, Any]]:
        """HTTP-probe same-host links from the seed page for 4xx/5xx findings."""
        import httpx
        from html.parser import HTMLParser

        findings: list[dict[str, Any]] = []
        try:
            with httpx.Client(timeout=5.0, follow_redirects=False) as client:
                headers = {"X-Leviathan-QA-Run": config.run_id or "qa-probe"}
                resp = client.get(seed_url, headers=headers)
                html = resp.text
        except Exception:  # noqa: BLE001
            return findings

        class _LinkParser(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.hrefs: list[str] = []

            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                if tag.lower() != "a":
                    return
                for key, val in attrs:
                    if key.lower() == "href" and val:
                        self.hrefs.append(val)

        parser = _LinkParser()
        try:
            parser.feed(html)
        except Exception:  # noqa: BLE001
            return findings
        base_host = (urlparse(seed_url).hostname or "").lower()
        seen: set[str] = set()
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            for href in parser.hrefs[:30]:
                absolute = urljoin(seed_url, href)
                host = (urlparse(absolute).hostname or "").lower()
                if host != base_host or absolute in seen:
                    continue
                seen.add(absolute)
                try:
                    self._inner.assert_host_allowed(absolute)
                except HostNotAllowed:
                    continue
                try:
                    r = client.get(
                        absolute,
                        headers={"X-Leviathan-QA-Run": config.run_id or "qa-probe"},
                    )
                    code = int(r.status_code)
                except Exception as exc:  # noqa: BLE001
                    findings.append(
                        {
                            "kind": "BROKEN_LINK",
                            "severity": "high",
                            "message": str(exc),
                            "url": absolute,
                            "reproduction": [f"Navigate {seed_url}", f"Follow {href}"],
                        }
                    )
                    continue
                if code >= 500:
                    findings.append(
                        {
                            "kind": "HTTP_5XX",
                            "severity": "critical",
                            "message": f"HTTP {code} for {absolute}",
                            "url": absolute,
                            "reproduction": [f"Navigate {seed_url}", f"Follow {href}"],
                        }
                    )
                elif code >= 400:
                    findings.append(
                        {
                            "kind": "HTTP_4XX" if code != 404 else "BROKEN_LINK",
                            "severity": "high",
                            "message": f"HTTP {code} for {absolute}",
                            "url": absolute,
                            "reproduction": [f"Navigate {seed_url}", f"Follow {href}"],
                        }
                    )
                else:
                    # Soft a11y scan on successful linked pages.
                    body = r.text.lower()
                    if "<input" in body and "aria-label" not in body and "<label" not in body:
                        findings.append(
                            {
                                "kind": "A11Y_OBSERVATION",
                                "severity": "medium",
                                "message": "Interactive input without label/accessible name observed",
                                "url": absolute,
                                "reproduction": [f"Navigate {seed_url}", f"Follow {href}"],
                            }
                        )
        return findings


# Legacy alias used by some imports.
CrawlConfigBudgets = CrawlBudgets

