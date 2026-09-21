"""Built-in HADES capabilities that participate in the same registry."""

from __future__ import annotations

from typing import Any

from ..contracts import CanonicalCapability
from ..taxonomy import NATIVE_PROVIDER_ID


def native_capabilities() -> list[CanonicalCapability]:
    specs: list[dict[str, Any]] = [
        {
            "id": "hades.coding_agent",
            "kind": "agent",
            "name": "Coding Agent",
            "description": "Native HADES coding agent: inspect, plan, patch, test.",
            "domains": ["software", "software.python", "debugging"],
            "intents": ["repair_bug", "implement_feature", "inspect_code", "diagnose_bug"],
            "produces": ["findings", "patch", "test_plan"],
            "cost_class": "expensive",
            "latency_class": "slow",
            "side_effect_class": "write",
            "accepts": ["coding_task", "debugging_task"],
        },
        {
            "id": "hades.repository.inspect",
            "kind": "tool",
            "name": "Repository inspection",
            "description": "Native repository intelligence and workspace inspection.",
            "domains": ["software.repository"],
            "intents": ["inspect_code", "code.search"],
            "produces": ["repository_findings", "search_results"],
            "cost_class": "cheap",
            "effects": ["read_files"],
            "side_effect_class": "read",
        },
        {
            "id": "hades.git.inspect",
            "kind": "tool",
            "name": "Git inspection",
            "description": "Inspect local git status, history and diffs.",
            "domains": ["software.repository", "software.git"],
            "intents": ["inspect_code"],
            "produces": ["repository_findings"],
            "cost_class": "cheap",
            "side_effect_class": "read",
        },
        {
            "id": "hades.research",
            "kind": "workflow",
            "name": "Research",
            "description": "Native research runner and knowledge synthesis.",
            "domains": ["research"],
            "intents": ["research", "gather_evidence"],
            "produces": ["artifact", "structured_data"],
            "cost_class": "moderate",
            "latency_class": "slow",
        },
        {
            "id": "hades.retrieval",
            "kind": "tool",
            "name": "Retrieval",
            "description": "Memory and knowledge retrieval.",
            "domains": ["knowledge"],
            "intents": ["retrieve", "search_knowledge"],
            "produces": ["search_results"],
            "cost_class": "cheap",
            "side_effect_class": "read",
        },
        {
            "id": "hades.artifact.generate",
            "kind": "tool",
            "name": "Artifact generation",
            "description": "Persist generated artifacts with provenance.",
            "domains": ["artifacts"],
            "intents": ["generate_artifact"],
            "produces": ["artifact"],
            "cost_class": "cheap",
        },
        {
            "id": "hades.verification",
            "kind": "agent",
            "name": "Verifier",
            "description": "Deterministic + structured verification of task outcomes.",
            "domains": ["verification"],
            "intents": ["result.verify", "tests.execute"],
            "produces": ["test_results", "verification_result"],
            "cost_class": "cheap",
            "accepts": ["verification"],
        },
        {
            "id": "hades.work_runtime",
            "kind": "service",
            "name": "Work Runtime",
            "description": "Durable task DAG, checkpoints and completion gates.",
            "domains": ["orchestration"],
            "intents": ["plan.coordinate"],
            "cost_class": "moderate",
            "latency_class": "normal",
        },
        {
            "id": "hades.model.routing",
            "kind": "resource",
            "name": "Model routing",
            "description": "Local model selection over LM Studio; no hardcoded model IDs.",
            "domains": ["models"],
            "intents": ["route_model"],
            "cost_class": "moderate",
            "required_resources": ["lm_studio"],
        },
        {
            "id": "hades.trading_lab",
            "kind": "service",
            "name": "Trading Lab",
            "description": "Point-in-time simulation, ledger, risk and independent evaluation. Deterministic engines stay specialized.",
            "domains": ["trading"],
            "intents": ["trading.simulate", "trading.evaluate"],
            "produces": ["experiment_ref", "evaluation_report"],
            "cost_class": "moderate",
            "side_effect_class": "none",
        },
        {
            "id": "hades.media",
            "kind": "service",
            "name": "Media Intelligence",
            "description": "FFmpeg rendering, assets and platform publishing. Specialized runtime.",
            "domains": ["media"],
            "intents": ["media.render", "media.publish"],
            "produces": ["artifact_ref", "render"],
            "cost_class": "moderate",
            "side_effect_class": "write",
        },
        {
            "id": "hades.chat",
            "kind": "service",
            "name": "Chat",
            "description": "Chat-primary conversation runtime over the shared brain.",
            "domains": ["chat"],
            "intents": ["explain", "answer"],
            "cost_class": "cheap",
        },
    ]
    records: list[CanonicalCapability] = []
    for spec in specs:
        extras: dict[str, Any] = {}
        if spec.get("id") == "hades.trading_lab":
            extras["domain_truth"] = "deterministic"
            extras["specialized_runtime"] = True
        if spec.get("id") == "hades.media":
            extras["specialized_runtime"] = True
        if spec.get("accepts"):
            extras["agent"] = {
                "canonical_id": spec["id"],
                "specialties": spec.get("domains") or [],
                "accepts": spec.get("accepts") or [],
                "produces": spec.get("produces") or [],
                "executable": True,
            }
        records.append(
            CanonicalCapability(
                canonical_id=spec["id"],
                kind=spec["kind"],
                name=spec["name"],
                description=spec.get("description") or "",
                provider_id=NATIVE_PROVIDER_ID,
                plugin_id=None,
                source="native",
                version="hades",
                domains=list(spec.get("domains") or []),
                intents=list(spec.get("intents") or []),
                produces=list(spec.get("produces") or []),
                effects=list(spec.get("effects") or []),
                side_effect_class=spec.get("side_effect_class") or "none",
                cost_class=spec.get("cost_class") or "cheap",
                latency_class=spec.get("latency_class") or "fast",
                health="available",
                availability=True,
                extras=extras,
                adapter_id="native_hades",
            )
        )
    return records
