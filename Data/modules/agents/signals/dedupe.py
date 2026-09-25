"""Durable idempotency / dedupe for Signal Fabric actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import SignalStore


class SignalDedupe:
    def __init__(self, store: SignalStore) -> None:
        self.store = store

    def check_or_register(self, key: str, signal_id: str, *, scope: str = "signal") -> str | None:
        """Return existing signal_id if duplicate; otherwise register and return None."""
        if not key:
            return None
        existing = self.store.dedupe_lookup(key)
        if existing:
            return existing
        inserted = self.store.dedupe_register(key, signal_id, scope=scope)
        if not inserted:
            return self.store.dedupe_lookup(key)
        return None

    @staticmethod
    def action_key(*, mission_id: str | None, action: str, node_id: str | None = None) -> str:
        parts = [p for p in (mission_id or "none", node_id or "none", action) if p]
        return ":".join(parts)
