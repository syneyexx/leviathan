"""Context Engine — sole model prompt/context compiler (U061)."""

from .builder import ContextBuilder
from .compaction import CompactionResult, compact_conversation
from .multimodal import (
    MultimodalMessage,
    MultimodalPart,
    MultimodalSession,
    MultimodalSessionRegistry,
    PartKind,
    new_sync_id,
)
from .snapshots import ContextSnapshot, snapshot_context_pack
from .types import (
    CONTEXT_LAYERS,
    BudgetLedger,
    BudgetLedgerEntry,
    ContextPack,
    ContextSection,
    estimate_tokens,
)

__all__ = [
    "CONTEXT_LAYERS",
    "BudgetLedger",
    "BudgetLedgerEntry",
    "CompactionResult",
    "ContextBuilder",
    "ContextPack",
    "ContextSection",
    "ContextSnapshot",
    "MultimodalMessage",
    "MultimodalPart",
    "MultimodalSession",
    "MultimodalSessionRegistry",
    "PartKind",
    "compact_conversation",
    "estimate_tokens",
    "new_sync_id",
    "snapshot_context_pack",
]
