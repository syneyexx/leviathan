"""Backend↔frontend Settings contract: nullability and Unlimited semantics must match."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "backend" / "main.py"
API_TS = REPO / "lib" / "hades-api.ts"

# SettingsInput fields that are int|None in backend (None = Unlimited).
NULLABLE_INT_FIELDS = {
    "request_timeout_seconds",
    "model_refresh_seconds",
    "max_concurrent_tasks",
    "max_retrieval_items",
    "max_retrieval_chars",
    "max_retrieval_chars_per_hit",
    "max_tool_rounds",
    "expert_max_cycles",
    "max_model_calls_per_task",
    "max_specialist_steps",
    "max_subtasks",
    "max_dependency_depth",
    "max_parallel_steps",
    "max_model_concurrency",
    "retrieval_diversity_window",
    "research_max_questions",
}


def _settings_input_nullability() -> dict[str, bool]:
    """Parse SettingsInput field annotations: True if int|None (or Optional[int])."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    out: dict[str, bool] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SettingsInput":
            for item in node.body:
                if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                    continue
                name = item.target.id
                ann = ast.unparse(item.annotation)
                nullable = "None" in ann and ("int" in ann or "float" in ann)
                out[name] = nullable
            break
    return out


def _app_settings_nullability() -> dict[str, bool]:
    text = API_TS.read_text(encoding="utf-8")
    match = re.search(r"export type AppSettings = \{([\s\S]*?)\n\};", text)
    if not match:
        raise AssertionError("AppSettings type not found in lib/hades-api.ts")
    body = match.group(1)
    out: dict[str, bool] = {}
    for line in body.splitlines():
        line = line.strip().rstrip(";")
        if not line or line.startswith("//") or ":" not in line:
            continue
        field, _, rest = line.partition(":")
        field = field.strip()
        rest = rest.strip()
        out[field] = "null" in rest
    return out


class SettingsContractDriftTests(unittest.TestCase):
    def test_nullable_ceilings_match_frontend(self) -> None:
        backend = _settings_input_nullability()
        frontend = _app_settings_nullability()
        missing = []
        for field in NULLABLE_INT_FIELDS:
            self.assertIn(field, backend, f"backend SettingsInput missing {field}")
            self.assertTrue(backend[field], f"backend {field} should be int|None")
            if field not in frontend:
                missing.append(f"frontend AppSettings missing {field}")
            elif not frontend[field]:
                missing.append(f"frontend AppSettings.{field} is not number|null")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_backend_nullables_are_subset_of_expected(self) -> None:
        backend = _settings_input_nullability()
        unexpected = [name for name, nullable in backend.items() if nullable and name not in NULLABLE_INT_FIELDS]
        # New nullable fields must be added to NULLABLE_INT_FIELDS and AppSettings together.
        self.assertEqual(
            unexpected,
            [],
            "New SettingsInput nullable fields must be listed in NULLABLE_INT_FIELDS and mirrored in AppSettings: "
            + ", ".join(unexpected),
        )


if __name__ == "__main__":
    unittest.main()
