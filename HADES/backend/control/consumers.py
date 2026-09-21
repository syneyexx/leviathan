"""Runtime consumers for settings that claim ``implemented=True``.

Each entry is evidence that the setting's semantics are enforced outside the
control-plane catalog (module path + symbol or call site). The registry test
fails if a definition sets ``implemented=True`` without a consumer here.
"""

from __future__ import annotations

# setting_id → one or more consumer evidence strings (module:symbol or path)
SETTING_CONSUMERS: dict[str, tuple[str, ...]] = {
    "network.domain_allowlist": (
        "url_security.load_network_domain_policy",
        "url_security.validate_public_http_url",
    ),
    "network.domain_denylist": (
        "url_security.load_network_domain_policy",
        "url_security.validate_public_http_url",
    ),
    "network.redirect_limit": (
        "url_security.load_network_domain_policy",
        "web_research_service.fetch_url",
    ),
    "logging.retention_days": (
        "retention.resolve_retention_days",
        "retention.run_retention_job",
    ),
}


def consumer_ids() -> frozenset[str]:
    return frozenset(SETTING_CONSUMERS.keys())
