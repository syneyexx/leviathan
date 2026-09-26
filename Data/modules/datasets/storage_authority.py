"""Storage authority classification — canonical DB vs data plane vs scratch."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any


class StorageClass(str, Enum):
    CANONICAL_TRANSACTIONAL = "CANONICAL_TRANSACTIONAL"
    IMMUTABLE_DATA_PLANE = "IMMUTABLE_DATA_PLANE"
    INDEX = "INDEX"
    CACHE = "CACHE"
    EPHEMERAL_SCRATCH = "EPHEMERAL_SCRATCH"


FORBIDDEN_COMPETING_DB_NAMES = frozenset(
    {
        "knowledge.db",
        "trading.db",
        "simulation.db",
        "portfolio.db",
        "datasets.db",
        "control.db",
        "agents.db",
        "semantic.db",
        "native.db",
        "learning.db",
        "research.db",
    }
)


STORAGE_AUTHORITY_TRUTH = {
    "canonicalTransactionalAuthority": "central_sqlite",
    "immutableDataPlaneAllowed": True,
    "indexesAreRebuildable": True,
    "cachesAreDisposable": True,
    "ephemeralScratchAllowed": True,
    "competingDomainDatabasesForbidden": True,
    "scratchIsNotBusinessAuthority": True,
}


def classify_path(
    path: Path,
    *,
    canonical_db: Path | None = None,
    corpus_root: Path | None = None,
    scratch_root: Path | None = None,
) -> StorageClass:
    resolved = Path(path).resolve()
    if canonical_db is not None and resolved == Path(canonical_db).resolve():
        return StorageClass.CANONICAL_TRANSACTIONAL
    if scratch_root is not None:
        try:
            resolved.relative_to(Path(scratch_root).resolve())
            return StorageClass.EPHEMERAL_SCRATCH
        except ValueError:
            pass
    name = resolved.name.lower()
    if name.endswith(".db") and name in FORBIDDEN_COMPETING_DB_NAMES:
        # Detected as competing authority candidate — caller must refuse.
        return StorageClass.CANONICAL_TRANSACTIONAL
    if corpus_root is not None:
        try:
            resolved.relative_to(Path(corpus_root).resolve())
            if "index" in resolved.parts or resolved.suffix in {".faiss", ".ann"}:
                return StorageClass.INDEX
            if "cache" in resolved.parts:
                return StorageClass.CACHE
            return StorageClass.IMMUTABLE_DATA_PLANE
        except ValueError:
            pass
    return StorageClass.IMMUTABLE_DATA_PLANE


def assert_no_competing_domain_db(path: Path) -> None:
    name = Path(path).name.lower()
    if name in FORBIDDEN_COMPETING_DB_NAMES:
        raise ValueError(
            f"Forbidden competing domain database authority: {name}. "
            "Use the central transactional metadata store or governed ephemeral scratch."
        )


def storage_authority_public_dict() -> dict[str, Any]:
    return {
        "storageClasses": [c.value for c in StorageClass],
        "forbiddenCompetingDatabases": sorted(FORBIDDEN_COMPETING_DB_NAMES),
        "truth": dict(STORAGE_AUTHORITY_TRUTH),
    }
