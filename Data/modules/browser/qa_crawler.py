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
from urllib.parse import urljoin, urlparse


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
                "not_a_second_browser_runtime": True,
                "cancelled_is_not_success": True,
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
        self._cancel.add(run_id)
        report = self._runs.get(run_id)
        if report and report.status in {CrawlStatus.ACCEPTED, CrawlStatus.RUNNING}:
            report.status = CrawlStatus.CANCELLED
            report.finished_at = _utc_now()
            self._flush_artifacts(report)
            self._emit("crawler.cancelled", {"run_id": run_id})
        if report is None:
            raise KeyError(run_id)
        return report

    def status(self, run_id: str) -> CrawlReport:
        report = self._runs.get(run_id)
        if report is None:
            raise KeyError(run_id)
        return report

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

                candidates = self._candidate_actions(obs, persona=report.persona)
                if not candidates:
                    break
                action_spec = candidates[rng.randrange(0, len(candidates))]
                if self._is_destructive(action_spec) and not self.allow_destructive:
                    continue
                if action_spec.get("kind") == "FORM_FILL" and forms_filled >= self.budget.max_forms:
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
        payload = {"json": report.public_dict(), "markdown": report.markdown()}
        if self.artifact_store is not None:
            try:
                art = self.artifact_store.put_bytes(
                    report.markdown().encode("utf-8"),
                    media_type="text/markdown",
                    metadata={"kind": "qa_crawl_report", "run_id": run_id},
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
        self, obs: dict[str, Any], *, persona: JourneyPersona
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        elements = obs.get("interactive_elements") or []
        if isinstance(elements, list):
            for el in elements[:40]:
                if not isinstance(el, dict):
                    continue
                tag = str(el.get("tag") or el.get("role") or "").lower()
                name = str(el.get("name") or el.get("text") or el.get("label") or "")
                selector = (
                    el.get("selector")
                    or el.get("css")
                    or el.get("test_id")
                    or (f"text={name}" if name else None)
                )
                if not selector:
                    continue
                if tag in {"a", "button", "link"} or el.get("role") in {"button", "link"}:
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

    def _synthetic_value(self, el: dict[str, Any]) -> str:
        kind = str(el.get("type") or el.get("name") or el.get("label") or "").lower()
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
        for net in (obs.get("network_failures") or obs.get("failed_requests") or [])[:20]:
            if len(report.network_issues) >= self.budget.max_network_events_collected:
                break
            entry = net if isinstance(net, dict) else {"url": str(net)}
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
            name = el.get("name") or el.get("accessible_name") or el.get("label")
            if not name and str(el.get("tag") or "").lower() in {"button", "a", "input"}:
                report.accessibility_observations.append(
                    {
                        "kind": "missing_accessible_name",
                        "selector": el.get("selector"),
                        "url": url,
                    }
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
            shot_result = self._action(
                "SCREENSHOT",
                {"session_id": (payload.get("session") or {}).get("session_id")},
                run_id=report.run_id,
            )
            shot = (
                (shot_result.get("observation") or {}).get("screenshot_artifact_id")
                or shot_result.get("screenshot_artifact_id")
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
        try:
            self.artifact_store.put_bytes(
                report.markdown().encode("utf-8"),
                media_type="text/markdown",
                metadata={
                    "kind": "qa_crawl_report",
                    "run_id": report.run_id,
                    "status": report.status.value,
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.observability is None:
            return
        try:
            if hasattr(self.observability, "emit"):
                self.observability.emit(event, payload)
            elif hasattr(self.observability, "record"):
                self.observability.record(event, payload)
        except Exception:  # noqa: BLE001
            pass
