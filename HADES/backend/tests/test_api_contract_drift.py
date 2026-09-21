"""Backend↔frontend API contract drift beyond Settings.

Extracts high-value enums and field shapes via AST (Python) / lightweight TS
parsing rather than brittle full-file dumps. Settings nullability remains in
``test_settings_contract_drift.py``; this module covers Gen2, agents console,
and coding-job status contracts.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
API_TS = REPO / "lib" / "hades-api.ts"
GEN2_SERVICES = REPO / "backend" / "gen2" / "services.py"
GEN2_MISSION = REPO / "backend" / "gen2" / "mission_control.py"
GEN2_BUDGET = REPO / "backend" / "gen2" / "mission_budget.py"
AGENT_OPS = REPO / "backend" / "agent_ops.py"
CODING_CONTROL = REPO / "backend" / "coding_job_control.py"
MAIN = REPO / "backend" / "main.py"

# Capability payload keys always emitted by Gen2Services.dashboard status().
CAPABILITY_REQUIRED_KEYS = {
    "implemented",
    "available_on_host",
    "operationally_tested",
    "quality_evaluated",
    "note",
}

# Committee statuses assigned in Gen2Services (store default + live fallback).
COMMITTEE_STATUSES = {"completed", "completed_heuristic_fallback"}

# Eval run statuses written by Gen2Services / Gen2Store.
EVAL_STATUSES = {"completed", "unmeasured"}

# Mission gate statuses used by compile/decide paths.
GATE_STATUSES = {"pending", "approved", "rejected"}


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dict_str_keys(module: ast.Module, name: str) -> set[str]:
    """Keys of a module-level ``NAME = { "k": ... }`` or ``dict[str, set[str]]``."""
    for node in module.body:
        if not isinstance(node, (ast.AnnAssign, ast.Assign)):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        for target in targets:
            if not isinstance(target, ast.Name) or target.id != name:
                continue
            value = node.value
            if not isinstance(value, ast.Dict):
                raise AssertionError(f"{name} is not a dict literal in {module}")
            keys: set[str] = set()
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
                else:
                    raise AssertionError(f"{name} has non-string key: {ast.unparse(key) if key else key}")
            return keys
    raise AssertionError(f"{name} not found")


def _literal_str_union(module: ast.Module, name: str) -> set[str]:
    """Members of ``Name = Literal["a", "b", ...]`` (Assign or AnnAssign)."""

    def _from_subscript(ann: ast.AST) -> set[str] | None:
        if not isinstance(ann, ast.Subscript):
            return None
        # Literal[...] — value may be Name(id='Literal') or Attribute.
        slice_node = ann.slice
        elts: list[ast.expr]
        if isinstance(slice_node, ast.Tuple):
            elts = list(slice_node.elts)
        else:
            elts = [slice_node]
        out: set[str] = set()
        for elt in elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.add(elt.value)
            else:
                raise AssertionError(f"{name} Literal member not a string: {ast.unparse(elt)}")
        return out

    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            found = _from_subscript(node.annotation)
            if found is not None:
                return found
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    found = _from_subscript(node.value)
                    if found is not None:
                        return found
    raise AssertionError(f"Literal alias {name} not found")


def _empty_ledger_keys(module: ast.Module) -> set[str]:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_empty_ledger":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                    keys: set[str] = set()
                    for key in child.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            keys.add(key.value)
                    return keys
    raise AssertionError("_empty_ledger keys not found")


def _ts_export_alias(name: str) -> str:
    """Return the RHS text of ``export type Name = ...`` (brace-balanced object or union)."""
    text = API_TS.read_text(encoding="utf-8")
    pattern = re.compile(rf"export type {re.escape(name)}\b")
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"export type {name} not found in lib/hades-api.ts")
    start = match.start()
    eq = text.find("=", start + len(match.group(0)))
    if eq < 0:
        raise AssertionError(f"export type {name} missing '='")
    i = eq + 1
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i < len(text) and text[i] == "{":
        depth = 0
        j = i
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    j += 1
                    while j < len(text) and text[j] in " \t\r\n":
                        j += 1
                    if j < len(text) and text[j] == ";":
                        j += 1
                    return text[i:j].strip().rstrip(";").strip()
            j += 1
        raise AssertionError(f"unbalanced braces for {name}")
    # Union / primitive: read until newline that starts ``export `` at column 0.
    j = i
    while j < len(text):
        if text.startswith("\nexport ", j) or text.startswith("\n\nexport ", j):
            break
        j += 1
    return text[i:j].strip().rstrip(";").strip()


def _ts_string_union_members(alias_rhs: str) -> set[str] | None:
    """Parse ``"a" | "b"`` (optionally multiline with leading |). None if open ``string``."""
    if re.search(r"(^|\|)\s*string(\s*\||$)", alias_rhs):
        return None
    members = set(re.findall(r'"([^"]+)"', alias_rhs))
    if not members:
        raise AssertionError(f"no string union members in: {alias_rhs[:120]}")
    return members


def _ts_object_fields(alias_rhs: str) -> dict[str, str]:
    """Map top-level field name → type text for a ``{ ... }`` type (brace-aware)."""
    body = alias_rhs.strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    out: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,;":
            i += 1
        if i >= n:
            break
        # Skip comments.
        if body.startswith("//", i):
            nl = body.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if body.startswith("/*", i):
            end = body.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if body[i] in "[.":
            # Skip index signatures / rest until semicolon at depth 0.
            depth = 0
            while i < n:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                elif body[i] == ";" and depth <= 0:
                    i += 1
                    break
                i += 1
            continue
        # Field name
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(\?)?\s*:", body[i:])
        if not m:
            i += 1
            continue
        name = m.group(1)
        optional = bool(m.group(2))
        i += m.end()
        while i < n and body[i] in " \t\r\n":
            i += 1
        type_start = i
        depth = 0
        while i < n:
            ch = body[i]
            if ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
            elif ch == ";" and depth <= 0:
                break
            elif ch == "\n" and depth <= 0:
                # Allow multiline unions without braces: peek if next non-ws is `|`.
                k = i + 1
                while k < n and body[k] in " \t":
                    k += 1
                if k < n and body[k] == "|":
                    i = k
                    continue
                # End of field if next line looks like a new field or comment/close.
                if k >= n or body.startswith("//", k) or re.match(r"[A-Za-z_][A-Za-z0-9_]*\??\s*:", body[k:]):
                    break
            i += 1
        type_text = body[type_start:i].strip().rstrip(",").strip()
        out[name] = ("?" if optional else "") + type_text
        if i < n and body[i] == ";":
            i += 1
    return out


def _field_allows_null(type_text: str) -> bool:
    return "null" in type_text


def _field_is_optional(type_text: str) -> bool:
    return type_text.startswith("?")


class ApiContractDriftTests(unittest.TestCase):
    def test_gen2_mission_statuses_match_frontend(self) -> None:
        # Lifecycle map lives in mission_control (re-exported from services).
        source = GEN2_MISSION if GEN2_MISSION.exists() else GEN2_SERVICES
        backend = _dict_str_keys(_module(source), "MISSION_TRANSITIONS")
        fe_rhs = _ts_export_alias("Gen2MissionStatus")
        frontend = _ts_string_union_members(fe_rhs)
        self.assertIsNotNone(frontend, "Gen2MissionStatus must be a closed string union, not `string`")
        missing = sorted(backend - frontend)  # type: ignore[operator]
        extra = sorted(frontend - backend)  # type: ignore[operator]
        self.assertEqual(missing, [], f"FE Gen2MissionStatus missing backend statuses: {missing}")
        self.assertEqual(extra, [], f"FE Gen2MissionStatus has unknown statuses: {extra}")

    def test_gen2_gate_and_eval_and_committee_status_unions(self) -> None:
        gate = _ts_string_union_members(_ts_export_alias("Gen2GateStatus"))
        eval_st = _ts_string_union_members(_ts_export_alias("Gen2EvalStatus"))
        committee = _ts_string_union_members(_ts_export_alias("Gen2CommitteeStatus"))
        self.assertIsNotNone(gate)
        self.assertIsNotNone(eval_st)
        self.assertIsNotNone(committee)
        self.assertEqual(sorted(GATE_STATUSES - gate), [], "Gen2GateStatus missing values")  # type: ignore[arg-type]
        self.assertEqual(sorted(EVAL_STATUSES - eval_st), [], "Gen2EvalStatus missing values")  # type: ignore[arg-type]
        self.assertEqual(sorted(COMMITTEE_STATUSES - committee), [], "Gen2CommitteeStatus missing values")  # type: ignore[arg-type]

    def test_gen2_mission_null_fields(self) -> None:
        fields = _ts_object_fields(_ts_export_alias("Gen2Mission"))
        for name in ("task_id", "execution_id", "error"):
            self.assertIn(name, fields, f"Gen2Mission missing {name}")
            self.assertTrue(_field_allows_null(fields[name]), f"Gen2Mission.{name} must allow null")
        self.assertIn("status", fields)
        self.assertIn("Gen2MissionStatus", fields["status"])
        # Backend store always returns executions list (may be empty).
        self.assertIn("executions", fields, "Gen2Mission missing executions (backend store field)")

    def test_gen2_budget_ledger_shape(self) -> None:
        ledger_keys = _empty_ledger_keys(_module(GEN2_BUDGET))
        fields = _ts_object_fields(_ts_export_alias("Gen2MissionBudgetLedger"))
        for required in ("mission_id", "budgets", "ledger"):
            self.assertIn(required, fields)
            self.assertFalse(_field_is_optional(fields[required]), f"{required} must be required")
        # Nested ledger keys appear in the inline ledger type text.
        ledger_type = fields["ledger"]
        for key in ledger_keys:
            self.assertIn(key, ledger_type, f"Gen2MissionBudgetLedger.ledger missing backend key {key}")

    def test_gen2_eval_and_committee_fields(self) -> None:
        eval_fields = _ts_object_fields(_ts_export_alias("Gen2EvalRun"))
        for name in ("id", "suite", "mode", "status", "summary", "scores", "created_at"):
            self.assertIn(name, eval_fields, f"Gen2EvalRun missing {name}")
        self.assertIn("Gen2EvalStatus", eval_fields["status"])
        self.assertTrue(_field_allows_null(eval_fields["model_id"]), "Gen2EvalRun.model_id must allow null")

        cms = _ts_object_fields(_ts_export_alias("Gen2CommitteeSession"))
        for name in ("id", "topic", "domain", "status", "positions", "consensus", "run_id", "created_at"):
            self.assertIn(name, cms, f"Gen2CommitteeSession missing {name}")
        self.assertIn("Gen2CommitteeStatus", cms["status"])
        self.assertTrue(_field_allows_null(cms["run_id"]), "run_id is nullable in store")

    def test_gen2_capability_status_keys(self) -> None:
        fields = _ts_object_fields(_ts_export_alias("Gen2CapabilityStatus"))
        for key in CAPABILITY_REQUIRED_KEYS:
            self.assertIn(key, fields, f"Gen2CapabilityStatus missing {key}")
            if key != "note":
                self.assertFalse(_field_is_optional(fields[key]), f"{key} should be required")
        self.assertIn("os_isolation_enforced", fields)

    def test_agent_console_status_and_planned_enabled(self) -> None:
        backend_status = _dict_str_keys(_module(AGENT_OPS), "STATUS_LABELS")
        backend_health = _dict_str_keys(_module(AGENT_OPS), "HEALTH_LABELS")
        fe_status = _ts_string_union_members(_ts_export_alias("AgentStatus"))
        fe_health = _ts_string_union_members(_ts_export_alias("AgentHealth"))
        self.assertEqual(sorted(backend_status - fe_status), [])  # type: ignore[operator]
        self.assertEqual(sorted(fe_status - backend_status), [])  # type: ignore[operator]
        self.assertEqual(sorted(backend_health - fe_health), [])  # type: ignore[operator]
        self.assertEqual(sorted(fe_health - backend_health), [])  # type: ignore[operator]

        agent = _ts_object_fields(_ts_export_alias("HadesAgent"))
        self.assertIn("enabled", agent)
        self.assertFalse(_field_is_optional(agent["enabled"]))
        self.assertIn("planned", agent)
        summary = _ts_object_fields(_ts_export_alias("AgentsConsoleResponse"))
        # summary is nested — check the type text contains planned/enabled counts.
        self.assertIn("planned", summary.get("summary", "") + str(summary))
        # Direct nested parse via AgentsConsoleResponse body already flattened poorly;
        # assert on HadesAgent + dedicated summary fields in the raw alias.
        raw = _ts_export_alias("AgentsConsoleResponse")
        self.assertIn("enabled: number", raw)
        self.assertIn("planned: number", raw)

        contract = _ts_object_fields(_ts_export_alias("SpecialistContract"))
        self.assertIn("planned_only", contract)
        self.assertIn("enabled", contract)

    def test_coding_job_statuses_match_frontend(self) -> None:
        backend = _literal_str_union(_module(CODING_CONTROL), "JobStatus")
        fe = _ts_string_union_members(_ts_export_alias("CodingJobStatus"))
        self.assertIsNotNone(fe, "CodingJobStatus must be a closed string union")
        self.assertEqual(sorted(backend - fe), [], f"FE CodingJobStatus missing: {sorted(backend - fe)}")  # type: ignore[operator]
        self.assertEqual(sorted(fe - backend), [], f"FE CodingJobStatus extras: {sorted(fe - backend)}")  # type: ignore[operator]

    def test_settings_nullable_still_covered_by_sibling(self) -> None:
        """Guard: settings drift suite must remain present."""
        sibling = REPO / "backend" / "tests" / "test_settings_contract_drift.py"
        self.assertTrue(sibling.is_file())
        text = sibling.read_text(encoding="utf-8")
        self.assertIn("SettingsInput", text)
        self.assertIn("NULLABLE_INT_FIELDS", text)


if __name__ == "__main__":
    unittest.main()
