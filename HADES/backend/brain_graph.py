"""Brain graph assembly (sync I/O) — extracted from main for maintainability (work package L).

Callers should run ``assemble_brain_graph`` via ``asyncio.to_thread`` from async handlers.
"""

from __future__ import annotations

from typing import Any


RELATION_KINDS = (
    "structural",
    "provenance",
    "supersession",
    "explicit_link",
    "execution",
    "semantic_similarity",
)

DERIVED_PREFIXES = ("memory_", "knowledge_", "conversation_", "task_", "step_", "core_")


def is_derived_entity_id(entity_id: str) -> bool:
    return str(entity_id).startswith(DERIVED_PREFIXES)


def assemble_brain_graph(
    *,
    database: Any,
    platform_db: Any,
    soft_cap: int,
    view_id: str = "default",
) -> dict[str, Any]:
    """Build the Brain GET payload. Blocking SQLite/platform I/O — keep off the event loop.

    The assembled graph is deliberately self-consistent: persisted external links whose
    endpoint no longer exists (for example after deleting a memory/knowledge source/task)
    are not exposed to clients. The persisted row is left untouched so this read path never
    performs surprising cleanup writes.
    """
    soft_cap = max(50, int(soft_cap))
    nodes = list(database.list_brain_nodes())
    links = list(database.list_brain_links())
    links.extend(platform_db.list_brain_external_links())
    layout = database.list_brain_layout(view_id)
    layout_by_id = {row["entity_id"]: row for row in layout.get("positions") or []}

    available = {
        "memories": database.count_memories(active_only=True),
        "knowledge": platform_db.count_knowledge_sources(),
        "conversations": database.count_conversations(),
        "tasks": database.count_tasks(),
        "manual_nodes": len(nodes),
    }
    included = {"memories": 0, "knowledge": 0, "conversations": 0, "tasks": 0, "work_steps": 0}

    for memory in database.list_memories(limit=soft_cap):
        included["memories"] += 1
        node_id = f"memory_{memory['id']}"
        layout_row = layout_by_id.get(node_id) or {}
        nodes.append(
            {
                "id": node_id,
                "label": memory["title"],
                "kind": "memory",
                "description": memory["summary"] or memory["content"],
                "tags": memory["tags"],
                "source": memory["source"],
                "created_at": memory["created_at"],
                "updated_at": memory["updated_at"],
                "open_href": f"#/memory?id={memory['id']}",
                "status": memory.get("status"),
                "persistent": True,
                "pos_x": layout_row.get("pos_x"),
                "pos_y": layout_row.get("pos_y"),
                "pinned": bool(layout_row.get("pinned")),
                "content_editable": False,
                "layout_movable": True,
            }
        )
        links.append(
            {"source_id": "core_memory", "target_id": node_id, "relation": "bevat", "relation_kind": "structural"}
        )
        if memory.get("supersedes"):
            links.append(
                {
                    "source_id": node_id,
                    "target_id": f"memory_{memory['supersedes']}",
                    "relation": "vervangt",
                    "relation_kind": "supersession",
                }
            )
    for source in platform_db.list_knowledge_sources(soft_cap):
        included["knowledge"] += 1
        node_id = f"knowledge_{source['id']}"
        layout_row = layout_by_id.get(node_id) or {}
        nodes.append(
            {
                "id": node_id,
                "label": source["title"][:90],
                "kind": "knowledge",
                "description": source["uri"],
                "tags": [source["source_type"]],
                "source": source["source_type"],
                "created_at": source["created_at"],
                "updated_at": source["updated_at"],
                "open_href": f"#/files?knowledge={source['id']}",
                "version": source.get("content_hash"),
                "persistent": True,
                "pos_x": layout_row.get("pos_x"),
                "pos_y": layout_row.get("pos_y"),
                "pinned": bool(layout_row.get("pinned")),
                "content_editable": False,
                "layout_movable": True,
            }
        )
        links.append(
            {
                "source_id": "core_memory",
                "target_id": node_id,
                "relation": "kennisbron",
                "relation_kind": "provenance",
            }
        )
    for conversation in database.list_conversations()[:soft_cap]:
        included["conversations"] += 1
        node_id = f"conversation_{conversation['id']}"
        layout_row = layout_by_id.get(node_id) or {}
        nodes.append(
            {
                "id": node_id,
                "label": conversation.get("title") or conversation["id"],
                "kind": "chat",
                "description": f"Gesprek {conversation['id']}",
                "tags": ["conversation"],
                "source": "chat",
                "created_at": conversation.get("created_at"),
                "updated_at": conversation.get("updated_at"),
                "open_href": f"#/chat?c={conversation['id']}",
                "persistent": True,
                "pos_x": layout_row.get("pos_x"),
                "pos_y": layout_row.get("pos_y"),
                "pinned": bool(layout_row.get("pinned")),
                "content_editable": False,
                "layout_movable": True,
            }
        )
        links.append(
            {"source_id": "core_chat", "target_id": node_id, "relation": "bevat", "relation_kind": "structural"}
        )
        state = conversation.get("working_state") if isinstance(conversation.get("working_state"), dict) else {}
        for artifact in (state or {}).get("artifact_refs") or []:
            if str(artifact).startswith("task:"):
                links.append(
                    {
                        "source_id": node_id,
                        "target_id": f"task_{str(artifact).split(':', 1)[1]}",
                        "relation": "koppelt_taak",
                        "relation_kind": "explicit_link",
                    }
                )
    for task in database.list_tasks()[:soft_cap]:
        included["tasks"] += 1
        node_id = f"task_{task['id']}"
        layout_row = layout_by_id.get(node_id) or {}
        nodes.append(
            {
                "id": node_id,
                "label": task.get("title") or task["id"],
                "kind": "task",
                "description": (task.get("prompt") or "")[:240],
                "tags": [task.get("status") or "task", task.get("agent") or ""],
                "source": "work",
                "created_at": task.get("created_at"),
                "updated_at": task.get("updated_at"),
                "open_href": f"#/tasks?t={task['id']}",
                "pos_x": layout_row.get("pos_x"),
                "pos_y": layout_row.get("pos_y"),
                "pinned": bool(layout_row.get("pinned")),
                "content_editable": False,
                "layout_movable": True,
            }
        )
        links.append(
            {"source_id": "core_tasks", "target_id": node_id, "relation": "bevat", "relation_kind": "structural"}
        )
        for step in platform_db.work_steps(task["id"]):
            included["work_steps"] += 1
            step_id = f"step_{step['id']}"
            step_layout = layout_by_id.get(step_id) or {}
            nodes.append(
                {
                    "id": step_id,
                    "label": step.get("title") or step["id"],
                    "kind": "work_step",
                    "description": f"{step.get('agent_id')}: {(step.get('instruction') or '')[:160]}",
                    "tags": [step.get("status") or "", step.get("agent_id") or ""],
                    "source": "work",
                    "created_at": step.get("created_at"),
                    "updated_at": step.get("updated_at"),
                    "open_href": f"#/tasks?t={task['id']}",
                    "pos_x": step_layout.get("pos_x"),
                    "pos_y": step_layout.get("pos_y"),
                    "pinned": bool(step_layout.get("pinned")),
                    "content_editable": False,
                    "layout_movable": True,
                }
            )
            links.append(
                {"source_id": node_id, "target_id": step_id, "relation": "produceert", "relation_kind": "execution"}
            )

    # Normalize permissions/layout for *every* node. Previously these flags were
    # accidentally only added to manual/core nodes after a saved layout existed.
    for node in nodes:
        saved = layout_by_id.get(node["id"]) or {}
        if saved:
            if node.get("pos_x") is None:
                node["pos_x"] = saved.get("pos_x")
            if node.get("pos_y") is None:
                node["pos_y"] = saved.get("pos_y")
            node["pinned"] = bool(saved.get("pinned"))
        else:
            node.setdefault("pinned", False)
        if "content_editable" not in node:
            node["content_editable"] = not is_derived_entity_id(str(node["id"]))
        if "layout_movable" not in node:
            node["layout_movable"] = True

    # External links intentionally have no foreign keys because their endpoints
    # live across multiple stores. Never send a dangling edge to the UI: stale
    # edges otherwise inflate counts, block relation creation and break inspector
    # consistency after an entity is deleted or excluded by the current soft cap.
    node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    links = [
        link
        for link in links
        if str(link.get("source_id") or "") in node_ids and str(link.get("target_id") or "") in node_ids
    ]

    truncated = any(
        included[key] < available[key] for key in ("memories", "knowledge", "conversations", "tasks")
    )
    return {
        "nodes": nodes,
        "links": links,
        "layout": layout,
        "view_id": view_id,
        "counts": {
            "nodes": len(nodes),
            "links": len(links),
            "available": available,
            "included": included,
            "visible_hint": len(nodes),
            "truncated": truncated,
        },
        "relation_kinds": list(RELATION_KINDS),
    }
