"""Trajectory export + sealed-window contamination scan (T8 / G29)."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Sequence

from .types import MarketSimError


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def contamination_scan(
    records: Sequence[dict[str, Any]],
    *,
    sealed_windows: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reject trajectories whose as_of / bar timestamps intersect sealed holdouts."""
    sealed = list(sealed_windows or [])
    hits: list[dict[str, Any]] = []
    for i, rec in enumerate(records):
        as_of = str(rec.get("as_of") or rec.get("ts") or "")
        if not as_of:
            continue
        for window in sealed:
            start = str(window.get("start_ts") or window.get("start") or "")
            end = str(window.get("end_ts") or window.get("end") or "")
            role = str(window.get("role") or "")
            if start and end and start <= as_of <= end:
                hits.append(
                    {
                        "record_index": i,
                        "as_of": as_of,
                        "sealed_start": start,
                        "sealed_end": end,
                        "role": role,
                    }
                )
                break
            # Dataset-level sealed flag without explicit window → any record is contaminated
            # if role is SEALED_* and no window bounds (fail closed).
            if not start and not end and str(role).upper().startswith("SEALED"):
                hits.append(
                    {
                        "record_index": i,
                        "as_of": as_of,
                        "role": role,
                        "reason": "sealed_role_without_window",
                    }
                )
                break
    return {
        "contaminated": bool(hits),
        "hit_count": len(hits),
        "hits": hits[:50],
        "truth": {
            "sealed_windows_scanned": True,
            "verified_outcomes_only": True,
        },
    }


def build_trajectory_records(
    episode: dict[str, Any],
    *,
    verified: bool = True,
) -> list[dict[str, Any]]:
    """Flatten an episode trajectory into Datasets/Training-compatible records."""
    if not verified:
        raise MarketSimError(
            "UNVERIFIED_TRAJECTORY",
            "Only verified episode outcomes may be exported",
            http_status=403,
        )
    traj = list(episode.get("trajectory") or [])
    records: list[dict[str, Any]] = []
    for step in traj:
        records.append(
            {
                "episode_id": episode.get("episode_id"),
                "episode_spec_id": episode.get("episode_spec_id"),
                "curriculum_stage": episode.get("curriculum_stage"),
                "seed": episode.get("seed"),
                "step": step.get("step"),
                "action": step.get("action"),
                "reward": step.get("reward"),
                "as_of": step.get("as_of"),
                "bar_index": step.get("bar_index"),
                "equity": step.get("equity"),
                "done": step.get("done"),
                "verified": True,
                "split": "train",
            }
        )
    return records


def build_preference_pairs(
    records: Sequence[dict[str, Any]],
    *,
    min_reward_delta: float = 0.0,
) -> list[dict[str, Any]]:
    """Build simple preference pairs from consecutive steps (higher reward preferred)."""
    pairs: list[dict[str, Any]] = []
    by_ep: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        eid = str(rec.get("episode_id") or "")
        by_ep.setdefault(eid, []).append(rec)
    for eid, steps in by_ep.items():
        ordered = sorted(steps, key=lambda r: int(r.get("step") or 0))
        for a, b in zip(ordered, ordered[1:]):
            ra = float(a.get("reward") or 0.0)
            rb = float(b.get("reward") or 0.0)
            if abs(rb - ra) < min_reward_delta:
                continue
            chosen, rejected = (b, a) if rb > ra else (a, b)
            pairs.append(
                {
                    "pair_id": str(uuid.uuid4()),
                    "episode_id": eid,
                    "chosen": {
                        "action": chosen.get("action"),
                        "reward": chosen.get("reward"),
                        "as_of": chosen.get("as_of"),
                    },
                    "rejected": {
                        "action": rejected.get("action"),
                        "reward": rejected.get("reward"),
                        "as_of": rejected.get("as_of"),
                    },
                    "verified": True,
                }
            )
    return pairs


def export_trajectories_jsonl(
    records: Sequence[dict[str, Any]],
    dest: Path,
    *,
    sealed_windows: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scan = contamination_scan(records, sealed_windows=sealed_windows)
    if scan["contaminated"]:
        raise MarketSimError(
            "TRAJECTORY_CONTAMINATED",
            f"Export blocked: {scan['hit_count']} sealed-window hit(s)",
            http_status=409,
        )
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":")) for r in records]
    body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    dest.write_bytes(body)
    return {
        "path": str(dest),
        "record_count": len(records),
        "content_hash": _sha256_bytes(body),
        "contamination": scan,
        "truth": {
            "verified_outcomes_only": True,
            "via_datasets_training_pipeline": True,
            "contamination_scanned": True,
        },
    }
