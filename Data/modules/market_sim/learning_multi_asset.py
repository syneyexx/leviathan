"""Strategy learning multi-asset types (W20)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


ALLOWED_LEARNING_FAMILIES = frozenset(
    {"equity", "crypto_spot", "forex", "futures"}
)


@dataclass(frozen=True)
class MultiAssetLearningMandate:
    """Declares which instrument families a learning run may touch."""

    run_id: str
    instrument_families: tuple[str, ...]
    primary_family: str
    symbols: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fams = tuple(f.lower() for f in self.instrument_families)
        object.__setattr__(self, "instrument_families", fams)
        object.__setattr__(self, "primary_family", self.primary_family.lower())
        unknown = [f for f in fams if f not in ALLOWED_LEARNING_FAMILIES]
        if unknown:
            raise ValueError(f"unsupported learning families: {unknown}")
        if self.primary_family not in fams:
            raise ValueError("primary_family must be in instrument_families")

    def allows_family(self, family: str) -> bool:
        return family.lower() in self.instrument_families

    def public_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "instrumentFamilies": list(self.instrument_families),
            "primaryFamily": self.primary_family,
            "symbols": list(self.symbols),
            "metadata": dict(self.metadata),
            "truth": {
                "multi_asset_learning_does_not_imply_options_fi": True,
                "options_fixed_income_excluded_until_implemented": True,
            },
        }


def validate_learning_symbols(
    mandate: MultiAssetLearningMandate,
    *,
    symbol_families: dict[str, str],
) -> dict[str, Any]:
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    for sym, fam in symbol_families.items():
        if mandate.allows_family(fam):
            accepted.append(sym)
        else:
            rejected.append({"symbol": sym, "family": fam, "reason": "family_not_in_mandate"})
    return {
        "accepted": accepted,
        "rejected": rejected,
        "ok": not rejected,
        "mandate": mandate.public_dict(),
    }
