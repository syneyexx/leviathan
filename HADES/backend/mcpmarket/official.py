"""Verified MCPMarket.com public surface.

Inspected 2026-09-14 via official site pages. No public REST management
API, authentication API, install API, or Toolkit catalog API was found.
Do not invent endpoints.
"""

from __future__ import annotations

from typing import Any, Final

BASE_URL: Final[str] = "https://mcpmarket.com"

# Public HTML pages confirmed by fetching official URLs.
SERVER_PATH: Final[str] = "/server/{slug}"
SKILLS_INDEX_PATH: Final[str] = "/tools/skills"
SKILL_PATH: Final[str] = "/tools/skills/{slug}"
CATEGORY_PATH: Final[str] = "/categories/{slug}"

VERIFIED_PAGES: dict[str, str] = {
    "home": BASE_URL + "/",
    "server_example": BASE_URL + "/server/context7",
    "skills_index": BASE_URL + SKILLS_INDEX_PATH,
    "skill_explainer": BASE_URL + "/tools/skills/what-are-skills",
}

UNSUPPORTED_APIS: tuple[str, ...] = (
    "official_rest_catalog_api",
    "official_search_api",
    "official_auth_api",
    "official_install_api",
    "official_toolkit_catalog_api",
    "official_rate_limit_docs",
    "hades_export_to_mcpmarket",
)

VERIFIED_FACTS: dict[str, Any] = {
    "product": "MCP Market directory of MCP servers, agent skills, clients and tools",
    "hosting": "Vercel; unauthenticated automated clients may receive HTTP 429 challenge",
    "server_pages": "https://mcpmarket.com/server/{slug} — name, publisher (by X), description, features, use cases",
    "skills": "https://mcpmarket.com/tools/skills — Agent Skills / SKILL.md-style instruction packages",
    "skills_vs_mcp": "Skills teach how; MCP servers connect to tools/data. Skills are not tools unless they contain executable code.",
    "toolkits": "No first-class official Toolkit catalog/API found. Toolkit-shaped metadata is normalized only when present on a listing.",
    "json_ld": "Community scrapers report JSON-LD on pages; raw HTML was not always retrievable due to bot challenge. Parser accepts JSON-LD when present without requiring it.",
    "auth": "No marketplace credential API documented. MCP server auth is a HADES MCP Host concern after operator approval.",
}

DEFAULT_TTL_SECONDS: Final[int] = 900
DEFAULT_TIMEOUT_SECONDS: Final[float] = 8.0
USER_AGENT: Final[str] = "HADES-MCPMarketConnector/1.0 (discovery-only; does-not-execute-tools)"


def server_url(slug: str) -> str:
    return BASE_URL + SERVER_PATH.format(slug=slug.strip().strip("/"))


def skill_url(slug: str) -> str:
    return BASE_URL + SKILL_PATH.format(slug=slug.strip().strip("/"))


def official_surface() -> dict[str, Any]:
    return {
        "base_url": BASE_URL,
        "verified_pages": dict(VERIFIED_PAGES),
        "verified_facts": dict(VERIFIED_FACTS),
        "unsupported_apis": list(UNSUPPORTED_APIS),
        "executes_tools": False,
        "grants_trust": False,
        "required_for_hades_startup": False,
    }
