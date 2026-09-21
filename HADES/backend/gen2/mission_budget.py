"""Transactional shared mission budget ledger.

Supports reserve → consume / release with reservation ids and idempotency keys.
Amounts must be finite and non-negative. Known budget keys are validated.
"""

from __future__ import annotations

import math
import threading
from typing import Any, Callable

from gen2.store import new_id, utc_now

# Known mission budget types (Unlimited = key absent / null on mission.budgets).
KNOWN_MISSION_BUDGET_KEYS = frozenset(
    {
        "max_tool_calls",
        "max_model_calls",
        "max_replans",
        "max_tokens",
        "context_tokens",
        "max_wall_time_s",
        "max_time_seconds",
        "max_cost_units",
    }
)

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _mission_lock(mission_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(mission_id)
        if lock is None:
            lock = threading.RLock()
            _locks[mission_id] = lock
        return lock


def _validate_amount(amount: float | int) -> float:
    try:
        value = float(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("budget_amount_invalid:not_numeric") from exc
    if not math.isfinite(value):
        raise ValueError("budget_amount_invalid:non_finite")
    if value < 0:
        raise ValueError("budget_amount_invalid:negative")
    return value


def _validate_key(key: str) -> str:
    cleaned = str(key or "").strip()
    if not cleaned:
        raise ValueError("budget_key_invalid:empty")
    if cleaned not in KNOWN_MISSION_BUDGET_KEYS:
        raise ValueError(f"budget_key_invalid:unknown:{cleaned}")
    return cleaned


def _empty_ledger() -> dict[str, Any]:
    return {
        "reserved": {},
        "consumed": {},
        "reservations": {},
        "entries": [],
        "idempotency": {},
    }


def normalize_ledger(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = _empty_ledger()
    if not isinstance(raw, dict):
        return base
    base["reserved"] = dict(raw.get("reserved") or {})
    base["consumed"] = dict(raw.get("consumed") or {})
    base["reservations"] = dict(raw.get("reservations") or {})
    base["entries"] = list(raw.get("entries") or [])
    base["idempotency"] = dict(raw.get("idempotency") or {})
    return base


def _find_idempotent(ledger: dict[str, Any], idempotency_key: str | None) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    hit = (ledger.get("idempotency") or {}).get(idempotency_key)
    return dict(hit) if isinstance(hit, dict) else None


class MissionBudgetLedger:
    """Mission-scoped transactional budget operations."""

    def __init__(
        self,
        *,
        get_mission: Callable[[str], dict[str, Any] | None],
        update_mission: Callable[..., dict[str, Any] | None],
        record: Callable[..., Any] | None = None,
    ) -> None:
        self._get_mission = get_mission
        self._update_mission = update_mission
        self._record = record

    def snapshot(self, mission_id: str) -> dict[str, Any]:
        mission = self._get_mission(mission_id)
        if not mission:
            raise ValueError("mission not found")
        budgets = dict(mission.get("budgets") or {})
        ledger = normalize_ledger(budgets.get("ledger"))
        return {
            "mission_id": mission_id,
            "budgets": {k: v for k, v in budgets.items() if k != "ledger"},
            "ledger": ledger,
            "shared": True,
            "note": "Shared across waves/steps; reservation ids required for consume/release.",
        }

    def reserve(
        self,
        mission_id: str,
        *,
        key: str,
        amount: float,
        step_id: str | None = None,
        reason: str = "reserve",
        idempotency_key: str | None = None,
        reservation_id: str | None = None,
    ) -> dict[str, Any]:
        key = _validate_key(key)
        amount = _validate_amount(amount)
        with _mission_lock(mission_id):
            mission = self._get_mission(mission_id)
            if not mission:
                raise ValueError("mission not found")
            budgets = dict(mission.get("budgets") or {})
            ledger = normalize_ledger(budgets.get("ledger"))
            prior = _find_idempotent(ledger, idempotency_key)
            if prior and prior.get("op") == "reserve":
                return self.snapshot(mission_id)

            limit = budgets.get(key)
            if limit is None:
                remaining = None
            else:
                try:
                    limit_f = float(limit)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"invalid budget limit for {key}") from exc
                if not math.isfinite(limit_f) or limit_f < 0:
                    raise ValueError(f"invalid budget limit for {key}")
                used = float(ledger["reserved"].get(key) or 0) + float(ledger["consumed"].get(key) or 0)
                remaining = limit_f - used
                if amount > remaining + 1e-9:
                    raise ValueError(
                        f"budget_exceeded:{key}:requested={amount}:remaining={remaining}:limit={limit_f}"
                    )

            rid = str(reservation_id or new_id("bres")).strip()
            if rid in ledger["reservations"]:
                raise ValueError(f"reservation_id_conflict:{rid}")
            ledger["reserved"][key] = float(ledger["reserved"].get(key) or 0) + amount
            entry = {
                "op": "reserve",
                "reservation_id": rid,
                "key": key,
                "amount": amount,
                "step_id": step_id,
                "reason": reason,
                "at": utc_now(),
                "idempotency_key": idempotency_key,
            }
            ledger["reservations"][rid] = {
                "key": key,
                "amount": amount,
                "remaining": amount,
                "step_id": step_id,
                "status": "open",
                "reason": reason,
                "created_at": entry["at"],
            }
            ledger["entries"] = (ledger["entries"] + [entry])[-200:]
            if idempotency_key:
                ledger["idempotency"][idempotency_key] = {
                    "op": "reserve",
                    "reservation_id": rid,
                    "at": entry["at"],
                }
            budgets["ledger"] = ledger
            self._update_mission(mission_id, budgets=budgets)
            if self._record:
                self._record(mission_id, "BUDGET_RESERVED", entry, component="mission_control", severity="info")
            out = self.snapshot(mission_id)
            out["reservation_id"] = rid
            out["entry"] = entry
            return out

    def consume(
        self,
        mission_id: str,
        *,
        key: str,
        amount: float,
        reservation_id: str | None = None,
        step_id: str | None = None,
        from_reservation: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = _validate_key(key)
        amount = _validate_amount(amount)
        with _mission_lock(mission_id):
            mission = self._get_mission(mission_id)
            if not mission:
                raise ValueError("mission not found")
            budgets = dict(mission.get("budgets") or {})
            ledger = normalize_ledger(budgets.get("ledger"))
            prior = _find_idempotent(ledger, idempotency_key)
            if prior and prior.get("op") == "consume":
                return self.snapshot(mission_id)

            if from_reservation:
                if not reservation_id:
                    raise ValueError("reservation_id_required")
                reservation = ledger["reservations"].get(reservation_id)
                if not isinstance(reservation, dict):
                    raise ValueError(f"reservation_not_found:{reservation_id}")
                if reservation.get("status") not in {"open", "partial"}:
                    raise ValueError(f"reservation_not_open:{reservation_id}:{reservation.get('status')}")
                if str(reservation.get("key")) != key:
                    raise ValueError(
                        f"reservation_key_mismatch:expected={reservation.get('key')}:got={key}"
                    )
                remaining = float(reservation.get("remaining") or 0)
                if amount > remaining + 1e-9:
                    raise ValueError(
                        f"reservation_insufficient:{reservation_id}:requested={amount}:remaining={remaining}"
                    )
                reservation["remaining"] = max(0.0, remaining - amount)
                reservation["status"] = "closed" if reservation["remaining"] <= 1e-12 else "partial"
                ledger["reservations"][reservation_id] = reservation
                ledger["reserved"][key] = max(0.0, float(ledger["reserved"].get(key) or 0) - amount)
            else:
                # Direct consume against limit (no reservation) — still cannot exceed remaining.
                limit = budgets.get(key)
                if limit is not None:
                    limit_f = float(limit)
                    used = float(ledger["reserved"].get(key) or 0) + float(ledger["consumed"].get(key) or 0)
                    remaining = limit_f - used
                    if amount > remaining + 1e-9:
                        raise ValueError(
                            f"budget_exceeded:{key}:requested={amount}:remaining={remaining}:limit={limit_f}"
                        )

            ledger["consumed"][key] = float(ledger["consumed"].get(key) or 0) + amount
            entry = {
                "op": "consume",
                "reservation_id": reservation_id,
                "key": key,
                "amount": amount,
                "step_id": step_id,
                "from_reservation": from_reservation,
                "at": utc_now(),
                "idempotency_key": idempotency_key,
            }
            ledger["entries"] = (ledger["entries"] + [entry])[-200:]
            if idempotency_key:
                ledger["idempotency"][idempotency_key] = {
                    "op": "consume",
                    "reservation_id": reservation_id,
                    "at": entry["at"],
                }
            budgets["ledger"] = ledger
            self._update_mission(mission_id, budgets=budgets)
            if self._record:
                self._record(mission_id, "BUDGET_CONSUMED", entry, component="mission_control")
            return self.snapshot(mission_id)

    def release(
        self,
        mission_id: str,
        *,
        reservation_id: str,
        reason: str = "release",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        reservation_id = str(reservation_id or "").strip()
        if not reservation_id:
            raise ValueError("reservation_id_required")
        with _mission_lock(mission_id):
            mission = self._get_mission(mission_id)
            if not mission:
                raise ValueError("mission not found")
            budgets = dict(mission.get("budgets") or {})
            ledger = normalize_ledger(budgets.get("ledger"))
            prior = _find_idempotent(ledger, idempotency_key)
            if prior and prior.get("op") == "release":
                return self.snapshot(mission_id)

            reservation = ledger["reservations"].get(reservation_id)
            if not isinstance(reservation, dict):
                raise ValueError(f"reservation_not_found:{reservation_id}")
            if reservation.get("status") in {"released", "closed"} and float(reservation.get("remaining") or 0) <= 1e-12:
                # Idempotent no-op for already fully settled reservations.
                return self.snapshot(mission_id)
            key = _validate_key(str(reservation.get("key") or ""))
            remaining = float(reservation.get("remaining") or 0)
            if remaining > 0:
                ledger["reserved"][key] = max(0.0, float(ledger["reserved"].get(key) or 0) - remaining)
            reservation["remaining"] = 0.0
            reservation["status"] = "released"
            reservation["released_reason"] = reason
            ledger["reservations"][reservation_id] = reservation
            entry = {
                "op": "release",
                "reservation_id": reservation_id,
                "key": key,
                "amount": remaining,
                "reason": reason,
                "at": utc_now(),
                "idempotency_key": idempotency_key,
            }
            ledger["entries"] = (ledger["entries"] + [entry])[-200:]
            if idempotency_key:
                ledger["idempotency"][idempotency_key] = {
                    "op": "release",
                    "reservation_id": reservation_id,
                    "at": entry["at"],
                }
            budgets["ledger"] = ledger
            self._update_mission(mission_id, budgets=budgets)
            if self._record:
                self._record(mission_id, "BUDGET_RELEASED", entry, component="mission_control")
            return self.snapshot(mission_id)
