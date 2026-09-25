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
            id="coding.advance",
            name="Advance Coding Session",
            description=(
                "Advance one Coding Cognition round for a session. "
                "Owned by JobRuntime substrate; executed by CodingWorker (external-style)."
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
            metadata={"tags": ["browser"], "domains": ["browser"], "worker_kind": "browser"},
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
            metadata={"tags": ["browser"], "domains": ["browser"], "worker_kind": "browser"},
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
            metadata={"tags": ["browser"], "domains": ["browser"], "worker_kind": "browser"},
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
                "tags": ["media", "retrieval", "cross-modal"],
                "domains": ["media", "knowledge"],
                "aliases": ["cross modal search", "find scene"],
                "cacheable": True,
                "worker_kind": "media",
            },
        )
    )
    # Wave 7 — voice capabilities (fixture RealtimeVoiceService via ExecutionGateway).
    catalog.register(
        CapabilityDefinition(
            id="voice.start_session",
            name="Voice Start Session",
            description="Start a realtime voice session bound to shared conversation/run context.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.VOICE,
            provider_ref="START_SESSION",
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
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="voice.transcribe",
            name="Voice Transcribe",
            description="Streaming ASR with partials + VAD (fixture backend).",
            side_effects=(SideEffect.READ, SideEffect.EXECUTE),
            provider_kind=CapabilityProviderKind.VOICE,
            provider_ref="STREAM_ASR",
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
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="voice.synthesize",
            name="Voice Synthesize",
            description="Streaming TTS with persona params (fixture backend).",
            side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
            provider_kind=CapabilityProviderKind.VOICE,
            provider_ref="STREAM_TTS",
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
            },
        )
    )
    catalog.register(
        CapabilityDefinition(
            id="voice.barge_in",
            name="Voice Barge-In",
            description="Cancel in-flight ASR/LLM/TTS generation on user interruption.",
            side_effects=(SideEffect.EXECUTE,),
            provider_kind=CapabilityProviderKind.VOICE,
            provider_ref="BARGE_IN",
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
            },
        )
    )
    _register_fabric_worker_capabilities(catalog)
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
        name="Retrieve Research Evidence",
        description="Run a retrieval wave for an active research project.",
        side_effects=(SideEffect.READ, SideEffect.NETWORK),
        worker_kind="research",
        required_args=["project_id"],
        properties={"project_id": {"type": "string"}, "query": {"type": "string"}},
        permissions=("knowledge.read",),
        tags=["research", "retrieve"],
    )
    _ext(
        cap_id="research.synthesize",
        name="Synthesize Research Findings",
        description="Synthesize claims/report from gathered evidence (reasoning-tier work).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="research",
        required_args=["project_id"],
        properties={"project_id": {"type": "string"}},
        permissions=("process.execute",),
        tags=["research", "synthesize"],
        extra_meta={"requires_reasoning": True, "compute_tier_hint": 3},
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
        cap_id="maintenance.reconcile",
        name="Maintenance Reconcile",
        description="Lease recovery, stale cleanup, and reconciliation sweep.",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="maintenance",
        properties={"scope": {"type": "string"}},
        permissions=("process.execute",),
        tags=["maintenance", "reconcile"],
        domains=["jobs"],
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
        cap_id="training.control",
        name="Training Control",
        description="Own trainer subprocess lifecycle (start/stop/status).",
        side_effects=(SideEffect.EXECUTE,),
        worker_kind="training_control",
        properties={
            "job_id": {"type": "string"},
            "action": {"type": "string"},
        },
        permissions=("process.execute",),
        tags=["training", "control"],
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
        cap_id="backup.create",
        name="Create Backup",
        description="Create a durable backup snapshot.",
        side_effects=(SideEffect.WRITE, SideEffect.EXECUTE),
        worker_kind="backup",
        properties={"label": {"type": "string"}},
        permissions=("filesystem.write",),
        tags=["backup", "create"],
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
            "allow_private_hosts": {"type": "boolean"},
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
            "allow_private_hosts": {"type": "boolean"},
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
