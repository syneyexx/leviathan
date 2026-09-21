"""Resolve durable Brain entities into full, user-readable detail payloads.

The graph itself intentionally stays lightweight. This module is used by the
on-demand detail endpoint so clicking a node can show the underlying stored
content without inflating every /brain response.
"""

from __future__ import annotations

from typing import Any

DETAIL_CHAR_LIMIT = 2_000_000
DETAIL_ITEM_LIMIT = 5_000


def _section(title: str, content: Any, **metadata: Any) -> dict[str, Any]:
    return {
        "title": str(title or "Inhoud"),
        "content": str(content or ""),
        "metadata": {key: value for key, value in metadata.items() if value is not None},
    }


def _bound_sections(sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool, int, int]:
    """Bound pathological payloads while keeping normal research pages complete."""
    total_chars = sum(len(str(item.get("content") or "")) for item in sections)
    remaining = DETAIL_CHAR_LIMIT
    output: list[dict[str, Any]] = []
    truncated = len(sections) > DETAIL_ITEM_LIMIT

    for item in sections[:DETAIL_ITEM_LIMIT]:
        if remaining <= 0:
            truncated = True
            break
        content = str(item.get("content") or "")
        clipped = content[:remaining]
        output.append({**item, "content": clipped})
        remaining -= len(clipped)
        if len(clipped) < len(content):
            truncated = True
            break

    if len(output) < min(len(sections), DETAIL_ITEM_LIMIT):
        truncated = True
    returned_chars = sum(len(str(item.get("content") or "")) for item in output)
    return output, truncated, total_chars, returned_chars


def _finish(
    *,
    node_id: str,
    kind: str,
    title: str,
    description: str = "",
    source: str = "",
    source_uri: str | None = None,
    open_href: str | None = None,
    status: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    sections: list[dict[str, Any]] | None = None,
    force_truncated: bool = False,
) -> dict[str, Any]:
    bounded, truncated, total_chars, returned_chars = _bound_sections(sections or [])
    return {
        "id": node_id,
        "kind": kind,
        "title": title,
        "description": description,
        "source": source,
        "source_uri": source_uri,
        "open_href": open_href,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "metadata": metadata or {},
        "sections": bounded,
        "truncated": bool(force_truncated or truncated),
        "content_chars": total_chars,
        "returned_chars": returned_chars,
    }


