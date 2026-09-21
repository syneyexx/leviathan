"""T10/F-10-structural: implemented=True settings must have a runtime consumer."""

from __future__ import annotations

import unittest

from control.consumers import SETTING_CONSUMERS
from control.definitions import create_default_registry


# Confirmed F-04 keys that must stay labeled unimplemented until wired.
_UNIMPLEMENTED_F04 = frozenset(
    {
        "agents.autonomy.destructive_actions_policy",
        "agents.autonomy.external_side_effect_policy",
        "agents.delegation.timeout_seconds",
        "tools.timeout_seconds",
        "reasoning.verification_passes",
        "reasoning.critic_passes",
        "memory.read_enabled",
        "research.prefer_local",
    }
)

_IMPLEMENTED_F04 = frozenset(
    {
        "network.domain_allowlist",
        "network.domain_denylist",
        "network.redirect_limit",
        "logging.retention_days",
    }
)


class SettingsImplementedFlagTests(unittest.TestCase):
    def test_implemented_true_requires_consumer(self) -> None:
        registry = create_default_registry()
        missing = [
            d.id
            for d in registry.all()
            if d.implemented is True and d.id not in SETTING_CONSUMERS
        ]
        self.assertEqual(
            missing,
            [],
            f"implemented=True without SETTING_CONSUMERS entry: {missing}",
        )

    def test_consumers_only_reference_known_settings(self) -> None:
        registry = create_default_registry()
        known = {d.id for d in registry.all()}
        orphan = sorted(sid for sid in SETTING_CONSUMERS if sid not in known)
        self.assertEqual(orphan, [], f"SETTING_CONSUMERS orphans: {orphan}")

    def test_f04_unimplemented_keys_are_labeled(self) -> None:
        registry = create_default_registry()
        for setting_id in _UNIMPLEMENTED_F04:
            definition = registry.require(setting_id)
            self.assertIs(
                definition.implemented,
                False,
                f"{setting_id} must be implemented=False until a consumer exists",
            )

    def test_f04_enforced_network_and_retention_are_implemented(self) -> None:
        registry = create_default_registry()
        for setting_id in _IMPLEMENTED_F04:
            definition = registry.require(setting_id)
            self.assertIs(
                definition.implemented,
                True,
                f"{setting_id} must claim implemented=True (has runtime consumer)",
            )
            self.assertIn(setting_id, SETTING_CONSUMERS)

    def test_to_public_exposes_implemented_flag(self) -> None:
        registry = create_default_registry()
        public = registry.require("network.domain_allowlist").to_public()
        self.assertTrue(public["implemented"])
        public_false = registry.require("research.prefer_local").to_public()
        self.assertIs(public_false["implemented"], False)


if __name__ == "__main__":
    unittest.main()
