"""Table ownership intelligence for the SQLite Manager operator surface.

Builds on ``Data.backend.table_ownership`` — does not duplicate the map.
"""

from __future__ import annotations

from typing import Any, Literal

from Data.backend.table_ownership import (
    EPHEMERAL_OR_NON_PRODUCT,
    PER_DATABASE_INFRASTRUCTURE,
    TableOwnershipError,
    is_fts_shadow_table,
    ownership_for,
    tables_for,
)
from Data.modules.common.database_domains import DatabaseDomain

OwnershipState = Literal[
    "EXPECTED",
    "INFRASTRUCTURE",
    "EPHEMERAL",
    "UNKNOWN",
    "WRONG_DATABASE",
    "AMBIGUOUS",
    "MISSING",
]

_DOMAIN_OWNERSHIP_DESC: dict[str, str] = {
    DatabaseDomain.CONTROL.value: "system/control-plane state",
    DatabaseDomain.KNOWLEDGE.value: "knowledge/retrieval/datasets/ingestion metadata",
    DatabaseDomain.MARKET.value: "trading/market simulation/market ledger/results",
}


def _coerce_domain(domain: DatabaseDomain | str) -> DatabaseDomain:
    if isinstance(domain, DatabaseDomain):
        return domain
    return DatabaseDomain(str(domain).strip().upper())


def domain_ownership_description(domain: DatabaseDomain | str) -> str:
    key = _coerce_domain(domain)
    return _DOMAIN_OWNERSHIP_DESC[key.value]


def classify_table_in_domain(table: str, present_domain: DatabaseDomain | str) -> dict[str, Any]:
    """Classify a table found in ``present_domain`` against the ownership map."""
    present = _coerce_domain(present_domain)
    name = table.strip()
    if not name:
        return {
            "name": name,
            "presentDomain": present.value,
            "declaredOwner": None,
            "ownershipState": "UNKNOWN",
        }
    if name in EPHEMERAL_OR_NON_PRODUCT or is_fts_shadow_table(name):
        return {
            "name": name,
            "presentDomain": present.value,
            "declaredOwner": None,
            "ownershipState": "EPHEMERAL",
        }
    if name in PER_DATABASE_INFRASTRUCTURE:
        # commit_receipts/batches are also listed under CONTROL for cutover copy;
        # per-DB presence is infrastructure, not WRONG_DATABASE.
        return {
            "name": name,
            "presentDomain": present.value,
            "declaredOwner": None,
            "ownershipState": "INFRASTRUCTURE",
        }
    try:
        owner = ownership_for(name)
    except TableOwnershipError:
        return {
            "name": name,
            "presentDomain": present.value,
            "declaredOwner": None,
            "ownershipState": "AMBIGUOUS",
        }
    if owner is None:
        return {
            "name": name,
            "presentDomain": present.value,
            "declaredOwner": None,
            "ownershipState": "UNKNOWN",
        }
    if owner is present:
        state: OwnershipState = "EXPECTED"
    else:
        state = "WRONG_DATABASE"
    return {
        "name": name,
        "presentDomain": present.value,
        "declaredOwner": owner.value,
        "ownershipState": state,
    }


def ownership_audit_for_tables(
    *,
    present_by_domain: dict[str, set[str]],
) -> dict[str, Any]:
    """Machine-readable ownership / schema-drift audit across three domains.

    ``present_by_domain`` maps domain value → set of table/view names present on disk.
    """
    findings: list[dict[str, Any]] = []
    counts = {
        "EXPECTED": 0,
        "INFRASTRUCTURE": 0,
        "EPHEMERAL": 0,
        "UNKNOWN": 0,
        "WRONG_DATABASE": 0,
        "AMBIGUOUS": 0,
        "MISSING": 0,
        "DUPLICATE_PRODUCT": 0,
    }

    # Duplicate product tables across domains.
    product_locations: dict[str, list[str]] = {}
    for domain_value, names in present_by_domain.items():
        domain = DatabaseDomain(domain_value)
        for name in sorted(names):
            if name.startswith("sqlite_"):
                continue
            item = classify_table_in_domain(name, domain)
            state = item["ownershipState"]
            counts[state] = counts.get(state, 0) + 1
            if state in {"WRONG_DATABASE", "UNKNOWN", "AMBIGUOUS"}:
                findings.append({"kind": state, **item})
            if state == "EXPECTED" or (
                item.get("declaredOwner") and state == "WRONG_DATABASE"
            ):
                product_locations.setdefault(name, []).append(domain.value)

    for name, locs in sorted(product_locations.items()):
        if len(set(locs)) > 1:
            counts["DUPLICATE_PRODUCT"] += 1
            findings.append(
                {
                    "kind": "DUPLICATE_PRODUCT",
                    "name": name,
                    "presentDomains": sorted(set(locs)),
                    "declaredOwner": (
                        ownership_for(name).value if ownership_for(name) else None
                    ),
                }
            )

    # Missing expected product tables per domain.
    for domain in DatabaseDomain:
        present = present_by_domain.get(domain.value, set())
        expected = tables_for(domain)
        for name in sorted(expected):
            if name in PER_DATABASE_INFRASTRUCTURE:
                continue
            if name not in present:
                counts["MISSING"] += 1
                findings.append(
                    {
                        "kind": "MISSING",
                        "name": name,
                        "presentDomain": None,
                        "declaredOwner": domain.value,
                        "ownershipState": "MISSING",
                    }
                )

    # Unexpected canonical DB absence.
    missing_dbs = [
        domain.value
        for domain in DatabaseDomain
        if domain.value not in present_by_domain
    ]

    return {
        "schemaVersion": 1,
        "counts": counts,
        "findings": findings,
        "missingDatabases": missing_dbs,
        "ok": (
            counts["WRONG_DATABASE"] == 0
            and counts["AMBIGUOUS"] == 0
            and counts["DUPLICATE_PRODUCT"] == 0
            and not missing_dbs
        ),
    }
