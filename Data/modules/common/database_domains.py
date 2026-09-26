"""Canonical three-database domain contracts for LEVIATHAN.

Exactly three product SQLite authorities:
  CONTROL   — transactional system / control-plane state
  KNOWLEDGE — knowledge, retrieval, datasets, ingestion metadata
  MARKET    — market simulation / trading ledger and results

``LEVIATHAN_DATABASE_PATH`` is legacy upgrade input only — not the post-cutover
product authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator, Mapping


class DatabaseDomain(str, Enum):
    CONTROL = "CONTROL"
    KNOWLEDGE = "KNOWLEDGE"
    MARKET = "MARKET"


DEFAULT_CONTROL_DB_REL = "Data/backend/data/leviathan_control.db"
DEFAULT_KNOWLEDGE_DB_REL = "Data/backend/data/leviathan_knowledge.db"
DEFAULT_MARKET_DB_REL = "Data/backend/data/leviathan_market.db"
DEFAULT_LEGACY_DB_REL = "Data/backend/data/leviathan.db"

ENV_CONTROL = "LEVIATHAN_CONTROL_DATABASE_PATH"
ENV_KNOWLEDGE = "LEVIATHAN_KNOWLEDGE_DATABASE_PATH"
ENV_MARKET = "LEVIATHAN_MARKET_DATABASE_PATH"
ENV_LEGACY = "LEVIATHAN_DATABASE_PATH"


@dataclass(frozen=True)
class DatabasePaths:
    """Typed registry of the three canonical DB paths (+ optional legacy)."""

    control: Path
    knowledge: Path
    market: Path
    legacy: Path | None = None

    def path_for(self, domain: DatabaseDomain | str) -> Path:
        key = DatabaseDomain(domain)
        if key is DatabaseDomain.CONTROL:
            return self.control
        if key is DatabaseDomain.KNOWLEDGE:
            return self.knowledge
        if key is DatabaseDomain.MARKET:
            return self.market
        raise ValueError(f"Unknown database domain: {domain!r}")

    def all_canonical(self) -> tuple[tuple[DatabaseDomain, Path], ...]:
        return (
            (DatabaseDomain.CONTROL, self.control),
            (DatabaseDomain.KNOWLEDGE, self.knowledge),
            (DatabaseDomain.MARKET, self.market),
        )

    def as_mapping(self) -> dict[str, str]:
        out = {
            "control": str(self.control),
            "knowledge": str(self.knowledge),
            "market": str(self.market),
        }
        if self.legacy is not None:
            out["legacy"] = str(self.legacy)
        return out

    def public_dict(self) -> dict[str, object]:
        return {
            "domains": [d.value for d in DatabaseDomain],
            "paths": self.as_mapping(),
            "legacy_path": str(self.legacy) if self.legacy is not None else None,
            "legacy_is_product_authority": False,
            "canonical_count": 3,
        }

    def __iter__(self) -> Iterator[tuple[DatabaseDomain, Path]]:
        yield from self.all_canonical()

    def ensure_parent_dirs(self) -> None:
        for _, path in self.all_canonical():
            path.parent.mkdir(parents=True, exist_ok=True)


def resolve_database_paths(
    *,
    control_raw: str | None = None,
    knowledge_raw: str | None = None,
    market_raw: str | None = None,
    legacy_raw: str | None = None,
    resolve_path,
) -> DatabasePaths:
    """Resolve three canonical paths + optional legacy from raw env strings.

    ``resolve_path`` must be a callable ``(raw: str) -> Path`` matching backend
    config resolution (relative under project root).
    """
    control = resolve_path(control_raw or DEFAULT_CONTROL_DB_REL)
    knowledge = resolve_path(knowledge_raw or DEFAULT_KNOWLEDGE_DB_REL)
    market = resolve_path(market_raw or DEFAULT_MARKET_DB_REL)

    legacy: Path | None = None
    if legacy_raw is not None and str(legacy_raw).strip():
        legacy = resolve_path(str(legacy_raw).strip())
        # If operator still points LEVIATHAN_DATABASE_PATH at one of the three
        # canonical files, treat it as legacy-absent (already on 3-DB layout).
        if legacy.resolve() in {control.resolve(), knowledge.resolve(), market.resolve()}:
            legacy = None

    return DatabasePaths(
        control=control,
        knowledge=knowledge,
        market=market,
        legacy=legacy,
    )


def domain_from_commit_operation(operation: str, domain_hint: str | None = None) -> DatabaseDomain:
    """Map a commit operation / intent domain string to a DatabaseDomain."""
    hint = (domain_hint or "").strip().lower()
    op = (operation or "").strip().lower()
    blob = f"{hint}:{op}"
    if any(
        token in blob
        for token in (
            "knowledge",
            "dataset",
            "source_ingestion",
            "atlas",
            "embedding",
            "ingest",
            "retrieval",
        )
    ):
        return DatabaseDomain.KNOWLEDGE
    if any(
        token in blob
        for token in (
            "market",
            "trading",
            "portfolio",
            "paper",
            "fill",
            "sim",
            "institutional",
        )
    ):
        # Approvals / governance ops stay on control even if "trading" appears.
        if any(token in blob for token in ("approval", "mandate", "governance", "permission", "policy")):
            return DatabaseDomain.CONTROL
        return DatabaseDomain.MARKET
    return DatabaseDomain.CONTROL


def assert_canonical_paths_distinct(paths: DatabasePaths) -> None:
    resolved = [p.resolve() for _, p in paths.all_canonical()]
    if len(set(resolved)) != 3:
        raise ValueError(
            "Control, Knowledge, and Market database paths must be three distinct files; "
            f"got {paths.as_mapping()}"
        )


def iter_domains() -> Iterable[DatabaseDomain]:
    return tuple(DatabaseDomain)
