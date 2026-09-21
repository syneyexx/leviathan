"""Specialist agent contracts used by Chat, Work and Research.

An agent name + prompt is not enough: each specialist declares inputs, outputs,
capabilities, tools, model profile, context policy, budgets and recovery.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Capability = Literal[
    "chat",
    "plan",
    "research",
    "documents",
    "code",
    "verify",
    "memory",
    "tools",
    "workspace",
    "deterministic",
    "web",
    "trading",
    "voice",
]

ModelProfileHint = Literal["fast", "standard", "high", "maximum", "adaptive"]


def _default_performance_contract(budget: dict[str, int], *, sla_class: str = "interactive") -> dict[str, Any]:
    """Local SLA-like contract derived from specialist budgets (C8)."""
    return {
        "sla_class": sla_class,
        "max_model_calls": int(budget.get("max_model_calls", 0) or 0),
        "max_tool_rounds": int(budget.get("max_tool_rounds", 0) or 0),
        "max_wall_time_s_hint": 30 if sla_class == "interactive" else 300,
        "honesty": "local_budget_contract_not_measured_p95",
    }


@dataclass(slots=True)
class SpecialistContract:
    agent_id: str
    name: str
    responsibility: str
    required_inputs: list[str]
    expected_outputs: list[str]
    capabilities: list[Capability]
    allowed_tools: list[str]  # empty = use policy shortlist; ["none"] = no tools
    model_profile: ModelProfileHint
    context_kinds: list[str]
    budget: dict[str, int]
    acceptance_criteria: list[str]
    error_recovery: str
    deterministic: bool = False
    planned_only: bool = False
    performance_contract: dict[str, Any] = field(default_factory=dict)
    # Honesty class — not a vanity score. Measured advantage lives in eval scoreboard.
    engine_class: str = "PROMPT_SPECIALIST"

    def __post_init__(self) -> None:
        if not self.performance_contract:
            sla = "batch" if self.agent_id in {"executor", "build", "research_worker", "plugin_converter"} else "interactive"
            self.performance_contract = _default_performance_contract(self.budget, sla_class=sla)
        if self.engine_class == "PROMPT_SPECIALIST":
            if self.deterministic:
                self.engine_class = "DOMAIN_ENGINE"
            elif self.allowed_tools and self.allowed_tools != ["none"]:
                self.engine_class = "TOOL_SPECIALIST"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def within_performance_budget(self, *, model_calls: int = 0, tool_rounds: int = 0) -> bool:
        contract = self.performance_contract or _default_performance_contract(self.budget)
        max_m = int(contract.get("max_model_calls") or 0)
        max_t = int(contract.get("max_tool_rounds") or 0)
        if max_m and int(model_calls) > max_m:
            return False
        if max_t and int(tool_rounds) > max_t:
            return False
        return True


SPECIALISTS: dict[str, SpecialistContract] = {
    "chat": SpecialistContract(
        agent_id="chat",
        name="Chat / Synthesis",
        responsibility="Gesprek voeren en het gebruikersantwoord samenstellen.",
        required_inputs=["user_text"],
        expected_outputs=["assistant_message"],
        capabilities=["chat"],
        allowed_tools=[],
        model_profile="adaptive",
        context_kinds=["recent_message", "memory", "user_constraint"],
        budget={"max_model_calls": 4, "max_tool_rounds": 2},
        acceptance_criteria=["Antwoord adresseert het huidige doel", "Geen onbewezen voltooiingsclaims"],
        error_recovery="Geef een eerlijk deelantwoord en open vragen.",
    ),
    "executor": SpecialistContract(
        agent_id="executor",
        name="Planner / Coordinator",
        responsibility="Taakverdeling, voortgang en samenvoegen van specialistenresultaten.",
        required_inputs=["task_prompt"],
        expected_outputs=["plan", "merged_result"],
        capabilities=["plan", "chat"],
        allowed_tools=[],
        model_profile="maximum",
        context_kinds=["plan", "tool_result", "memory", "knowledge"],
        budget={"max_model_calls": 12, "max_tool_rounds": 4, "max_subtasks": 8},
        acceptance_criteria=["Plan is acyclisch", "Acceptatiecriteria zijn controleerbaar"],
        error_recovery="Herplan alleen mislukte of ongeldig geworden stappen.",
    ),
    "research_worker": SpecialistContract(
        agent_id="research_worker",
        name="Research Worker",
        responsibility="Onderzoekt een begrensde deelvraag met bronverwijzingen.",
        required_inputs=["research_question"],
        expected_outputs=["findings", "evidence_refs", "open_gaps"],
        capabilities=["research"],
        allowed_tools=[],
        model_profile="high",
        context_kinds=["knowledge", "evidence", "memory"],
        budget={"max_model_calls": 6, "max_tool_rounds": 3},
        acceptance_criteria=["Bronnen zijn herleidbaar", "Onzekerheden zijn expliciet"],
        error_recovery="Markeer ontbrekende bronnen; claim geen expertise op aantallen.",
    ),
    "research_planner": SpecialistContract(
        agent_id="research_planner",
        name="Research Planner",
        responsibility="Splitst onderzoek in vragen, bronnen en controlepunten.",
        required_inputs=["topic"],
        expected_outputs=["questions", "source_plan"],
        capabilities=["research", "plan"],
        allowed_tools=["none"],
        model_profile="high",
        context_kinds=["knowledge", "plan"],
        budget={"max_model_calls": 4, "max_tool_rounds": 0, "max_subtasks": 6},
        acceptance_criteria=["Deelvragen zijn begrensd", "Lokale kennis eerst"],
        error_recovery="Val terug op een enkele onderzoeksvraag gelijk aan het topic.",
    ),
    "document_intel": SpecialistContract(
        agent_id="document_intel",
        name="Document / Workspace Worker",
        responsibility="Structureert, extraheert en indexeert documenten en workspacebestanden.",
        required_inputs=["document_ref_or_path"],
        expected_outputs=["structured_extract", "indexed_source_id"],
        capabilities=["documents", "workspace"],
        allowed_tools=[],
        model_profile="standard",
        context_kinds=["workspace", "knowledge"],
        budget={"max_model_calls": 4, "max_tool_rounds": 2},
        acceptance_criteria=["Bronversie/hash vastgelegd", "Extractiestatus expliciet"],
        error_recovery="Rapporteer extractiefout apart van irrelevante inhoud.",
    ),
    "workspace": SpecialistContract(
        agent_id="workspace",
        name="File / Workspace Agent",
        responsibility="Beheert workspaces binnen bestandstoestemmingen.",
        required_inputs=["workspace_ref"],
        expected_outputs=["file_ops_result"],
        capabilities=["workspace", "documents"],
        allowed_tools=[],
        model_profile="standard",
        context_kinds=["workspace"],
        budget={"max_model_calls": 3, "max_tool_rounds": 2},
        acceptance_criteria=["Toestemmingen gecontroleerd vóór schrijven"],
        error_recovery="Blokkeer schrijfacties bij ask/block beleid.",
    ),
    "build": SpecialistContract(
        agent_id="build",
        name="Code / Build Worker",
        responsibility="Codeanalyse en gecontroleerde ontwikkeltaken met proof-of-work.",
        required_inputs=["code_task"],
        expected_outputs=["analysis_or_patch_summary", "proof"],
        capabilities=["code", "tools"],
        allowed_tools=[],
        model_profile="maximum",
        context_kinds=["workspace", "knowledge", "tool_result"],
        budget={"max_model_calls": 10, "max_tool_rounds": 6},
        acceptance_criteria=["Geen succesclaim zonder controle", "Wijzigingen zijn begrensd"],
        error_recovery="Stop bij onzekere bijwerkingen; vraag om sturing.",
        engine_class="DOMAIN_ENGINE",
    ),
    "coding_investigator": SpecialistContract(
        agent_id="coding_investigator",
        name="Repository Investigator",
        responsibility="Read-only repository investigation and ranked hypotheses.",
        required_inputs=["code_task"],
        expected_outputs=["findings", "hypotheses"],
        capabilities=["code", "deterministic"],
        allowed_tools=["none"],
        model_profile="standard",
        context_kinds=["workspace"],
        budget={"max_model_calls": 2, "max_tool_rounds": 4},
        acceptance_criteria=["No mutation of source workspace"],
        error_recovery="Fall back to lexical exploration.",
        deterministic=True,
    ),
    "coding_planner": SpecialistContract(
        agent_id="coding_planner",
        name="Implementation Planner",
        responsibility="Dependency-aware coding DAG for non-trivial tasks.",
        required_inputs=["code_task"],
        expected_outputs=["plan"],
        capabilities=["plan", "code"],
        allowed_tools=["none"],
        model_profile="high",
        context_kinds=["workspace", "plan"],
        budget={"max_model_calls": 2, "max_tool_rounds": 0},
        acceptance_criteria=["Plan is acyclic", "Trivial tasks skip heavy plans"],
        error_recovery="Use the trivial two-step implement→verify DAG.",
    ),
    "coding_editor": SpecialistContract(
        agent_id="coding_editor",
        name="Code Editor",
        responsibility="Minimal edits in an isolated worktree.",
        required_inputs=["plan"],
        expected_outputs=["diff"],
        capabilities=["code"],
        allowed_tools=["none"],
        model_profile="high",
        context_kinds=["workspace"],
        budget={"max_model_calls": 4, "max_tool_rounds": 2},
        acceptance_criteria=["No silent source apply", "No whole-file rewrite unless required"],
        error_recovery="Stop on stale baseline rather than force-apply.",
    ),
    "coding_test_engineer": SpecialistContract(
        agent_id="coding_test_engineer",
        name="Test Engineer",
        responsibility="Impacted-test selection and verification quality.",
        required_inputs=["diff"],
        expected_outputs=["test_results"],
        capabilities=["verify", "code"],
        allowed_tools=["none"],
        model_profile="standard",
        context_kinds=["workspace", "evidence"],
        budget={"max_model_calls": 1, "max_tool_rounds": 4},
        acceptance_criteria=["Tests are evidence not proof", "No test weakening"],
        error_recovery="Mark verification incomplete; never fake green.",
        deterministic=True,
    ),
    "coding_debugger": SpecialistContract(
        agent_id="coding_debugger",
        name="Debugging Specialist",
        responsibility="Structured failure normalization and information-gain next tests.",
        required_inputs=["test_results"],
        expected_outputs=["structured_failure", "hypotheses"],
        capabilities=["code", "verify"],
        allowed_tools=["none"],
        model_profile="high",
        context_kinds=["evidence", "workspace"],
        budget={"max_model_calls": 3, "max_tool_rounds": 4},
        acceptance_criteria=["Repair from structured failures", "No identical repeat patches"],
        error_recovery="Stop honestly when the repair loop stalls.",
    ),
    "coding_security_reviewer": SpecialistContract(
        agent_id="coding_security_reviewer",
        name="Security Reviewer",
        responsibility="Trust-boundary review of coding diffs using existing policy systems.",
        required_inputs=["diff"],
        expected_outputs=["review"],
        capabilities=["verify"],
        allowed_tools=["none"],
        model_profile="high",
        context_kinds=["evidence"],
        budget={"max_model_calls": 1, "max_tool_rounds": 0},
        acceptance_criteria=["Does not replace executable verification"],
        error_recovery="Escalate suspicions; do not auto-apply.",
    ),
    "coding_api_reviewer": SpecialistContract(
        agent_id="coding_api_reviewer",
        name="API Compatibility Reviewer",
        responsibility="Detect deliberate vs accidental public contract changes.",
        required_inputs=["diff"],
        expected_outputs=["review"],
        capabilities=["verify"],
        allowed_tools=["none"],
        model_profile="standard",
        context_kinds=["evidence"],
        budget={"max_model_calls": 1, "max_tool_rounds": 0},
        acceptance_criteria=["Contract changes remain explicit"],
        error_recovery="Mark COMPLETED_PARTIALLY_VERIFIED when contracts are unverified.",
    ),
    "coding_final_reviewer": SpecialistContract(
        agent_id="coding_final_reviewer",
        name="Independent Final Reviewer",
        responsibility="Checklist review independent from the generating model.",
        required_inputs=["diff", "test_results"],
        expected_outputs=["review"],
        capabilities=["verify"],
        allowed_tools=["none"],
        model_profile="maximum",
        context_kinds=["evidence", "plan"],
        budget={"max_model_calls": 1, "max_tool_rounds": 0},
        acceptance_criteria=["Suggestions are not proven defects"],
        error_recovery="Reject on critical test weakening.",
        deterministic=True,
    ),
    "critic": SpecialistContract(
        agent_id="critic",
        name="Evidence / Verification Worker",
        responsibility="Beoordeelt bewijs, claims en voltooiing onafhankelijk.",
        required_inputs=["candidate_result", "acceptance_criteria"],
        expected_outputs=["verification_result"],
        capabilities=["verify"],
        allowed_tools=["none"],
        model_profile="maximum",
        context_kinds=["evidence", "plan", "tool_result"],
        budget={"max_model_calls": 3, "max_tool_rounds": 0},
        acceptance_criteria=["Evidence_refs bestaan", "Onvoldoende steun blijft zichtbaar"],
        error_recovery="Faal-closed: geen passed bij ontbrekende of tegengesproken steun.",
    ),
    "memory_curator": SpecialistContract(
        agent_id="memory_curator",
        name="Memory Curator",
        responsibility="Beheert duurzame informatie met scope, status en supersessie.",
        required_inputs=["candidate_memory"],
        expected_outputs=["memory_record"],
        capabilities=["memory", "deterministic"],
        allowed_tools=["none"],
        model_profile="standard",
        context_kinds=["memory", "user_constraint"],
        budget={"max_model_calls": 2, "max_tool_rounds": 0},
        acceptance_criteria=["Modelzekerheid niet als objectieve score", "Vervangen info blijft historisch"],
        error_recovery="Sla niets op bij ambigue of tegenstrijdige instructies zonder correctie.",
        deterministic=False,
    ),
    "retrieval": SpecialistContract(
        agent_id="retrieval",
        name="Retrieval Service",
        responsibility="Zoekt relevante Memory, Knowledge en Evidence zonder contextbloat.",
        required_inputs=["query"],
        expected_outputs=["ranked_passages"],
        capabilities=["deterministic", "documents"],
        allowed_tools=["none"],
        model_profile="fast",
        context_kinds=["memory", "knowledge", "evidence"],
        budget={"max_model_calls": 0, "max_tool_rounds": 0},
        acceptance_criteria=["Workspace-scheiding", "Selectiereden zichtbaar"],
        error_recovery="Lexicale fallback blijft werken zonder embeddings.",
        deterministic=True,
    ),
    "knowledge_builder": SpecialistContract(
        agent_id="knowledge_builder",
        name="Knowledge Builder",
        responsibility=(
            "Zet tool/plugin-output om naar KnowledgeItems, normaliseert/samenvat indien nodig, "
            "en persist/verify via de knowledge repository. Geen plugin-registry lookup of plugin-uitvoering."
        ),
        required_inputs=["validated_findings"],
        expected_outputs=["knowledge_source"],
        capabilities=["documents", "memory", "deterministic"],
        allowed_tools=["none"],
        model_profile="standard",
        context_kinds=["knowledge", "evidence", "tool_result"],
        budget={"max_model_calls": 0, "max_tool_rounds": 0},
        acceptance_criteria=["Provenance behouden", "Geen plugin lookup/execute"],
        error_recovery="Sla geen onbewezen interpretatie op als feitelijke kennis.",
        deterministic=True,
    ),
    "plugin_converter": SpecialistContract(
        agent_id="plugin_converter",
        name="Plugin Conversion Agent",
        responsibility=(
            "Analyseert externe source en bouwt gecontroleerde adapters. "
            "Alleen voor CREATE_OR_CONVERT_PLUGIN — niet voor bestaande plugin-uitvoering."
        ),
        required_inputs=["plugin_source"],
        expected_outputs=["adapter_plan"],
        capabilities=["tools", "code"],
        allowed_tools=[],
        model_profile="high",
        context_kinds=["workspace", "tool_result"],
        budget={"max_model_calls": 6, "max_tool_rounds": 3},
        acceptance_criteria=["Geen autonome installatie zonder policy", "Niet gebruiken voor USE_EXISTING_PLUGIN"],
        error_recovery="Laat plugin disabled tot review.",
    ),
    "compressor": SpecialistContract(
        agent_id="compressor",
        name="Context Compressor",
        responsibility="Comprimeert oude context met behoud van bronverwijzingen.",
        required_inputs=["history_blob"],
        expected_outputs=["compact_summary"],
        capabilities=["chat", "deterministic"],
        allowed_tools=["none"],
        model_profile="fast",
        context_kinds=["recent_message"],
        budget={"max_model_calls": 1, "max_tool_rounds": 0},
        acceptance_criteria=["Bronverwijzingen blijven intact"],
        error_recovery="Bij falen: recente berichten ongewijzigd houden.",
    ),
    "web_scout": SpecialistContract(
        agent_id="web_scout",
        name="Web Scout",
        responsibility="Verkent actuele webbronnen via WebResearchService met robots/network policy.",
        required_inputs=["query_or_url"],
        expected_outputs=["ingested_sources", "freshness_notes", "blocked_or_errors"],
        capabilities=["web", "research", "deterministic"],
        allowed_tools=["none"],
        model_profile="high",
        context_kinds=["knowledge", "evidence"],
        budget={"max_model_calls": 0, "max_tool_rounds": 0, "max_urls": 4},
        acceptance_criteria=[
            "Network block wint altijd",
            "Geen succesclaim zonder ingest of expliciete lege resultaatset",
            "Bron-URI/source_id vastgelegd wanneer beschikbaar",
        ],
        error_recovery="Rapporteer policy-block of fetchfout; val terug op lokale Knowledge.",
        deterministic=True,
    ),
    "evidence_auditor": SpecialistContract(
        agent_id="evidence_auditor",
        name="Evidence Auditor",
        responsibility="Audit provenance, contradicties en claimdekking tegen lokale Evidence/Knowledge/Graph.",
        required_inputs=["claim_or_entity"],
        expected_outputs=["audit_report", "contradictions", "unsupported_claims", "missing_evidence"],
        capabilities=["verify", "deterministic"],
        allowed_tools=["none"],
        model_profile="maximum",
        context_kinds=["evidence", "knowledge", "plan"],
        budget={"max_model_calls": 0, "max_tool_rounds": 0},
        acceptance_criteria=[
            "Ontbrekende steun blijft zichtbaar",
            "Contradicties zijn querybaar of expliciet afwezig gemeld",
        ],
        error_recovery="Fail-closed: geen 'passed' bij ontbrekende of tegengesproken steun.",
        deterministic=True,
    ),
    "tool_orchestrator": SpecialistContract(
        agent_id="tool_orchestrator",
        name="Tool Orchestrator",
        responsibility="Plant multi-plugin workflows via dezelfde PluginManager permission/logging spine.",
        required_inputs=["workflow_goal"],
        expected_outputs=["eligible_tools", "orchestration_plan", "policy_notes"],
        capabilities=["tools", "plan", "deterministic"],
        allowed_tools=[],
        model_profile="high",
        context_kinds=["tool_result", "plan", "workspace"],
        budget={"max_model_calls": 2, "max_tool_rounds": 6},
        acceptance_criteria=[
            "Alleen Ready/eligible tools in shortlist",
            "Blocked/failed toolresultaten blijven failures",
        ],
        error_recovery="Stop bij policy-block; geen stille simulatie van tooluitvoer.",
        deterministic=True,
    ),
    "trading_specialist": SpecialistContract(
        agent_id="trading_specialist",
        name="Trading Specialist",
        responsibility="PAPER-only strategie- en marktanalyse via PaperTradingService/TradingBot.",
        required_inputs=["trading_question"],
        expected_outputs=["paper_state_summary", "strategy_notes"],
        capabilities=["trading", "deterministic"],
        allowed_tools=["none"],
        model_profile="high",
        context_kinds=["knowledge", "evidence"],
        budget={"max_model_calls": 0, "max_tool_rounds": 0},
        acceptance_criteria=["Geen live broker-pad", "PAPER-modus expliciet in output"],
        error_recovery="Meld disabled/kill-switch eerlijk; inventeer geen fills.",
        deterministic=True,
        engine_class="DOMAIN_ENGINE",
    ),
    "voice_specialist": SpecialistContract(
        agent_id="voice_specialist",
        name="Voice Specialist",
        responsibility="Spraak-/transcriptworkflows: voice doctor status of transcript→taakvoorstel.",
        required_inputs=["transcript_or_voice_request"],
        expected_outputs=["task_draft_or_doctor_report"],
        capabilities=["voice", "deterministic"],
        allowed_tools=["none"],
        model_profile="standard",
        context_kinds=["user_constraint", "recent_message"],
        budget={"max_model_calls": 0, "max_tool_rounds": 0},
        acceptance_criteria=[
            "Geen cloud-STT claim",
            "Transcript-pad produceert reviewbare task draft",
        ],
        error_recovery="Degraded host-status wanneer ASR/TTS niet geïnstalleerd is.",
        deterministic=True,
    ),
}


# Map common task kinds to preferred specialists (not exclusive).
KIND_TO_SPECIALIST: dict[str, str] = {
    "chat": "chat",
    "question": "chat",
    "research": "research_worker",
    "code": "build",
    "debug": "build",
    "coding": "build",
    "documents": "document_intel",
    "document": "document_intel",
    "workspace": "workspace",
    "verify": "critic",
    "verification": "critic",
    "evidence": "evidence_auditor",
    "audit": "evidence_auditor",
    "memory": "memory_curator",
    "memory_write": "memory_curator",
    "knowledge": "knowledge_builder",
    "plan": "executor",
    "planning": "executor",
    "multi_step": "executor",
    "analysis": "executor",
    "tool_use": "tool_orchestrator",
    "plugins": "tool_orchestrator",
    "plugin_use": "tool_orchestrator",
    "plugin_create": "plugin_converter",
    "web": "web_scout",
    "trading": "trading_specialist",
    "voice": "voice_specialist",
    "build": "build",
    "work": "executor",
}


def get_specialist(agent_id: str) -> SpecialistContract | None:
    return SPECIALISTS.get(agent_id)


def list_active_specialists(*, include_planned: bool = False) -> list[SpecialistContract]:
    return [item for item in SPECIALISTS.values() if include_planned or not item.planned_only]


def route_specialist(
    prompt: str,
    *,
    requested: str | None = None,
    enabled_ids: set[str] | None = None,
    kind: str | None = None,
) -> str:
    """Route to a specialist. Explicit choice cannot grant missing capabilities.

    If the user requests a disabled/unknown agent, fall back to a safe enabled agent
    rather than elevating privileges.

    Plugin routing is intent-aware and capability-based:
    - USE_EXISTING_PLUGIN → tool_orchestrator (never plugin_converter / evidence_auditor / build)
    - CREATE_PLUGIN / CONVERT_PLUGIN → plugin_converter
    - EVIDENCE_AUDIT → evidence_auditor only when explicitly requested
    """
    from .work_intents import (
        classify_plugin_intent,
        classify_work_intent,
        is_evidence_primary_task,
        wants_knowledge_persist,
    )

    enabled = enabled_ids or set(SPECIALISTS.keys())
    requested_norm = (requested or "").strip().lower()
    if requested_norm and requested_norm not in {"auto", "generalist"}:
        if requested_norm in enabled and requested_norm in SPECIALISTS:
            return requested_norm
        # Explicit but unavailable: do not invent privileges.
        return "executor" if "executor" in enabled else next(iter(sorted(enabled)), "chat")

    work_intent = classify_work_intent(prompt)
    plugin_intent = classify_plugin_intent(prompt)
    if work_intent == "USE_EXISTING_PLUGIN" or plugin_intent == "USE_EXISTING_PLUGIN":
        if "tool_orchestrator" in enabled:
            return "tool_orchestrator"
        if "executor" in enabled:
            return "executor"
    if work_intent in {"CREATE_PLUGIN", "CONVERT_PLUGIN"} and "plugin_converter" in enabled:
        return "plugin_converter"
    if plugin_intent == "CREATE_OR_CONVERT_PLUGIN" and "plugin_converter" in enabled:
        return "plugin_converter"
    if work_intent == "EVIDENCE_AUDIT" and "evidence_auditor" in enabled:
        return "evidence_auditor"
    if work_intent == "WEB_RESEARCH" and "web_scout" in enabled:
        return "web_scout"
    if work_intent == "BUILD_CODE" and "build" in enabled:
        return "build"
    if work_intent == "KNOWLEDGE_INGESTION" and "knowledge_builder" in enabled:
        return "knowledge_builder"

    # Evidence auditor is never the primary route for simple plugin-execution work.
    if kind and kind in KIND_TO_SPECIALIST:
        candidate = KIND_TO_SPECIALIST[kind]
        if candidate in {"evidence_auditor", "plugin_converter", "build", "retrieval"} and plugin_intent == "USE_EXISTING_PLUGIN":
            candidate = "tool_orchestrator"
        if candidate in enabled:
            return candidate

    lower = prompt.lower()
    # Pure knowledge-persist without plugin use.
    if wants_knowledge_persist(prompt) and "plugin" not in lower and "knowledge_builder" in enabled:
        if any(tok in lower for tok in ("kennis", "knowledge", "ingest", "knowledgeitem")):
            return "knowledge_builder"

    rules: list[tuple[str, tuple[str, ...]]] = [
        ("web_scout", ("http://", "https://", "web scout", "crawl ", "duckduckgo", "actuele bron", "freshness")),
        ("trading_specialist", ("paper trading", "backtest", "strategie", "trading", "orderboek", "ohlcv", "paper bot")),
        ("voice_specialist", ("spraak", "transcript", "voice", "dictee", "tts", "asr")),
        ("tool_orchestrator", ("multi-plugin", "tool orchestr", "plugin workflow", "meerdere tools", "voer plugin", "gebruik plugin")),
        ("evidence_auditor", ("contradictie", "provenance", "evidence audit", "claimdekking", "unsupported claim")),
        ("build", ("codebase", "refactor", "python", "typescript", "patch", "repository", "unit test", "pytest", "compiler")),
        ("research_worker", ("research", "onderzoek", "bronnen", "literatuur", "bewijs", "vergelijk document")),
        ("document_intel", ("document", "pdf", "docx", "extracteer", "parse")),
        # CREATE only — bare "plugin" must not select converter (handled by intent above).
        ("plugin_converter", ("bouw een plugin", "maak een plugin", "converteer", "adapter bouwen", ".hadesplugin", "plugin van github")),
        ("workspace", ("bestand", "map", "folder", "workspace", "bestandspad")),
        ("knowledge_builder", ("knowledgeitem", "kennisbron", "naar kennis", "ingest knowledge")),
        ("memory_curator", ("onthoud", "memory", "voortaan")),
        ("critic", ("verifieer", "controleer claims", "acceptance", "bewijscontrole")),
    ]
    for agent_id, keywords in rules:
        if agent_id == "evidence_auditor" and not is_evidence_primary_task(prompt):
            # Require explicit evidence-audit intent; keyword alone is not enough when mixed with plugin use.
            if plugin_intent != "NONE" or work_intent == "USE_EXISTING_PLUGIN":
                continue
        if agent_id == "build" and plugin_intent == "USE_EXISTING_PLUGIN":
            continue
        if agent_id in enabled and any(keyword in lower for keyword in keywords):
            return agent_id
    return "executor" if "executor" in enabled else "chat"


def specialist_context_filter(agent_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contract = SPECIALISTS.get(agent_id)
    if not contract:
        return items
    allowed = set(contract.context_kinds)
    if not allowed:
        return items
    return [item for item in items if item.get("kind") in allowed or item.get("kind") == "system_policy"]
