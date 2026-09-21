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
            description="Read a local text file.",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.FUNCTION,
            provider_ref="text_file_read",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer"},
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
        )
    )
    return catalog
