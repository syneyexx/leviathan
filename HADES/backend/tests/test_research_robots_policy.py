from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from platform_services import (
    RESEARCH_ROBOTS_OFF_FRAGMENT,
    RESEARCH_ROBOTS_OFF_SOURCE,
    WebResearchService,
    _RESEARCH_ROBOTS_POLICY,
    _ResearchPolicyDatabaseView,
)
from platform_services_core import WebResearchService as CoreWebResearchService


class _KnowledgeStub:
    pass


class _DatabaseStub:
    def __init__(self, project: dict) -> None:
        self.project = project

    def get_research_project(self, project_id: str) -> dict:
        assert project_id == self.project["id"]
        return dict(self.project)

    def delegated_method(self) -> str:
        return "delegated"


class ResearchPolicyDatabaseViewTests(unittest.TestCase):
    def test_default_policy_is_on_and_sources_are_unchanged(self) -> None:
        db = _DatabaseStub({"id": "research_1", "source_inputs": ["https://example.com"]})
        view = _ResearchPolicyDatabaseView(db)

        project = view.get_research_project("research_1")

        self.assertIsNotNone(project)
        self.assertIs(project["respect_robots_txt"], True)
        self.assertEqual(project["source_inputs"], ["https://example.com"])
        self.assertEqual(view.delegated_method(), "delegated")

    def test_opt_out_marker_is_persisted_but_hidden_from_runner_sources(self) -> None:
        db = _DatabaseStub(
            {
                "id": "research_2",
                "source_inputs": ["https://example.com", RESEARCH_ROBOTS_OFF_SOURCE],
            }
        )
        view = _ResearchPolicyDatabaseView(db)

        project = view.get_research_project("research_2")

        self.assertIsNotNone(project)
        self.assertIs(project["respect_robots_txt"], False)
        self.assertEqual(project["source_inputs"], ["https://example.com"])


class ResearchPolicyWebServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_local_policy_overrides_core_fetch_flag(self) -> None:
        service = WebResearchService(_KnowledgeStub())
        core_get = AsyncMock(return_value=object())

        with patch.object(CoreWebResearchService, "_get", core_get):
            token = _RESEARCH_ROBOTS_POLICY.set(False)
            try:
                await service._get("https://example.com", respect_robots=True)
            finally:
                _RESEARCH_ROBOTS_POLICY.reset(token)

        core_get.assert_awaited_once_with("https://example.com", respect_robots=False)

    async def test_harvest_defaults_to_respecting_robots(self) -> None:
        service = WebResearchService(_KnowledgeStub())
        observed: dict[str, object] = {}

        async def fake_harvest(_service, seed_url: str, **kwargs):
            observed["seed_url"] = seed_url
            observed["policy"] = _RESEARCH_ROBOTS_POLICY.get()
            observed["kwargs"] = kwargs
            return {"seed_url": seed_url}

        with patch.object(CoreWebResearchService, "harvest_site_documents", new=fake_harvest):
            result = await service.harvest_site_documents(
                "https://example.com/docs#section",
                max_pages=3,
                authorized_downloads=True,
            )

        self.assertEqual(observed["seed_url"], "https://example.com/docs#section")
        self.assertIs(observed["policy"], True)
        self.assertIs(result["respect_robots_txt"], True)
        self.assertIsNone(_RESEARCH_ROBOTS_POLICY.get())

    async def test_harvest_opt_out_marker_is_removed_before_network_use(self) -> None:
        service = WebResearchService(_KnowledgeStub())
        observed: dict[str, object] = {}

        async def fake_harvest(_service, seed_url: str, **kwargs):
            observed["seed_url"] = seed_url
            observed["policy"] = _RESEARCH_ROBOTS_POLICY.get()
            observed["kwargs"] = kwargs
            return {"seed_url": seed_url}

        marked_url = f"https://example.com/docs#section&{RESEARCH_ROBOTS_OFF_FRAGMENT}"
        with patch.object(CoreWebResearchService, "harvest_site_documents", new=fake_harvest):
            result = await service.harvest_site_documents(marked_url, authorized_downloads=True)

        self.assertEqual(observed["seed_url"], "https://example.com/docs#section")
        self.assertIs(observed["policy"], False)
        self.assertIs(result["respect_robots_txt"], False)
        self.assertIsNone(_RESEARCH_ROBOTS_POLICY.get())


if __name__ == "__main__":
    unittest.main()
