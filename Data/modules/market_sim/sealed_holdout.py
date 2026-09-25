"""Sealed holdout windows — block strategy-development access to sealed test data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .causality import compare_ts, ts_available
from .types import MarketSimError


class SealedHoldoutViolation(MarketSimError):
    def __init__(self, message: str) -> None:
        super().__init__("SEALED_HOLDOUT", message, http_status=409)


@dataclass
class SealedHoldoutWindow:
    holdout_id: str
    strategy_id: str | None
    strategy_version: int | None
    start_ts: str
    end_ts: str
    status: str = "SEALED"  # SEALED | DISCLOSED
    dataset_id: str | None = None
    content_hash: str = ""

    def contains_ts(self, ts: str) -> bool:
        return compare_ts(self.start_ts, ts) <= 0 and compare_ts(ts, self.end_ts) <= 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "holdout_id": self.holdout_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "status": self.status,
            "dataset_id": self.dataset_id,
            "content_hash": self.content_hash,
        }


# Phases that must not see sealed holdout bars / outcomes.
_DESIGN_PHASES = frozenset(
    {
        "RESEARCH",
        "RESEARCH_WINDOW",
        "DESIGN",
        "STRATEGY_CREATION",
        "VALIDATION",
        "VALIDATION_WINDOW",
        "IDEA",
        "DRAFT",
        "BACKTESTING",
    }
)


@dataclass
class SealedHoldoutGuard:
    """Refuse sealed-holdout leakage into strategy design for a strategy version.

    After disclosure, adaptation requires a NEW strategy version — this guard
    does not mutate sealed versions; callers must bump version explicitly.
    """

    windows: list[SealedHoldoutWindow] = field(default_factory=list)

    def add(self, window: SealedHoldoutWindow) -> None:
        self.windows.append(window)

    def load_from_store(self, store: Any, *, strategy_id: str | None = None) -> None:
        for row in store.list_sealed_holdouts(strategy_id=strategy_id, status="SEALED", limit=500):
            self.windows.append(
                SealedHoldoutWindow(
                    holdout_id=row["holdout_id"],
                    strategy_id=row.get("strategy_id"),
                    strategy_version=row.get("strategy_version"),
                    start_ts=row["start_ts"],
                    end_ts=row["end_ts"],
                    status=row.get("status") or "SEALED",
                    dataset_id=row.get("dataset_id"),
                    content_hash=row.get("content_hash") or "",
                )
            )

    def active_for(
        self,
        *,
        strategy_id: str | None,
        strategy_version: int | None = None,
    ) -> list[SealedHoldoutWindow]:
        out: list[SealedHoldoutWindow] = []
        for w in self.windows:
            if w.status != "SEALED":
                continue
            if strategy_id and w.strategy_id and w.strategy_id != strategy_id:
                continue
            if (
                strategy_version is not None
                and w.strategy_version is not None
                and w.strategy_version != strategy_version
            ):
                continue
            out.append(w)
        return out

    def assert_ts_allowed(
        self,
        ts: str,
        *,
        phase: str,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
    ) -> None:
        phase_u = (phase or "").upper()
        if phase_u not in _DESIGN_PHASES and phase_u not in {"SEALED_TEST", "TEST"}:
            # Live / paper / disclosed evaluation may proceed.
            if phase_u not in {"RESEARCH", "DESIGN"}:
                pass
        if phase_u not in _DESIGN_PHASES:
            return
        for w in self.active_for(strategy_id=strategy_id, strategy_version=strategy_version):
            if w.contains_ts(ts):
                raise SealedHoldoutViolation(
                    f"Timestamp {ts} falls inside sealed holdout {w.holdout_id} "
                    f"[{w.start_ts} .. {w.end_ts}] during phase {phase_u}"
                )

    def filter_bars(
        self,
        bars: Sequence[Any],
        *,
        phase: str,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
    ) -> list[Any]:
        phase_u = (phase or "").upper()
        if phase_u not in _DESIGN_PHASES:
            return list(bars)
        active = self.active_for(strategy_id=strategy_id, strategy_version=strategy_version)
        if not active:
            return list(bars)
        kept: list[Any] = []
        for bar in bars:
            ts = getattr(bar, "ts", None) or (bar.get("ts") if isinstance(bar, dict) else None)
            if ts is None:
                kept.append(bar)
                continue
            if any(w.contains_ts(str(ts)) for w in active):
                continue
            kept.append(bar)
        return kept

    def assert_outcome_not_used_to_mutate_version(
        self,
        *,
        strategy_id: str,
        strategy_version: int,
        holdout_id: str,
        mutating: bool,
    ) -> None:
        """Completed holdout results cannot silently mutate the current version."""
        if not mutating:
            return
        for w in self.windows:
            if w.holdout_id != holdout_id:
                continue
            if w.strategy_id == strategy_id and w.strategy_version == strategy_version:
                raise SealedHoldoutViolation(
                    f"Holdout {holdout_id} results cannot modify strategy "
                    f"{strategy_id} v{strategy_version}; create a new version"
                )

    def memory_visible(
        self,
        *,
        available_at: str,
        as_of: str,
        phase: str,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
    ) -> bool:
        if not ts_available(available_at, as_of):
            return False
        phase_u = (phase or "").upper()
        if phase_u not in _DESIGN_PHASES:
            return True
        for w in self.active_for(strategy_id=strategy_id, strategy_version=strategy_version):
            if w.contains_ts(available_at):
                return False
        return True
