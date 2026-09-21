from __future__ import annotations

import unittest

from global_search import GlobalSearchService


class _DatabaseStub:
    def list_conversations(self):
        return [
            {"id": "conv-a", "title": "A", "project_id": "project-a"},
            {"id": "conv-b", "title": "B", "project_id": "project-b"},
            {"id": "conv-global", "title": "Global", "project_id": None},
        ]

    def search_messages(self, query: str, *, limit: int):
        return [
            {"id": "msg-a", "conversation_id": "conv-a", "role": "user", "content": query},
            {"id": "msg-b", "conversation_id": "conv-b", "role": "user", "content": query},
            {"id": "msg-global", "conversation_id": "conv-global", "role": "user", "content": query},
        ]

    def list_tasks(self):
        return []

    def list_memories(self, *, query: str, limit: int):
        return []


class _PlatformStub:
    def search_knowledge(self, query: str, *, limit: int):
        return []


class GlobalSearchProjectMessageScopeTests(unittest.TestCase):
    def test_project_search_excludes_messages_from_other_projects(self) -> None:
        service = GlobalSearchService(_DatabaseStub(), _PlatformStub())
        result = service.search("scope-fixture", project_id="project-a")
        ids = {item["id"] for item in result["groups"]["messages"]}

        self.assertIn("msg-a", ids)
        self.assertIn("msg-global", ids, "existing unscoped-conversation visibility must be preserved")
        self.assertNotIn("msg-b", ids)


if __name__ == "__main__":
    unittest.main()
