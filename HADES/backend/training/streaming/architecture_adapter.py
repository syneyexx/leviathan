"""Architecture adapter contract for ATME layer streaming."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass
class ArchitectureLayout:
    family: str
    embedding_module_names: list[str] = field(default_factory=list)
    layer_module_names: list[str] = field(default_factory=list)
    final_norm_module_names: list[str] = field(default_factory=list)
    lm_head_module_names: list[str] = field(default_factory=list)
    tied_parameter_pairs: list[tuple[str, str]] = field(default_factory=list)
    lora_target_module_names: list[str] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)
    persistent_modules: list[str] = field(default_factory=list)


class ArchitectureAdapter(Protocol):
    family: str

    def matches(self, model: Any) -> bool:
        ...

    def inspect(self, model: Any) -> ArchitectureLayout:
        ...

    def iter_transformer_blocks(self, model: Any) -> Sequence[Any]:
        ...


def resolve_adapter(model: Any) -> ArchitectureAdapter:
    from training.streaming.llama_like import LlamaLikeAdapter

    adapter = LlamaLikeAdapter()
    if adapter.matches(model):
        return adapter
    raise ValueError("UNSUPPORTED_ARCHITECTURE: model family is not on the ATME streaming allowlist")
