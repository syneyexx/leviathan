"""Canonical evidence package for answer generation and critic coverage.

One bounded package per run: retrieved passages, attachments, and tool
observations share stable ref identities across critic validation, coverage,
and UI metadata. Draft text is never evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .contracts import ContextItem
from .evidence_coverage import EvidenceKind, quote_in_source, normalize_text

EvidenceRole = Literal[
    "source_material",
    "tool_observation",
    "memory",
    "attachment",
    "user_assertion",
    "derived_memory",
    "model_interpretation",
    "rejected",
    "truncated",
    "unread",
]


@dataclass(slots=True)
class EvidenceEntry:
    ref_id: str
    role: EvidenceRole
    text: str
    provenance: str
    status: str = "available"  # available | rejected | truncated | unread | failed
    call_id: str | None = None
    item_id: str | None = None
    observes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def coverage_kind(self) -> EvidenceKind:
        if self.status in {"rejected", "unread", "failed"}:
            return "unknown"
        if self.role in {"source_material", "attachment", "memory"}:
            return "source_material"
        if self.role == "tool_observation":
            return "tool_observation"
        if self.role in {"user_assertion", "derived_memory"}:
            return "model_interpretation"
        if self.role == "model_interpretation":
            return "model_interpretation"
        return "unknown"


@dataclass(slots=True)
class EvidencePackage:
    entries: list[EvidenceEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, entry: EvidenceEntry) -> None:
        if any(item.ref_id == entry.ref_id for item in self.entries):
            return
        self.entries.append(entry)

    def known_refs(self, *, usable_only: bool = True) -> set[str]:
        refs: set[str] = set()
        for item in self.entries:
            if usable_only and item.status not in {"available", "truncated"}:
                continue
            if item.role == "model_interpretation":
                continue
            refs.add(item.ref_id)
        return refs

    def evidence_texts(self, *, usable_only: bool = True) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in self.entries:
            if usable_only and item.status not in {"available", "truncated"}:
                continue
            if not item.text.strip():
                continue
            out[item.ref_id] = item.text
        return out

    def evidence_kinds(self) -> dict[str, EvidenceKind]:
        return {item.ref_id: item.coverage_kind for item in self.entries}

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [item.to_dict() for item in self.entries],
            "notes": list(self.notes),
            "known_refs": sorted(self.known_refs()),
        }


def _ref_for_context_item(item: ContextItem) -> str:
    prov = str(item.provenance or "").strip()
    item_id = str(item.item_id or "").strip()
    if prov.startswith(("attachment:", "memory:", "knowledge:", "tool:", "step:", "mention:")):
        return prov
    if item_id:
        return f"ctx:{item_id}"
    fallback = prov or item.content[:64]
    digest = hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:16]
    return f"ctx:{digest}"


def _role_for_context_item(item: ContextItem) -> EvidenceRole:
    kind = str(item.kind or "")
    prov = str(item.provenance or "")
    if kind == "user_constraint":
        return "user_assertion"
    if kind == "plan" and "working_state" in prov:
        return "derived_memory"
    if kind == "memory" or prov.startswith("memory:"):
        return "memory"
    if prov.startswith("attachment:") or (kind == "knowledge" and "BIJLAGE" in (item.content or "")[:40]):
        return "attachment"
    if kind in {"knowledge", "evidence", "workspace"}:
        return "source_material"
    if kind == "tool_result":
        return "tool_observation"
    return "source_material"


def build_evidence_package(
    *,
    context_items: list[ContextItem] | None = None,
    tool_log: list[dict[str, Any]] | None = None,
    attachment_records: list[dict[str, Any]] | None = None,
    max_chars_per_entry: int = 12_000,
    max_entries: int = 48,
) -> EvidencePackage:
    """Build one canonical evidence package for this run."""
    package = EvidencePackage()

    for record in attachment_records or []:
        artifact_id = str(record.get("artifact_id") or record.get("id") or "").strip()
        if not artifact_id:
            continue
        status = str(record.get("extract_status") or "ready")
        text = str(record.get("text") or "").strip()
        name = str(record.get("filename") or record.get("name") or artifact_id)
        if status in {"skipped", "error"} or not text:
            package.add(
                EvidenceEntry(
                    ref_id=f"attachment:{artifact_id}",
                    role="attachment",
                    text="",
                    provenance=f"attachment:{artifact_id}",
                    status="unread" if status == "skipped" else "failed",
                    item_id=f"attachment-{artifact_id}",
                    metadata={"filename": name, "extract_error": record.get("extract_error")},
                )
            )
            continue
        clipped = text[:max_chars_per_entry]
        package.add(
            EvidenceEntry(
                ref_id=f"attachment:{artifact_id}",
                role="attachment",
                text=clipped,
                provenance=f"attachment:{artifact_id}",
                status="truncated" if len(text) > max_chars_per_entry else "available",
                item_id=f"attachment-{artifact_id}",
                metadata={"filename": name, "used_in_context": bool(record.get("used_in_context"))},
            )
        )
        if len(package.entries) >= max_entries:
            package.notes.append("evidence_entry_cap_reached")
            return package

    for item in context_items or []:
        if not item:
            continue
        # Skip attachment items when attachment_records already carry them.
        if str(item.provenance or "").startswith("attachment:") and attachment_records:
            continue
        role = _role_for_context_item(item)
        text = str(item.content or "")
        clipped = text[:max_chars_per_entry]
        package.add(
            EvidenceEntry(
                ref_id=_ref_for_context_item(item),
                role=role,
                text=clipped,
                provenance=str(item.provenance or item.item_id or ""),
                status="truncated" if len(text) > max_chars_per_entry else "available",
                item_id=str(item.item_id or "") or None,
                metadata={"kind": item.kind, "trusted": bool(item.trusted)},
            )
        )
        if len(package.entries) >= max_entries:
            package.notes.append("evidence_entry_cap_reached")
            return package

    for row in tool_log or []:
        status = str(row.get("status") or "").lower()
        call_id = str(row.get("call_id") or row.get("id") or "").strip()
        if not call_id:
            continue
        ref = f"tool:{call_id}"
        output = str(row.get("output") or row.get("stdout") or row.get("result") or "")
        if status not in {"completed", "succeeded", "success", "ok"}:
            package.add(
                EvidenceEntry(
                    ref_id=ref,
                    role="tool_observation",
                    text=output[:max_chars_per_entry],
                    provenance=ref,
                    status="failed",
                    call_id=call_id,
                    metadata={
                        "plugin_id": row.get("plugin_id"),
                        "tool_name": row.get("tool_name"),
                        "status": status,
                    },
                )
            )
            continue
        package.add(
            EvidenceEntry(
                ref_id=ref,
                role="tool_observation",
                text=output[:max_chars_per_entry],
                provenance=ref,
                status="truncated" if len(output) > max_chars_per_entry else "available",
                call_id=call_id,
                observes=[f"tool_call:{call_id}"],
                metadata={
                    "plugin_id": row.get("plugin_id"),
                    "tool_name": row.get("tool_name"),
                    "status": status,
                },
            )
        )
        # Alias step: refs used by older critic prompts for the same observation.
        package.add(
            EvidenceEntry(
                ref_id=f"step:{call_id}",
                role="tool_observation",
                text=output[:max_chars_per_entry],
                provenance=ref,
                status="available",
                call_id=call_id,
                metadata={"alias_of": ref},
            )
        )
        if len(package.entries) >= max_entries:
            package.notes.append("evidence_entry_cap_reached")
            break

    return package


def bind_claims_to_evidence(
    claims: list[str],
    package: EvidencePackage,
    *,
    critic_refs: list[str] | None = None,
    per_claim_refs: list[list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Attach evidence per claim. Global critic refs do not auto-prove every claim."""
    texts = package.evidence_texts()
    known = package.known_refs()
    usable_critic = [ref for ref in (critic_refs or []) if ref in known]
    bound: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        claim_text = str(claim or "").strip()
        if not claim_text:
            continue
        explicit = None
        if per_claim_refs and index < len(per_claim_refs):
            explicit = [ref for ref in per_claim_refs[index] if ref in known]
        matched: list[str] = []
        if explicit is not None:
            matched = list(explicit)
        else:
            # Prefer passage/tool content that actually supports this claim.
            for ref, text in texts.items():
                kind = package.evidence_kinds().get(ref, "unknown")
                if kind in {"draft_under_review", "model_interpretation"}:
                    continue
                if not text:
                    continue
                if len(claim_text) > 40 and quote_in_source(claim_text[:200], text):
                    matched.append(ref)
                    continue
                claim_tokens = set(normalize_text(claim_text).split())
                src_tokens = set(normalize_text(text).split())
                if len(claim_tokens & src_tokens) >= 4:
                    matched.append(ref)
            # If nothing matched, do NOT fall back to all critic refs — that would
            # let an unrelated tool success validate every claim.
            if not matched and len(usable_critic) == 1:
                # Single critic ref may be intended for a single-claim answer.
                if len(claims) == 1:
                    matched = list(usable_critic)
        is_tool = bool(matched) and all(
            package.evidence_kinds().get(ref) == "tool_observation" for ref in matched
        )
        bound.append(
            {
                "text": claim_text,
                "evidence_refs": matched[:6],
                "is_tool_observation": is_tool and bool(matched),
                "claim_id": None,
            }
        )
    return bound


def evidence_steps_for_critic(package: EvidencePackage) -> list[dict[str, Any]]:
    """Step outputs for verification prompts — never includes draft text."""
    steps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in package.entries:
        if item.status not in {"available", "truncated"}:
            continue
        if item.role not in {"source_material", "attachment", "memory", "tool_observation"}:
            continue
        # Prefer primary tool: refs over step: aliases.
        if item.ref_id.startswith("step:") and item.metadata.get("alias_of"):
            continue
        key = item.call_id or item.ref_id
        if key in seen:
            continue
        seen.add(key)
        steps.append(
            {
                "title": item.provenance or item.ref_id,
                "agent_id": "tool" if item.role == "tool_observation" else "retrieval",
                "output": item.text[:12_000],
                "step_id": item.call_id or item.ref_id,
                "provenance": item.provenance or item.ref_id,
                "evidence_role": (
                    "tool_observation" if item.role == "tool_observation" else "source_material"
                ),
            }
        )
    return steps
