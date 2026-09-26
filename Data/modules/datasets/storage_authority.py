"""Storage authority classification — three canonical DBs vs data plane vs scratch."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class StorageClass(str, Enum):
    CANONICAL_TRANSACTIONAL = "CANONICAL_TRANSACTIONAL"
    IMMUTABLE_DATA_PLANE = "IMMUTABLE_DATA_PLANE"
    INDEX = "INDEX"
    CACHE = "CACHE"
    EPHEMERAL_SCRATCH = "EPHEMERAL_SCRATCH"


# Competing *product* authorities — not the three canonical LEVIATHAN DB files.
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

# Allowed product SQLite filenames (basename). Paths may vary; names must not
# introduce a fourth authority under a competing domain filename.
CANONICAL_PRODUCT_DB_BASENAMES = frozenset(
    {
        "leviathan_control.db",
        "leviathan_knowledge.db",
        "leviathan_market.db",
        # Legacy single-DB artifact (upgrade input / preserved backup only).
        "leviathan.db",
    }
)


STORAGE_AUTHORITY_TRUTH = {
    "canonicalTransactionalAuthority": "three_sqlite_databases_control_knowledge_market",
    "canonicalDatabaseCount": 3,
    "canonicalDomains": ["CONTROL", "KNOWLEDGE", "MARKET"],
    "immutableDataPlaneAllowed": True,
    "indexesAreRebuildable": True,
    "cachesAreDisposable": True,
    "ephemeralScratchAllowed": True,
    "competingDomainDatabasesForbidden": True,
    "scratchIsNotBusinessAuthority": True,
    "legacySingleDbIsNotProductAuthority": True,
}


def _canonical_path_set(
    *,
    canonical_db: Path | None = None,
    canonical_dbs: Iterable[Path] | None = None,
    database_paths: Any | None = None,
) -> set[Path]:
    out: set[Path] = set()
    if canonical_db is not None:
        out.add(Path(canonical_db).resolve())
    if canonical_dbs is not None:
        for p in canonical_dbs:
            out.add(Path(p).resolve())
    if database_paths is not None:
        for attr in ("control", "knowledge", "market"):
            p = getattr(database_paths, attr, None)
            if p is not None:
                out.add(Path(p).resolve())
    return out


def classify_path(
    path: Path,
    *,
    canonical_db: Path | None = None,
    canonical_dbs: Iterable[Path] | None = None,
    database_paths: Any | None = None,
    corpus_root: Path | None = None,
    scratch_root: Path | None = None,
) -> StorageClass:
    resolved = Path(path).resolve()
    canonical = _canonical_path_set(
        canonical_db=canonical_db,
        canonical_dbs=canonical_dbs,
        database_paths=database_paths,
    )
    if resolved in canonical:
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
    if name in CANONICAL_PRODUCT_DB_BASENAMES:
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
            "Use the three canonical LEVIATHAN databases "
            "(leviathan_control.db / leviathan_knowledge.db / leviathan_market.db) "
            "or governed ephemeral scratch."
        )


def storage_authority_public_dict() -> dict[str, Any]:
    return {
        "storageClasses": [c.value for c in StorageClass],
        "forbiddenCompetingDatabases": sorted(FORBIDDEN_COMPETING_DB_NAMES),
        "canonicalProductDatabaseBasenames": sorted(CANONICAL_PRODUCT_DB_BASENAMES),
        "truth": dict(STORAGE_AUTHORITY_TRUTH),
    }
