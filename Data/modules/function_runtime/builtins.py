"""Builtin function catalog registration for LEVIATHAN."""

from __future__ import annotations

from .registry import FunctionRegistry
from .types import FunctionDefinition, LifecycleMode, SideEffect


def register_builtin_functions(registry: FunctionRegistry) -> FunctionRegistry:
    registry.register(
        FunctionDefinition(
            id="text_file_read",
            name="Text File Read",
            version="1.1.0",
            description="Read a local UTF-8 text file with line numbers and optional range.",
            entrypoint="Data.functions.text_file_read:run",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                    "line_count": {"type": "integer"},
                },
            },
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=True,
            timeout_seconds=15.0,
            ram_expectation_mb=32,
        )
    )
    registry.register(
        FunctionDefinition(
            id="csv_inspector",
            name="CSV Inspector",
            version="1.0.0",
            description="Inspect CSV headers and sample rows.",
            entrypoint="Data.functions.csv_inspector:run",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_rows": {"type": "integer"},
                    "max_bytes": {"type": "integer"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "header": {"type": "array"},
                    "sample_rows": {"type": "array"},
                },
            },
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=True,
            timeout_seconds=20.0,
            ram_expectation_mb=64,
        )
    )
    registry.register(
        FunctionDefinition(
            id="pdf_parser",
            name="PDF Parser",
            version="1.0.0",
            description="Extract text from PDF pages (optional pypdf dependency).",
            entrypoint="Data.functions.pdf_parser:run",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_pages": {"type": "integer"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "pages": {"type": "array"},
                    "page_count": {"type": "integer"},
                },
            },
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=True,
            timeout_seconds=60.0,
            ram_expectation_mb=256,
            warmup_cost="cold",
        )
    )
    registry.register(
        FunctionDefinition(
            id="text_file_write",
            name="Text File Write",
            version="1.0.0",
            description="Atomically write a UTF-8 text file.",
            entrypoint="Data.functions.text_file_write:run",
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "create_parents": {"type": "boolean"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.WRITE,),
            filesystem_requirement=True,
            timeout_seconds=20.0,
            ram_expectation_mb=32,
        )
    )
    registry.register(
        FunctionDefinition(
            id="text_file_patch",
            name="Text File Patch",
            version="1.0.0",
            description="Apply a unified diff fail-closed.",
            entrypoint="Data.functions.text_file_patch:run",
            input_schema={
                "type": "object",
                "required": ["path", "unified_diff"],
                "properties": {
                    "path": {"type": "string"},
                    "unified_diff": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.WRITE,),
            filesystem_requirement=True,
            timeout_seconds=20.0,
            ram_expectation_mb=32,
        )
    )
    registry.register(
        FunctionDefinition(
            id="text_file_delete",
            name="Text File Delete",
            version="1.0.0",
            description="Delete a local file.",
            entrypoint="Data.functions.text_file_delete:run",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.DELETE, SideEffect.DESTRUCTIVE),
            filesystem_requirement=True,
            timeout_seconds=15.0,
            ram_expectation_mb=16,
        )
    )
    registry.register(
        FunctionDefinition(
            id="workspace_list",
            name="Workspace List",
            version="1.0.0",
            description="List files/directories in the coding workspace.",
            entrypoint="Data.functions.workspace_list:run",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "max_entries": {"type": "integer"},
                    "workspace_root": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=True,
            timeout_seconds=20.0,
            ram_expectation_mb=32,
        )
    )
    registry.register(
        FunctionDefinition(
            id="workspace_search",
            name="Workspace Search",
            version="1.0.0",
            description="Search workspace file contents (ripgrep or Python fallback).",
            entrypoint="Data.functions.workspace_search:run",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                    "max_hits": {"type": "integer"},
                    "workspace_root": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=True,
            timeout_seconds=30.0,
            ram_expectation_mb=64,
        )
    )
    registry.register(
        FunctionDefinition(
            id="coding_run_tests",
            name="Coding Run Tests",
            version="1.0.0",
            description="Run pytest or npm tests and capture exit code.",
            entrypoint="Data.functions.coding_run_tests:run",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "selector": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "cwd": {"type": "string"},
                    "workspace_root": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.EXECUTE,),
            filesystem_requirement=True,
            timeout_seconds=180.0,
            ram_expectation_mb=256,
        )
    )
    registry.register(
        FunctionDefinition(
            id="git_status",
            name="Git Status",
            version="1.0.0",
            description="Read git status; honest FAILED when .git missing.",
            entrypoint="Data.functions.git_status:run",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {"path": {"type": "string"}},
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=True,
            timeout_seconds=20.0,
            ram_expectation_mb=16,
        )
    )
    registry.register(
        FunctionDefinition(
            id="git_diff",
            name="Git Diff",
            version="1.0.0",
            description="Read git diff; honest FAILED when .git missing.",
            entrypoint="Data.functions.git_diff:run",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "path": {"type": "string"},
                    "staged": {"type": "boolean"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=True,
            timeout_seconds=30.0,
            ram_expectation_mb=32,
        )
    )
    registry.register(
        FunctionDefinition(
            id="numeric_compute",
            name="Numeric Compute",
            version="1.0.0",
            description="Deterministic Tier-0 math/statistics (CAGR, mean, correlation, …).",
            entrypoint="Data.functions.numeric_compute:run",
            input_schema={
                "type": "object",
                "required": ["operation"],
                "properties": {
                    "operation": {"type": "string"},
                    "arguments": {"type": "object"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "periods": {"type": "number"},
                    "values": {"type": "array"},
                    "xs": {"type": "array"},
                    "ys": {"type": "array"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=False,
            timeout_seconds=10.0,
            ram_expectation_mb=16,
        )
    )
    registry.register(
        FunctionDefinition(
            id="math_calculate",
            name="Math Calculate",
            version="1.0.0",
            description="Safe AST numeric expression evaluator (GI6).",
            entrypoint="Data.functions.math_calculate:run",
            input_schema={
                "type": "object",
                "required": ["expression"],
                "properties": {"expression": {"type": "string"}},
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=False,
            timeout_seconds=5.0,
            ram_expectation_mb=16,
        )
    )
    registry.register(
        FunctionDefinition(
            id="system_inspect",
            name="System Inspect",
            version="1.0.0",
            description="Honest self-inspection of process state (GI2).",
            entrypoint="Data.functions.system_inspect:run",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {"scope": {"type": "string"}},
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ,),
            filesystem_requirement=False,
            timeout_seconds=10.0,
            ram_expectation_mb=32,
        )
    )
    registry.register(
        FunctionDefinition(
            id="web_search",
            name="Web Search",
            version="1.0.0",
            description="Web search via WebResearchProvider (GI7; never fabricates).",
            entrypoint="Data.functions.web_search:run",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ, SideEffect.NETWORK),
            network_requirement=True,
            filesystem_requirement=False,
            timeout_seconds=30.0,
            ram_expectation_mb=64,
        )
    )
    registry.register(
        FunctionDefinition(
            id="web_fetch",
            name="Web Fetch",
            version="1.0.0",
            description="Fetch URL via WebResearchProvider (GI7; SSRF-safe).",
            entrypoint="Data.functions.web_fetch:run",
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                    "max_bytes": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            lifecycle_mode=LifecycleMode.ON_DEMAND,
            side_effects=(SideEffect.READ, SideEffect.NETWORK),
            network_requirement=True,
            filesystem_requirement=False,
            timeout_seconds=45.0,
            ram_expectation_mb=128,
        )
    )
    return registry


def build_default_registry() -> FunctionRegistry:
    return register_builtin_functions(FunctionRegistry())
