"""Builtin function catalog registration for LEVIATHAN."""

from __future__ import annotations

from .registry import FunctionRegistry
from .types import FunctionDefinition, LifecycleMode, SideEffect


def register_builtin_functions(registry: FunctionRegistry) -> FunctionRegistry:
    registry.register(
        FunctionDefinition(
            id="text_file_read",
            name="Text File Read",
            version="1.0.0",
            description="Read a local UTF-8 text file with a size bound.",
            entrypoint="Data.functions.text_file_read:run",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "size_bytes": {"type": "integer"},
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
    return registry


def build_default_registry() -> FunctionRegistry:
    return register_builtin_functions(FunctionRegistry())
