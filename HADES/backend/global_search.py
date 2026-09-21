"""Unified local search across conversations, tasks, memories, knowledge and artifacts."""

from __future__ import annotations

import urllib.parse
from typing import Any


def _snippet(text: str, needle: str, radius: int = 80) -> str:
    lower = text.lower()
    idx = lower.find(needle.lower())
    if idx < 0:
        return text[: radius * 2].strip()
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


class GlobalSearchService:
    def __init__(self, database: Any, platform_db: Any) -> None:
        self.database = database
        self.platform_db = platform_db

    def search(
        self,
        query: str,
        *,
        limit_per_type: int = 8,
        project_id: str | None = None,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        needle = (query or "").strip()
        if not needle:
            return {"query": query, "groups": {}, "commands": self.commands_matching("")}
        groups: dict[str, list[dict[str, Any]]] = {
            "pages": [],
            "conversations": [],
            "messages": [],
            "tasks": [],
            "memories": [],
            "knowledge": [],
            "artifacts": [],
            "research": [],
        }

        # Conversations / messages. Project-scoped search may include unscoped
        # conversations (existing product behavior), but must never surface a
        # message whose parent conversation belongs to another project.
        conversations = self.database.list_conversations()
        allowed_conversation_ids = {
            str(conversation.get("id") or "")
            for conversation in conversations
            if conversation.get("id")
            and (
                not project_id
                or conversation.get("project_id") in {None, project_id}
            )
        }
        for conversation in conversations:
            if project_id and conversation.get("project_id") not in {None, project_id}:
                continue
            title = str(conversation.get("title") or "")
            if needle.lower() in title.lower():
                groups["conversations"].append({
                    "type": "conversation",
                    "id": conversation["id"],
                    "title": title,
                    "snippet": title,
                    "updated_at": conversation.get("updated_at"),
                    "href": f"#/chat?c={conversation['id']}",
                })
            if len(groups["conversations"]) >= limit_per_type:
                break

        for message in self.database.search_messages(needle, limit=limit_per_type):
            if message.get("deleted"):
                continue
            if project_id and str(message.get("conversation_id") or "") not in allowed_conversation_ids:
                continue
            groups["messages"].append({
                "type": "message",
                "id": message["id"],
                "title": f"{message.get('role', 'message')} · {message.get('conversation_id')}",
                "snippet": _snippet(str(message.get("content") or ""), needle),
                "updated_at": message.get("created_at"),
                "conversation_id": message.get("conversation_id"),
                "href": f"#/chat?c={message.get('conversation_id')}&m={message['id']}",
            })

        for task in self.database.list_tasks():
            blob = f"{task.get('title', '')} {task.get('prompt', '')} {task.get('result') or ''}"
            if needle.lower() not in blob.lower():
                continue
            groups["tasks"].append({
                "type": "task",
                "id": task["id"],
                "title": task.get("title") or task["id"],
                "snippet": _snippet(blob, needle),
                "updated_at": task.get("updated_at"),
                "status": task.get("status"),
                "href": f"#/tasks?t={task['id']}",
            })
            if len(groups["tasks"]) >= limit_per_type:
                break

        for memory in self.database.list_memories(query=needle, limit=limit_per_type):
            if memory.get("status") == "deleted" and not include_deleted:
                continue
            if memory.get("status") == "forgotten" and not include_deleted:
                continue
            groups["memories"].append({
                "type": "memory",
                "id": memory["id"],
                "title": memory.get("title") or memory["id"],
                "snippet": _snippet(str(memory.get("content") or memory.get("summary") or ""), needle),
                "updated_at": memory.get("updated_at"),
                "href": f"#/memory?id={memory['id']}",
            })

        for hit in self.platform_db.search_knowledge(needle, limit=limit_per_type):
            meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            if meta.get("forgotten") and not include_deleted:
                continue
            groups["knowledge"].append({
                "type": "knowledge",
                "id": hit.get("chunk_id") or hit.get("id"),
                "title": hit.get("title") or "Knowledge",
                "snippet": _snippet(str(hit.get("text") or hit.get("content") or ""), needle),
                "updated_at": hit.get("updated_at"),
                "href": f"#/files?q={urllib.parse.quote(needle)}",
            })

        if hasattr(self.platform_db, "search_artifacts"):
            for art in self.platform_db.search_artifacts(needle, limit=limit_per_type):
                if art.get("status") == "deleted" and not include_deleted:
                    continue
                if project_id and art.get("project_id") not in {None, project_id}:
                    continue
                groups["artifacts"].append({
                    "type": "artifact",
                    "id": art["id"],
                    "title": art.get("name") or art["id"],
                    "snippet": f"{art.get('kind')} · {art.get('mime_type')} · {art.get('status')}",
                    "updated_at": art.get("updated_at"),
                    "href": f"#/files?artifact={art['id']}",
                })

        if hasattr(self.platform_db, "list_research_projects"):
            for project in self.platform_db.list_research_projects()[:200]:
                blob = f"{project.get('title', '')} {project.get('goal', '')} {project.get('status', '')}"
                if needle.lower() not in blob.lower():
                    continue
                groups["research"].append({
                    "type": "research",
                    "id": project["id"],
                    "title": project.get("title") or project["id"],
                    "snippet": _snippet(blob, needle),
                    "updated_at": project.get("updated_at"),
                    "href": f"#/research?p={project['id']}",
                })
                if len(groups["research"]) >= limit_per_type:
                    break

        # Trim empty groups for UI clarity but keep key order.
        compact = {key: value for key, value in groups.items() if value}
        return {
            "query": needle,
            "groups": compact,
            "commands": self.commands_matching(needle),
        }

    def commands_matching(self, query: str) -> list[dict[str, Any]]:
        commands = [
            {"id": "new_chat", "title": "Nieuw gesprek", "href": "#/chat?new=1", "action": "navigate", "group": "os"},
            {"id": "pin_folder", "title": "Map vastzetten", "href": "#/chat?pin=folder", "action": "navigate", "group": "os"},
            {"id": "start_research", "title": "Onderzoek starten", "href": "#/chat?mode=research", "action": "navigate", "group": "os"},
            {"id": "start_coding", "title": "Coding starten", "href": "#/chat?mode=code", "action": "navigate", "group": "os"},
            {"id": "open_settings", "title": "Instellingen", "href": "#/settings", "action": "navigate", "group": "os"},
            {"id": "new_task", "title": "Nieuwe taak", "href": "#/tasks?new=1", "action": "navigate", "group": "os"},
            {"id": "voice_to_task", "title": "Spraak → taak", "href": "#/tasks?voice=1", "action": "navigate", "group": "os"},
            {"id": "open_approvals", "title": "Openstaande aanvragen", "href": "#/tasks?inbox=approvals", "action": "navigate", "group": "os"},
            {"id": "open_inbox", "title": "Inbox openen", "href": "#/tasks?inbox=1", "action": "navigate", "group": "os"},
            {"id": "open_agents", "title": "Agents / specialisten", "href": "#/agents", "action": "navigate", "group": "os"},
            {"id": "open_plugins", "title": "Plugins", "href": "#/plugins", "action": "navigate", "group": "os"},
            {"id": "open_marketplace", "title": "Lokale plugin-marketplace", "href": "#/plugins?tab=marketplace", "action": "navigate", "group": "os"},
            {"id": "open_mcp_catalog", "title": "MCP", "href": "#/mcp", "action": "navigate", "group": "os"},
            {"id": "open_mcp_plugins_tab", "title": "MCP-catalogus (plugins)", "href": "#/plugins?tab=mcp", "action": "navigate", "group": "os"},
            {"id": "open_files", "title": "Bestanden / resultaten", "href": "#/files", "action": "navigate", "group": "os"},
            {"id": "open_memory", "title": "Geheugen", "href": "#/memory", "action": "navigate", "group": "os"},
            {"id": "open_brain", "title": "Brain openen", "href": "#/brain", "action": "navigate", "group": "os"},
            {"id": "open_research", "title": "Onderzoek", "href": "#/research", "action": "navigate", "group": "os"},
            {"id": "open_models", "title": "Modellen / router", "href": "#/models", "action": "navigate", "group": "os"},
            {"id": "switch_model", "title": "Model wisselen", "href": "#/models", "action": "navigate", "group": "os"},
            {"id": "plugin_invoke", "title": "Plugin aanroepen", "href": "#/plugins?invoke=1", "action": "navigate", "group": "os"},
            {"id": "jump_coding_job", "title": "Coding job openen", "href": "#/coding-agent", "action": "navigate", "group": "os"},
            {"id": "insert_harvest", "title": "Insert /harvest", "href": "#/chat?q=%2Fharvest%20", "action": "navigate", "group": "os"},
            {"id": "open_mission_control", "title": "Mission Control (Advanced)", "href": "#/mission-control", "action": "navigate", "group": "advanced"},
            {"id": "open_workflows", "title": "Workflows (Advanced)", "href": "#/workflows", "action": "navigate", "group": "advanced"},
            {"id": "open_eval_lab", "title": "Eval Lab via Mission Control", "href": "#/mission-control", "action": "navigate", "group": "advanced"},
            {"id": "open_flight_recorder", "title": "Flight Recorder via Mission Control", "href": "#/mission-control", "action": "navigate", "group": "advanced"},
            {"id": "open_sandbox_profiles", "title": "Sandbox / zero-trust via Mission Control", "href": "#/mission-control", "action": "navigate", "group": "advanced"},
            {"id": "open_agent_factory", "title": "Agent Factory via Mission Control", "href": "#/mission-control", "action": "navigate", "group": "advanced"},
            {"id": "open_settings_security", "title": "Beveiliging / capability clarity", "href": "#/settings", "action": "navigate", "group": "os"},
            {"id": "chat_harvest_help", "title": "Site harvest via chat (/harvest)", "href": "#/chat?q=%2Fhelp", "action": "navigate", "group": "os"},
            {"id": "open_settings_network", "title": "Netwerkbeleid (Instellingen)", "href": "#/settings", "action": "navigate", "group": "os"},
        ]
        needle = (query or "").strip().lower()
        if not needle or needle.startswith(">") or needle.startswith("/"):
            # Empty / command-palette prefix: product OS actions only.
            # Advanced surfaces stay discoverable via explicit queries.
            return [item for item in commands if item.get("group") == "os"]
        matched = [
            item
            for item in commands
            if needle in item["title"].lower() or needle in item["id"] or needle in str(item.get("group") or "")
        ]
        # Keep shortcuts visible alongside content hits when nothing command-specific matched.
        return matched or [item for item in commands if item.get("group") == "os"]
