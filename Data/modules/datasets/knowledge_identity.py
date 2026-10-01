"""Canonical Dataset ↔ Knowledge ↔ Research source/scope identity contract.

Contract (I-005 / P0-001)
-------------------------
Primary Knowledge ``source`` written by dataset indexing:

    dataset:<dataset_id>:<version_id>

Compatible broader Research scope (exact filter, never a wildcard):

    dataset:<dataset_id>

Forbidden ambiguous forms for new writes:

    dataset:dataset
    dataset          (bare)

Legacy forms may exist in older Knowledge rows. Migration remaps them using
``trust_metadata.datasetId`` / ``versionId``. Research connect never relies on
bare ``dataset`` to find learned evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LEGACY_AMBIGUOUS_SOURCE = "dataset:dataset"
LEGACY_BARE_SCOPE = "dataset"


@dataclass(frozen=True)
class DatasetKnowledgeIdentity:
    dataset_id: str
    version_id: str | None = None

    @property
    def canonical_source(self) -> str:
        if not self.dataset_id:
            raise ValueError("dataset_id is required for Knowledge source identity")
        if self.version_id:
            return f"dataset:{self.dataset_id}:{self.version_id}"
        return f"dataset:{self.dataset_id}"

    @property
    def dataset_source(self) -> str:
        if not self.dataset_id:
            raise ValueError("dataset_id is required")
        return f"dataset:{self.dataset_id}"

    def research_scopes(self) -> list[str]:
        """Ordered scopes for Research local retrieval (most specific first)."""
        scopes: list[str] = []
        if self.version_id:
            scopes.append(self.canonical_source)
        ds = self.dataset_source
        if ds not in scopes:
            scopes.append(ds)
        return scopes

    def public_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "versionId": self.version_id,
            "canonicalSource": self.canonical_source,
            "datasetSource": self.dataset_source,
            "researchScopes": self.research_scopes(),
            "truth": {
                "canonical_form": "dataset:<dataset_id>:<version_id>",
                "legacy_dataset_dataset_forbidden_for_new_writes": True,
                "bare_dataset_scope_not_used_for_retrieval": True,
            },
        }


def knowledge_source_for_version(dataset_id: str, version_id: str) -> str:
    return DatasetKnowledgeIdentity(dataset_id, version_id).canonical_source


def knowledge_source_for_dataset(dataset_id: str) -> str:
    return DatasetKnowledgeIdentity(dataset_id).dataset_source


def research_scopes_for_dataset(
    dataset_id: str, *, version_id: str | None = None
) -> list[str]:
    return DatasetKnowledgeIdentity(dataset_id, version_id).research_scopes()


def parse_dataset_knowledge_source(source: str | None) -> DatasetKnowledgeIdentity | None:
    """Parse ``dataset:<id>`` or ``dataset:<id>:<version>``; reject ambiguous forms."""
    raw = (source or "").strip()
    if not raw.startswith("dataset:"):
        return None
    rest = raw[len("dataset:") :]
    if not rest or rest == "dataset":
        # ``dataset:dataset`` and empty rejected as ambiguous
        return None
    parts = rest.split(":")
    if len(parts) == 1:
        return DatasetKnowledgeIdentity(parts[0], None)
    if len(parts) == 2:
        return DatasetKnowledgeIdentity(parts[0], parts[1])
    # Extra colons — treat last segment as version, join middle into id only if needed.
    # Canonical ids do not contain ':'; reject over-qualified forms.
    return None


def is_legacy_ambiguous_source(source: str | None) -> bool:
    raw = (source or "").strip()
    return raw in {LEGACY_AMBIGUOUS_SOURCE, LEGACY_BARE_SCOPE}


def resolve_index_scope(
    *,
    dataset_id: str,
    version_id: str,
    requested_scope: str | None = None,
) -> str:
    """Resolve the Knowledge source / index knowledge_scope for a new index write.

    Explicit caller scopes that already match the canonical contract are honored.
    Opaque legacy defaults (``dataset``, ``dataset:dataset``) are replaced.
    """
    canonical = knowledge_source_for_version(dataset_id, version_id)
    req = (requested_scope or "").strip()
    if not req or req in {LEGACY_BARE_SCOPE, LEGACY_AMBIGUOUS_SOURCE, "dataset:dataset"}:
        return canonical
    # Allow exact canonical / dataset-level forms
    parsed = parse_dataset_knowledge_source(req)
    if parsed is not None and parsed.dataset_id == dataset_id:
        if parsed.version_id and parsed.version_id != version_id:
            # Caller asked for a different version scope — still write canonical for
            # the version actually being indexed.
            return canonical
        return parsed.canonical_source if parsed.version_id else canonical
    # Non-dataset scopes (rare operator override) — still prefer canonical identity
    # so Research can retrieve. Preserve override only if it already starts with
    # dataset:<this_id>
    if req.startswith(f"dataset:{dataset_id}"):
        return req
    return canonical
