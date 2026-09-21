"""Trading Lab agent roles.

Ten roles, each with a narrow mandate, an explicit read/write permission set and a structured
output contract. They are *logical* roles on HADES's existing model gateway, not separate
processes and not separate model downloads: by default every role shares the one loaded local
model and a role may override it only if the operator configures one.

What is deliberately **not** an agent:

- the exchange simulator, the ledger, the risk engine and the order executor. These are
  deterministic services. Asking a language model to decide a fill price or to approve a
  position size would make results unreproducible and unauditable, which is the opposite of
  what this lab is for.

Every role returns structured JSON that is validated before use. A role's free-text reasoning
is never stored as a hidden transcript: what gets persisted is the structured summary, the
evidence it cites and the verification outcome.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

ChatFn = Callable[..., Awaitable[dict[str, Any]]]

READ = "read"
WRITE = "write"


@dataclass(frozen=True)
class AgentRole:
    role_id: str
    name: str
    mandate: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    forbidden: tuple[str, ...]
    output_schema: dict[str, str]
    splits: tuple[str, ...] = ("development",)
    temperature: float = 0.2
    max_tokens: int = 1200

    def as_json(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "name": self.name,
            "mandate": self.mandate,
            "reads": list(self.reads),
            "writes": list(self.writes),
            "forbidden": list(self.forbidden),
            "output_schema": self.output_schema,
            "splits": list(self.splits),
        }


ROLES: dict[str, AgentRole] = {
    role.role_id: role
    for role in (
        AgentRole(
            role_id="research_director",
            name="Research Director",
            mandate=(
                "Turn an operator question into a bounded research plan: which markets, which strategy "
                "families, which datasets, what would count as failure, and in what order the work happens."
            ),
            reads=("strategies", "experiments", "evaluations", "datasets", "knowledge", "trading_beliefs"),
            writes=("plans", "agent_tasks"),
            forbidden=("orders", "risk_limits", "holdout_data"),
            output_schema={
                "objective": "string",
                "steps": "list of {role, task, rationale, depends_on}",
                "success_criteria": "list of strings",
                "failure_criteria": "list of strings",
                "out_of_scope": "list of strings",
            },
        ),
        AgentRole(
            role_id="market_specialist",
            name="Market Specialist",
            mandate=(
                "Describe how one instrument family actually trades: sessions, tick and lot conventions, "
                "typical costs, funding or carry mechanics, and the failure modes a naive backtest hides."
            ),
            reads=("instruments", "datasets", "knowledge", "trading_beliefs"),
            writes=("knowledge_notes",),
            forbidden=("orders", "risk_limits", "holdout_data"),
            output_schema={
                "instrument_family": "string",
                "mechanics": "list of strings",
                "cost_drivers": "list of strings",
                "simulation_caveats": "list of strings",
                "unknowns": "list of strings",
            },
        ),
        AgentRole(
            role_id="data_steward",
            name="Data Steward",
            mandate=(
                "Judge whether a dataset is fit for the question: coverage, gaps, timestamp integrity, "
                "provenance, licence and whether the split boundaries make sense."
            ),
            reads=("datasets", "data_quality", "instruments"),
            writes=("dataset_notes",),
            forbidden=("orders", "holdout_data", "strategy_promotion"),
            output_schema={
                "verdict": "usable | usable_with_caveats | unusable",
                "blocking_issues": "list of strings",
                "caveats": "list of strings",
                "recommended_window": "{start, end}",
            },
        ),
        AgentRole(
            role_id="strategy_researcher",
            name="Strategy Researcher",
            mandate=(
                "Propose a falsifiable strategy hypothesis with an economic rationale, the regimes where it "
                "should and should not work, its benchmark, and how it would be shown to be wrong. Consult "
                "retrieved prior beliefs, known failures and already-tested fingerprints. Prefer research that "
                "adds information; label a replication explicitly rather than repeating a failed candidate."
            ),
            reads=("knowledge", "datasets", "experiments", "instruments", "trading_beliefs", "learning_findings"),
            writes=("strategy_drafts",),
            forbidden=("orders", "risk_limits", "holdout_data", "strategy_promotion"),
            output_schema={
                "name": "string",
                "family": "one of the supported strategy families",
                "economic_rationale": "string, at least two sentences",
                "direction": "long_only | short_only | long_short",
                "horizon": "scalping | intraday | swing | position",
                "params": "object",
                "no_trade_conditions": "list of strings",
                "falsification_criteria": "list of strings",
                "benchmarks": "list of strings",
                "plausible_regimes": "string",
                "implausible_regimes": "string",
            },
        ),
        AgentRole(
            role_id="quant_builder",
            name="Quant Builder",
            mandate=(
                "Map a hypothesis onto the supported strategy families and concrete parameters, or state "
                "plainly that the lab cannot express it. Never invent a family that does not exist."
            ),
            reads=("capabilities", "strategy_drafts", "instruments", "trading_beliefs"),
            writes=("strategy_specs",),
            forbidden=("orders", "risk_limits", "holdout_data"),
            output_schema={
                "family": "string",
                "params": "object",
                "order_type": "string",
                "time_in_force": "string",
                "sizing": "{mode, value}",
                "unsupported_aspects": "list of strings",
            },
        ),
        AgentRole(
            role_id="experiment_planner",
            name="Experiment Planner",
            mandate=(
                "Pre-register the search: parameter space, budget, seed, split and the promotion criteria, "
                "before any trial runs."
            ),
            reads=("strategy_specs", "datasets", "experiments", "trading_beliefs"),
            writes=("experiment_specs",),
            forbidden=("orders", "holdout_data", "strategy_promotion"),
            output_schema={
                "param_space": "object of parameter -> list of values",
                "search_method": "single | grid | random | sequential_refinement",
                "search_budget": "integer",
                "seed": "integer",
                "split": "development",
                "promotion_criteria": "object",
            },
        ),
        AgentRole(
            role_id="independent_validator",
            name="Independent Validator",
            mandate=(
                "Read an evaluation report and state whether the evidence supports the claim. Adversarial by "
                "design: look for selection effects, survivorship, cost optimism and single-trade dependence."
            ),
            reads=("evaluations", "experiments", "runs", "datasets"),
            writes=("validation_notes",),
            forbidden=("strategy_specs", "orders", "experiment_specs"),
            splits=("development", "validation"),
            output_schema={
                "supports_claim": "boolean",
                "weaknesses": "list of strings",
                "alternative_explanations": "list of strings",
                "required_additional_evidence": "list of strings",
            },
            temperature=0.1,
        ),
        AgentRole(
            role_id="risk_analyst",
            name="Risk Analyst",
            mandate=(
                "Interpret exposure, drawdown, margin and concentration in words. Recommends limit changes to "
                "the operator; never applies them."
            ),
            reads=("portfolio", "risk_limits", "runs", "orders", "trading_beliefs"),
            writes=("risk_notes",),
            forbidden=("risk_limits_write", "orders", "holdout_data"),
            output_schema={
                "concerns": "list of strings",
                "recommended_limit_changes": "list of {limit, current, proposed, reason}",
                "kill_switch_recommended": "boolean",
            },
            temperature=0.1,
        ),
        AgentRole(
            role_id="portfolio_analyst",
            name="Portfolio Analyst",
            mandate="Explain where the return came from: which instruments, which regimes, which costs ate it.",
            reads=("portfolio", "runs", "fills", "ledger", "trading_beliefs"),
            writes=("portfolio_notes",),
            forbidden=("orders", "risk_limits", "holdout_data"),
            output_schema={
                "attribution": "list of {bucket, contribution, note}",
                "cost_drag": "string",
                "concentration": "string",
                "caveats": "list of strings",
            },
        ),
        AgentRole(
            role_id="learning_curator",
            name="Learning Curator",
            mandate=(
                "Convert finished experiments into durable lessons, including the negative ones, and link each "
                "lesson to the run, finding or report that supports it. You interpret aggregated metrics; you "
                "do not compute them. A claim without an evidence reference is not knowledge."
            ),
            reads=("experiments", "evaluations", "runs", "knowledge", "trading_beliefs", "learning_findings"),
            writes=("knowledge_notes", "belief_proposals", "candidate_suggestions"),
            forbidden=("orders", "strategy_promotion", "holdout_data"),
            output_schema={
                "new_findings": "list of {claim, evidence_refs, applies_to, confidence_note}",
                "confirmed_beliefs": "list of {belief_id or claim, evidence_refs}",
                "weakened_beliefs": "list of {belief_id or claim, evidence_refs}",
                "contradicted_beliefs": "list of {belief_id or claim, evidence_refs}",
                "superseded_beliefs": "list of {belief_id or claim, evidence_refs, superseded_by}",
                "retired_beliefs": "list of {belief_id or claim, evidence_refs}",
                "open_questions": "list of strings",
                "suggested_next_hypotheses": "list of {hypothesis, evidence_refs, rationale}",
                "suggested_candidate_mutations": "list of {kind, params, reason, evidence_refs}",
            },
        ),
    )
}

DETERMINISTIC_SERVICES = {
    "exchange_simulator": "decides fills; must be reproducible, so no model is involved",
    "ledger": "double-entry accounting; arithmetic, not judgement",
    "risk_engine": "holds the veto; a model can propose, only code decides",
    "order_executor": "translates approved intents into venue actions",
    "evaluation_metrics": "statistics; a model may interpret them but never compute them",
    "experience_store": "derives experiences from delayed outcomes; idempotent, no model",
    "regime_classifier": "point-in-time OHLCV features; no future bars",
    "aggregation_engine": "grouped metrics and sample-sufficiency; no model",
    "belief_confidence": "evidence-quality cap; an LLM cannot raise it",
    "strategy_evolution": "bounded declarative mutations, fingerprints and lineage",
    "champion_policy": "admission and replacement rules over existing evaluations",
}


class RoleViolation(RuntimeError):
    pass


def assert_can_read(role_id: str, resource: str) -> None:
    role = ROLES.get(role_id)
    if role is None:
        raise RoleViolation(f"unknown_role:{role_id}")
    if resource in role.forbidden:
        raise RoleViolation(f"role_{role_id}_may_not_read:{resource}")
    if resource not in role.reads:
        raise RoleViolation(f"role_{role_id}_has_no_read_permission_for:{resource}")


def assert_can_write(role_id: str, resource: str) -> None:
    role = ROLES.get(role_id)
    if role is None:
        raise RoleViolation(f"unknown_role:{role_id}")
    if resource not in role.writes:
        raise RoleViolation(f"role_{role_id}_has_no_write_permission_for:{resource}")


def assert_split_allowed(role_id: str, split: str) -> None:
    role = ROLES.get(role_id)
    if role is None:
        raise RoleViolation(f"unknown_role:{role_id}")
    if split not in role.splits:
        raise RoleViolation(
            f"role_{role_id}_may_not_access_split:{split}; sealed data is reachable only through the "
            "registry's one-shot holdout gate"
        )


@dataclass
class AgentContext:
    """The bounded, factual context a role receives. No free-form dump of the whole database."""

    question: str
    facts: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    prior_results: list[dict[str, Any]] = field(default_factory=list)
    max_fact_chars: int = 12000

    def render(self) -> str:
        payload = json.dumps(self.facts, ensure_ascii=False, indent=2, default=str)
        if len(payload) > self.max_fact_chars:
            payload = payload[: self.max_fact_chars] + "\n...[truncated to keep the context bounded]"
        blocks = [f"QUESTION:\n{self.question}", f"FACTS (the only data you may rely on):\n{payload}"]
        if self.constraints:
            blocks.append("CONSTRAINTS:\n" + "\n".join(f"- {item}" for item in self.constraints))
        if self.prior_results:
            blocks.append(
                "PRIOR STEP OUTPUT:\n"
                + json.dumps(self.prior_results[-3:], ensure_ascii=False, indent=2, default=str)[:4000]
            )
        return "\n\n".join(blocks)


SYSTEM_PREAMBLE = (
    "You are one role inside HADES Trading Lab, a local PAPER and SIMULATION research environment. "
    "No real money, no broker account and no live order ever results from your output.\n"
    "Hard rules:\n"
    "1. Use only the facts provided. If a fact is missing, say it is missing; never estimate a price, "
    "a return or a date.\n"
    "2. You cannot execute, size or approve a trade. The risk engine and the exchange simulator are code "
    "and they ignore anything you say about limits.\n"
    "3. Never claim a result was verified unless the facts contain the verification.\n"
    "4. Answer with a single JSON object matching the schema. No prose outside the JSON.\n"
    "5. Do not reveal step-by-step private reasoning; give conclusions, the evidence behind them and the "
    "uncertainty that remains."
)


def build_messages(role: AgentRole, context: AgentContext) -> list[dict[str, str]]:
    schema = json.dumps(role.output_schema, ensure_ascii=False, indent=2)
    system = (
        f"{SYSTEM_PREAMBLE}\n\nROLE: {role.name}\nMANDATE: {role.mandate}\n"
        f"YOU MAY READ: {', '.join(role.reads)}\nYOU MAY WRITE: {', '.join(role.writes)}\n"
        f"YOU MAY NOT TOUCH: {', '.join(role.forbidden)}\n\nOUTPUT SCHEMA:\n{schema}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": context.render()}]


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_structured(content: str) -> tuple[dict[str, Any] | None, str]:
    """Extract the JSON object. A role that cannot produce valid JSON has failed its contract."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text), ""
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(text)
    if match:
        try:
            return json.loads(match.group(0)), "recovered JSON from surrounding prose"
        except json.JSONDecodeError as exc:
            return None, f"invalid_json:{exc}"
    return None, "no_json_object_in_response"


