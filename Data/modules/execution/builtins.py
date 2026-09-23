from __future__ import annotations

from Data.modules.function_runtime.types import SideEffect

from .catalog import CapabilityCatalog
from .types import CapabilityDefinition, CapabilityProviderKind


def build_default_catalog() -> CapabilityCatalog:
    catalog = CapabilityCatalog()
    catalog.register(
        CapabilityDefinition(
            id="file.read",
            name="Read File",
            description="Read a local text file with optional line range.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="text_file_read",
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
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.inspect_csv",
            name="Inspect CSV",
            description="Inspect CSV headers and sample rows.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="csv_inspector",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_rows": {"type": "integer"},
                    "max_bytes": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.parse_pdf",
            name="Parse PDF",
            description="Extract text from a PDF file.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="pdf_parser",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_pages": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.write",
            name="Write File",
            description="Atomically write a UTF-8 text file.",
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="text_file_write",
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
            required_permissions=("filesystem.write",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.patch",
            name="Patch File",
            description="Apply a unified diff fail-closed.",
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="text_file_patch",
            input_schema={
                "type": "object",
                "required": ["path", "unified_diff"],
                "properties": {
                    "path": {"type": "string"},
                    "unified_diff": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.write",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.delete",
            name="Delete File",
            description="Delete a local file.",
            side_effects=(SideEffect.DELETE, SideEffect.DESTRUCTIVE),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="text_file_delete",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.write",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="workspace.list",
            name="List Workspace",
            description="List coding workspace entries.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="workspace_list",
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
            required_permissions=("filesystem.read",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="workspace.search",
            name="Search Workspace",
            description="Search coding workspace contents.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="workspace_search",
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
            required_permissions=("filesystem.read",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.run_tests",
            name="Run Tests",
            description="Run pytest/npm tests and capture exit code.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_run_tests",
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
            required_permissions=("process.execute",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="git.status",
            name="Git Status",
            description="Read git status (honest if no .git).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="git_status",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {"path": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="git.diff",
            name="Git Diff",
            description="Read git diff (honest if no .git).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="git_diff",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "path": {"type": "string"},
                    "staged": {"type": "boolean"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="knowledge.search",
            name="Search Knowledge",
            description="Search READY knowledge chunks.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.KNOWLEDGE,
            provider_ref="hybrid_search",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "source": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("knowledge.read",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="knowledge.ingest_scan",
            name="Ingest ModelData Scan",
            description="Incremental Knowledge V2 scan of configured ModelData root.",
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.KNOWLEDGE,
            provider_ref="ingest_scan",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("knowledge.write",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="artifact.create_text",
            name="Create Text Artifact",
            description="Create a text artifact on disk with metadata.",
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.ARTIFACT,
            provider_ref="create_text",
            input_schema={
                "type": "object",
                "required": ["content", "filename"],
                "properties": {
                    "content": {"type": "string"},
                    "filename": {"type": "string"},
                    "run_id": {"type": "string"},
                    "artifact_type": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("artifact.write",),
            metadata={"tags": ["artifact"], "domains": ["artifact"], "cacheable": False},
        )
    )
    # Wave 5 — browser capabilities (fixture worker via ExecutionGateway).
    catalog.register(
        CapabilityDefinition(
            id="browser.navigate",
            name="Browser Navigate",
            description="Navigate a supervised browser session to a URL (fixture or real backend).",
            side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="navigate",
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "session_id": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.navigate",),
            metadata={
                "tags": ["browser", "navigate", "web", "dom"],
                "domains": ["browser"],
                "aliases": ["open page", "goto", "browse"],
                "worker_kind": "browser",
                "isolation": "session",
                "risk_tier": "network",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.extract_text",
            name="Browser Extract Text",
            description="Extract DOM/accessibility text from the current browser session page.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="extract_text",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {"session_id": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("browser.read",),
            metadata={
                "tags": ["browser", "dom", "extract", "read"],
                "domains": ["browser"],
                "aliases": ["page text", "read page"],
                "cacheable": True,
                "idempotent": True,
                "worker_kind": "browser",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.screenshot",
            name="Browser Screenshot",
            description="Capture a page screenshot artifact from the browser session.",
            side_effects=(SideEffect.READ, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="screenshot",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {"session_id": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("browser.read", "artifact.write"),
            metadata={
                "tags": ["browser", "screenshot", "vision"],
                "domains": ["browser"],
                "aliases": ["capture page", "snapshot"],
                "worker_kind": "browser",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.click",
            name="Browser Click",
            description="Click a target in the current browser session.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="click",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "session_id": {"type": "string"},
                    "selector": {"type": "string"},
                    "target": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.interact",),
            metadata={
                "tags": ["browser", "click", "interact"],
                "domains": ["browser"],
                "worker_kind": "browser",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.type",
            name="Browser Type",
            description="Type text into a target in the current browser session.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="type",
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "session_id": {"type": "string"},
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.interact",),
            metadata={
                "tags": ["browser", "type", "input"],
                "domains": ["browser"],
                "worker_kind": "browser",
            },
        )
    )
    return catalog
