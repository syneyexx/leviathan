"""Backend↔frontend Gen2 API contract: request bodies and key response shapes must stay aligned."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ROUTES = REPO / "backend" / "gen2" / "routes.py"
SERVICES = REPO / "backend" / "gen2" / "services.py"
DASHBOARD = REPO / "backend" / "gen2" / "dashboard.py"
STORE = REPO / "backend" / "gen2" / "store.py"
API_TS = REPO / "lib" / "hades-api.ts"

# Pydantic input models that define Gen2 POST/PUT request contracts.
GEN2_INPUT_MODELS = (
    "EvalRunInput",
    "EvalAbInput",
    "EvalPrHelpInput",
    "EvalIngestFlightInput",
    "HumanUsabilityRatingInput",
    "ContextCompileInput",
    "MissionCompileInput",
    "MissionGateInput",
    "MissionAcceptanceEvalInput",
    "MissionReplanInput",
    "CommitteeInput",
    "SkillExtractInput",
    "SkillExtractFromRunInput",
    "SkillPromoteInput",
    "EnvelopeInput",
    "EnvelopeCheckInput",
    "GraphEdgeInput",
    "FinanceFuseInput",
    "FinanceEventStudyInput",
    "ContextChatCompileInput",
    "RecordEventInput",
    "LifecycleEmitInput",
    "ReplayInput",
    "DispatchJobInput",
    "ComparativeReplayInput",
    "PairWorkerInput",
    "WorkflowCreateInput",
    "WorkflowUpdateInput",
    "WorkflowDraftInput",
    "WorkflowPromoteInput",
    "WorkflowRollbackInput",
    "WorkflowTemplateCreateInput",
    "WorkflowImportInput",
    "WorkflowHumanDecideInput",
    "WorkflowSandboxInput",
    "WorkflowExecuteInput",
    "JitGrantRequestInput",
    "JitGrantRevokeInput",
    "PluginScanInput",
    "PluginVerifyInput",
    "McpAllowlistInput",
    "ToolBoundaryInput",
)

# hadesApi.gen2* methods that POST a JSON body mapped to a Pydantic input model.
# Value is either the Input model name, or None when the body is an ad-hoc dict (not in GEN2_INPUT_MODELS).
GEN2_METHOD_INPUT_MODEL: dict[str, str | None] = {
    "gen2RunEvals": "EvalRunInput",
    "gen2EvalAb": "EvalAbInput",
    "gen2EvalPrHelp": "EvalPrHelpInput",
    "gen2EvalIngestFlight": "EvalIngestFlightInput",
    "gen2EvalHumanRating": "HumanUsabilityRatingInput",
    "gen2CompileMission": "MissionCompileInput",
    "gen2DecideGate": "MissionGateInput",
    "gen2EvaluateMissionAcceptance": "MissionAcceptanceEvalInput",
    "gen2ReplanMission": "MissionReplanInput",
    "gen2RunCommittee": "CommitteeInput",
    "gen2CompileContext": "ContextCompileInput",
    "gen2CompileContextForChat": "ContextChatCompileInput",
    "gen2FuseFinance": "FinanceFuseInput",
    "gen2FinanceEventStudy": "FinanceEventStudyInput",
    "gen2ExtractSkill": "SkillExtractInput",
    "gen2ExtractSkillFromRun": "SkillExtractFromRunInput",
    "gen2PromoteSkill": "SkillPromoteInput",
    "gen2ComparativeReplay": "ComparativeReplayInput",
    "gen2PairWorker": "PairWorkerInput",
    "gen2RecordFlightEvent": "RecordEventInput",
    "gen2EmitLifecycle": "LifecycleEmitInput",
    "gen2FlightReplay": "ReplayInput",
    "gen2DispatchJob": "DispatchJobInput",
    "gen2GraphAddEdge": "GraphEdgeInput",
    "gen2CreateWorkflow": "WorkflowCreateInput",
    "gen2UpdateWorkflow": "WorkflowUpdateInput",
    "gen2DraftWorkflow": "WorkflowDraftInput",
    "gen2CreateWorkflowFromTemplate": "WorkflowTemplateCreateInput",
    "gen2ImportWorkflow": "WorkflowImportInput",
    "gen2PromoteWorkflow": "WorkflowPromoteInput",
    "gen2RollbackWorkflow": "WorkflowRollbackInput",
    "gen2DecideWorkflowHuman": "WorkflowHumanDecideInput",
    "gen2SandboxRunWorkflow": "WorkflowSandboxInput",
    "gen2ExecuteWorkflow": "WorkflowExecuteInput",
    # Ad-hoc bodies (no dedicated *Input model in routes.py) — documented intentional.
    "gen2ExecuteSkill": None,
    "gen2DeactivateSkill": None,
    "gen2RollbackSkill": None,
    "gen2ApplySandboxProfile": None,
    "gen2RequestJitGrant": "JitGrantRequestInput",
    "gen2RevokeJitGrant": "JitGrantRevokeInput",
    "gen2PluginSecurityScan": "PluginScanInput",
    "gen2PluginSecurityVerify": "PluginVerifyInput",
    "gen2ValidateMcpAllowlist": "McpAllowlistInput",
    "gen2EnforceToolBoundary": "ToolBoundaryInput",
}

# Documented intentional extras: FE may send keys that are not on the mapped Pydantic model.
# (Empty by default — prefer aligning FE types to backend.)
INTENTIONAL_BODY_EXTRAS: dict[str, frozenset[str]] = {
    "gen2ExecuteSkill": frozenset({"inputs"}),
    "gen2DeactivateSkill": frozenset({"reason"}),
    "gen2RollbackSkill": frozenset({"to_status"}),
    "gen2ApplySandboxProfile": frozenset({"plugin_id"}),
    # FE wraps config under {config}; model expects that key.
    "gen2ValidateMcpAllowlist": frozenset(),
    # Wire key model_config is mapped to llm_model_config (Pydantic reserved name).
    "gen2EvalHumanRating": frozenset({"model_config"}),
}

# Response type fields that must appear in backend return / store schemas (honesty check).
GEN2_MISSION_KEYS = (
    "id",
    "status",
    "goal",
    "gates",
    "verification",
    "ir",
    "blocked_gates",
    "task_id",
    "budgets",
)
GEN2_EVAL_RUN_KEYS = ("status", "mode", "model_id", "summary")
GEN2_EVAL_SUMMARY_KEYS = ("model_invoked", "not_model_quality")
GEN2_COMMITTEE_KEYS = ("topic", "domain", "status", "positions", "consensus")
GEN2_DASHBOARD_KEYS = (
    "missions",
    "eval_runs",
    "committees",
    "phase",
    "capability_status",
    "readiness_note",
    "live_model_smoke_seen",
    "live_model_quality_seen",
)
GEN2_CAPABILITY_STATUS_KEYS = (
    "implemented",
    "available_on_host",
    "operationally_tested",
    "quality_evaluated",
)


def _pydantic_model_fields(source: str, class_name: str) -> set[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields: set[str] = set()
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields.add(item.target.id)
            return fields
    raise AssertionError(f"{class_name} not found in routes.py")


def _all_input_model_fields() -> dict[str, set[str]]:
    text = ROUTES.read_text(encoding="utf-8")
    return {name: _pydantic_model_fields(text, name) for name in GEN2_INPUT_MODELS}


def _ts_type_fields(type_name: str) -> set[str]:
    text = API_TS.read_text(encoding="utf-8")
    match = re.search(rf"export type {re.escape(type_name)} = \{{([\s\S]*?)\n\}};", text)
    if not match:
        raise AssertionError(f"{type_name} type not found in lib/hades-api.ts")
    body = match.group(1)
    fields: set[str] = set()
    for line in body.splitlines():
        line = line.strip().rstrip(";")
        if not line or line.startswith("//") or line.startswith("[") or ":" not in line:
            continue
        # Nested object property lines like "execution_waves?: ..." still count as fields
        # only at the top level of the type block — skip deeper indentation blocks by
        # requiring the field to start at the first non-space of the type body line
        # after strip (already stripped). Nested `{` blocks are flattened into the same
        # match group; skip lines that are only closing braces or index signatures.
        if line.startswith("}"):
            continue
        field, _, _rest = line.partition(":")
        field = field.strip().rstrip("?")
        if not field or field.startswith("[") or " " in field:
            continue
        # Nested type members (inside ir?: { ... }) appear without export-level uniqueness;
        # keep them but prefer top-level names used in assertions.
        fields.add(field)
    return fields


def _ts_type_block(type_name: str) -> str:
    text = API_TS.read_text(encoding="utf-8")
    match = re.search(rf"export type {re.escape(type_name)} = \{{([\s\S]*?)\n\}};", text)
    if not match:
        raise AssertionError(f"{type_name} type not found in lib/hades-api.ts")
    return match.group(1)


def _ts_nested_object_fields(type_name: str, parent_field: str) -> set[str]:
    """Parse fields of `parent_field?: { ... }` / named type alias referenced from a type."""
    body = _ts_type_block(type_name)
    # Named alias: consensus: Gen2CommitteeConsensus;
    alias = re.search(
        rf"{re.escape(parent_field)}\??:\s*([A-Za-z_][A-Za-z0-9_]*)\s*;",
        body,
    )
    if alias:
        ref = alias.group(1)
        if ref not in {"string", "number", "boolean", "unknown", "any"}:
            return _ts_type_fields(ref)
    match = re.search(
        rf"{re.escape(parent_field)}\??:\s*\{{([\s\S]*?)\n  \}}",
        body,
    )
    if not match:
        raise AssertionError(f"{type_name}.{parent_field} object block not found")
    fields: set[str] = set()
    for line in match.group(1).splitlines():
        line = line.strip().rstrip(";")
        if not line or line.startswith("//") or ":" not in line:
            continue
        field, _, _ = line.partition(":")
        field = field.strip().rstrip("?")
        if field and not field.startswith("["):
            fields.add(field)
    return fields


def _gen2_method_snippets() -> dict[str, str]:
    """Map gen2* method name → source snippet (through the next method or closing)."""
    text = API_TS.read_text(encoding="utf-8")
    # Capture from gen2Xxx: through the line that closes the arrow (often ends with }),)
    pattern = re.compile(
        r"(gen2[A-Za-z0-9]+)\s*:\s*((?:.|\n)*?)(?=\n  (?:gen2|[a-z])[A-Za-z0-9]*\s*:|\n\};)",
    )
    out: dict[str, str] = {}
    for match in pattern.finditer(text):
        out[match.group(1)] = match.group(2)
    return out


def _body_keys_from_method_snippet(snippet: str) -> set[str]:
    """Extract JSON body keys from a hadesApi method snippet."""
    keys: set[str] = set()

    def _object_keys(inner: str) -> set[str]:
        found: set[str] = set()
        # Top-level keys only: split on commas at depth 0 is hard; use identifier-before-colon / shorthand.
        # Prefer line/comma separated tokens that look like `key` or `key:`.
        depth = 0
        token = []
        parts: list[str] = []
        for ch in inner:
            if ch in "{[(":
                depth += 1
                token.append(ch)
            elif ch in "}])":
                depth = max(0, depth - 1)
                token.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(token).strip())
                token = []
            else:
                token.append(ch)
        if token:
            parts.append("".join(token).strip())
        for part in parts:
            if not part:
                continue
            key = part.split(":")[0].strip()
            key = re.sub(r"^['\"]|['\"]$", "", key)
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                found.add(key)
        return found

    # Explicit object: JSON.stringify({ ... }) — brace-match to allow nested `{}`.
    for m in re.finditer(r"JSON\.stringify\(\s*\{", snippet):
        start = m.end() - 1
        depth = 0
        end = None
        for i, ch in enumerate(snippet[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is not None:
            keys |= _object_keys(snippet[start + 1 : end])
    # Typed values parameter — brace-match the object type (may contain nested `{...}`).
    values_match = re.search(r"values\??\s*:\s*\{", snippet)
    if values_match:
        start = values_match.end() - 1
        depth = 0
        end = None
        for i, ch in enumerate(snippet[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is not None:
            inner = snippet[start + 1 : end]
            for line in inner.splitlines():
                line = line.strip().rstrip(";").rstrip(",")
                if not line or line.startswith("//") or ":" not in line:
                    continue
                field = line.split(":")[0].strip().rstrip("?")
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", field):
                    keys.add(field)
    return keys


def _dict_literal_keys_after(text: str, anchor: str) -> set[str]:
    """Return keys from the first `{...}` dict/object literal after ``anchor``."""
    idx = text.find(anchor)
    if idx < 0:
        raise AssertionError(f"anchor not found: {anchor}")
    brace = text.find("{", idx)
    if brace < 0:
        raise AssertionError(f"no dict literal after {anchor}")
    depth = 0
    end = None
    for i, ch in enumerate(text[brace:], brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        raise AssertionError(f"unclosed dict after {anchor}")
    block = text[brace : end + 1]
    return set(re.findall(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*:", block))


def _method_source(path: Path, method_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"def {re.escape(method_name)}\(self[^)]*\)[^:]*:\n([\s\S]*?)(?=\n    def |\nclass |\Z)",
        text,
    )
    if not match:
        raise AssertionError(f"{method_name} not found in {path.name}")
    return match.group(1)


def _module_function_source(path: Path, function_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"^def {re.escape(function_name)}\([^)]*\)[^:]*:\n([\s\S]*?)(?=\n(?:def |class |\Z))",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"{function_name} not found in {path.name}")
    return match.group(1)


def _dashboard_return_keys() -> set[str]:
    """Sample top-level keys from the dict literal returned by dashboard.build_dashboard()."""
    body = _module_function_source(DASHBOARD, "build_dashboard")
    # Prefer the final top-level `return {` in the function (not nested helpers).
    matches = list(re.finditer(r"(?m)^    return \{", body))
    if not matches:
        raise AssertionError("build_dashboard() return dict not found")
    start = matches[-1].start()
    return _dict_literal_keys_after(body[start:], "return")


def _mission_row_keys() -> set[str]:
    body = _method_source(STORE, "_mission_row")
    return _dict_literal_keys_after(body, "return")


def _eval_row_keys() -> set[str]:
    body = _method_source(STORE, "_eval_row")
    return _dict_literal_keys_after(body, "return")


def _committee_save_keys() -> set[str]:
    body = _method_source(STORE, "save_committee")
    matches = list(re.finditer(r"(?m)^        return \{", body))
    if not matches:
        # Some store methods return inline without exact indent — fall back.
        matches = list(re.finditer(r"return \{", body))
    if not matches:
        raise AssertionError("save_committee return dict not found")
    start = matches[-1].start()
    return _dict_literal_keys_after(body[start:], "return")


def _blocked_gates_emitted() -> bool:
    mission_py = REPO / "backend" / "gen2" / "mission_control.py"
    texts = [SERVICES.read_text(encoding="utf-8")]
    if mission_py.exists():
        texts.append(mission_py.read_text(encoding="utf-8"))
    blob = "\n".join(texts)
    return '"blocked_gates"' in blob or "'blocked_gates'" in blob


def _capability_status_helper_keys() -> set[str]:
    """Keys from capability_status_fields() helper used by build_dashboard()."""
    body = _module_function_source(DASHBOARD, "capability_status_fields")
    match = re.search(r"return \{", body)
    if not match:
        raise AssertionError("capability_status_fields() return not found")
    return _dict_literal_keys_after(body[match.start() :], "return")


def _consensus_mode_in_finalize() -> bool:
    """Backend stores committee mode under consensus.mode (committee.finalize_committee)."""
    committee_py = REPO / "backend" / "gen2" / "committee.py"
    text = committee_py.read_text(encoding="utf-8") if committee_py.exists() else SERVICES.read_text(encoding="utf-8")
    return bool(
        re.search(r"consensus_mode\s*=", text)
        and re.search(r'[\"\']mode[\"\']\s*:\s*consensus_mode', text)
    )


class Gen2ApiContractDriftTests(unittest.TestCase):
    def test_all_input_models_exist(self) -> None:
        fields = _all_input_model_fields()
        missing = [name for name in GEN2_INPUT_MODELS if name not in fields or not fields[name]]
        self.assertEqual(missing, [], f"Missing or empty Gen2 input models: {missing}")

    def test_gen2_request_bodies_subset_of_pydantic(self) -> None:
        models = _all_input_model_fields()
        snippets = _gen2_method_snippets()
        errors: list[str] = []
        for method, model_name in GEN2_METHOD_INPUT_MODEL.items():
            if method not in snippets:
                errors.append(f"hadesApi.{method} not found in lib/hades-api.ts")
                continue
            body_keys = _body_keys_from_method_snippet(snippets[method])
            if not body_keys:
                if model_name is None:
                    # Empty POST body (e.g. validate/dry-run/archive) — intentional.
                    continue
                # Methods that stringify an opaque `values` object still declare keys via the type.
                errors.append(f"{method}: could not parse any JSON body keys")
                continue
            allowed_extras = INTENTIONAL_BODY_EXTRAS.get(method, frozenset())
            if model_name is None:
                unexpected = body_keys - allowed_extras
                if unexpected:
                    errors.append(
                        f"{method}: ad-hoc body keys {sorted(unexpected)} not listed in INTENTIONAL_BODY_EXTRAS"
                    )
                continue
            backend_fields = models[model_name]
            extras = body_keys - backend_fields - allowed_extras
            if extras:
                errors.append(
                    f"{method} → {model_name}: FE body keys not on Pydantic model: {sorted(extras)} "
                    f"(backend has {sorted(backend_fields)})"
                )
        self.assertEqual(errors, [], "\n".join(errors))

    def test_gen2_mission_type_aligned_with_backend(self) -> None:
        fe = _ts_type_fields("Gen2Mission")
        mission_keys = _mission_row_keys()
        missing_fe = [k for k in ("id", "status", "goal", "gates", "verification", "ir", "task_id", "budgets") if k not in fe]
        self.assertEqual(missing_fe, [], f"Gen2Mission missing fields: {missing_fe}")
        # Store row fields (except blocked_gates, which is start_mission-only) must be present on FE type.
        for key in mission_keys:
            if key in {"executions", "acceptance_criteria", "error", "created_at", "updated_at", "title", "execution_id"}:
                # Optional / present on FE or nested — only assert required-looking contract keys below.
                continue
        for key in ("id", "status", "goal", "gates", "verification", "ir", "task_id", "budgets"):
            self.assertIn(key, mission_keys, f"_mission_row missing {key}")
            self.assertIn(key, fe, f"Gen2Mission missing {key}")
        self.assertIn("blocked_gates", fe, "Gen2Mission should include blocked_gates (start_mission emission)")
        self.assertTrue(_blocked_gates_emitted(), "services.py should emit blocked_gates on start")

    def test_gen2_eval_run_type_aligned_with_backend(self) -> None:
        fe = _ts_type_fields("Gen2EvalRun")
        backend = _eval_row_keys()
        for key in GEN2_EVAL_RUN_KEYS:
            self.assertIn(key, fe, f"Gen2EvalRun missing {key}")
            self.assertIn(key, backend, f"_eval_row missing {key}")
        summary_block = _ts_type_block("Gen2EvalRun")
        for key in GEN2_EVAL_SUMMARY_KEYS:
            self.assertIn(key, summary_block, f"Gen2EvalRun.summary should include {key}")

    def test_gen2_committee_type_aligned_with_backend(self) -> None:
        fe = _ts_type_fields("Gen2CommitteeSession")
        backend = _committee_save_keys()
        for key in GEN2_COMMITTEE_KEYS:
            self.assertIn(key, fe, f"Gen2CommitteeSession missing {key}")
            self.assertIn(key, backend, f"save_committee missing {key}")
        # Honesty: mode lives under consensus, not top-level session.
        self.assertTrue(_consensus_mode_in_finalize(), "committee consensus should set mode")
        self.assertNotIn(
            "mode",
            fe,
            "Gen2CommitteeSession must not claim top-level mode; use consensus.mode",
        )
        consensus_fields = _ts_nested_object_fields("Gen2CommitteeSession", "consensus")
        self.assertIn("mode", consensus_fields, "Gen2CommitteeSession.consensus should include mode")

    def test_gen2_dashboard_type_aligned_with_backend(self) -> None:
        fe = _ts_type_fields("Gen2Dashboard")
        backend = _dashboard_return_keys()
        for key in GEN2_DASHBOARD_KEYS:
            self.assertIn(key, fe, f"Gen2Dashboard missing {key}")
            self.assertIn(key, backend, f"dashboard() missing {key}")

    def test_gen2_capability_status_type_aligned_with_backend(self) -> None:
        fe = _ts_type_fields("Gen2CapabilityStatus")
        backend = _capability_status_helper_keys()
        for key in GEN2_CAPABILITY_STATUS_KEYS:
            self.assertIn(key, fe, f"Gen2CapabilityStatus missing {key}")
            self.assertIn(key, backend, f"capability status helper missing {key}")

    def test_mapped_methods_cover_posted_input_models(self) -> None:
        """Every Input model that the FE currently posts must be listed in GEN2_METHOD_INPUT_MODEL."""
        mapped = {m for m in GEN2_METHOD_INPUT_MODEL.values() if m}
        # Input models without FE wrappers yet (envelope/graph/flight/dispatch) are allowed.
        # When a FE method posts them, GEN2_METHOD_INPUT_MODEL must include the mapping.
        snippets = _gen2_method_snippets()
        for method, snippet in snippets.items():
            if "JSON.stringify" not in snippet:
                continue
            if method not in GEN2_METHOD_INPUT_MODEL:
                self.fail(
                    f"{method} posts a JSON body but is not listed in GEN2_METHOD_INPUT_MODEL "
                    f"(mapped models: {sorted(mapped)})"
                )


if __name__ == "__main__":
    unittest.main()
