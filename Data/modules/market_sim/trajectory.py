"""Trajectory artifacts — durable gym/sim step records (P1C).

A trajectory is the ordered sequence of (observation, action, reward, info)
events produced by TradingGym / SimulationEngine. Content-addressed via
``TrajectoryHash``. Export is JSONL suitable for DatasetService ingest.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from Data.modules.common.hashing import sha256_file

from .hashes import trajectory_hash
from .types import MarketSimError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TrajectoryStep:
    step_index: int
    bar_index: int
    ts: str | None
    observation: dict[str, Any]
    action: dict[str, Any]
    reward: dict[str, Any]
    done: bool
    info: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "bar_index": self.bar_index,
            "ts": self.ts,
            "observation": self.observation,
            "action": self.action,
            "reward": self.reward,
            "done": self.done,
            "info": self.info,
        }


@dataclass
class TrajectoryArtifact:
    trajectory_id: str
    run_id: str
    split_role: str
    reward_spec: dict[str, Any]
    steps: list[TrajectoryStep]
    trajectory_hash: str
    input_fingerprint: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "run_id": self.run_id,
            "split_role": self.split_role,
            "reward_spec": self.reward_spec,
            "step_count": len(self.steps),
            "trajectory_hash": self.trajectory_hash,
            "input_fingerprint": self.input_fingerprint,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "steps": [s.public_dict() for s in self.steps],
            "truth": {
                "content_addressed": True,
                "kernel_owned": True,
            },
        }

    def step_payloads(self) -> list[dict[str, Any]]:
        return [s.public_dict() for s in self.steps]


class TrajectoryBuilder:
    """Accumulate gym steps then seal into a TrajectoryArtifact."""

    def __init__(
        self,
        *,
        run_id: str,
        split_role: str = "TRAIN",
        reward_spec: dict[str, Any] | None = None,
        input_fingerprint: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.split_role = split_role
        self.reward_spec = dict(reward_spec or {})
        self.input_fingerprint = input_fingerprint
        self.metadata = dict(metadata or {})
        self._steps: list[TrajectoryStep] = []

    def add_step(
        self,
        *,
        observation: dict[str, Any],
        action: dict[str, Any],
        reward: dict[str, Any],
        done: bool,
        info: dict[str, Any] | None = None,
    ) -> TrajectoryStep:
        step = TrajectoryStep(
            step_index=len(self._steps),
            bar_index=int(observation.get("bar_index") or 0),
            ts=observation.get("ts"),
            observation=dict(observation),
            action=dict(action),
            reward=dict(reward),
            done=bool(done),
            info=dict(info or {}),
        )
        self._steps.append(step)
        return step

    def seal(self, *, trajectory_id: str | None = None) -> TrajectoryArtifact:
        payloads = [s.public_dict() for s in self._steps]
        th = trajectory_hash(payloads)
        return TrajectoryArtifact(
            trajectory_id=trajectory_id or str(uuid.uuid4()),
            run_id=self.run_id,
            split_role=self.split_role,
            reward_spec=self.reward_spec,
            steps=list(self._steps),
            trajectory_hash=th,
            input_fingerprint=self.input_fingerprint,
            created_at=utc_now(),
            metadata=self.metadata,
        )


def write_trajectory_jsonl(artifact: TrajectoryArtifact, dest: Path) -> dict[str, Any]:
    """Write one JSON object per step + a trailing manifest line."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        header = {
            "record_type": "trajectory_manifest",
            "trajectory_id": artifact.trajectory_id,
            "run_id": artifact.run_id,
            "split_role": artifact.split_role,
            "trajectory_hash": artifact.trajectory_hash,
            "input_fingerprint": artifact.input_fingerprint,
            "reward_spec": artifact.reward_spec,
            "step_count": len(artifact.steps),
            "created_at": artifact.created_at,
            "metadata": artifact.metadata,
        }
        fh.write(json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n")
        for step in artifact.steps:
            row = {"record_type": "trajectory_step", **step.public_dict()}
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    digest = sha256_file(dest)
    return {
        "path": str(dest),
        "content_hash": digest,
        "byte_size": dest.stat().st_size,
        "step_count": len(artifact.steps),
        "trajectory_hash": artifact.trajectory_hash,
        "format": "jsonl",
    }


def load_trajectory_jsonl(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(path)
    if not path.is_file():
        raise MarketSimError("TRAJECTORY_NOT_FOUND", str(path), http_status=404)
    manifest: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.get("record_type")
            if kind == "trajectory_manifest":
                manifest = row
            elif kind == "trajectory_step":
                steps.append(row)
            else:
                # Treat untyped rows as steps for forward compat
                steps.append(row)
    if manifest is None:
        raise MarketSimError("TRAJECTORY_INVALID", "missing trajectory_manifest header")
    return manifest, steps
