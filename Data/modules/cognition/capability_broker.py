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
        # Inspect top hits for semantic shortlist (schemas only for shortlisted IDs).
        inspected: dict[str, dict[str, Any]] = {}
        for cap in found[: min(3, len(found))]:
            cid = str(getattr(cap, "id", "") or "")
            if not cid:
                continue
            data = self.catalog.inspect(cid)
            if data:
                # Prefer normalized metadata surface for shortlist consumers.
                inspected[cid] = {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "description": data.get("description"),
                    "provider_kind": data.get("provider_kind"),
                    "side_effects": data.get("side_effects"),
                    "available": data.get("available"),
                    "metadata": data.get("metadata"),
                    "schema_hash": data.get("schema_hash"),
                }
        notes = (
            "Capability availability is independent of initial intent classification",
            "Authorization still requires ExecutionGateway + policy/approvals",
            "Semantic shortlist uses metadata tags/aliases/domains — not keyword-NLU gating",
        )
        return CapabilityShortlist(
            query=query,
            capability_ids=ids,
            inspected=inspected,
            notes=notes,
        )

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
        skill_store: Any | None = None,
    ) -> CapabilityShortlist:
        short = self.search(goal, limit=limit, domain=domain)
        # Inspect only top few — avoid prompt explosion.
        inspected = self.inspect(short.capability_ids[:3])
        notes = list(inspected.notes)
        inspected_map = dict(inspected.inspected)
        store = skill_store if skill_store is not None else getattr(self, "_skill_store", None)
        # Bounded skill metadata — never inject instruction bodies into prompts.
        if store is not None and goal.strip():
            try:
                skills = store.search_skills(
                    query=goal.strip(),
                    enabled_only=True,
                    include_catalog=False,
                    limit=min(5, limit),
                )
                for skill in skills:
                    sid = f"skill:{skill.get('skill_id')}"
                    inspected_map[sid] = {
                        "id": sid,
                        "name": skill.get("name"),
                        "description": skill.get("description"),
                        "provider_kind": "skill",
                        "available": bool(skill.get("enabled")),
                        "metadata": {
                            "skill_id": skill.get("skill_id"),
                            "module_id": skill.get("module_id"),
                            "on_demand_instructions": True,
                            "required_capabilities": skill.get("required_capabilities") or [],
                        },
                    }
                if skills:
                    notes.append(
                        f"Matched {len(skills)} installed skill(s); instructions load on demand only"
                    )
            except Exception:  # noqa: BLE001
                notes.append("skill search unavailable")
        return CapabilityShortlist(
            query=inspected.query,
            capability_ids=inspected.capability_ids,
            inspected=inspected_map,
            notes=tuple(notes),
        )