def build_brain_node_detail(*, database: Any, platform_db: Any, node_id: str) -> dict[str, Any]:
    """Return the persisted content behind a Brain node.

    Raises ``KeyError`` when the derived entity no longer exists. The HTTP layer
    maps that to a 404, which also handles stale graph tabs cleanly.
    """
    if node_id.startswith("knowledge_"):
        source_id = node_id.removeprefix("knowledge_")
        source = platform_db.get_knowledge_source(source_id)
        if not source:
            raise KeyError(node_id)
        chunks = platform_db.list_knowledge_chunks(source_id, limit=DETAIL_ITEM_LIMIT + 1)
        has_more_chunks = len(chunks) > DETAIL_ITEM_LIMIT
        chunks = chunks[:DETAIL_ITEM_LIMIT]
        sections = [
            _section(
                chunk.get("heading") or f"Fragment {int(chunk.get('sequence') or 0) + 1}",
                chunk.get("content") or "",
                sequence=chunk.get("sequence"),
                token_estimate=chunk.get("token_estimate"),
                created_at=chunk.get("created_at"),
            )
            for chunk in chunks
        ]
        return _finish(
            node_id=node_id,
            kind="knowledge",
            title=str(source.get("title") or source_id),
            description=str(source.get("uri") or ""),
            source=str(source.get("source_type") or "knowledge"),
            source_uri=str(source.get("uri") or "") or None,
            open_href=f"#/files?knowledge={source_id}",
            status=source.get("status"),
            created_at=source.get("created_at"),
            updated_at=source.get("updated_at"),
            metadata={
                **(source.get("metadata") if isinstance(source.get("metadata"), dict) else {}),
                "local_path": source.get("local_path"),
                "content_hash": source.get("content_hash"),
                "chunk_count_loaded": len(chunks),
            },
            sections=sections,
            force_truncated=has_more_chunks,
        )

    if node_id.startswith("memory_"):
        memory_id = node_id.removeprefix("memory_")
        memory = database.get_memory(memory_id)
        if not memory:
            raise KeyError(node_id)
        return _finish(
            node_id=node_id,
            kind="memory",
            title=str(memory.get("title") or memory_id),
            description=str(memory.get("summary") or ""),
            source=str(memory.get("source") or "memory"),
            open_href=f"#/memory?id={memory_id}",
            status=memory.get("status"),
            created_at=memory.get("created_at"),
            updated_at=memory.get("updated_at"),
            metadata={
                "collection": memory.get("collection"),
                "tags": memory.get("tags") or [],
                "scope": memory.get("scope"),
                "memory_type": memory.get("memory_type"),
                "confidence": memory.get("confidence"),
                "importance": memory.get("importance"),
            },
            sections=[_section("Volledige memory", memory.get("content") or "")],
        )

    if node_id.startswith("conversation_"):
        conversation_id = node_id.removeprefix("conversation_")
        conversation = database.get_conversation(conversation_id)
        if not conversation:
            raise KeyError(node_id)
        messages = database.list_messages(conversation_id, active_only=False)
        sections = [
            _section(
                f"{str(message.get('role') or 'bericht').capitalize()} · {index + 1}",
                message.get("content") or "",
                created_at=message.get("created_at"),
                message_id=message.get("id"),
                branch_id=message.get("branch_id"),
                active=message.get("is_active"),
            )
            for index, message in enumerate(messages)
        ]
        return _finish(
            node_id=node_id,
            kind="chat",
            title=str(conversation.get("title") or conversation_id),
            description=f"{len(messages)} opgeslagen bericht(en)",
            source="chat",
            open_href=f"#/chat?c={conversation_id}",
            created_at=conversation.get("created_at"),
            updated_at=conversation.get("updated_at"),
            metadata={
                "model_id": conversation.get("model_id"),
                "system_prompt_override": conversation.get("system_prompt_override"),
                "active_branch_id": conversation.get("active_branch_id"),
                "message_count": len(messages),
            },
            sections=sections,
        )

    if node_id.startswith("task_"):
        task_id = node_id.removeprefix("task_")
        task = database.get_task(task_id)
        if not task:
            raise KeyError(node_id)
        events = database.task_events(task_id)
        steps = platform_db.work_steps(task_id)
        sections = [_section("Opdracht", task.get("prompt") or "")]
        if task.get("result"):
            sections.append(_section("Resultaat", task.get("result")))
        if task.get("error"):
            sections.append(_section("Fout", task.get("error")))
        if events:
            sections.append(
                _section(
                    "Taaklog",
                    "\n".join(
                        f"[{event.get('created_at') or ''}] {event.get('level') or 'info'}: {event.get('message') or ''}"
                        for event in events
                    ),
                    events=len(events),
                )
            )
        for step in steps:
            step_content = str(step.get("instruction") or "")
            if step.get("output"):
                step_content += f"\n\nResultaat:\n{step.get('output')}"
            if step.get("error"):
                step_content += f"\n\nFout:\n{step.get('error')}"
            sections.append(
                _section(
                    f"Stap {int(step.get('step_index') or 0) + 1}: {step.get('title') or step.get('id')}",
                    step_content,
                    status=step.get("status"),
                    agent_id=step.get("agent_id"),
                    step_id=step.get("id"),
                )
            )
        return _finish(
            node_id=node_id,
            kind="task",
            title=str(task.get("title") or task_id),
            description=str(task.get("prompt") or "")[:500],
            source="work",
            open_href=f"#/tasks?t={task_id}",
            status=task.get("status"),
            created_at=task.get("created_at"),
            updated_at=task.get("updated_at"),
            metadata={
                "agent": task.get("agent"),
                "priority": task.get("priority"),
                "progress": task.get("progress"),
                "model_id": task.get("model_id"),
                "control_state": task.get("control_state"),
                "plan_version": task.get("plan_version"),
                "events": len(events),
                "steps": len(steps),
            },
            sections=sections,
        )

    if node_id.startswith("step_"):
        step_id = node_id.removeprefix("step_")
        step = next(
            (item for item in platform_db.list_work_steps(limit=10_000) if str(item.get("id")) == step_id),
            None,
        )
        if not step:
            raise KeyError(node_id)
        content = str(step.get("instruction") or "")
        if step.get("output"):
            content += f"\n\nResultaat:\n{step.get('output')}"
        if step.get("error"):
            content += f"\n\nFout:\n{step.get('error')}"
        task_id = str(step.get("task_id") or "")
        return _finish(
            node_id=node_id,
            kind="work_step",
            title=str(step.get("title") or step_id),
            description=str(step.get("instruction") or "")[:500],
            source="work",
            open_href=f"#/tasks?t={task_id}" if task_id else None,
            status=step.get("status"),
            created_at=step.get("created_at"),
            updated_at=step.get("updated_at"),
            metadata={
                "task_id": task_id,
                "agent_id": step.get("agent_id"),
                "step_index": step.get("step_index"),
                "step_key": step.get("step_key"),
                "depends_on": step.get("depends_on") or [],
            },
            sections=[_section("Volledige stap", content)],
        )

    node = next((item for item in database.list_brain_nodes() if str(item.get("id")) == node_id), None)
    if not node:
        raise KeyError(node_id)
    return _finish(
        node_id=node_id,
        kind=str(node.get("kind") or "note"),
        title=str(node.get("label") or node_id),
        description=str(node.get("description") or ""),
        source=str(node.get("source") or "brain"),
        created_at=node.get("created_at"),
        updated_at=node.get("updated_at"),
        metadata={"tags": node.get("tags") or []},
        sections=[_section("Inhoud", node.get("description") or "")],
    )
