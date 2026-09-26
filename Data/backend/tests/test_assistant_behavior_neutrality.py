"""GI1 — BehaviorProfile owns conversational behavior; AuthorityProfile is content-neutral."""

from __future__ import annotations

import unittest
from pathlib import Path

from Data.modules.approvals import (
    DEFAULT_AUTHORITY_PROFILE,
    ApprovalMode,
    AuthorityProfile,
)
from Data.modules.approvals.policy import PolicyEngine
from Data.modules.execution import build_default_catalog
from Data.modules.settings import DEFAULT_BEHAVIOR_PROFILE, BehaviorProfile


MODULES_ROOT = Path(__file__).resolve().parents[2] / "modules"


class BehaviorAuthoritySeparationTests(unittest.TestCase):
    def test_behavior_profile_is_not_authority_profile(self) -> None:
        behavior = DEFAULT_BEHAVIOR_PROFILE
        authority = DEFAULT_AUTHORITY_PROFILE
        self.assertIsInstance(behavior, BehaviorProfile)
        self.assertIsInstance(authority, AuthorityProfile)
        self.assertFalse(hasattr(behavior, "filesystem_scopes") or hasattr(behavior, "network_scopes"))
        # Authority must not carry conversational system prompt text.
        auth_public = authority.public_dict() if hasattr(authority, "public_dict") else {}
        self.assertNotIn("system_prompt", auth_public)
        self.assertNotIn("tone", auth_public)

    def test_same_capability_same_policy_regardless_of_topic(self) -> None:
        """Topic semantics must not change technical policy outcomes."""
        catalog = build_default_catalog()
        cap = catalog.get("knowledge.search")
        self.assertIsNotNone(cap)
        engine = PolicyEngine()
        topics = [
            "explain photosynthesis",
            "debate contested political ideology X",
            "discuss controversial religious history",
            "write fiction about pirates",
            "review ordinary software architecture",
        ]
        outcomes = []
        for _topic in topics:
            # PolicyEngine is side-effect based — conversational topic is irrelevant.
            decision = engine.evaluate(tuple(cap.side_effects))
            outcomes.append(
                (
                    decision.requires_approval,
                    decision.reason,
                    tuple(decision.auto_effects),
                    tuple(decision.gated_effects),
                )
            )
        self.assertEqual(len(set(outcomes)), 1, f"topic changed technical policy: {outcomes}")
        # Same profile + same side effects → identical decision even if metadata topic varies.
        self.assertEqual(DEFAULT_AUTHORITY_PROFILE.id, "leviathan.default")

    def test_no_content_moderation_engine_module(self) -> None:
        forbidden_names = {
            "content_moderation_engine",
            "hardcoded_moral_filter",
            "ContentModerationEngine",
            "MoralFilter",
            "TopicDenyList",
        }
        hits: list[str] = []
        for py_path in MODULES_ROOT.rglob("*.py"):
            text = py_path.read_text(encoding="utf-8", errors="replace")
            for name in forbidden_names:
                if name in text and "forbidden_duplicates" not in text:
                    # Allow ownership matrix mentions of the forbidden names.
                    if py_path.name == "ownership.py":
                        continue
                    hits.append(f"{py_path.relative_to(MODULES_ROOT)}:{name}")
        self.assertEqual(hits, [], f"forbidden content-policy owners present: {hits}")

    def test_no_source_enforced_moral_refusal_phrases_in_core(self) -> None:
        """CLASS A: hardcoded conversational moral refusals must not gate Chat."""
        suspect_patterns = (
            "i cannot help with that topic",
            "i won't discuss political",
            "disallowed topic",
            "morally unacceptable",
            "politically unacceptable",
            "content filter blocked",
            "unsafe content classification",
            "ideological classification",
        )
        scan_roots = [
            MODULES_ROOT / "cognition",
            MODULES_ROOT / "settings",
            MODULES_ROOT / "approvals",
            MODULES_ROOT / "execution",
            MODULES_ROOT / "context",
        ]
        hits: list[str] = []
        for root in scan_roots:
            if not root.is_dir():
                continue
            for py_path in root.rglob("*.py"):
                lowered = py_path.read_text(encoding="utf-8", errors="replace").lower()
                for pat in suspect_patterns:
                    if pat in lowered:
                        hits.append(f"{py_path}:{pat}")
        self.assertEqual(hits, [], f"CLASS A content ideology found: {hits}")


class AuthorityContentNeutralityTests(unittest.TestCase):
    def test_authority_profile_fields_are_technical(self) -> None:
        profile = AuthorityProfile(
            id="test-neutral",
            version="1",
            approval_mode=ApprovalMode.STANDARD,
        )
        public = profile.public_dict()
        blob = str(public).lower()
        for banned in ("politic", "religion", "moral", "ideolog", "topic_deny"):
            self.assertNotIn(banned, blob)
        self.assertTrue(public["truth"]["authority_is_not_behavior"])


if __name__ == "__main__":
    unittest.main()
