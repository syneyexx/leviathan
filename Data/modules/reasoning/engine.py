from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReasoningPlan:
    intent: str
    complexity: str
    use_knowledge: bool
    steps: tuple[str, ...]
    use_deep_recall: bool = False
    use_atlas: bool = False
    economy: dict | None = None

    def public_summary(self) -> dict:
        """Return a compact execution summary, never hidden chain-of-thought."""
        return asdict(self)


class ReasoningEngine:
    """Small deterministic planning layer.

    Stable seam for later planner/router work without making model-generated
    hidden reasoning authoritative.
    """

    CODING_TERMS = {
        "code", "python", "javascript", "typescript", "c++", "bug", "debug",
        "repo", "repository", "function", "class", "api", "database", "sql",
    }
    RESEARCH_TERMS = {
        "research", "onderzoek", "analyseer", "analyze", "compare", "vergelijk",
        "latest", "recent", "bron", "source", "evidence",
    }
    KNOWLEDGE_TERMS = {
        "knowledge", "kennis", "remember", "memory", "project", "leviathan",
        "hades", "document", "database", "context", "recall", "atlas",
    }
    DEEP_RECALL_TERMS = {
        "exactly", "exact", "detail", "cite", "citation", "quote", "precise",
        "deep recall", "hydrate", "evidence id", "chunk",
    }

    def analyze(
        self,
        message: str,
        has_knowledge: bool,
        *,
        deep_recall_enabled: bool = False,
        economy_allow_deep_recall: bool = False,
        memory_coverage: float = 1.0,
    ) -> ReasoningPlan:
        text = message.strip().lower()
        words = set(text.replace("/", " ").replace("-", " ").split())

        if words & self.CODING_TERMS:
            intent = "coding"
        elif words & self.RESEARCH_TERMS:
            intent = "research"
        elif words & self.KNOWLEDGE_TERMS:
            intent = "knowledge"
        elif text.endswith("?"):
            intent = "question"
        else:
            intent = "conversation"

        word_count = len(text.split())
        complexity = "high" if word_count > 120 else "medium" if word_count > 35 else "low"

        use_knowledge = has_knowledge and (intent != "conversation" or word_count >= 8)
        use_atlas = use_knowledge and intent in {"knowledge", "research", "analysis", "question"}
        wants_precision = any(term in text for term in self.DEEP_RECALL_TERMS)
        use_deep_recall = bool(
            deep_recall_enabled
            and use_knowledge
            and (
                economy_allow_deep_recall
                or wants_precision
                or (memory_coverage < 0.35 and complexity in {"medium", "high"})
            )
        )

        steps: list[str] = ["understand_request"]
        if use_atlas and not use_deep_recall:
            steps.append("retrieve_atlas_context")
        if use_deep_recall:
            steps.append("deep_recall_hydrate")
        elif use_knowledge:
            steps.append("retrieve_relevant_knowledge")
        if complexity in {"medium", "high"}:
            steps.append("structure_response")
        steps.append("generate_answer")

        return ReasoningPlan(
            intent=intent,
            complexity=complexity,
            use_knowledge=use_knowledge,
            steps=tuple(steps),
            use_deep_recall=use_deep_recall,
            use_atlas=use_atlas,
        )
