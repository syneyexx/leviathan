"""W0B — declared/planned capabilities ⊆ CapabilityCatalog.

Production prompts, planners, coding tool gates, agent seeds, and
EXTERNAL_WORKER_CAPABILITIES must not invent capability ids that are absent
from the catalog. Inventory descriptors and trading role labels are excluded.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from Data.modules.agents.fleet import _DEFAULT_SEED
from Data.modules.agents.general_orchestra import general_intelligence_orchestra_seed
from Data.modules.coding.prompts import CODING_COGNITIVE_OVERLAY
from Data.modules.coding.tools import GATED_CAPS, READ_CAPS
from Data.modules.cognition.planner import CognitivePlanner
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.types import ReasoningStrategy
from Data.modules.execution import build_default_catalog
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES


ROOT = Path(__file__).resolve().parents[3]
MODULES = ROOT / "Data" / "modules"

# Capability-like tokens that are NOT ExecutionGateway catalog ids.
_EXCLUDED_ABSTRACT_PREFIXES = (
    "capability.",
    "models.",
    "plan.",
    "mission.",
    "missions.",
    "definitions.",
    "delegate.",
    "orchestrator.",
    "gates.",
    "dag.",
    "blackboard.",
    "approval.",
    "cognition.",
    "cortex.",
    "neuro.",
    "residual.",
    "strategy.",
)

_EXCLUDED_ROLE_LABELS = frozenset(
    {
        # Trading orchestra role labels (fleet metadata, not gateway capabilities).
        "market_sim.observe",
        "market_sim.propose",
        "market_sim.strategy",
        "market_sim.critique",
        "market_sim.risk_veto",
        "market_sim.portfolio",
        "market_sim.evaluate",
        "market_sim.orchestrate",
        "market_sim.news.read",
        "market_sim.paper.intent",
        "market_sim.lesson.write",
        "market_sim.run",
        # Agent inventory / planner abstracts
        "coding.execute",
        "coding.verify",
        "research.run",  # legacy alias; planner must use research.advance
        "coding.session",  # legacy alias; planner must use coding.advance
    }
)

_CAP_ID_RE = re.compile(r"\b([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)\b")
# Prompt catalog lines look like: "  workspace.list      args: ..."
_PROMPT_CATALOG_RE = re.compile(
    r"(?m)^[ \t]{0,4}([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)[ \t]+args:"
)


def _is_abstract(cap_id: str) -> bool:
    if cap_id in _EXCLUDED_ROLE_LABELS:
        return True
    return any(cap_id.startswith(prefix) for prefix in _EXCLUDED_ABSTRACT_PREFIXES)


def _collect_prompt_catalog_ids(text: str) -> set[str]:
    return set(_PROMPT_CATALOG_RE.findall(text))


def _collect_string_literals_matching_caps(path: Path) -> set[str]:
    """AST-scan string literals that look like capability ids."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if _CAP_ID_RE.fullmatch(value) and not _is_abstract(value):
                found.add(value)
    return found


class CapabilityContractDriftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = build_default_catalog()
        cls.catalog_ids = {item.id for item in cls.catalog.list()}

    def test_coding_prompt_catalog_subseteq_catalog(self) -> None:
        declared = _collect_prompt_catalog_ids(CODING_COGNITIVE_OVERLAY)
        self.assertTrue(declared, "coding overlay must declare a capability catalog")
        missing = sorted(declared - self.catalog_ids)
        self.assertEqual(missing, [], f"coding prompt invents capabilities: {missing}")

    def test_coding_tool_gates_subseteq_catalog(self) -> None:
        declared = set(GATED_CAPS) | set(READ_CAPS)
        missing = sorted(declared - self.catalog_ids)
        self.assertEqual(missing, [], f"coding tool gates invent capabilities: {missing}")

    def test_external_worker_capabilities_subseteq_catalog(self) -> None:
        missing = sorted(set(EXTERNAL_WORKER_CAPABILITIES) - self.catalog_ids)
        self.assertEqual(
            missing,
            [],
            f"EXTERNAL_WORKER_CAPABILITIES missing from catalog: {missing}",
        )

    def test_agent_fleet_seed_capabilities_subseteq_catalog(self) -> None:
        declared: set[str] = set()
        for spec in [*_DEFAULT_SEED, *general_intelligence_orchestra_seed()]:
            for cap in spec.get("capabilities") or []:
                declared.add(str(cap))
        missing = sorted(c for c in declared if c not in self.catalog_ids and not _is_abstract(c))
        self.assertEqual(missing, [], f"agent fleet seed invents capabilities: {missing}")

    def test_cognition_planner_likely_capabilities_subseteq_catalog(self) -> None:
        planner = CognitivePlanner()
        declared: set[str] = set()
        task = TaskModelBuilder().build("probe")
        for strategy in ReasoningStrategy:
            steps = planner._steps_for(task, strategy)  # noqa: SLF001
            for step in steps:
                declared.update(step.likely_capabilities or ())
        missing = sorted(c for c in declared if c not in self.catalog_ids and not _is_abstract(c))
        self.assertEqual(missing, [], f"cognition planner invents capabilities: {missing}")

    def test_catalog_entries_have_execution_metadata(self) -> None:
        """Each catalog entry must expose honest execution class + side effects."""
        for item in self.catalog.list():
            self.assertTrue(item.side_effects, f"{item.id} missing side_effects")
            execution_class = item.execution_class()
            self.assertIn(
                execution_class,
                {"INLINE_SAFE", "EXTERNAL_PREFERRED", "EXTERNAL_REQUIRED"},
                f"{item.id} bad execution_class={execution_class}",
            )
            meta = item.normalized_metadata()
            if execution_class == "EXTERNAL_REQUIRED" and item.provider_kind.value == "external":
                self.assertTrue(
                    meta.get("worker_kind"),
                    f"{item.id} EXTERNAL_REQUIRED without worker_kind",
                )

    def test_action_selector_and_runtime_tool_ids_subseteq_catalog(self) -> None:
        """Hard-coded capability ids in cognition action/runtime paths ⊆ catalog."""
        scan_paths = [
            MODULES / "cognition" / "action_selector.py",
            MODULES / "cognition" / "runtime.py",
            MODULES / "cognition" / "completion.py",
        ]
        declared: set[str] = set()
        for path in scan_paths:
            declared |= _collect_string_literals_matching_caps(path)
        # Filter to known capability-shaped ids that look like tool invocations.
        interested = {
            c
            for c in declared
            if c.split(".", 1)[0]
            in {
                "web",
                "math",
                "compute",
                "system",
                "knowledge",
                "coding",
                "research",
                "file",
                "workspace",
                "browser",
                "git",
            }
            and not _is_abstract(c)
        }
        missing = sorted(interested - self.catalog_ids)
        self.assertEqual(missing, [], f"cognition hard-codes missing caps: {missing}")


if __name__ == "__main__":
    unittest.main()
