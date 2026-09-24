"""Citation-backed research report generation."""

from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir

from .evidence import EvidenceLedger
from .store import ResearchStore
from .types import AnalysisMode, ClaimStatus, ResearchProject, ResearchReport


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReportBuilder:
    def __init__(
        self,
        store: ResearchStore,
        reports_root: Path | None = None,
        *,
        model_caller: Any | None = None,
    ) -> None:
        self.store = store
        self.reports_root = Path(reports_root) if reports_root else None
        self.ledger = EvidenceLedger(store)
        self.model_caller = model_caller

    def set_model_caller(self, caller: Any | None) -> None:
        self.model_caller = caller

    def generate(self, project: ResearchProject) -> ResearchReport:
        evidence = self.store.list_evidence(project.project_id)
        sources = self.store.list_sources(project.project_id)
        claims = self.store.list_claims(project.project_id)
        conflicts = self.store.list_conflicts(project.project_id)
        coverage = project.coverage

        evidence_ids = [e.evidence_id for e in evidence]
        source_ids = [s.source_id for s in sources]
        source_by_id = {s.source_id: s for s in sources}

        findings_lines: list[str] = []
        used_evidence: list[str] = []
        for claim in claims:
            status = claim.status.value
            cites = []
            for eid in claim.supporting_evidence_ids[:5]:
                resolution = self.ledger.resolve_citation(project.project_id, f"e:{eid}")
                if resolution.resolved:
                    cites.append(f"[e:{eid}]")
                    used_evidence.append(eid)
            cite_str = " ".join(cites)
            findings_lines.append(f"- ({status}) {claim.proposition} {cite_str}".rstrip())

        conflict_lines: list[str] = []
        for conflict in conflicts:
            support = " ".join(
                f"[e:{eid}]"
                for eid in conflict.supporting_evidence_ids
                if self.ledger.resolve_citation(project.project_id, f"e:{eid}").resolved
            )
            contra = " ".join(
                f"[e:{eid}]"
                for eid in conflict.contradicting_evidence_ids
                if self.ledger.resolve_citation(project.project_id, f"e:{eid}").resolved
            )
            conflict_lines.append(
                f"- {conflict.summary}\n"
                f"  - Supporting: {support or '_none resolvable_'}\n"
                f"  - Contradicting: {contra or '_none resolvable_'}\n"
                f"  - Analysis: {conflict.analysis.get('note', 'preserve both sides')}"
            )
            used_evidence.extend(conflict.supporting_evidence_ids)
            used_evidence.extend(conflict.contradicting_evidence_ids)

        if not findings_lines:
            findings_lines.append("- No structured claims were produced from retrieved evidence.")

        if not conflict_lines:
            conflict_lines.append("- No unresolved contradictions recorded.")

        uncertainty: list[str] = []
        if coverage:
            for q in coverage.unresolved_questions:
                uncertainty.append(f"- {q}")
            for note in coverage.notes:
                uncertainty.append(f"- {note}")
        if conflicts:
            uncertainty.append(
                "- Conflicting sources were preserved; no single account was selected without justification."
            )
        if not uncertainty:
            uncertainty.append("- Coverage appears complete relative to the stored plan, within budget.")

        evidence_section: list[str] = []
        for ev in evidence:
            src = source_by_id.get(ev.source_id)
            title = (src.title if src else None) or ev.source_id
            evidence_section.append(
                f"- `[e:{ev.evidence_id}]` ({title}): {ev.span_text[:400]}"
            )

        sources_section: list[str] = []
        for src in sources:
            uri = src.canonical_uri or src.original_uri or ""
            sources_section.append(
                f"- `{src.source_id}` [{src.source_type.value}] {src.title or ''} — {uri}"
            )

        methodology = [
            f"- Depth: `{project.depth.value}`",
            f"- Rounds completed: {project.current_round}/{project.total_rounds}",
            f"- Allow web: {project.allow_web}",
            f"- Local scopes: {', '.join(project.local_scopes) or '(all knowledge)'}",
            "- Citations resolve only through the evidence ledger to stored source snapshots.",
            f"- Analysis mode: `{project.analysis_mode.value}`",
        ]
        if project.web_unavailable_reason:
            methodology.append(
                f"- Web status: unavailable (`{project.web_unavailable_reason}`)"
            )

        executive = (
            f"Research on **{project.topic}** collected {len(sources)} source(s), "
            f"{len(evidence)} evidence span(s), {len(claims)} claim(s), "
            f"and {len(conflicts)} conflict record(s)."
        )
        model_narrative: str | None = None
        model_meta: dict[str, Any] = {}
        if (
            project.analysis_mode == AnalysisMode.MODEL
            and self.model_caller is not None
        ):
            # Shared Model Control Plane path — research role, background priority.
            # Narrative may only restate listed findings; citations remain ledger-gated.
            digest = "\n".join(
                [
                    f"Topic: {project.topic}",
                    "Findings:",
                    *findings_lines[:40],
                    "Uncertainty:",
                    *uncertainty[:20],
                ]
            )
            try:
                result = self.model_caller(
                    system_prompt=(
                        "You are LEVIATHAN Research Cognition summarizing verified findings. "
                        "Do not invent claims, sources, or citations. "
                        "Only restate what appears in the provided findings. "
                        "If evidence is thin, say so."
                    ),
                    messages=[{"role": "user", "content": digest}],
                    role="researcher",
                    domain="research",
                    model_role="research",
                    job_class="BACKGROUND",
                    run_id=project.project_id,
                    max_tokens=800,
                )
                text = str(
                    (result or {}).get("text")
                    or (result or {}).get("content")
                    or ""
                ).strip()
                if text:
                    model_narrative = text
                    model_meta = {
                        "model_id": (result or {}).get("model_id"),
                        "route": (result or {}).get("route"),
                        "usage_source": (result or {}).get("usage_source"),
                    }
            except Exception as exc:  # noqa: BLE001 — deterministic report remains authoritative
                model_meta = {"error": str(exc), "fallback": "deterministic_executive_summary"}

        body_parts = [
            f"# {project.title}",
            "",
            "## Executive Summary",
            executive,
        ]
        if model_narrative:
            body_parts.extend(
                [
                    "",
                    "## Model-assisted narrative (non-authoritative)",
                    (
                        "_Produced via shared Model Control Plane with role=`research`. "
                        "Claims in Findings remain the evidence-backed authority._"
                    ),
                    "",
                    model_narrative,
                ]
            )
        body_parts.extend(
            [
                "",
                "## Research Question",
                project.topic,
                "",
                "## Scope",
                (
                    project.objective
                    or (project.plan.scope if project.plan else "")
                    or "local research"
                ),
                "",
                "## Methodology",
                *methodology,
                "",
                "## Findings",
                *findings_lines,
                "",
                "## Evidence",
                *(evidence_section or ["- _(none)_"]),
                "",
                "## Contradictions / Alternative Evidence",
                *conflict_lines,
                "",
                "## Uncertainty / Gaps",
                *uncertainty,
                "",
                "## Conclusion",
                (
                    "This report only asserts claims that are backed by resolvable evidence citations. "
                    "Where sources conflict, both sides remain represented."
                ),
                "",
                "## Sources",
                *(sources_section or ["- _(none)_"]),
                "",
            ]
        )
        body = "\n".join(body_parts)

        # Ensure no fabricated citation markers survive.
        body = self.ledger.mark_unresolved_in_text(project.project_id, body)
        resolutions = self.ledger.resolve_all_in_text(project.project_id, body)
        unresolved = [r for r in resolutions if not r.resolved]

        version = int(project.report_version) + 1
        report = ResearchReport(
            report_id=str(uuid.uuid4()),
            project_id=project.project_id,
            version=version,
            title=project.title,
            body_markdown=body,
            body_html=_markdown_lite_html(body),
            evidence_ids=list(dict.fromkeys(used_evidence or evidence_ids)),
            source_ids=source_ids,
            model_profile=dict(project.model_profile),
            generation_trace={
                "generator": "research.reports.ReportBuilder",
                "deterministic": model_narrative is None,
                "model_assisted": model_narrative is not None,
                "analysis_mode": project.analysis_mode.value,
                "model_control_plane": bool(self.model_caller),
                "model_role": "research" if model_narrative is not None else None,
                "model_meta": model_meta,
                "citation_resolutions": len(resolutions),
                "unresolved_citations": len(unresolved),
                "claims": len(claims),
                "conflicts": len(conflicts),
            },
            created_at=utc_now(),
        )
        self.store.add_report(report)
        if self.reports_root is not None:
            dest = ensure_dir(self.reports_root / project.project_id)
            atomic_write_text(dest / f"report_v{version}.md", body)
        return report

    def export_bundle(self, project_id: str, *, fmt: str = "markdown") -> dict:
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        report = self.store.get_latest_report(project_id)
        if report is None:
            raise ValueError("No report available to export")
        fmt_norm = (fmt or "markdown").lower()
        if fmt_norm in {"md", "markdown"}:
            return {
                "format": "markdown",
                "filename": f"{project.project_id}_report_v{report.version}.md",
                "content": report.body_markdown,
                "media_type": "text/markdown",
            }
        if fmt_norm == "html":
            return {
                "format": "html",
                "filename": f"{project.project_id}_report_v{report.version}.html",
                "content": report.body_html or _markdown_lite_html(report.body_markdown),
                "media_type": "text/html",
            }
        if fmt_norm == "json":
            import json

            bundle = {
                "schema_version": 1,
                "project": project.public_dict(),
                "report": report.public_dict(),
                "sources": [s.public_dict() for s in self.store.list_sources(project_id)],
                "evidence": [e.public_dict() for e in self.store.list_evidence(project_id)],
                "claims": [c.public_dict() for c in self.store.list_claims(project_id)],
                "conflicts": [c.public_dict() for c in self.store.list_conflicts(project_id)],
                "citations": [
                    self.ledger.resolve_citation(project_id, f"e:{e.evidence_id}").public_dict()
                    for e in self.store.list_evidence(project_id)
                ],
            }
            return {
                "format": "json",
                "filename": f"{project.project_id}_evidence_bundle_v{report.version}.json",
                "content": json.dumps(bundle, indent=2, ensure_ascii=False),
                "media_type": "application/json",
            }
        raise ValueError(
            f"Unsupported export format {fmt!r}; supported: markdown, html, json"
        )


def _markdown_lite_html(md: str) -> str:
    lines = []
    for line in md.splitlines():
        if line.startswith("# "):
            lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            lines.append(f"<li>{html.escape(line[2:])}</li>")
        elif not line.strip():
            lines.append("<br/>")
        else:
            lines.append(f"<p>{html.escape(line)}</p>")
    return "\n".join(lines)