def missing_fields(role: AgentRole, payload: dict[str, Any]) -> list[str]:
    return [key for key in role.output_schema if key not in payload]


@dataclass
class AgentResult:
    role_id: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    raw_excerpt: str = ""
    error: str = ""
    model_id: str = ""
    prompt_hash: str = ""
    missing_fields: list[str] = field(default_factory=list)
    note: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "model_id": self.model_id,
            "prompt_hash": self.prompt_hash,
            "missing_fields": self.missing_fields,
            "note": self.note,
            "raw_excerpt": self.raw_excerpt[:1200],
        }


class AgentTeam:
    """Runs roles against the shared model gateway with bounded concurrency."""

    def __init__(
        self,
        chat: ChatFn,
        *,
        default_model: str = "",
        role_models: dict[str, str] | None = None,
        max_concurrency: int = 1,
    ) -> None:
        self.chat = chat
        self.default_model = default_model
        self.role_models = dict(role_models or {})
        self.max_concurrency = max(1, int(max_concurrency))

    def model_for(self, role_id: str) -> str:
        return self.role_models.get(role_id) or self.default_model

    async def run_role(
        self,
        role_id: str,
        context: AgentContext,
        *,
        run_id: str | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> AgentResult:
        role = ROLES.get(role_id)
        if role is None:
            return AgentResult(role_id=role_id, status="failed", error=f"unknown_role:{role_id}")
        if cancelled and cancelled():
            return AgentResult(role_id=role_id, status="cancelled", error="cancelled_before_start")
        model_id = self.model_for(role_id)
        if not model_id:
            return AgentResult(
                role_id=role_id,
                status="unavailable",
                error=(
                    "no_model_selected: HADES has no loaded LM Studio model for this role. Load a model or "
                    "configure a role override; the lab will not invent an answer."
                ),
            )
        messages = build_messages(role, context)
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": role.temperature,
            "max_tokens": role.max_tokens,
            "stream": False,
        }
        from trading_lab.contracts import stable_hash

        prompt_hash = stable_hash(messages)
        try:
            response = await self.chat(payload, surface="trading_lab", run_id=run_id, model_id=model_id)
        except Exception as exc:  # noqa: BLE001 - a model failure is a reported outcome, not a crash
            return AgentResult(
                role_id=role_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                model_id=model_id,
                prompt_hash=prompt_hash,
            )
        content = _extract_content(response)
        parsed, note = parse_structured(content)
        if parsed is None:
            return AgentResult(
                role_id=role_id,
                status="invalid_output",
                error=note,
                raw_excerpt=content,
                model_id=model_id,
                prompt_hash=prompt_hash,
            )
        absent = missing_fields(role, parsed)
        return AgentResult(
            role_id=role_id,
            status="completed" if not absent else "incomplete",
            output=parsed,
            raw_excerpt=content,
            model_id=model_id,
            prompt_hash=prompt_hash,
            missing_fields=absent,
            note=note,
        )

    async def run_sequence(
        self,
        steps: Sequence[tuple[str, AgentContext]],
        *,
        run_id: str | None = None,
        cancelled: Callable[[], bool] | None = None,
        on_step: Callable[[AgentResult], None] | None = None,
    ) -> list[AgentResult]:
        """Roles run in order and each sees the previous structured outputs, never raw transcripts."""
        results: list[AgentResult] = []
        for role_id, context in steps:
            if cancelled and cancelled():
                results.append(AgentResult(role_id=role_id, status="cancelled", error="cancelled_by_operator"))
                break
            context.prior_results = [result.output for result in results if result.output]
            result = await self.run_role(role_id, context, run_id=run_id, cancelled=cancelled)
            results.append(result)
            if on_step:
                on_step(result)
            if result.status in {"failed", "unavailable"}:
                break
        return results


