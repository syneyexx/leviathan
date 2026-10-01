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
                    "offset": {"type": "integer"},
                    "length": {"type": "integer"},
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
            metadata={
                "tags": ["filesystem", "pdf"],
                "domains": ["filesystem"],
                "execution_class": "EXTERNAL_REQUIRED",
            },
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
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "content_path": {"type": "string"},
                    "content_artifact_id": {"type": "string"},
                    "create_parents": {"type": "boolean"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.write",),
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.hash",
            name="Hash File",
            description="Streaming SHA-256 hash of a local file.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="file_hash",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "algorithm": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={"tags": ["filesystem", "file_io"], "worker_kind": "file_io"},
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.copy",
            name="Copy File",
            description="Copy a single file (not a directory tree).",
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="file_copy",
            input_schema={
                "type": "object",
                "required": ["source_path", "dest_path"],
                "properties": {
                    "source_path": {"type": "string"},
                    "dest_path": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                    "preserve_metadata": {"type": "boolean"},
                    "compute_hashes": {"type": "boolean"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read", "filesystem.write"),
            metadata={"tags": ["filesystem", "file_io"], "worker_kind": "file_io"},
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.parse_csv",
            name="Parse CSV",
            description="Streaming full CSV parse (external for large files).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="csv_parse",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "delimiter": {"type": "string"},
                    "encoding": {"type": "string"},
                    "max_rows": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "tags": ["filesystem", "csv", "file_io"],
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "file_io",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.profile_csv",
            name="Profile CSV",
            description="Streaming CSV profile with exact/approximate provenance.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="csv_profile",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "delimiter": {"type": "string"},
                    "encoding": {"type": "string"},
                    "exact_distinct_max": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "tags": ["filesystem", "csv", "file_io"],
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "file_io",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="file.process_parquet",
            name="Process Parquet",
            description="Minimal Parquet metadata inspect / row-group processing.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="parquet_process",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "mode": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "tags": ["filesystem", "parquet", "file_io"],
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "file_io",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="filesystem.scan",
            name="Scan Filesystem",
            description="Bounded recursive filesystem scan (always external).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="filesystem_scan",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "max_depth": {"type": "integer"},
                    "max_entries": {"type": "integer"},
                    "follow_symlinks": {"type": "boolean"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "tags": ["filesystem", "file_io"],
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "file_io",
            },
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
            id="file.list",
            name="List Files",
            description=(
                "List directory entries (alias of workspace.list). "
                "Dispatches through the same workspace_list provider."
            ),
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
            metadata={"alias_of": "workspace.list", "tags": ["filesystem"]},
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
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "tags": ["coding", "tests"],
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.test",
            name="Run Tests (alias)",
            description=(
                "Run pytest/npm tests and capture exit code (alias of coding.run_tests). "
                "Dispatches through the same coding_run_tests provider."
            ),
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
            metadata={
                "alias_of": "coding.run_tests",
                "tags": ["coding", "tests"],
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.advance",
            name="Advance Coding Session",
            description=(
                "Advance one Coding Cognition round for a session. "
                "Owned by JobRuntime substrate; executed by coding pool worker."
            ),
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_advance",
            input_schema={
                "type": "object",
                "required": ["session_id"],
                "properties": {
                    "session_id": {"type": "string"},
                    "approval_id": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("process.execute",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "tags": ["coding"],
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.semantic_map.build",
            name="Build Coding Semantic Map",
            description=(
                "Build or refresh a repository semantic map on the coding worker. "
                "Cached reads remain inline; generation is EXTERNAL_REQUIRED."
            ),
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_semantic_map_build",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "workspace_root": {"type": "string"},
                    "session_id": {"type": "string"},
                    "max_files": {"type": "integer"},
                    "action": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "resource_classes": ["CPU_HEAVY", "IO_HEAVY", "MEMORY_HEAVY"],
                "tags": ["coding", "index"],
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.verify",
            name="Coding Verify",
            description=(
                "Run typed coding verification (test/lint/typecheck/build) on the coding worker."
            ),
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_verify",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "phase": {"type": "string"},
                    "selector": {"type": "string"},
                    "tool": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "cwd": {"type": "string"},
                    "workspace_root": {"type": "string"},
                    "session_id": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("process.execute",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "tags": ["coding", "verify"],
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.git.clone",
            name="Coding Git Clone",
            description="Clone a remote Git repository into a coding workspace (coding worker).",
            side_effects=(SideEffect.EXECUTE, SideEffect.WRITE, SideEffect.NETWORK),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_git_clone",
            input_schema={
                "type": "object",
                "required": ["remote", "destination"],
                "properties": {
                    "remote": {"type": "string"},
                    "destination": {"type": "string"},
                    "workspace_root": {"type": "string"},
                    "depth": {"type": "integer"},
                    "overwrite": {"type": "boolean"},
                    "timeout_seconds": {"type": "number"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("process.execute", "filesystem.write", "network.outbound"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "resource_classes": ["NETWORK_BOUND", "IO_HEAVY"],
                "tags": ["coding", "git"],
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.git.fetch",
            name="Coding Git Fetch",
            description="Fetch from a remote into an existing coding repository (coding worker).",
            side_effects=(SideEffect.EXECUTE, SideEffect.WRITE, SideEffect.NETWORK),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_git_fetch",
            input_schema={
                "type": "object",
                "required": ["repository"],
                "properties": {
                    "repository": {"type": "string"},
                    "remote": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                    "timeout_seconds": {"type": "number"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("process.execute", "filesystem.write", "network.outbound"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "resource_classes": ["NETWORK_BOUND", "IO_HEAVY"],
                "tags": ["coding", "git"],
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.git.update",
            name="Coding Git Update",
            description="Deterministic fast-forward update of a coding repository (coding worker).",
            side_effects=(SideEffect.EXECUTE, SideEffect.WRITE, SideEffect.NETWORK),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_git_update",
            input_schema={
                "type": "object",
                "required": ["repository"],
                "properties": {
                    "repository": {"type": "string"},
                    "remote": {"type": "string"},
                    "ref": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("process.execute", "filesystem.write", "network.outbound"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "resource_classes": ["NETWORK_BOUND", "IO_HEAVY"],
                "tags": ["coding", "git"],
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.git.checkout",
            name="Coding Git Checkout",
            description="Checkout a validated ref in a coding repository (coding worker).",
            side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_git_checkout",
            input_schema={
                "type": "object",
                "required": ["repository", "ref"],
                "properties": {
                    "repository": {"type": "string"},
                    "ref": {"type": "string"},
                    "allow_dirty": {"type": "boolean"},
                    "timeout_seconds": {"type": "number"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("process.execute", "filesystem.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "resource_classes": ["IO_HEAVY"],
                "tags": ["coding", "git"],
            },
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
            metadata={"execution_class": "INLINE_SAFE", "tags": ["git"]},
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
            metadata={"execution_class": "INLINE_SAFE", "tags": ["git"]},
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="coding.repo.analyze",
            name="Coding Repository Analyze",
            description=(
                "Repository structure/symbol/dependency analysis on the coding worker "
                "(alias path into semantic-map build)."
            ),
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="coding_repo_analyze",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "workspace_root": {"type": "string"},
                    "session_id": {"type": "string"},
                    "max_files": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "worker_kind": "coding",
                "alias_of": "coding.semantic_map.build",
                "tags": ["coding", "index"],
            },
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
            description="Navigate a supervised browser session to a URL (local_dom real HTML; fixture test-only).",
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
                "execution_class": "EXTERNAL_REQUIRED",
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
                "execution_class": "EXTERNAL_REQUIRED",
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
                "execution_class": "EXTERNAL_REQUIRED",
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
                "execution_class": "EXTERNAL_REQUIRED",
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
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["browser", "type", "input"],
                "domains": ["browser"],
                "worker_kind": "browser",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.form_fill",
            name="Browser Form Fill",
            description="Fill form fields in the current browser session.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="form_fill",
            input_schema={
                "type": "object",
                "required": ["fields"],
                "properties": {
                    "session_id": {"type": "string"},
                    "fields": {"type": "object"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.interact",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["browser", "form"],
                "domains": ["browser"],
                "worker_kind": "browser",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.download",
            name="Browser Download",
            description="Download a linked resource from the current page.",
            side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="download",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "selector": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.interact", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["browser", "download"],
                "domains": ["browser"],
                "worker_kind": "browser",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.upload",
            name="Browser Upload",
            description="Upload a permitted local file into a file input.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="upload",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "session_id": {"type": "string"},
                    "selector": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.interact",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["browser", "upload"],
                "domains": ["browser"],
                "worker_kind": "browser",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.verify_state",
            name="Browser Verify State",
            description="Verify resulting DOM state after an interaction (click ≠ completion).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="verify_state",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "predicates": {"type": "array"},
                    "contains_text": {"type": "string"},
                    "selector_exists": {"type": "string"},
                    "attribute_equals": {"type": "object"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.read",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["browser", "verify"],
                "domains": ["browser"],
                "worker_kind": "browser",
                "click_is_not_task_completion": True,
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.scroll",
            name="Browser Scroll",
            description="Scroll the current browser session viewport.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="scroll",
            input_schema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("browser.interact",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED","tags": ["browser"], "domains": ["browser"], "worker_kind": "browser"},
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.wait",
            name="Browser Wait",
            description="Wait in the current browser session.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="wait",
            input_schema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("browser.read",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED","tags": ["browser"], "domains": ["browser"], "worker_kind": "browser"},
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.keypress",
            name="Browser Keypress",
            description="Send a keypress to the current browser session.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="keypress",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "key": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.interact",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED","tags": ["browser"], "domains": ["browser"], "worker_kind": "browser"},
        )
    )
    # GI9/GI10 — localhost QA journey crawler
    catalog.register(
        CapabilityDefinition(
            id="browser.qa.crawl",
            name="Browser QA Crawl",
            description=(
                "Run a localhost-scoped normal-user journey crawl "
                "(EXTERNAL_REQUIRED — JobRuntime cancel/checkpoint/resume)."
            ),
            side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="qa_crawl",
            input_schema={
                "type": "object",
                "required": ["seed_url"],
                "properties": {
                    "seed_url": {"type": "string"},
                    "persona": {"type": "string"},
                    "budgets": {"type": "object"},
                    "seed": {"type": "integer"},
                    "allow_destructive_test_actions": {"type": "boolean"},
                    "allowed_hosts": {"type": "array"},
                    "auth_secret_ref": {"type": "string"},
                    "auth_lease_id": {"type": "string"},
                    "journey_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "trace_id": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.qa", "browser.interact"),
            metadata={
                "tags": ["browser", "qa", "crawl"],
                "domains": ["browser"],
                "worker_kind": "browser",
                "execution_class": "EXTERNAL_REQUIRED",
                "localhost_scoped_by_default": True,
                "no_stealth_anti_bot": True,
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.qa.advance",
            name="Browser QA Advance",
            description=(
                "Bounded QA crawl continuation slice (EXTERNAL_REQUIRED). "
                "Releases the singleton browser worker between slices."
            ),
            side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="qa_advance",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "journey_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "checkpoint": {"type": "object"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.qa", "browser.interact"),
            metadata={
                "tags": ["browser", "qa", "advance"],
                "domains": ["browser"],
                "worker_kind": "browser",
                "execution_class": "EXTERNAL_REQUIRED",
                "localhost_scoped_by_default": True,
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.qa.status",
            name="Browser QA Status",
            description="Status for a QA journey crawl (JobRuntime EXTERNAL_REQUIRED ownership).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="qa_status",
            input_schema={
                "type": "object",
                "required": ["journey_id"],
                "properties": {"journey_id": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("browser.qa",),
            metadata={
                "tags": ["browser", "qa"],
                "domains": ["browser"],
                "worker_kind": "browser",
                "execution_class": "INLINE_SAFE",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.qa.cancel",
            name="Browser QA Cancel",
            description="Request cancel for a QA journey (JobRuntime EXTERNAL_REQUIRED ownership for durable runs).",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="qa_cancel",
            input_schema={
                "type": "object",
                "required": ["journey_id"],
                "properties": {"journey_id": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("browser.qa",),
            metadata={
                "tags": ["browser", "qa", "cancel"],
                "domains": ["browser"],
                "worker_kind": "browser",
                "execution_class": "INLINE_SAFE",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.qa.replay",
            name="Browser QA Replay",
            description="Replay a prior QA journey with seeded timing jitter.",
            side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="qa_replay",
            input_schema={
                "type": "object",
                "required": ["journey_id"],
                "properties": {
                    "journey_id": {"type": "string"},
                    "seed": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("browser.qa", "browser.interact"),
            metadata={
                "tags": ["browser", "qa", "replay"],
                "domains": ["browser"],
                "worker_kind": "browser",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="browser.qa.report",
            name="Browser QA Report",
            description="Fetch structured QA journey report + artifact refs.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.BROWSER,
            provider_ref="qa_report",
            input_schema={
                "type": "object",
                "required": ["journey_id"],
                "properties": {"journey_id": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("browser.qa",),
            metadata={
                "tags": ["browser", "qa", "report"],
                "domains": ["browser"],
                "worker_kind": "browser",
                "execution_class": "INLINE_SAFE",
            },
        )
    )
    # Wave 7 — media capabilities (fixture MediaService via ExecutionGateway).
    catalog.register(
        CapabilityDefinition(
            id="media.probe",
            name="Media Probe",
            description="Probe a media file path for kind/size without decoding (fixture — not production).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="PROBE",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("media.read",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "probe", "inspect"],
                "domains": ["media"],
                "aliases": ["probe media", "inspect file"],
                "cacheable": True,
                "idempotent": True,
                "worker_kind": "media",
                "fixture_is_not_production": True,
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.thumbnail",
            name="Media Thumbnail",
            description="Generate a thumbnail artifact for a media path (fixture SVG).",
            side_effects=(SideEffect.READ, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="THUMBNAIL",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {"path": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("media.read", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "thumbnail", "image"],
                "domains": ["media"],
                "worker_kind": "media",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.image_generate",
            name="Media Image Generate",
            description="Generate an image artifact from a prompt into the shared ArtifactStore.",
            side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="IMAGE_GENERATE",
            input_schema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "model_revision": {"type": "string"},
                    "sync_id": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("media.write", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "image", "generate"],
                "domains": ["media"],
                "aliases": ["generate image", "draw"],
                "worker_kind": "media",
                "risk_tier": "write",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.image_edit",
            name="Media Image Edit",
            description="Edit an existing image artifact with an instruction (shared lineage).",
            side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="IMAGE_EDIT",
            input_schema={
                "type": "object",
                "required": ["instruction"],
                "properties": {
                    "source_artifact_id": {"type": "string"},
                    "path": {"type": "string"},
                    "instruction": {"type": "string"},
                    "prompt": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("media.write", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "image", "edit"],
                "domains": ["media"],
                "worker_kind": "media",
                "risk_tier": "write",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.video_ingest",
            name="Media Video Ingest",
            description="Ingest video into frames/shots/transcript spans with timestamp citations.",
            side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="VIDEO_INGEST",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "duration_ms": {"type": "number"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("media.read", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "video", "ingest", "frames"],
                "domains": ["media"],
                "aliases": ["ingest video", "video frames"],
                "worker_kind": "media",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.vision_inspect",
            name="Media Vision Inspect",
            description="Tile a high-res image into regions for iterative visual inspection.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="VISION_INSPECT",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "path": {"type": "string"},
                    "artifact_id": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "tile": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("media.read",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "vision", "ocr", "tiles"],
                "domains": ["media", "vision"],
                "aliases": ["inspect image", "vision tiles"],
                "cacheable": True,
                "worker_kind": "media",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.cross_modal_search",
            name="Media Cross-Modal Search",
            description="Search the modality-aware caption index (image/audio/video/text).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="CROSS_MODAL_SEARCH",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "modality": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("media.read",),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "retrieval", "cross-modal"],
                "domains": ["media", "knowledge"],
                "aliases": ["cross modal search", "find scene"],
                "cacheable": True,
                "worker_kind": "media",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.transcode",
            name="Media Transcode",
            description="Typed FFmpeg transcode/convert on the media worker (EXTERNAL_REQUIRED).",
            side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="TRANSCODE",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "container": {"type": "string"},
                    "video_codec": {"type": "string"},
                    "audio_codec": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("media.write", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "transcode", "ffmpeg"],
                "domains": ["media"],
                "worker_kind": "media",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.convert",
            name="Media Convert",
            description="Typed media container/codec conversion (EXTERNAL_REQUIRED).",
            side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="CONVERT",
            input_schema={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
            output_schema={"type": "object"},
            required_permissions=("media.write", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "convert"],
                "domains": ["media"],
                "worker_kind": "media",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.audio.process",
            name="Media Audio Process",
            description="Deterministic audio transform via FFmpeg (EXTERNAL_REQUIRED). ASR/TTS remain Voice-owned.",
            side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="AUDIO_PROCESS",
            input_schema={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
            output_schema={"type": "object"},
            required_permissions=("media.write", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "audio"],
                "domains": ["media"],
                "worker_kind": "media",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.video.process",
            name="Media Video Process",
            description="Deterministic video transform via FFmpeg (EXTERNAL_REQUIRED).",
            side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="VIDEO_PROCESS",
            input_schema={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
            output_schema={"type": "object"},
            required_permissions=("media.write", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "video"],
                "domains": ["media"],
                "worker_kind": "media",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="media.image.batch",
            name="Media Image Batch",
            description="Bounded streamed image-processing batch (EXTERNAL_REQUIRED).",
            side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.MEDIA,
            provider_ref="IMAGE_BATCH",
            input_schema={
                "type": "object",
                "required": ["paths"],
                "properties": {"paths": {"type": "array"}},
            },
            output_schema={"type": "object"},
            required_permissions=("media.write", "artifact.write"),
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "tags": ["media", "image", "batch"],
                "domains": ["media"],
                "worker_kind": "media",
            },
        )
    )
    # Voice — EXTERNAL_REQUIRED on singleton voice worker (transport only; not intelligence).
    catalog.register(
        CapabilityDefinition(
            id="voice.start_session",
            name="Voice Start Session",
            description="Start a realtime voice session bound to shared conversation/run context (voice worker).",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="voice.worker",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "conversation_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "sync_id": {"type": "string"},
                    "persona": {"type": "object"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("voice.session",),
            metadata={
                "tags": ["voice", "realtime", "session"],
                "domains": ["voice"],
                "aliases": ["start voice", "voice session"],
                "worker_kind": "voice",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="voice.transcribe",
            name="Voice Transcribe",
            description="Streaming/batch ASR on the voice worker (real backend or honest UNAVAILABLE).",
            side_effects=(SideEffect.READ, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="voice.worker",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "session_id": {"type": "string"},
                    "audio_ref": {"type": "string"},
                    "path": {"type": "string"},
                    "text": {"type": "string"},
                    "hint": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("voice.asr",),
            metadata={
                "tags": ["voice", "asr", "transcribe"],
                "domains": ["voice"],
                "aliases": ["speech to text", "transcribe"],
                "worker_kind": "voice",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="voice.synthesize",
            name="Voice Synthesize",
            description="Streaming/batch TTS on the voice worker (real backend or honest UNAVAILABLE).",
            side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="voice.worker",
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "session_id": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("voice.tts",),
            metadata={
                "tags": ["voice", "tts", "synthesize"],
                "domains": ["voice"],
                "aliases": ["text to speech", "speak"],
                "worker_kind": "voice",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="voice.barge_in",
            name="Voice Barge-In",
            description="Cancel in-flight ASR/TTS generation on user interruption (voice worker).",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="voice.worker",
            input_schema={
                "type": "object",
                "required": ["session_id"],
                "properties": {"session_id": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("voice.session",),
            metadata={
                "tags": ["voice", "barge-in", "interrupt", "cancel"],
                "domains": ["voice"],
                "aliases": ["interrupt", "stop speaking"],
                "worker_kind": "voice",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="voice.preprocess",
            name="Voice Preprocess",
            description="Heavy voice audio preprocess (validate/bounds) on the voice worker.",
            side_effects=(SideEffect.READ, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="voice.worker",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "audio_ref": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("voice.asr",),
            metadata={
                "tags": ["voice", "preprocess", "audio"],
                "domains": ["voice"],
                "worker_kind": "voice",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="voice.postprocess",
            name="Voice Postprocess",
            description="Bounded transcript/audio postprocess on the voice worker.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="voice.worker",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {"text": {"type": "string"}},
            },
            output_schema={"type": "object"},
            required_permissions=("voice.tts",),
            metadata={
                "tags": ["voice", "postprocess"],
                "domains": ["voice"],
                "worker_kind": "voice",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="source_ingestion.process",
            name="Process Source Ingestion",
            description=(
                "Durable source/archive ingestion executed by the source-ingestion worker "
                "(not the API JobRuntime)."
            ),
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="source_ingestion.worker",
            input_schema={
                "type": "object",
                "required": ["source_id"],
                "properties": {
                    "source_id": {"type": "string"},
                    "project_id": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("knowledge.write", "filesystem.write"),
            metadata={
                "tags": ["ingestion", "research", "archive"],
                "domains": ["source_ingestion"],
                "worker_kind": "source_ingestion",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="source_ingestion.ocr_continue",
            name="Continue Source Ingestion After OCR",
            description=(
                "Resume source ingestion after document_ai OCR completes — snapshot, Brain sync, member finalize."
            ),
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="source_ingestion.worker",
            input_schema={
                "type": "object",
                "required": ["source_id", "project_id"],
                "properties": {
                    "source_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "container_source_id": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "ocr_job_id": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("knowledge.write", "filesystem.write"),
            metadata={
                "tags": ["ingestion", "ocr", "research"],
                "domains": ["source_ingestion"],
                "worker_kind": "source_ingestion",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="source_ingestion.brain_retry",
            name="Retry Source Brain Sync",
            description="Retry Brain sync for already-parsed source ingestion children.",
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="source_ingestion.worker",
            input_schema={
                "type": "object",
                "required": ["source_id"],
                "properties": {
                    "source_id": {"type": "string"},
                    "project_id": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("knowledge.write",),
            metadata={
                "tags": ["ingestion", "brain", "retry"],
                "domains": ["source_ingestion"],
                "worker_kind": "source_ingestion",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="ocr.extract",
            name="OCR Extract",
            description=(
                "Optical character recognition / scanned-document text extraction. "
                "Owned exclusively by the document_ai worker pool (EXTERNAL_REQUIRED). "
                "When no OCR backend is configured the worker fails closed with OCR_UNAVAILABLE."
            ),
            side_effects=(SideEffect.READ, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="document_ai.worker",
            input_schema={
                "type": "object",
                "required": ["source_id", "path"],
                "properties": {
                    "source_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "path": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "mime_type": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "tags": ["ocr", "document_ai", "ingestion"],
                "domains": ["document_ai"],
                "worker_kind": "document_ai",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="document_ai.ocr",
            name="Document AI OCR",
            description=(
                "Document-AI OCR capability alias. EXTERNAL_REQUIRED on document_ai pool. "
                "Never executed inline by FastAPI or source_ingestion API callers."
            ),
            side_effects=(SideEffect.READ, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="document_ai.worker",
            input_schema={
                "type": "object",
                "required": ["source_id"],
                "properties": {
                    "source_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "path": {"type": "string"},
                    "relative_path": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "tags": ["ocr", "document_ai"],
                "domains": ["document_ai"],
                "worker_kind": "document_ai",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="document_ai.extract",
            name="Document AI Extract",
            description=(
                "Document-AI extraction alias (OCR/layout). EXTERNAL_REQUIRED on document_ai. "
                "Fails closed with DOCUMENT_AI_UNAVAILABLE when no backend is configured."
            ),
            side_effects=(SideEffect.READ, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="document_ai.worker",
            input_schema={
                "type": "object",
                "required": ["source_id"],
                "properties": {
                    "source_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "tags": ["ocr", "document_ai"],
                "domains": ["document_ai"],
                "worker_kind": "document_ai",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="document_ai.process",
            name="Document AI Process",
            description=(
                "Document-AI process alias. EXTERNAL_REQUIRED on document_ai pool."
            ),
            side_effects=(SideEffect.READ, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.EXTERNAL,
            provider_ref="document_ai.worker",
            input_schema={
                "type": "object",
                "required": ["source_id"],
                "properties": {
                    "source_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("filesystem.read",),
            metadata={
                "tags": ["ocr", "document_ai"],
                "domains": ["document_ai"],
                "worker_kind": "document_ai",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="compute.numeric",
            name="Numeric Compute",
            description="Deterministic Tier-0 math/statistics (never the main LLM).",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="numeric_compute",
            input_schema={
                "type": "object",
                "required": ["operation"],
                "properties": {
                    "operation": {"type": "string"},
                    "arguments": {"type": "object"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=(),
            metadata={
                "tags": ["compute", "tier0", "deterministic"],
                "domains": ["compute"],
                "worker_kind": "general",
                "execution_class": "INLINE_SAFE",
                "aliases": ["math.calculate", "calculator"],
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="math.calculate",
            name="Math Calculate",
            description=(
                "Safe AST numeric expression evaluator (no eval). "
                "Alias path for deterministic arithmetic via compute.numeric."
            ),
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="math_calculate",
            input_schema={
                "type": "object",
                "required": ["expression"],
                "properties": {
                    "expression": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=(),
            metadata={
                "tags": ["math", "compute", "tier0", "deterministic", "gi6"],
                "domains": ["compute"],
                "aliases": ["calculate", "calc"],
                "worker_kind": "general",
                "execution_class": "INLINE_SAFE",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="system.inspect",
            name="System Inspect",
            description=(
                "Honest self-inspection of process state (version, model, cognition, "
                "fleet, telemetry). Never invents brain percentage or model values."
            ),
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="system_inspect",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "scope": {
                        "type": "string",
                        "description": "all or comma-separated section names",
                    },
                },
            },
            output_schema={"type": "object"},
            required_permissions=(),
            metadata={
                "tags": ["system", "inspect", "self", "cognition", "gi2"],
                "domains": ["system", "cognition"],
                "aliases": ["self_inspect", "whoami", "system_status"],
                "worker_kind": "general",
                "execution_class": "INLINE_SAFE",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="web.search",
            name="Web Search",
            description=(
                "Search the web via configured WebResearchProvider. "
                "Returns WEB_SEARCH_UNAVAILABLE when search is not configured — never fabricates."
            ),
            side_effects=(SideEffect.READ, SideEffect.NETWORK),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="web_search",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("network.outbound",),
            metadata={
                "tags": ["web", "search", "research", "gi7"],
                "domains": ["web", "research"],
                "aliases": ["search_web", "internet_search"],
                "worker_kind": "research",
                "execution_class": "EXTERNAL_PREFERRED",
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="web.fetch",
            name="Web Fetch",
            description=(
                "Fetch a URL via WebResearchProvider (SSRF-safe). "
                "May work when search is unconfigured if outbound is allowed."
            ),
            side_effects=(SideEffect.READ, SideEffect.NETWORK),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="web_fetch",
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
            required_permissions=("network.outbound",),
            metadata={
                "tags": ["web", "fetch", "research", "gi7"],
                "domains": ["web", "research"],
                "aliases": ["fetch_url", "http_fetch"],
                "worker_kind": "research",
                "execution_class": "EXTERNAL_PREFERRED",
            },
        )
    )
    _register_fabric_worker_capabilities(catalog)
    try:
        from Data.modules.market_sim.chat_capabilities import register_market_sim_chat_capabilities

        register_market_sim_chat_capabilities(catalog)
    except Exception:  # noqa: BLE001
        # Catalog build must not fail closed on optional research chat surface.
        pass
    try:
        from Data.modules.module_manager.external.catalog_register import (
            register_external_control_capabilities,
        )

        register_external_control_capabilities(catalog)
    except Exception:  # noqa: BLE001
        # External control caps are also registered at FastAPI startup; catalog
        # build must still include them for EXTERNAL_WORKER_CAPABILITIES drift.
        pass
    return catalog


def _register_fabric_worker_capabilities(catalog: CapabilityCatalog) -> None:
    """Durable jobs claimed by generic worker pools (API enqueues; workers execute)."""

    def _ext(
        *,
        cap_id: str,
        name: str,
        description: str,
        side_effects: tuple[SideEffect, ...],
        worker_kind: str,
        properties: dict | None = None,
        required_args: list[str] | None = None,
        tags: list[str] | None = None,
        domains: list[str] | None = None,
        permissions: tuple[str, ...] = (),
        extra_meta: dict | None = None,
    ) -> None:
        props = dict(properties or {})
        meta: dict = {
            "tags": tags or [worker_kind, cap_id.split(".", 1)[-1]],
            "domains": domains or [cap_id.split(".", 1)[0]],
            "worker_kind": worker_kind,
            "execution_class": "EXTERNAL_REQUIRED",
            "idempotent": True,
            "cacheable": False,
        }
        if extra_meta:
            meta.update(extra_meta)
        catalog.register(
            CapabilityDefinition(
                id=cap_id,
                name=name,
                description=description,
                side_effects=side_effects,
                provider_kind=CapabilityProviderKind.EXTERNAL,
                provider_ref=f"{worker_kind}.worker",
                input_schema={
                    "type": "object",
                    "required": list(required_args or []),
                    "properties": props,
                },
                output_schema={"type": "object"},
                required_permissions=permissions,
                metadata=meta,
            )
        )

    _project = {
        "project_id": {"type": "string"},
        "action": {"type": "string"},
        "deepen": {"type": "boolean"},
        "extra_rounds": {"type": "integer"},
        "resume": {"type": "boolean"},
    }
    _ext(
        cap_id="research.advance",
        name="Advance Research Project",
        description="Advance one durable research project step (research worker pool).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="research",
        required_args=["project_id"],
        properties=_project,
        permissions=("process.execute",),
        tags=["research", "advance", "durable"],
    )
    _ext(
        cap_id="research.plan",
        name="Plan Research Project",
        description="Generate or refresh a research plan for a project.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="research",
        required_args=["project_id"],
        properties={"project_id": {"type": "string"}, "edits": {"type": "object"}},
        permissions=("process.execute",),
        tags=["research", "plan"],
        extra_meta={"compute_tier_hint": 3},
    )
    _ext(
        cap_id="research.retrieve",
        name="Retrieve Research Evidence (internal phase)",
        description=(
            "NOT a standalone public capability. Retrieve is a coordinator-internal "
            "phase of research.advance. Invoking this capability fails with "
            "CAPABILITY_UNSUPPORTED — enqueue research.advance instead."
        ),
        side_effects=(SideEffect.READ, SideEffect.NETWORK),
        worker_kind="research",
        required_args=["project_id"],
        properties={"project_id": {"type": "string"}, "query": {"type": "string"}},
        permissions=("knowledge.read",),
        tags=["research", "retrieve", "internal_phase", "unsupported_standalone"],
        extra_meta={
            "public_availability": "UNSUPPORTED",
            "canonical_capability": "research.advance",
            "error_code": "CAPABILITY_UNSUPPORTED",
            "advertise_as_available": False,
        },
    )
    _ext(
        cap_id="research.synthesize",
        name="Synthesize Research Findings (internal phase)",
        description=(
            "NOT a standalone public capability. Synthesize is a coordinator-internal "
            "phase of research.advance. Invoking this capability fails with "
            "CAPABILITY_UNSUPPORTED — enqueue research.advance instead."
        ),
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="research",
        required_args=["project_id"],
        properties={"project_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["research", "synthesize", "internal_phase", "unsupported_standalone"],
        extra_meta={
            "public_availability": "UNSUPPORTED",
            "canonical_capability": "research.advance",
            "error_code": "CAPABILITY_UNSUPPORTED",
            "advertise_as_available": False,
            "requires_reasoning": True,
            "compute_tier_hint": 3,
        },
    )
    _ext(
        cap_id="research.verify",
        name="Verify Research Citations",
        description="Verify citation coverage and claim support for a research project.",
        side_effects=(SideEffect.READ,),
        worker_kind="research",
        required_args=["project_id"],
        properties={"project_id": {"type": "string"}},
        permissions=("knowledge.read",),
        tags=["research", "verify"],
    )
    _ext(
        cap_id="research.fetch_url",
        name="Fetch Research URL Source",
        description="Fetch/parse a URL source and sync to Brain (research worker; not API).",
        side_effects=(SideEffect.NETWORK, SideEffect.WRITE),
        worker_kind="research",
        required_args=["project_id", "url"],
        properties={
            "project_id": {"type": "string"},
            "url": {"type": "string"},
            "source_id": {"type": "string"},
            "action": {"type": "string"},
        },
        permissions=("knowledge.write",),
        tags=["research", "url", "fetch"],
    )
    _ext(
        cap_id="research.report.generate",
        name="Generate Research Report",
        description="Regenerate research report + optional Brain sync (research worker).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="research",
        required_args=["project_id"],
        properties={
            "project_id": {"type": "string"},
            "action": {"type": "string"},
        },
        permissions=("process.execute", "knowledge.write"),
        tags=["research", "report"],
    )
    _ext(
        cap_id="research.web.probe",
        name="Probe Research Web Path",
        description=(
            "Live search+fetch readiness probe (research worker). "
            "Not a control-plane readiness snapshot — performs real network I/O."
        ),
        side_effects=(SideEffect.NETWORK, SideEffect.READ),
        worker_kind="research",
        properties={
            "query": {"type": "string"},
            "limit": {"type": "integer"},
            "action": {"type": "string"},
        },
        permissions=("knowledge.read",),
        tags=["research", "web", "probe"],
    )
    _ext(
        cap_id="memory.consolidate",
        name="Consolidate Memory",
        description=(
            "Batch episodic→semantic memory consolidation (memory worker). "
            "Candidates remain AGENT_PROPOSED; model confidence is not truth."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="memory",
        properties={
            "scope": {"type": "string"},
            "project_id": {"type": "string"},
            "conversation_id": {"type": "string"},
            "limit": {"type": "integer"},
            "min_cluster_size": {"type": "integer"},
            "persist": {"type": "boolean"},
        },
        permissions=("process.execute",),
        tags=["memory", "consolidate"],
        domains=["memory"],
    )
    _ext(
        cap_id="memory.enrich",
        name="Enrich Memory",
        description="Heavy memory enrichment/clustering proposals (memory worker).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="memory",
        properties={
            "scope": {"type": "string"},
            "project_id": {"type": "string"},
            "conversation_id": {"type": "string"},
            "limit": {"type": "integer"},
        },
        permissions=("process.execute",),
        tags=["memory", "enrich"],
        domains=["memory"],
    )
    _ext(
        cap_id="memory.reconcile",
        name="Reconcile Memory",
        description="Scope/trust reconciliation sweep for durable MemoryStore.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="memory",
        properties={"scope": {"type": "string"}, "dry_run": {"type": "boolean"}},
        permissions=("process.execute",),
        tags=["memory", "reconcile"],
        domains=["memory"],
    )
    _ext(
        cap_id="brain.compute.snapshot",
        name="Brain Derived Snapshot",
        description=(
            "Heavy derived Brain graph snapshot/analysis artifact (brain_compute). "
            "Brain remains a facade — this never creates a Brain database."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="brain_compute",
        properties={
            "limit": {"type": "integer"},
            "algorithm": {"type": "string"},
            "q": {"type": "string"},
            "types": {"type": "array"},
        },
        permissions=("knowledge.read",),
        tags=["brain", "compute", "snapshot"],
        domains=["brain"],
    )
    _ext(
        cap_id="brain.rebuild",
        name="Brain Derived Rebuild",
        description="Recompute derived Brain projection/cache from authoritative stores.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="brain_compute",
        properties={"limit": {"type": "integer"}, "algorithm": {"type": "string"}},
        permissions=("knowledge.read",),
        tags=["brain", "rebuild"],
        domains=["brain"],
    )
    _ext(
        cap_id="brain.recompute",
        name="Brain Graph Recompute",
        description="Heavy derived graph recomputation (communities/centrality/stats).",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="brain_compute",
        properties={"limit": {"type": "integer"}, "algorithm": {"type": "string"}},
        permissions=("knowledge.read",),
        tags=["brain", "recompute"],
        domains=["brain"],
    )
    _ext(
        cap_id="brain.enrich",
        name="Brain Derived Enrichment",
        description=(
            "Advisory Brain enrichment proposals (brain_compute). "
            "Canonical mutations remain with Knowledge/Memory/Research owners."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="brain_compute",
        properties={"limit": {"type": "integer"}},
        permissions=("knowledge.read",),
        tags=["brain", "enrich"],
        domains=["brain"],
    )
    _ext(
        cap_id="brain.analyze",
        name="Brain Heavy Analysis",
        description="Heavy derived Brain analysis (communities, bridges, clusters).",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="brain_compute",
        properties={"limit": {"type": "integer"}, "algorithm": {"type": "string"}},
        permissions=("knowledge.read",),
        tags=["brain", "analyze"],
        domains=["brain"],
    )
    _ext(
        cap_id="knowledge.reconcile",
        name="Reconcile Knowledge Semantics",
        description=(
            "Diagnose/repair Knowledge semantic index mismatches "
            "(missing chunks, stale embeddings/FTS) via knowledge_prepare."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="knowledge_prepare",
        properties={
            "dry_run": {"type": "boolean"},
            "limit": {"type": "integer"},
            "apply": {"type": "boolean"},
        },
        permissions=("knowledge.write",),
        tags=["knowledge", "reconcile"],
        domains=["knowledge"],
    )
    _ext(
        cap_id="dataset.process",
        name="Process Dataset Job",
        description="Execute one durable dataset domain job (dataset worker pool).",
        side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
        worker_kind="dataset",
        required_args=["dataset_job_id"],
        properties={
            "dataset_job_id": {"type": "string"},
            "job_type": {"type": "string"},
            "dataset_id": {"type": "string"},
            "version_id": {"type": "string"},
        },
        permissions=("datasets.write",),
        tags=["datasets", "process", "durable"],
        domains=["datasets"],
    )
    _ext(
        cap_id="workflow.advance",
        name="Advance Workflow",
        description="Continue a durable workflow run by one step.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="workflow",
        required_args=["workflow_id"],
        properties={"workflow_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["workflow", "advance"],
        domains=["workflows"],
    )
    _ext(
        cap_id="schedule.tick",
        name="Schedule Tick",
        description="Evaluate due schedules and enqueue targets (enqueue-only; no inline execute).",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="scheduler",
        properties={"execute": {"type": "boolean"}},
        permissions=("process.execute",),
        tags=["schedule", "tick"],
        domains=["schedules"],
    )
    _ext(
        cap_id="knowledge.prepare",
        name="Prepare Knowledge Artifact",
        description="Chunk, embed-prep, backfill, or finish staged knowledge documents (worker pool).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="knowledge_prepare",
        properties={
            "artifact_id": {"type": "string"},
            "document_id": {"type": "string"},
            "action": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "source": {"type": "string"},
            "path": {"type": "string"},
            "limit": {"type": "integer"},
        },
        permissions=("knowledge.write",),
        tags=["knowledge", "prepare"],
        domains=["knowledge"],
    )
    _ext(
        cap_id="knowledge.commit",
        name="Commit Knowledge Artifact",
        description="Serialized canonical knowledge commit lane (single-writer pool).",
        side_effects=(SideEffect.WRITE,),
        worker_kind="db_commit",
        properties={
            "artifact_id": {"type": "string"},
            "artifact": {"type": "object"},
            "idempotency_key": {"type": "string"},
        },
        permissions=("knowledge.write",),
        tags=["knowledge", "commit", "db_commit"],
        domains=["knowledge"],
    )
    _ext(
        cap_id="knowledge.ingest_document",
        name="Ingest Knowledge Document",
        description=(
            "Stage/ingest a document into Knowledge via the knowledge_prepare worker "
            "(alias path of knowledge.prepare for document_id payloads)."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="knowledge_prepare",
        properties={
            "document_id": {"type": "string"},
            "content": {"type": "string"},
            "title": {"type": "string"},
            "source": {"type": "string"},
            "action": {"type": "string"},
        },
        permissions=("knowledge.write",),
        tags=["knowledge", "ingest", "document"],
        domains=["knowledge"],
        extra_meta={"aliases": ["knowledge.prepare"]},
    )
    _ext(
        cap_id="knowledge.ingest_path",
        name="Ingest Knowledge Path",
        description=(
            "Stage/ingest a filesystem path into Knowledge via the knowledge_prepare worker."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="knowledge_prepare",
        properties={
            "path": {"type": "string"},
            "title": {"type": "string"},
            "source": {"type": "string"},
            "action": {"type": "string"},
        },
        permissions=("knowledge.write",),
        tags=["knowledge", "ingest", "path"],
        domains=["knowledge"],
        extra_meta={"aliases": ["knowledge.prepare"]},
    )
    _ext(
        cap_id="embedding.batch",
        name="Embedding Batch",
        description="Specialist embedding batch (Tier-1 compute; not main LLM).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="embedding",
        properties={
            "texts": {"type": "array"},
            "model_id": {"type": "string"},
        },
        permissions=("process.execute",),
        tags=["embedding", "batch", "specialist"],
        domains=["embedding"],
        extra_meta={"compute_tier_hint": 1},
    )
    _ext(
        cap_id="rerank.batch",
        name="Rerank Batch",
        description=(
            "Specialist reranking batch (rerank worker pool). "
            "FEATURE_GATED when the rerank pool is not configured/desired."
        ),
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="rerank",
        properties={
            "query": {"type": "string"},
            "documents": {"type": "array"},
            "model_id": {"type": "string"},
            "top_k": {"type": "integer"},
        },
        permissions=("process.execute",),
        tags=["rerank", "batch", "specialist"],
        domains=["rerank"],
        extra_meta={"compute_tier_hint": 1, "feature_gated": True},
    )
    _ext(
        cap_id="maintenance.reconcile",
        name="Maintenance Reconcile",
        description="Lease recovery, stale cleanup, and reconciliation sweep.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="maintenance",
        properties={"scope": {"type": "string"}, "batch_limit": {"type": "integer"}},
        permissions=("process.execute",),
        tags=["maintenance", "reconcile"],
        domains=["jobs"],
    )
    _ext(
        cap_id="maintenance.db.integrity",
        name="Database Integrity Check",
        description="Full PRAGMA integrity_check / heavy quick_check under maintenance exclusivity.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="maintenance",
        properties={
            "domain": {"type": "string"},
            "kind": {"type": "string"},
            "max_errors": {"type": "integer"},
        },
        permissions=("process.execute", "filesystem.read"),
        tags=["maintenance", "integrity", "sqlite"],
        domains=["database"],
    )
    _ext(
        cap_id="maintenance.db.vacuum",
        name="Database VACUUM",
        description="Exclusive VACUUM rewrite of a canonical database domain.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={"domain": {"type": "string"}},
        permissions=("process.execute", "filesystem.write"),
        tags=["maintenance", "vacuum", "sqlite"],
        domains=["database"],
    )
    _ext(
        cap_id="maintenance.db.analyze",
        name="Database ANALYZE",
        description="Large ANALYZE of planner statistics for a domain/table/index.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={
            "domain": {"type": "string"},
            "table": {"type": "string"},
            "index": {"type": "string"},
        },
        permissions=("process.execute",),
        tags=["maintenance", "analyze", "sqlite"],
        domains=["database"],
    )
    _ext(
        cap_id="maintenance.db.checkpoint",
        name="Blocking WAL Checkpoint",
        description="FULL/RESTART/TRUNCATE WAL checkpoint under maintenance exclusivity.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={"domain": {"type": "string"}, "mode": {"type": "string"}},
        permissions=("process.execute",),
        tags=["maintenance", "wal", "sqlite"],
        domains=["database"],
    )
    _ext(
        cap_id="maintenance.db.cleanup",
        name="Database Retention Cleanup",
        description="Bounded retention / stale-data cleanup under maintenance.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={
            "domain": {"type": "string"},
            "policy": {"type": "string"},
            "batch_limit": {"type": "integer"},
            "dry_run": {"type": "boolean"},
        },
        permissions=("process.execute",),
        tags=["maintenance", "cleanup"],
        domains=["database"],
    )
    _ext(
        cap_id="maintenance.db.import",
        name="Controlled Database Import",
        description="Typed operator table import under maintenance (never arbitrary executescript).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={
            "domain": {"type": "string"},
            "table": {"type": "string"},
            "artifact_ref": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        permissions=("process.execute", "filesystem.write"),
        tags=["maintenance", "import"],
        domains=["database"],
    )
    _ext(
        cap_id="maintenance.db.migration_verify",
        name="Migration Verification",
        description="Heavy post-migration verification (not a second migration engine).",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="maintenance",
        properties={"domain": {"type": "string"}},
        permissions=("process.execute",),
        tags=["maintenance", "migration", "verify"],
        domains=["database"],
    )
    _ext(
        cap_id="maintenance.backup.restore",
        name="Restore Backup Cutover",
        description="System-wide maintenance restore via BackupService + MaintenanceCoordinator.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={
            "backup_id": {"type": "string"},
            "confirm": {"type": "boolean"},
        },
        permissions=("process.execute", "filesystem.write"),
        tags=["maintenance", "restore", "backup"],
        domains=["backup"],
    )
    _ext(
        cap_id="maintenance.artifacts.cleanup",
        name="Artifact Store Cleanup",
        description="Reference-aware ArtifactStore retention cleanup.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={"dry_run": {"type": "boolean"}, "batch_limit": {"type": "integer"}},
        permissions=("process.execute", "filesystem.write"),
        tags=["maintenance", "artifacts", "cleanup"],
        domains=["artifacts"],
    )
    _ext(
        cap_id="maintenance.cache.cleanup",
        name="Canonical Cache Cleanup",
        description="Cleanup of known canonical cache roots only (path-escape safe).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={"dry_run": {"type": "boolean"}},
        permissions=("process.execute", "filesystem.write"),
        tags=["maintenance", "cache", "cleanup"],
        domains=["system"],
    )
    _ext(
        cap_id="maintenance.orphans.cleanup",
        name="Orphan Cleanup",
        description="Cross-domain orphan staging/partial cleanup when ownership is proven.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="maintenance",
        properties={"dry_run": {"type": "boolean"}, "batch_limit": {"type": "integer"}},
        permissions=("process.execute",),
        tags=["maintenance", "orphans", "cleanup"],
        domains=["system"],
    )
    _ext(
        cap_id="evaluation.run",
        name="Run Evaluation",
        description="Execute an evaluation suite or case batch.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="evaluation",
        properties={
            "suite_id": {"type": "string"},
            "run_id": {"type": "string"},
        },
        permissions=("process.execute",),
        tags=["evaluation", "run"],
    )
    _ext(
        cap_id="evaluation.benchmark",
        name="Run Evaluation Benchmark",
        description="Execute a benchmark suite externally with provenance binding.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="evaluation",
        properties={"suite_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["evaluation", "benchmark"],
    )
    _ext(
        cap_id="evaluation.regression",
        name="Run Regression Suite",
        description="Execute immutable-identity regression corpus externally.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="evaluation",
        properties={"suite_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["evaluation", "regression"],
    )
    _ext(
        cap_id="evaluation.ablation",
        name="Run Ablation Suite",
        description="Execute feature ablation with explicit baseline/delta.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="evaluation",
        properties={"suite_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["evaluation", "ablation"],
    )
    _ext(
        cap_id="evaluation.scorecard",
        name="Build Large Scorecard",
        description="Aggregate existing measured evidence into a large scorecard (external).",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="evaluation",
        properties={"scope": {"type": "string"}},
        permissions=("process.execute",),
        tags=["evaluation", "scorecard"],
    )
    _ext(
        cap_id="evaluation.release.validate",
        name="Release Validation",
        description="Execute typed allowlisted release validation test plan externally.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="evaluation",
        properties={"plan_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["evaluation", "release", "validate"],
    )
    _ext(
        cap_id="evaluation.verify_tests",
        name="Verify Test Suites",
        description="Measured test-suite verification via typed allowlisted runners.",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="evaluation",
        properties={"suite_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["evaluation", "verify", "tests"],
    )
    _ext(
        cap_id="evaluation.statistics",
        name="Statistical Analysis",
        description="Generic statistical qualification/analysis (not MarketSim QualificationAuthority).",
        side_effects=(SideEffect.EXECUTE, SideEffect.READ),
        worker_kind="evaluation",
        properties={
            "method": {"type": "string"},
            "artifact_ref": {"type": "string"},
            "seed": {"type": "integer"},
        },
        permissions=("process.execute",),
        tags=["evaluation", "statistics"],
    )
    _ext(
        cap_id="evaluation.soak",
        name="Resource Soak Test",
        description="Bounded soak experiment orchestrated by evaluation; telemetry measures.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="evaluation",
        properties={
            "duration_seconds": {"type": "number"},
            "profile": {"type": "string"},
        },
        permissions=("process.execute",),
        tags=["evaluation", "soak"],
    )
    _ext(
        cap_id="evaluation.chaos",
        name="Chaos / Stress Experiment",
        description="Bounded explicit chaos/stress experiment with durable cleanup.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="evaluation",
        properties={
            "experiment_id": {"type": "string"},
            "duration_seconds": {"type": "number"},
        },
        permissions=("process.execute",),
        tags=["evaluation", "chaos"],
    )
    _ext(
        cap_id="training.control",
        name="Training Control",
        description=(
            "Own trainer subprocess lifecycle for its FULL duration "
            "(spawn, supervise, cancel, finalize). GPU_EXCLUSIVE while trainer runs."
        ),
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="training_control",
        properties={
            "training_job_id": {"type": "string"},
            "job_id": {"type": "string"},
            "action": {"type": "string"},
        },
        permissions=("process.execute",),
        tags=["training", "control"],
        domains=["training"],
    )
    _ext(
        cap_id="training.integrity.verify",
        name="Verify Training Artifact Integrity",
        description=(
            "Streaming integrity scan + optional model-registry publish gate. "
            "IO_HEAVY/CPU_HEAVY — not GPU_EXCLUSIVE."
        ),
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="training_control",
        properties={"training_job_id": {"type": "string"}},
        permissions=("filesystem.read", "process.execute"),
        tags=["training", "integrity"],
        domains=["training"],
    )
    _ext(
        cap_id="training.checkpoint.verify",
        name="Verify Training Checkpoint",
        description="Verify checkpoint completeness/compatibility (streaming hashes). IO_HEAVY.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="training_control",
        properties={
            "training_job_id": {"type": "string"},
            "checkpoint_path": {"type": "string"},
        },
        permissions=("filesystem.read", "process.execute"),
        tags=["training", "checkpoint"],
        domains=["training"],
    )
    _ext(
        cap_id="training.dataset.hash",
        name="Hash Training Dataset",
        description="Streaming dataset content/manifest hash with change detection. IO_HEAVY/CPU_HEAVY.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="training_control",
        properties={
            "training_job_id": {"type": "string"},
            "path": {"type": "string"},
        },
        permissions=("filesystem.read", "process.execute"),
        tags=["training", "dataset", "hash"],
        domains=["training"],
    )
    _ext(
        cap_id="market_sim.advance",
        name="Advance Market Simulation",
        description="Advance one market simulation step.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="market_sim",
        properties={"simulation_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["market_sim", "advance"],
    )
    _ext(
        cap_id="market_sim.gym_episode",
        name="Run TradingGym Episode",
        description="Execute a complete TradingGym episode on the market_sim worker (EXTERNAL_REQUIRED).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="market_sim",
        properties={"simulation_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["market_sim", "gym", "episode"],
    )
    _ext(
        cap_id="market_sim.research_campaign",
        name="Run Research Campaign",
        description="Execute/resume a durable ResearchCampaign on the market_sim worker (EXTERNAL_REQUIRED).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="market_sim",
        properties={"campaign_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["market_sim", "research", "campaign"],
    )
    _ext(
        cap_id="market_sim.learning_run",
        name="Run Strategy Learning Loop",
        description="Execute/resume adaptive Strategy DSL learning on the market_sim worker (EXTERNAL_REQUIRED).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={"learning_run_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["market_sim", "learning", "strategy"],
    )
    _ext(
        cap_id="market_sim.qualification_run",
        name="Run Institutional Qualification",
        description=(
            "Execute/resume QualificationAuthority evaluation on the market_sim worker "
            "(WFA folds, statistical gates, sealed holdout). EXTERNAL_REQUIRED; idempotent."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={"qualification_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["market_sim", "qualification"],
    )
    _ext(
        cap_id="market_sim.paper_order",
        name="Place Paper Order",
        description="Place a paper (non-live) order via MarketSimControlPlane + RiskGuard.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={
            "session_id": {"type": "string"},
            "side": {"type": "string"},
            "qty": {"type": "number"},
        },
        permissions=("process.execute",),
        tags=["market_sim", "paper", "order"],
    )
    _ext(
        cap_id="market_sim.portfolio_order",
        name="Place Portefeuille Paper Order",
        description="Place a paper order against a multi-asset Paper Portefeuille (RiskGuard gated).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={
            "portfolio_id": {"type": "string"},
            "symbol": {"type": "string"},
            "side": {"type": "string"},
            "qty": {"type": "number"},
        },
        permissions=("process.execute",),
        tags=["market_sim", "paper", "portefeuille", "order"],
    )
    _ext(
        cap_id="market_sim.portfolio_rebalance",
        name="Execute Portefeuille Rebalance",
        description="Execute paper rebalance orders for a Portefeuille via RiskGuard.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={"portfolio_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["market_sim", "paper", "portefeuille", "rebalance"],
    )
    _ext(
        cap_id="market_sim.portfolio_tick",
        name="Portefeuille Autonomous Tick",
        description="One autonomous paper Portefeuille decision/mark cycle on the market_sim worker.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={"portfolio_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["market_sim", "paper", "portefeuille", "autonomous"],
    )
    _ext(
        cap_id="market_sim.autonomous_step",
        name="Autonomous Paper Step",
        description=(
            "One durable autonomous paper-forward step (RiskGuard + paper broker). "
            "Scheduler/event cadence enqueues; never an infinite loop."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={
            "deployment_id": {"type": "string"},
            "side": {"type": "string"},
            "qty": {"type": "number"},
        },
        permissions=("process.execute",),
        tags=["market_sim", "paper", "autonomous"],
    )
    _ext(
        cap_id="market_sim.paper_forward_step",
        name="Paper-Forward Evaluation Step",
        description="One bounded paper-forward evaluation step with causal evidence only.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={
            "session_id": {"type": "string"},
            "side": {"type": "string"},
            "qty": {"type": "number"},
        },
        permissions=("process.execute",),
        tags=["market_sim", "paper", "forward"],
    )
    _ext(
        cap_id="market_sim.chart.render_batch",
        name="Render Market Chart Batch",
        description=(
            "Bounded deterministic OHLCV chart render batch → ArtifactStore. "
            "Continuation for large batches. No chart worker pool."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={
            "batch_id": {"type": "string"},
            "specs": {"type": "array"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        permissions=("process.execute", "filesystem.write"),
        tags=["market_sim", "chart", "batch"],
        domains=["market_sim"],
    )
    _ext(
        cap_id="market_sim.news.poll",
        name="Poll Market News Feeds",
        description="Fetch registered news feeds (via provider_io) and store items with a causal available_at.",
        side_effects=(SideEffect.NETWORK, SideEffect.WRITE),
        worker_kind="market_sim",
        properties={"feed_id": {"type": "string"}},
        permissions=("network.outbound",),
        tags=["market_sim", "news", "trading"],
    )
    _ext(
        cap_id="market_sim.scan_batch",
        name="Market Sim Scan Batch",
        description="Batch-scan market data sources / symbols on the market_sim worker.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="market_sim",
        properties={
            "symbols": {"type": "array"},
            "provider_id": {"type": "string"},
            "timeframe": {"type": "string"},
            "limit": {"type": "integer"},
            "payload": {"type": "object"},
        },
        permissions=("process.execute", "filesystem.read"),
        tags=["market_sim", "scan", "batch"],
        domains=["market_sim"],
    )
    _ext(
        cap_id="market_sim.data.scan",
        name="Market Data Directory Scan",
        description="Bounded/checkpointed markets_root discovery on the market_sim worker.",
        side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
        worker_kind="market_sim",
        properties={
            "max_entries": {"type": "integer"},
            "cursor": {"type": "object"},
            "register": {"type": "boolean"},
        },
        permissions=("process.execute", "filesystem.read"),
        tags=["market_sim", "market_data", "scan"],
        domains=["market_sim"],
    )
    _ext(
        cap_id="market_sim.data.import",
        name="Market Data Import",
        description="Streaming quarantine→validate→hash→register import on the market_sim worker.",
        side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
        worker_kind="market_sim",
        properties={
            "path": {"type": "string"},
            "symbol": {"type": "string"},
            "timeframe": {"type": "string"},
            "seal": {"type": "boolean"},
            "role": {"type": "string"},
            "provider": {"type": "string"},
        },
        permissions=("process.execute", "filesystem.read", "filesystem.write"),
        tags=["market_sim", "market_data", "import"],
        domains=["market_sim"],
    )
    _ext(
        cap_id="market_sim.data.validate",
        name="Market Data Validate",
        description="Streaming OHLCV validation/quality on the market_sim worker.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="market_sim",
        properties={
            "path": {"type": "string"},
            "source_id": {"type": "string"},
            "relative_path": {"type": "string"},
        },
        permissions=("process.execute", "filesystem.read"),
        tags=["market_sim", "market_data", "validate"],
        domains=["market_sim"],
    )
    _ext(
        cap_id="market_sim.data.profile",
        name="Market Data Profile",
        description="Streaming/online market-data profile on the market_sim worker.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="market_sim",
        properties={
            "path": {"type": "string"},
            "source_id": {"type": "string"},
            "relative_path": {"type": "string"},
        },
        permissions=("process.execute", "filesystem.read"),
        tags=["market_sim", "market_data", "profile"],
        domains=["market_sim"],
    )
    _ext(
        cap_id="market_sim.data.convert",
        name="Market Data Convert",
        description="Streaming CSV→analytical/Parquet conversion on the market_sim worker.",
        side_effects=(SideEffect.READ, SideEffect.WRITE, SideEffect.EXECUTE),
        worker_kind="market_sim",
        properties={
            "path": {"type": "string"},
            "source_id": {"type": "string"},
            "relative_path": {"type": "string"},
            "output_format": {"type": "string"},
        },
        permissions=("process.execute", "filesystem.read", "filesystem.write"),
        tags=["market_sim", "market_data", "convert"],
        domains=["market_sim"],
    )
    _ext(
        cap_id="market_sim.assurance.scan",
        name="Institutional Assurance Scan",
        description=(
            "Bounded institutional assurance scan on the market_sim worker "
            "(PASS/FAIL/UNMEASURED; not QualificationAuthority)."
        ),
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="market_sim",
        properties={"scope": {"type": "string"}},
        permissions=("process.execute", "filesystem.read"),
        tags=["market_sim", "assurance", "institutional"],
        domains=["market_sim"],
    )
    # Approval-identity capability for mandate loosening (control-plane; not a worker job).
    catalog.register(
        CapabilityDefinition(
            id="market_sim.mandate.loosen",
            name="Loosen Trading Orchestra Mandate",
            description=(
                "Approval-gated identity for loosening a Trading Orchestra mandate. "
                "Not a JobRuntime worker capability — ExecutionGateway / ApprovalService only."
            ),
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.INTERNAL,
            provider_ref="market_sim.mandate.loosen",
            input_schema={
                "type": "object",
                "required": ["orchestra_id"],
                "properties": {
                    "orchestra_id": {"type": "string"},
                    "approval_id": {"type": "string"},
                    "mandate": {"type": "object"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("process.execute",),
            metadata={
                "tags": ["market_sim", "mandate", "approval"],
                "domains": ["market_sim"],
                "execution_class": "INLINE_SAFE",
                "approval_identity": True,
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="market_sim.portfolio_risk.loosen",
            name="Loosen Portfolio Risk Settings",
            description=(
                "Approval-gated identity for loosening paper/portfolio risk settings. "
                "Not a JobRuntime worker capability — ApprovalService only. "
                "Must authorize before PortfolioService.patch_portfolio commits."
            ),
            side_effects=(SideEffect.WRITE,),
            provider_kind=CapabilityProviderKind.INTERNAL,
            provider_ref="market_sim.portfolio_risk.loosen",
            input_schema={
                "type": "object",
                "required": ["portfolio_id"],
                "properties": {
                    "portfolio_id": {"type": "string"},
                    "approval_id": {"type": "string"},
                    "settings": {"type": "object"},
                },
            },
            output_schema={"type": "object"},
            required_permissions=("process.execute",),
            metadata={
                "tags": ["market_sim", "portfolio", "risk", "approval"],
                "domains": ["market_sim"],
                "execution_class": "INLINE_SAFE",
                "approval_identity": True,
            },
        )
    )
    _ext(
        cap_id="backup.create",
        name="Create Backup",
        description="Create a durable backup snapshot.",
        side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
        worker_kind="backup",
        properties={"label": {"type": "string"}, "include_corpus": {"type": "boolean"}},
        permissions=("filesystem.write",),
        tags=["backup", "create"],
    )
    _ext(
        cap_id="backup.verify",
        name="Verify Backup",
        description="External backup verification at explicit verification levels.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="backup",
        properties={
            "backup_id": {"type": "string"},
            "level": {"type": "string"},
        },
        permissions=("filesystem.read",),
        tags=["backup", "verify"],
    )
    _ext(
        cap_id="sqlite_ops.query",
        name="Heavy SQLite Query",
        description="Read-only heavy operator SQL with deadline and result bounds.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="sqlite_ops",
        properties={
            "domain": {"type": "string"},
            "sql": {"type": "string"},
            "limit": {"type": "integer"},
            "deadline_seconds": {"type": "number"},
        },
        permissions=("filesystem.read",),
        tags=["sqlite_ops", "query"],
        domains=["database"],
    )
    _ext(
        cap_id="sqlite_ops.scan",
        name="Heavy SQLite Table Scan",
        description="Read-only large table scan / row browse for operator tooling.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="sqlite_ops",
        properties={
            "domain": {"type": "string"},
            "table": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        permissions=("filesystem.read",),
        tags=["sqlite_ops", "scan"],
        domains=["database"],
    )
    _ext(
        cap_id="sqlite_ops.search",
        name="Heavy SQLite Search",
        description="Bounded multi-column search across allowed tables (read-only).",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="sqlite_ops",
        properties={
            "domain": {"type": "string"},
            "table": {"type": "string"},
            "search": {"type": "string"},
            "limit": {"type": "integer"},
        },
        permissions=("filesystem.read",),
        tags=["sqlite_ops", "search"],
        domains=["database"],
    )
    _ext(
        cap_id="sqlite_ops.analytics",
        name="Heavy SQLite Analytics",
        description="Cross-table read analytics within one canonical domain.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="sqlite_ops",
        properties={"domain": {"type": "string"}, "sql": {"type": "string"}},
        permissions=("filesystem.read",),
        tags=["sqlite_ops", "analytics"],
        domains=["database"],
    )
    _ext(
        cap_id="sqlite_ops.export",
        name="SQLite Export",
        description="Stream table/query export to ArtifactStore (CSV/JSONL).",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="sqlite_ops",
        properties={
            "domain": {"type": "string"},
            "sql": {"type": "string"},
            "table": {"type": "string"},
            "format": {"type": "string"},
        },
        permissions=("filesystem.read", "filesystem.write"),
        tags=["sqlite_ops", "export"],
        domains=["database"],
    )
    _ext(
        cap_id="security.audit.deep",
        name="Deep Security Audit",
        description="Deep repository/filesystem/config security audit (external).",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="security",
        properties={"scope": {"type": "string"}},
        permissions=("filesystem.read",),
        tags=["security", "audit"],
        domains=["security"],
    )
    _ext(
        cap_id="security.repo.scan",
        name="Repository Security Scan",
        description="Bounded repository scan excluding HADES/editor; secrets redacted.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="security",
        properties={"root": {"type": "string"}},
        permissions=("filesystem.read",),
        tags=["security", "repo", "scan"],
        domains=["security"],
    )
    _ext(
        cap_id="security.dependencies.audit",
        name="Dependency Security Audit",
        description="Read-only dependency/manifest audit — never install or auto-fix.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="security",
        properties={"ecosystem": {"type": "string"}},
        permissions=("filesystem.read",),
        tags=["security", "dependencies"],
        domains=["security"],
    )
    _ext(
        cap_id="security.integrity.audit",
        name="Integrity Audit",
        description="Large integrity audit consuming domain evidence (not replacing domain owners).",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="security",
        properties={"scope": {"type": "string"}},
        permissions=("filesystem.read",),
        tags=["security", "integrity"],
        domains=["security"],
    )
    _ext(
        cap_id="telemetry.sample",
        name="Telemetry Sample",
        description="Collect one bounded hardware/process telemetry snapshot.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="telemetry",
        properties={},
        permissions=("process.execute",),
        tags=["telemetry", "sample"],
        domains=["observability"],
    )
    _ext(
        cap_id="telemetry.hardware_window",
        name="Hardware Telemetry Window",
        description="Bounded high-frequency hardware sampling window inside telemetry worker.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="telemetry",
        properties={
            "duration_seconds": {"type": "number"},
            "interval_seconds": {"type": "number"},
        },
        permissions=("process.execute",),
        tags=["telemetry", "hardware"],
        domains=["observability"],
    )
    _ext(
        cap_id="diagnostics.collect",
        name="Collect Diagnostics Bundle",
        description="Large redacted diagnostics collection bundled to ArtifactStore.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="telemetry",
        properties={"sections": {"type": "array"}},
        permissions=("process.execute", "filesystem.write"),
        tags=["diagnostics", "collect"],
        domains=["observability"],
    )
    _ext(
        cap_id="diagnostics.process_window",
        name="Process Diagnostics Window",
        description="Bounded diagnostics for LEVIATHAN-owned process IDs only.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="telemetry",
        properties={
            "pid": {"type": "integer"},
            "duration_seconds": {"type": "number"},
        },
        permissions=("process.execute",),
        tags=["diagnostics", "process"],
        domains=["observability"],
    )
    _ext(
        cap_id="agent.advance",
        name="Advance Agent Mission",
        description="Advance one long-running agent mission step.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="agents",
        properties={
            "agent_id": {"type": "string"},
            "mission_id": {"type": "string"},
        },
        permissions=("process.execute",),
        tags=["agent", "advance"],
        domains=["agents"],
    )
    _ext(
        cap_id="agent_signal.deliver",
        name="Deliver Agent Signal",
        description="Deliver one Signal Fabric delivery record (route/handler/ACK lifecycle).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="agent_signals",
        properties={"delivery_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["agent_signals", "signal", "deliver"],
        domains=["agents"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="agent_signal.retry",
        name="Retry Agent Signal Dead Letter",
        description="Manually retry a dead-lettered Signal Fabric delivery (idempotent).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="agent_signals",
        properties={"dead_letter_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["agent_signals", "signal", "retry"],
        domains=["agents"],
    )
    _ext(
        cap_id="agent_signal.housekeeping",
        name="Agent Signal Housekeeping",
        description="Expire due signals and purge retained telemetry per Signal Fabric policy.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="agent_signals",
        properties={},
        permissions=("process.execute",),
        tags=["agent_signals", "signal", "housekeeping"],
        domains=["agents"],
    )
    _ext(
        cap_id="provider.http",
        name="Provider HTTP",
        description="Bounded outbound HTTP via provider_io workers (SSRF-guarded).",
        side_effects=(SideEffect.NETWORK, SideEffect.READ),
        worker_kind="provider_io",
        properties={
            "provider": {"type": "string"},
            "capability": {"type": "string"},
            "payload": {"type": "object"},
            "credential_ref": {"type": "string"},
            "url": {"type": "string"},
            "method": {"type": "string"},
        },
        permissions=("network.outbound",),
        tags=["provider", "http", "external"],
        domains=["provider_io"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="provider.chat.complete",
        name="Provider Chat Complete",
        description="Non-streaming remote/OpenAI-compatible chat completion in provider_io.",
        side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE),
        worker_kind="provider_io",
        required_args=["provider"],
        properties={
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "payload": {"type": "object"},
            "credential_ref": {"type": "string"},
            "endpoint": {"type": "string"},
            "messages": {"type": "array"},
        },
        permissions=("network.outbound", "process.execute"),
        tags=["provider", "chat", "llm"],
        domains=["provider_io"],
        extra_meta={"idempotent": False, "compute_tier_hint": 3},
    )
    _ext(
        cap_id="provider.chat.stream",
        name="Provider Chat Stream",
        description="Streaming remote/OpenAI-compatible chat via provider_io event channel.",
        side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE),
        worker_kind="provider_io",
        required_args=["provider"],
        properties={
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "payload": {"type": "object"},
            "credential_ref": {"type": "string"},
            "streaming": {"type": "boolean"},
        },
        permissions=("network.outbound", "process.execute"),
        tags=["provider", "chat", "stream", "llm"],
        domains=["provider_io"],
        extra_meta={"idempotent": False, "streaming": True},
    )
    _ext(
        cap_id="provider.market.fetch",
        name="Provider Market Fetch",
        description="Fetch market OHLCV via provider_io (Binance/Stooq) — not Control Plane HTTP.",
        side_effects=(SideEffect.NETWORK, SideEffect.WRITE),
        worker_kind="provider_io",
        required_args=["provider"],
        properties={
            "provider": {"type": "string"},
            "provider_id": {"type": "string"},
            "symbol": {"type": "string"},
            "timeframe": {"type": "string"},
            "limit": {"type": "integer"},
            "markets_root": {"type": "string"},
            "payload": {"type": "object"},
        },
        permissions=("network.outbound", "filesystem.write"),
        tags=["provider", "market", "ohlcv"],
        domains=["provider_io", "market_sim"],
    )
    _ext(
        cap_id="provider.market.stream",
        name="Provider Market Stream",
        description=(
            "Long-lived Binance public combined market stream (kline/trade) via market_feed "
            "workers — market data only, never order/trading endpoints."
        ),
        side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE),
        worker_kind="market_feed",
        required_args=["provider"],
        properties={
            "provider": {"type": "string"},
            "provider_id": {"type": "string"},
            "symbols": {"type": "array"},
            "stream_kinds": {"type": "array"},
            "feed_id": {"type": "string"},
            "connection_id": {"type": "string"},
            "max_runtime_seconds": {"type": "number"},
            "gap_recovery_enabled": {"type": "boolean"},
            "payload": {"type": "object"},
        },
        permissions=("network.outbound", "process.execute"),
        tags=["provider", "market", "stream", "websocket"],
        domains=["provider_io", "market_sim"],
        extra_meta={"idempotent": False, "streaming": True},
    )
    _ext(
        cap_id="provider.market.stream.stop",
        name="Provider Market Stream Stop",
        description="Request stop of a long-lived market.stream job (market_feed workers).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="market_feed",
        properties={
            "provider": {"type": "string"},
            "feed_id": {"type": "string"},
            "job_id": {"type": "string"},
            "payload": {"type": "object"},
        },
        permissions=("process.execute",),
        tags=["provider", "market", "stream", "stop"],
        domains=["provider_io", "market_sim"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="provider.hf.list",
        name="Provider HuggingFace List",
        description="List HF dataset repository files via provider_io (not bulk download).",
        side_effects=(SideEffect.NETWORK, SideEffect.READ),
        worker_kind="provider_io",
        properties={
            "provider": {"type": "string"},
            "repository_id": {"type": "string"},
            "revision": {"type": "string"},
            "credential_ref": {"type": "string"},
            "payload": {"type": "object"},
        },
        permissions=("network.outbound",),
        tags=["provider", "huggingface", "list"],
        domains=["provider_io", "datasets"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="provider.alpaca.paper",
        name="Provider Alpaca Paper",
        description="Alpaca paper trading HTTP via provider_io — never Control Plane fallback.",
        side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE),
        worker_kind="provider_io",
        required_args=["provider"],
        properties={
            "provider": {"type": "string"},
            "action": {"type": "string"},
            "payload": {"type": "object"},
            "credential_ref": {"type": "string"},
            "symbol": {"type": "string"},
            "side": {"type": "string"},
            "qty": {"type": "number"},
            "client_order_id": {"type": "string"},
            "broker_order_id": {"type": "string"},
        },
        permissions=("network.outbound", "process.execute"),
        tags=["provider", "alpaca", "paper", "market"],
        domains=["provider_io", "market_sim"],
        extra_meta={"idempotent": False},
    )
    _ext(
        cap_id="model_download.start",
        name="Model Download Start",
        description="Bulk model artifact download in model_download workers (not Control Plane).",
        side_effects=(SideEffect.NETWORK, SideEffect.WRITE),
        worker_kind="model_download",
        required_args=["download_id", "repository_id"],
        properties={
            "download_id": {"type": "string"},
            "source": {"type": "string"},
            "repository_id": {"type": "string"},
            "revision": {"type": "string"},
            "destination": {"type": "string"},
            "filename": {"type": "string"},
            "credential_ref": {"type": "string"},
            "endpoint": {"type": "string"},
        },
        permissions=("network.outbound", "filesystem.write"),
        tags=["model", "download", "huggingface"],
        domains=["model_download", "models"],
        extra_meta={"idempotent": False},
    )
    _ext(
        cap_id="model_import.local",
        name="Local Model Import",
        description=(
            "Large local model file import/verification in model_download workers "
            "(streaming hash/header inspect — never Control Plane read_bytes)."
        ),
        side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
        worker_kind="model_download",
        required_args=["path"],
        properties={
            "path": {"type": "string"},
            "display_name": {"type": "string"},
            "import_id": {"type": "string"},
            "allowed_roots": {"type": "array"},
        },
        permissions=("filesystem.read", "filesystem.write"),
        tags=["model", "import", "local"],
        domains=["model_download", "models"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="model_runtime.load",
        name="Model Runtime Load",
        description=(
            "Start managed local model serving via model_runtime singleton "
            "(ServingSupervisor). FastAPI must not Popen."
        ),
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="model_runtime",
        required_args=["model_id"],
        properties={
            "model_id": {"type": "string"},
            "options": {"type": "object"},
            "confirm_oom": {"type": "boolean"},
        },
        permissions=("process.execute",),
        tags=["model", "runtime", "serving", "load"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": True, "compute_tier_hint": 3},
    )
    _ext(
        cap_id="model_runtime.unload",
        name="Model Runtime Unload",
        description="Drain and stop a managed serving worker (generation-fenced).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="model_runtime",
        required_args=["model_id"],
        properties={
            "model_id": {"type": "string"},
            "serving_generation": {"type": "integer"},
            "force": {"type": "boolean"},
        },
        permissions=("process.execute",),
        tags=["model", "runtime", "serving", "unload"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="model_runtime.reconcile",
        name="Model Runtime Reconcile",
        description="PID-safe reconcile of managed serving children (model_runtime owned).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="model_runtime",
        properties={},
        permissions=("process.execute",),
        tags=["model", "runtime", "reconcile"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="model_runtime.benchmark",
        name="Model Runtime Benchmark",
        description="External measured latency/throughput probe — raw metrics only.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="model_runtime",
        required_args=["model_id"],
        properties={
            "model_id": {"type": "string"},
            "warmup": {"type": "integer"},
            "iterations": {"type": "integer"},
            "prompt": {"type": "string"},
            "max_tokens": {"type": "integer"},
        },
        permissions=("process.execute",),
        tags=["model", "runtime", "benchmark"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": False, "compute_tier_hint": 3},
    )
    _ext(
        cap_id="model_runtime.probe",
        name="Model Runtime Capability Probe",
        description="Inference-based capability probes on model_runtime (not FastAPI).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="model_runtime",
        required_args=["model_id"],
        properties={
            "model_id": {"type": "string"},
            "capabilities": {"type": "array"},
            "timeout_seconds": {"type": "number"},
        },
        permissions=("process.execute",),
        tags=["model", "runtime", "probe"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": True, "compute_tier_hint": 3},
    )
    _ext(
        cap_id="model_runtime.inference_test",
        name="Model Runtime Inference Test",
        description="Direct API inference-test executed outside FastAPI.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="model_runtime",
        required_args=["model_id"],
        properties={
            "model_id": {"type": "string"},
            "prompt": {"type": "string"},
            "max_tokens": {"type": "integer"},
            "stream": {"type": "boolean"},
        },
        permissions=("process.execute",),
        tags=["model", "runtime", "inference_test"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": False, "compute_tier_hint": 3},
    )
    _ext(
        cap_id="mcp.call",
        name="MCP Tool Call",
        description="Long MCP tools/call execution in mcp_execution workers.",
        side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE),
        worker_kind="mcp_execution",
        required_args=["server_id", "tool_name"],
        properties={
            "server_id": {"type": "string"},
            "tool_name": {"type": "string"},
            "arguments": {"type": "object"},
            "capability_id": {"type": "string"},
            "timeout_seconds": {"type": "number"},
        },
        permissions=("process.execute", "network.outbound"),
        tags=["mcp", "tool", "execution"],
        domains=["mcp"],
        extra_meta={"idempotent": False},
    )
    _ext(
        cap_id="mcp.connect",
        name="MCP Connect",
        description="Live MCP connect/handshake (stdio spawn or HTTP) in mcp_execution workers.",
        side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE),
        worker_kind="mcp_execution",
        required_args=["server_id"],
        properties={
            "server_id": {"type": "string"},
            "expand_tools": {"type": "boolean"},
        },
        permissions=("process.execute", "network.outbound"),
        tags=["mcp", "connect"],
        domains=["mcp"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="mcp.list_tools",
        name="MCP List Tools",
        description="Live MCP tools/list requiring transport — mcp_execution owned.",
        side_effects=(SideEffect.NETWORK, SideEffect.EXECUTE),
        worker_kind="mcp_execution",
        required_args=["server_id"],
        properties={
            "server_id": {"type": "string"},
            "force_refresh": {"type": "boolean"},
        },
        permissions=("process.execute", "network.outbound"),
        tags=["mcp", "list"],
        domains=["mcp"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="model.serving.start",
        name="Model Serving Start",
        description="Start a LEVIATHAN-managed model server (llama.cpp/vLLM) via model_runtime.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="model_runtime",
        required_args=["model_id", "command"],
        properties={
            "model_id": {"type": "string"},
            "provider_id": {"type": "string"},
            "backend_kind": {"type": "string"},
            "command": {"type": "array"},
            "endpoint": {"type": "string"},
            "revision_id": {"type": "string"},
            "env": {"type": "object"},
            "ready_timeout_seconds": {"type": "number"},
            "managed_by_leviathan": {"type": "boolean"},
            "reservation_id": {"type": "string"},
        },
        permissions=("process.execute",),
        tags=["model", "serving", "start"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": False},
    )
    _ext(
        cap_id="model.serving.stop",
        name="Model Serving Stop",
        description="Stop a LEVIATHAN-managed model server via model_runtime (never operator-owned).",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="model_runtime",
        properties={
            "worker_id": {"type": "string"},
            "model_id": {"type": "string"},
            "launch_generation": {"type": "integer"},
            "drain": {"type": "boolean"},
            "managed_by_leviathan": {"type": "boolean"},
        },
        permissions=("process.execute",),
        tags=["model", "serving", "stop"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="model.serving.reconcile",
        name="Model Serving Reconcile",
        description="Reconcile managed serving process identity via model_runtime.",
        side_effects=(SideEffect.READ, SideEffect.EXECUTE),
        worker_kind="model_runtime",
        properties={},
        permissions=("process.execute",),
        tags=["model", "serving", "reconcile"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": True},
    )
    _ext(
        cap_id="model_runtime.start",
        name="Model Runtime Start (alias)",
        description="Alias for managed serving start — routes to model_runtime.load/serving.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="model_runtime",
        required_args=["model_id"],
        properties={
            "model_id": {"type": "string"},
            "command": {"type": "array"},
            "endpoint": {"type": "string"},
            "managed_by_leviathan": {"type": "boolean"},
        },
        permissions=("process.execute",),
        tags=["model", "runtime", "start"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": False},
    )
    _ext(
        cap_id="model_runtime.stop",
        name="Model Runtime Stop (alias)",
        description="Alias for managed serving stop — never kills operator-owned servers.",
        side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
        worker_kind="model_runtime",
        properties={
            "model_id": {"type": "string"},
            "worker_id": {"type": "string"},
            "launch_generation": {"type": "integer"},
            "managed_by_leviathan": {"type": "boolean"},
        },
        permissions=("process.execute",),
        tags=["model", "runtime", "stop"],
        domains=["model_runtime", "models"],
        extra_meta={"idempotent": True},
    )
