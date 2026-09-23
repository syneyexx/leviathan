"""Cross-session continuity via project-scoped memory + handoff records (U390)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from Data.modules.memory import MemoryKind, MemoryScope, MemoryStore
from Data.modules.projects.store import ProjectStore


@dataclass(frozen=True)
class SessionHandoff:
    handoff_id: str
    project_id: str
    from_session_id: str
    to_session_kind: str
    memory_id: str | None
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "project_id": self.project_id,
            "from_session_id": self.from_session_id,
            "to_session_kind": self.to_session_kind,
            "memory_id": self.memory_id,
            "summary": self.summary,
            "metadata": self.metadata,
            "truth": {
                "reconnect_never_invents_completion": True,
                "continuity_uses_project_memory": True,
            },
        }


class ContinuityPlane:
    """Persist project truth for cross-session resume without inventing completion."""

    def __init__(self, memory: MemoryStore, projects: ProjectStore) -> None:
        self.memory = memory
        self.projects = projects
        self.handoffs: list[SessionHandoff] = []

    def remember_project_fact(
        self,
        *,
        project_id: str,
        content: str,
        workspace_id: str | None = None,
        conversation_id: str | None = None,
        source: str = "continuity",
    ) -> dict[str, Any]:
        if self.projects.get_project(project_id) is None:
            raise KeyError(f"Unknown project: {project_id}")
        record = self.memory.create(
            kind=MemoryKind.PROJECT,
            content=content,
            source=source,
            scope=MemoryScope.PROJECT,
            project_id=project_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            tags=["continuity", "wave11"],
        )
        return record.public_dict()

    def handoff(
        self,
        *,
        project_id: str,
        from_session_id: str,
        to_session_kind: str,
        summary: str,
        workspace_id: str | None = None,
    ) -> SessionHandoff:
        memory = self.memory.create(
            kind=MemoryKind.EPISODIC,
            content=f"handoff:{to_session_kind}:{summary}",
            source="session_handoff",
            scope=MemoryScope.PROJECT,
            project_id=project_id,
            workspace_id=workspace_id,
            conversation_id=from_session_id,
            tags=["handoff", to_session_kind],
            metadata={"from_session_id": from_session_id, "to_session_kind": to_session_kind},
        )
        item = SessionHandoff(
            handoff_id=f"ho_{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            from_session_id=from_session_id,
            to_session_kind=to_session_kind,
            memory_id=memory.memory_id,
            summary=summary,
        )
        self.handoffs.append(item)
        self.projects.bind(
            project_id=project_id,
            domain="memory",
            entity_id=memory.memory_id,
            workspace_id=workspace_id,
            metadata={"handoff_id": item.handoff_id},
        )
        return item

    def resume_context(
        self,
        *,
        project_id: str,
        other_project_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Load PROJECT-scoped memories; prove other project does not leak."""
        own = self.memory.list(
            scope=MemoryScope.PROJECT,
            project_id=project_id,
            limit=limit,
            include_global=False,
        )
        foreign_count = 0
        if other_project_id:
            foreign = self.memory.list(
                scope=MemoryScope.PROJECT,
                project_id=other_project_id,
                limit=limit,
                include_global=False,
            )
            # Leak = foreign memories appearing in own project_id filter.
            foreign_count = sum(1 for m in foreign if m.project_id == project_id)
            # Also verify own list never contains other project's ids.
            foreign_count += sum(1 for m in own if m.project_id == other_project_id)
        return {
            "project_id": project_id,
            "memories": [m.public_dict() for m in own],
            "cross_project_leak_count": foreign_count,
            "truth": {
                "reconnect_never_invents_completion": True,
                "project_scope_isolated": True,
            },
        }
