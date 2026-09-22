"""Capability broker — search/shortlist without keyword-NLU gating."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CapabilityShortlist:
    query: str
    capability_ids: tuple[str, ...]
    inspected: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "capability_ids": list(self.capability_ids),
            "inspected": self.inspected,
            "notes": list(self.notes),
            "truth": {
                "availability_independent_of_keyword_nlu": True,
                "discoverable_is_not_authorized": True,
                "no_full_schema_dump": True,
            },
        }


class CapabilityBroker:
    """Thin cognition-facing facade over CapabilityCatalog.search/inspect."""

    def __init__(self, catalog: Any | None = None) -> None:
        self.catalog = catalog

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        domain: str | None = None,
        available_only: bool = False,
    ) -> CapabilityShortlist:
        if self.catalog is None:
            return CapabilityShortlist(
                query=query,
                capability_ids=(),
                notes=("capability catalog unavailable",),
            )
        # Domain is a soft bias, never a hard gate that removes tools.
        q = query.strip()
        if domain and domain not in q.lower():
            q = f"{domain} {q}".strip()
        found = list(self.catalog.search(q, limit=limit) or [])
        if available_only:
            found = [c for c in found if getattr(c, "available", True)]
        ids = tuple(str(getattr(c, "id", "")) for c in found if getattr(c, "id", None))
        notes = (
            "Capability availability is independent of initial intent classification",
            "Authorization still requires ExecutionGateway + policy/approvals",
        )
        return CapabilityShortlist(query=query, capability_ids=ids, notes=notes)

    def inspect(self, capability_ids: list[str] | tuple[str, ...]) -> CapabilityShortlist:
        inspected: dict[str, dict[str, Any]] = {}
        if self.catalog is None:
            return CapabilityShortlist(query="", capability_ids=tuple(capability_ids), inspected={})
        for cid in capability_ids:
            data = self.catalog.inspect(cid)
            if data:
                inspected[cid] = data
        return CapabilityShortlist(
            query="",
            capability_ids=tuple(capability_ids),
            inspected=inspected,
            notes=("schemas inspected only for shortlisted IDs",),
        )

    def shortlist_for_task(
        self,
        *,
        goal: str,
        domain: str | None = None,
        limit: int = 6,
    ) -> CapabilityShortlist:
        short = self.search(goal, limit=limit, domain=domain)
        # Inspect only top few — avoid prompt explosion.
        return self.inspect(short.capability_ids[:3])
