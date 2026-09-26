"""W52 — Immutable decision packets with hash references.

Extends orchestra.types.DecisionRecord — adds content-addressed packets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canon(dict(payload)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HashRef:
    kind: str  # payload | parent | mandate | artifact
    digest: str
    alg: str = "sha256"

    def public_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "digest": self.digest, "alg": self.alg}


@dataclass
class DecisionPacket:
    """Immutable decision packet — mutation requires a new packet id."""

    packet_id: str
    stage: str
    actor: str
    as_of: str
    payload: dict[str, Any]
    refs: tuple[HashRef, ...] = ()
    parent_packet_id: str | None = None
    created_at: str = ""
    status: str = MeasurementState.OBSERVED.value

    def content_hash(self) -> str:
        body = {
            "packet_id": self.packet_id,
            "stage": self.stage,
            "actor": self.actor,
            "as_of": self.as_of,
            "payload": self.payload,
            "refs": [r.public_dict() for r in self.refs],
            "parent_packet_id": self.parent_packet_id,
            "created_at": self.created_at,
        }
        return hash_payload(body)

    def public_dict(self) -> dict[str, Any]:
        return {
            "packetId": self.packet_id,
            "stage": self.stage,
            "actor": self.actor,
            "asOf": self.as_of,
            "payload": dict(self.payload),
            "payloadHash": hash_payload(self.payload),
            "contentHash": self.content_hash(),
            "refs": [r.public_dict() for r in self.refs],
            "parentPacketId": self.parent_packet_id,
            "createdAt": self.created_at,
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "immutable_packet": True,
                "extends_decision_record": True,
            },
        }


class DecisionLedger:
    """Append-only ledger of decision packets."""

    def __init__(self) -> None:
        self._packets: list[DecisionPacket] = []
        self._by_id: dict[str, DecisionPacket] = {}

    def append(self, packet: DecisionPacket) -> DecisionPacket:
        if packet.packet_id in self._by_id:
            raise ValueError(f"packet already exists: {packet.packet_id}")
        if packet.parent_packet_id and packet.parent_packet_id not in self._by_id:
            raise ValueError(f"missing parent packet: {packet.parent_packet_id}")
        self._packets.append(packet)
        self._by_id[packet.packet_id] = packet
        return packet

    def get(self, packet_id: str) -> DecisionPacket | None:
        return self._by_id.get(packet_id)

    def verify(self, packet_id: str, expected_content_hash: str) -> dict[str, Any]:
        pkt = self._by_id.get(packet_id)
        if pkt is None:
            return {
                "ok": False,
                "status": MeasurementState.UNAVAILABLE.value,
                "reason": "missing_packet",
            }
        actual = pkt.content_hash()
        ok = actual == expected_content_hash
        return {
            "ok": ok,
            "status": MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
            "expected": expected_content_hash,
            "actual": actual,
            "truth": {"tamper_evident": True},
        }

    def chain(self, packet_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        current = self._by_id.get(packet_id)
        seen: set[str] = set()
        while current is not None and current.packet_id not in seen:
            seen.add(current.packet_id)
            out.append(current.public_dict())
            current = self._by_id.get(current.parent_packet_id) if current.parent_packet_id else None
        return out

    def public_dict(self) -> dict[str, Any]:
        return {
            "count": len(self._packets),
            "packets": [p.public_dict() for p in self._packets],
            "truth": DEFAULT_TRUTH.public_dict(),
        }


def packet_from_decision_record(record: Any, *, packet_id: str | None = None) -> DecisionPacket:
    """Bridge from orchestra DecisionRecord when available."""
    if hasattr(record, "public_dict"):
        data = record.public_dict()
    elif isinstance(record, Mapping):
        data = dict(record)
    else:
        raise TypeError("record must be DecisionRecord or mapping")

    refs: list[HashRef] = [
        HashRef("payload", hash_payload(dict(data.get("payload") or {}))),
        HashRef("mandate", str(data.get("mandateFingerprint") or data.get("mandate_fingerprint") or "")),
    ]
    if data.get("parentDecisionId") or data.get("parent_decision_id"):
        parent = str(data.get("parentDecisionId") or data.get("parent_decision_id"))
        refs.append(HashRef("parent", hashlib.sha256(parent.encode()).hexdigest()))

    return DecisionPacket(
        packet_id=packet_id or str(data.get("decisionId") or data.get("decision_id")),
        stage=str(data.get("stage") or ""),
        actor=str(data.get("agentId") or data.get("agent_id") or data.get("actor") or ""),
        as_of=str(data.get("asOf") or data.get("as_of") or ""),
        payload=dict(data.get("payload") or {}),
        refs=tuple(r for r in refs if r.digest),
        parent_packet_id=(
            None
            if not (data.get("parentDecisionId") or data.get("parent_decision_id"))
            else str(data.get("parentDecisionId") or data.get("parent_decision_id"))
        ),
        created_at=str(data.get("createdAt") or data.get("created_at") or ""),
    )
