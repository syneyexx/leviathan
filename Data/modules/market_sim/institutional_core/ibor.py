"""W41 — IBOR-style portfolio hierarchy + deterministic reconstruction from events.

Hierarchy: Enterprise → Mandate → Strategy → Portfolio → Account → Sleeve → Position → Lot
Extends PortfolioBook owner — does not replace it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


HIERARCHY_LEVELS: tuple[str, ...] = (
    "enterprise",
    "mandate",
    "strategy",
    "portfolio",
    "account",
    "sleeve",
    "position",
    "lot",
)


@dataclass
class HierarchyNode:
    node_id: str
    level: str
    name: str
    parent_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "level": self.level,
            "name": self.name,
            "parentId": self.parent_id,
            "attributes": dict(self.attributes),
        }


@dataclass
class LotState:
    lot_id: str
    position_id: str
    instrument_id: str
    qty: float
    cost_basis: float
    opened_at: str
    side: str = "LONG"

    def public_dict(self) -> dict[str, Any]:
        return {
            "lotId": self.lot_id,
            "positionId": self.position_id,
            "instrumentId": self.instrument_id,
            "qty": self.qty,
            "costBasis": self.cost_basis,
            "openedAt": self.opened_at,
            "side": self.side,
        }


@dataclass
class PositionState:
    position_id: str
    sleeve_id: str
    instrument_id: str
    qty: float = 0.0
    avg_cost: float = 0.0
    side: str = "FLAT"
    lots: dict[str, LotState] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "positionId": self.position_id,
            "sleeveId": self.sleeve_id,
            "instrumentId": self.instrument_id,
            "qty": self.qty,
            "avgCost": self.avg_cost,
            "side": self.side,
            "lots": [lot.public_dict() for lot in self.lots.values()],
        }


@dataclass
class IborSnapshot:
    enterprise_id: str
    cash_by_account: dict[str, float]
    positions: dict[str, PositionState]
    nodes: dict[str, HierarchyNode]
    event_count: int
    as_of: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "enterpriseId": self.enterprise_id,
            "cashByAccount": dict(self.cash_by_account),
            "positions": {k: v.public_dict() for k, v in self.positions.items()},
            "nodes": {k: v.public_dict() for k, v in self.nodes.items()},
            "eventCount": self.event_count,
            "asOf": self.as_of,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_portfolio_book": True,
                "reconstruction_is_deterministic": True,
            },
        }


@dataclass
class IborEvent:
    """Canonical IBOR mutation event — ordered by (sequence, event_id)."""

    event_id: str
    sequence: int
    kind: str  # OPEN_LOT | ADJUST_QTY | CLOSE_LOT | CASH | UPSERT_NODE | TRANSFER_CASH
    ts: str
    payload: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "ts": self.ts,
            "payload": dict(self.payload),
        }


def _position_key(sleeve_id: str, instrument_id: str) -> str:
    return f"{sleeve_id}::{instrument_id}"


def reconstruct_ibor(
    events: Sequence[IborEvent | Mapping[str, Any]],
    *,
    enterprise_id: str = "enterprise",
    as_of: str | None = None,
) -> IborSnapshot:
    """Deterministically rebuild hierarchy + positions from an ordered event list."""
    normalized: list[IborEvent] = []
    for raw in events:
        if isinstance(raw, IborEvent):
            normalized.append(raw)
        else:
            normalized.append(
                IborEvent(
                    event_id=str(raw.get("event_id") or raw.get("eventId") or ""),
                    sequence=int(raw.get("sequence") or 0),
                    kind=str(raw.get("kind") or "").upper(),
                    ts=str(raw.get("ts") or ""),
                    payload=dict(raw.get("payload") or {}),
                )
            )
    normalized.sort(key=lambda e: (e.sequence, e.event_id))

    nodes: dict[str, HierarchyNode] = {
        enterprise_id: HierarchyNode(enterprise_id, "enterprise", enterprise_id),
    }
    cash_by_account: dict[str, float] = {}
    positions: dict[str, PositionState] = {}
    applied = 0

    for event in normalized:
        if as_of is not None and event.ts and event.ts > as_of:
            break
        applied += 1
        p = event.payload
        kind = event.kind

        if kind == "UPSERT_NODE":
            node = HierarchyNode(
                node_id=str(p["node_id"]),
                level=str(p["level"]),
                name=str(p.get("name") or p["node_id"]),
                parent_id=(None if p.get("parent_id") is None else str(p.get("parent_id"))),
                attributes=dict(p.get("attributes") or {}),
            )
            if node.level not in HIERARCHY_LEVELS:
                raise ValueError(f"invalid hierarchy level: {node.level}")
            nodes[node.node_id] = node

        elif kind == "CASH":
            account_id = str(p["account_id"])
            delta = float(p.get("delta") or 0.0)
            cash_by_account[account_id] = cash_by_account.get(account_id, 0.0) + delta

        elif kind == "TRANSFER_CASH":
            src = str(p["from_account_id"])
            dst = str(p["to_account_id"])
            amount = float(p["amount"])
            cash_by_account[src] = cash_by_account.get(src, 0.0) - amount
            cash_by_account[dst] = cash_by_account.get(dst, 0.0) + amount

        elif kind == "OPEN_LOT":
            sleeve_id = str(p["sleeve_id"])
            instrument_id = str(p["instrument_id"])
            pos_id = str(p.get("position_id") or _position_key(sleeve_id, instrument_id))
            lot_id = str(p["lot_id"])
            qty = float(p["qty"])
            cost = float(p.get("cost_basis") or p.get("avg_cost") or 0.0)
            side = str(p.get("side") or "LONG").upper()
            pos = positions.get(pos_id)
            if pos is None:
                pos = PositionState(
                    position_id=pos_id,
                    sleeve_id=sleeve_id,
                    instrument_id=instrument_id,
                )
                positions[pos_id] = pos
            lot = LotState(
                lot_id=lot_id,
                position_id=pos_id,
                instrument_id=instrument_id,
                qty=qty,
                cost_basis=cost,
                opened_at=str(p.get("opened_at") or event.ts),
                side=side,
            )
            pos.lots[lot_id] = lot
            _recompute_position(pos)

        elif kind == "ADJUST_QTY":
            pos_id = str(p["position_id"])
            lot_id = str(p["lot_id"])
            pos = positions[pos_id]
            lot = pos.lots[lot_id]
            lot.qty = float(p.get("qty", lot.qty + float(p.get("delta") or 0.0)))
            if "cost_basis" in p:
                lot.cost_basis = float(p["cost_basis"])
            _recompute_position(pos)

        elif kind == "CLOSE_LOT":
            pos_id = str(p["position_id"])
            lot_id = str(p["lot_id"])
            pos = positions[pos_id]
            if lot_id in pos.lots:
                del pos.lots[lot_id]
            _recompute_position(pos)

        else:
            # Unknown kinds are recorded as no-ops but still count for determinism.
            continue

    return IborSnapshot(
        enterprise_id=enterprise_id,
        cash_by_account=cash_by_account,
        positions=positions,
        nodes=nodes,
        event_count=applied,
        as_of=as_of,
    )


def _recompute_position(pos: PositionState) -> None:
    if not pos.lots:
        pos.qty = 0.0
        pos.avg_cost = 0.0
        pos.side = "FLAT"
        return
    total_qty = sum(lot.qty for lot in pos.lots.values())
    if total_qty == 0:
        pos.qty = 0.0
        pos.avg_cost = 0.0
        pos.side = "FLAT"
        return
    weighted = sum(lot.qty * lot.cost_basis for lot in pos.lots.values())
    pos.qty = total_qty
    pos.avg_cost = weighted / total_qty
    sides = {lot.side for lot in pos.lots.values()}
    pos.side = next(iter(sides)) if len(sides) == 1 else "MIXED"


def children_of(snapshot: IborSnapshot, parent_id: str) -> list[dict[str, Any]]:
    return [
        n.public_dict()
        for n in snapshot.nodes.values()
        if n.parent_id == parent_id
    ]


def validate_hierarchy(snapshot: IborSnapshot) -> dict[str, Any]:
    errors: list[str] = []
    for node in snapshot.nodes.values():
        if node.level not in HIERARCHY_LEVELS:
            errors.append(f"bad_level:{node.node_id}")
        if node.parent_id is None:
            if node.level != "enterprise":
                errors.append(f"missing_parent:{node.node_id}")
        elif node.parent_id not in snapshot.nodes:
            errors.append(f"dangling_parent:{node.node_id}->{node.parent_id}")
        else:
            parent = snapshot.nodes[node.parent_id]
            parent_idx = HIERARCHY_LEVELS.index(parent.level)
            child_idx = HIERARCHY_LEVELS.index(node.level)
            if child_idx <= parent_idx:
                errors.append(f"level_order:{node.node_id}")
    return {
        "ok": not errors,
        "errors": errors,
        "status": MeasurementState.PASS.value if not errors else MeasurementState.FAIL.value,
        "truth": DEFAULT_TRUTH.public_dict(),
    }