def _extract_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "")


def default_pipeline(question: str, facts: dict[str, Any]) -> list[tuple[str, AgentContext]]:
    """The standard research chain from question to a pre-registered experiment."""
    constraints = [
        "This is a simulation-only environment. Nothing you write can place an order.",
        "Cite only instruments and datasets that appear in the facts.",
        "If the available data cannot support the question, say so and stop.",
    ]
    return [
        ("research_director", AgentContext(question=question, facts=facts, constraints=constraints)),
        ("data_steward", AgentContext(question=f"Is the available data fit for: {question}", facts=facts, constraints=constraints)),
        ("strategy_researcher", AgentContext(question=question, facts=facts, constraints=constraints)),
        ("quant_builder", AgentContext(question=f"Express this hypothesis with supported families: {question}", facts=facts, constraints=constraints)),
        ("experiment_planner", AgentContext(question=f"Pre-register the search for: {question}", facts=facts, constraints=constraints)),
    ]


def roles_manifest() -> dict[str, Any]:
    return {
        "roles": [role.as_json() for role in ROLES.values()],
        "deterministic_services": DETERMINISTIC_SERVICES,
        "note": (
            "Roles share one local model by default. Per-role overrides are optional and are resolved from "
            "settings at call time; no model id is hardcoded."
        ),
    }


__all__ = [
    "AgentContext",
    "AgentResult",
    "AgentRole",
    "AgentTeam",
    "DETERMINISTIC_SERVICES",
    "ROLES",
    "RoleViolation",
    "assert_can_read",
    "assert_can_write",
    "assert_split_allowed",
    "build_messages",
    "default_pipeline",
    "parse_structured",
    "roles_manifest",
]
