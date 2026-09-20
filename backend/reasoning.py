from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReasoningPlan:
    intent: str
    complexity: str
    use_knowledge: bool
    steps: tuple[str, ...]

    def public_summary(self) -> dict:
        """Return a compact execution summary, never hidden chain-of-thought."""
        return asdict(self)


class ReasoningEngine:
    """Small deterministic planning layer for Step 1.

    This is intentionally simple. It gives the runtime a stable seam for a later
    planner/router without making model-generated hidden reasoning authoritative.
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
        "hades", "document", "database", "context",
    }

    def analyze(self, message: str, has_knowledge: bool) -> ReasoningPlan:
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

        # Step 1 uses retrieval for substantive prompts when knowledge exists.
        use_knowledge = has_knowledge and (intent != "conversation" or word_count >= 8)

        steps: list[str] = ["understand_request"]
        if use_knowledge:
            steps.append("retrieve_relevant_knowledge")
        if complexity in {"medium", "high"}:
            steps.append("structure_response")
        steps.append("generate_answer")

        return ReasoningPlan(
            intent=intent,
            complexity=complexity,
            use_knowledge=use_knowledge,
            steps=tuple(steps),
        )
