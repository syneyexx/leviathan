"""DatasetSplitManifest — chronological TRAIN / VAL / SEALED windows (P1A).

Financial time is never shuffled. SEALED is the immutable holdout window bound
to a sealed dataset version. Once the parent dataset is sealed, the manifest
is frozen (corrections create a new dataset version + new manifest).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from .types import Bar, MarketSimError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SplitRole:
    TRAIN = "TRAIN"
    VAL = "VAL"
    SEALED = "SEALED"


@dataclass(frozen=True)
class SplitWindow:
    role: str
    start_ts: str
    end_ts: str
    start_index: int
    end_index: int
    bar_count: int
    content_hash: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "bar_count": self.bar_count,
            "content_hash": self.content_hash,
        }


def _window_hash(
    *,
    role: str,
    start_ts: str,
    end_ts: str,
    start_index: int,
    end_index: int,
    bar_count: int,
    dataset_content_hash: str,
) -> str:
    payload = {
        "role": role,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "start_index": start_index,
        "end_index": end_index,
        "bar_count": bar_count,
        "dataset_content_hash": dataset_content_hash,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _make_window(
    *,
    role: str,
    bars: Sequence[Bar],
    start_index: int,
    end_index: int,
    dataset_content_hash: str,
) -> SplitWindow:
    if start_index > end_index or start_index < 0 or end_index >= len(bars):
        raise MarketSimError(
            "INVALID_SPLIT",
            f"bad window indices role={role} [{start_index},{end_index}] n={len(bars)}",
        )
    slice_bars = bars[start_index : end_index + 1]
    return SplitWindow(
        role=role,
        start_ts=slice_bars[0].ts,
        end_ts=slice_bars[-1].ts,
        start_index=start_index,
        end_index=end_index,
        bar_count=len(slice_bars),
        content_hash=_window_hash(
            role=role,
            start_ts=slice_bars[0].ts,
            end_ts=slice_bars[-1].ts,
            start_index=start_index,
            end_index=end_index,
            bar_count=len(slice_bars),
            dataset_content_hash=dataset_content_hash,
        ),
    )


@dataclass
class DatasetSplitManifest:
    """Immutable chronological TRAIN / VAL / SEALED split for one dataset version."""

    manifest_id: str
    dataset_id: str
    dataset_version: str
    dataset_content_hash: str
    train: SplitWindow
    val: SplitWindow | None
    sealed: SplitWindow | None
    train_frac: float
    val_frac: float
    sealed_frac: float
    embargo_bars: int = 0
    frozen: bool = False
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def version_key(self) -> str:
        return f"{self.dataset_id}@{self.dataset_version}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "version_key": self.version_key,
            "dataset_content_hash": self.dataset_content_hash,
            "train": self.train.public_dict(),
            "val": self.val.public_dict() if self.val else None,
            "sealed": self.sealed.public_dict() if self.sealed else None,
            "train_frac": self.train_frac,
            "val_frac": self.val_frac,
            "sealed_frac": self.sealed_frac,
            "embargo_bars": self.embargo_bars,
            "frozen": self.frozen,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "truth": {
                "chronological_only": True,
                "no_shuffle": True,
                "roles": [SplitRole.TRAIN, SplitRole.VAL, SplitRole.SEALED],
                "frozen_when_dataset_sealed": True,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DatasetSplitManifest":
        def _win(raw: dict[str, Any] | None) -> SplitWindow | None:
            if not raw:
                return None
            return SplitWindow(
                role=str(raw["role"]),
                start_ts=str(raw["start_ts"]),
                end_ts=str(raw["end_ts"]),
                start_index=int(raw["start_index"]),
                end_index=int(raw["end_index"]),
                bar_count=int(raw["bar_count"]),
                content_hash=str(raw["content_hash"]),
            )

        train_raw = payload.get("train") or {}
        train = _win(train_raw)
        if train is None:
            raise MarketSimError("INVALID_SPLIT", "manifest missing TRAIN window")
        return cls(
            manifest_id=str(payload["manifest_id"]),
            dataset_id=str(payload["dataset_id"]),
            dataset_version=str(payload["dataset_version"]),
            dataset_content_hash=str(payload.get("dataset_content_hash") or ""),
            train=train,
            val=_win(payload.get("val")),
            sealed=_win(payload.get("sealed")),
            train_frac=float(payload.get("train_frac") or 0.0),
            val_frac=float(payload.get("val_frac") or 0.0),
            sealed_frac=float(payload.get("sealed_frac") or 0.0),
            embargo_bars=int(payload.get("embargo_bars") or 0),
            frozen=bool(payload.get("frozen")),
            created_at=str(payload.get("created_at") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


def build_split_manifest(
    bars: Sequence[Bar],
    *,
    dataset_id: str,
    dataset_version: str,
    dataset_content_hash: str,
    train_frac: float = 0.60,
    val_frac: float = 0.20,
    sealed_frac: float = 0.20,
    embargo_bars: int = 0,
    frozen: bool = False,
    manifest_id: str | None = None,
) -> DatasetSplitManifest:
    """Build chronological TRAIN → VAL → (embargo) → SEALED windows.

    Fractions must sum to ~1.0. Small series may collapse VAL/SEALED to None
    with an honest warning in metadata — never invent shuffled holdouts.
    """
    total = train_frac + val_frac + sealed_frac
    if abs(total - 1.0) > 1e-6:
        raise MarketSimError(
            "INVALID_SPLIT",
            f"split fractions must sum to 1.0, got {total}",
        )
    if min(train_frac, val_frac, sealed_frac) < 0:
        raise MarketSimError("INVALID_SPLIT", "split fractions must be non-negative")
    if embargo_bars < 0:
        raise MarketSimError("INVALID_SPLIT", "embargo_bars must be >= 0")

    n = len(bars)
    meta: dict[str, Any] = {}
    if n < 30:
        # Honest single-window fallback — insufficient for TRAIN/VAL/SEALED.
        train = _make_window(
            role=SplitRole.TRAIN,
            bars=bars,
            start_index=0,
            end_index=max(0, n - 1),
            dataset_content_hash=dataset_content_hash,
        )
        meta["warning"] = "insufficient bars for TRAIN/VAL/SEALED; TRAIN-only fallback"
        return DatasetSplitManifest(
            manifest_id=manifest_id or str(uuid.uuid4()),
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            dataset_content_hash=dataset_content_hash,
            train=train,
            val=None,
            sealed=None,
            train_frac=1.0,
            val_frac=0.0,
            sealed_frac=0.0,
            embargo_bars=0,
            frozen=frozen,
            created_at=utc_now(),
            metadata=meta,
        )

    # Reserve embargo between VAL and SEALED from the sealed budget when possible.
    usable = n - embargo_bars
    if usable < 30:
        raise MarketSimError(
            "INVALID_SPLIT",
            f"embargo_bars={embargo_bars} leaves only {usable} usable bars",
        )

    train_end = max(10, int(usable * train_frac))
    val_end = max(train_end + 5, int(usable * (train_frac + val_frac)))
    train_end = min(train_end, usable - 10)
    val_end = min(max(val_end, train_end + 5), usable - 5)

    sealed_start = val_end + embargo_bars
    if sealed_start >= n:
        raise MarketSimError("INVALID_SPLIT", "embargo consumed sealed window")

    train = _make_window(
        role=SplitRole.TRAIN,
        bars=bars,
        start_index=0,
        end_index=train_end - 1,
        dataset_content_hash=dataset_content_hash,
    )
    val = _make_window(
        role=SplitRole.VAL,
        bars=bars,
        start_index=train_end,
        end_index=val_end - 1,
        dataset_content_hash=dataset_content_hash,
    )
    sealed = _make_window(
        role=SplitRole.SEALED,
        bars=bars,
        start_index=sealed_start,
        end_index=n - 1,
        dataset_content_hash=dataset_content_hash,
    )

    # Causality: windows must not overlap and must be chronological.
    if not (
        train.end_index < val.start_index
        and val.end_index < sealed.start_index
        and train.end_ts < val.start_ts
        and val.end_ts < sealed.start_ts
    ):
        raise MarketSimError("INVALID_SPLIT", "split windows overlap or are unordered")

    return DatasetSplitManifest(
        manifest_id=manifest_id or str(uuid.uuid4()),
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        dataset_content_hash=dataset_content_hash,
        train=train,
        val=val,
        sealed=sealed,
        train_frac=train_frac,
        val_frac=val_frac,
        sealed_frac=sealed_frac,
        embargo_bars=embargo_bars,
        frozen=frozen,
        created_at=utc_now(),
        metadata=meta,
    )


def build_split_manifest_from_iter(
    bars_iter: Iterable[Bar],
    *,
    dataset_id: str,
    dataset_version: str,
    dataset_content_hash: str,
    train_frac: float = 0.60,
    val_frac: float = 0.20,
    sealed_frac: float = 0.20,
    embargo_bars: int = 0,
    frozen: bool = False,
    manifest_id: str | None = None,
) -> DatasetSplitManifest:
    """Materialize only what build needs — caller should prefer windowed loads later.

    For very large series, Gym episodes load TRAIN/VAL/SEALED windows by
    timestamp via ``iter_ohlcv(..., start_ts=, end_ts=)`` rather than keeping
    the full list resident.
    """
    bars = list(bars_iter)
    return build_split_manifest(
        bars,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        dataset_content_hash=dataset_content_hash,
        train_frac=train_frac,
        val_frac=val_frac,
        sealed_frac=sealed_frac,
        embargo_bars=embargo_bars,
        frozen=frozen,
        manifest_id=manifest_id,
    )


def assert_manifest_frozen(manifest: DatasetSplitManifest) -> None:
    if not manifest.frozen:
        raise MarketSimError(
            "SPLIT_NOT_FROZEN",
            "SEALED evaluation requires a frozen DatasetSplitManifest",
            http_status=409,
        )


@dataclass(frozen=True)
class ResearchEpisodeBinding:
    """Canonical runtime contract for a research episode window.

    Caller-supplied role strings alone are NOT a research-integrity boundary.
    Episode creation must derive start/end from the frozen split manifest.
    """

    dataset_id: str
    dataset_version: str
    split_manifest_id: str
    split_manifest_hash: str
    split_role: str
    start_ts: str
    end_ts: str
    start_index: int
    end_index: int
    bar_count: int
    window_content_hash: str
    dataset_content_hash: str
    embargo_bars: int = 0
    purge_bars: int = 0
    strategy_id: str = ""
    strategy_version: int = 0
    objective_hash: str = ""
    run_fingerprint: str = ""
    source_id: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "split_manifest_id": self.split_manifest_id,
            "split_manifest_hash": self.split_manifest_hash,
            "split_role": self.split_role,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "bar_count": self.bar_count,
            "window_content_hash": self.window_content_hash,
            "dataset_content_hash": self.dataset_content_hash,
            "embargo_bars": self.embargo_bars,
            "purge_bars": self.purge_bars,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "objective_hash": self.objective_hash,
            "run_fingerprint": self.run_fingerprint,
            "source_id": self.source_id,
            "truth": {
                "manifest_bounds_authoritative": True,
                "caller_cannot_expand_window": True,
                "role_string_alone_insufficient": True,
            },
        }

    def as_split_ref(self) -> dict[str, Any]:
        """Compact durable ref stored on learning runs / trials."""
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "manifest_id": self.split_manifest_id,
            "split_manifest_hash": self.split_manifest_hash,
            "role": self.split_role,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "bar_count": self.bar_count,
            "hash": self.window_content_hash,
            "content_hash": self.window_content_hash,
            "dataset_content_hash": self.dataset_content_hash,
            "embargo_bars": self.embargo_bars,
            "purge_bars": self.purge_bars,
        }


def _manifest_integrity_hash(manifest: DatasetSplitManifest | dict[str, Any]) -> str:
    if isinstance(manifest, DatasetSplitManifest):
        payload = manifest.public_dict()
    else:
        payload = dict(manifest)
    # Hash the frozen geometry only — not created_at noise.
    geometry = {
        "manifest_id": payload.get("manifest_id"),
        "dataset_id": payload.get("dataset_id"),
        "dataset_version": payload.get("dataset_version"),
        "dataset_content_hash": payload.get("dataset_content_hash"),
        "train": payload.get("train"),
        "val": payload.get("val"),
        "sealed": payload.get("sealed"),
        "train_frac": payload.get("train_frac"),
        "val_frac": payload.get("val_frac"),
        "sealed_frac": payload.get("sealed_frac"),
        "embargo_bars": payload.get("embargo_bars"),
        "frozen": bool(payload.get("frozen")),
    }
    blob = json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _window_from_manifest(
    manifest: DatasetSplitManifest | dict[str, Any],
    split_role: str,
) -> dict[str, Any]:
    role = str(split_role or SplitRole.TRAIN).upper()
    if isinstance(manifest, DatasetSplitManifest):
        payload = manifest.public_dict()
    else:
        payload = dict(manifest)
    key = {
        SplitRole.TRAIN: "train",
        "VALIDATION": "val",
        SplitRole.VAL: "val",
        SplitRole.SEALED: "sealed",
    }.get(role)
    if key is None:
        raise MarketSimError(
            "INVALID_SPLIT_ROLE",
            f"unsupported split_role={role}",
            http_status=400,
        )
    window = payload.get(key)
    if not window:
        raise MarketSimError(
            "SPLIT_WINDOW_MISSING",
            f"manifest has no {role} window",
            http_status=409,
        )
    return dict(window)


def resolve_research_episode_binding(
    manifest: DatasetSplitManifest | dict[str, Any],
    *,
    split_role: str,
    strategy_id: str = "",
    strategy_version: int = 0,
    objective_hash: str = "",
    run_fingerprint: str = "",
    source_id: str = "",
    require_frozen: bool = False,
    caller_start_ts: str | None = None,
    caller_end_ts: str | None = None,
) -> ResearchEpisodeBinding:
    """Derive an authoritative episode binding from a frozen split manifest.

    Caller-supplied timestamps may only *narrow* the window, never expand it.
    """
    if isinstance(manifest, DatasetSplitManifest):
        payload = manifest.public_dict()
        frozen = bool(manifest.frozen)
        embargo = int(manifest.embargo_bars)
        dataset_id = manifest.dataset_id
        dataset_version = manifest.dataset_version
        manifest_id = manifest.manifest_id
        dataset_content_hash = manifest.dataset_content_hash
    else:
        payload = dict(manifest)
        frozen = bool(payload.get("frozen"))
        embargo = int(payload.get("embargo_bars") or 0)
        dataset_id = str(payload.get("dataset_id") or "")
        dataset_version = str(payload.get("dataset_version") or "")
        manifest_id = str(payload.get("manifest_id") or "")
        dataset_content_hash = str(payload.get("dataset_content_hash") or "")

    role = str(split_role or SplitRole.TRAIN).upper()
    if role == SplitRole.SEALED or require_frozen:
        if not frozen:
            raise MarketSimError(
                "SPLIT_NOT_FROZEN",
                "research episode requires a frozen DatasetSplitManifest",
                http_status=409,
            )
    if not dataset_id or not dataset_version or not manifest_id:
        raise MarketSimError(
            "SPLIT_BINDING_INCOMPLETE",
            "dataset_id, dataset_version, and manifest_id are required",
            http_status=400,
        )

    window = _window_from_manifest(payload, role)
    start_ts = str(window["start_ts"])
    end_ts = str(window["end_ts"])
    start_index = int(window["start_index"])
    end_index = int(window["end_index"])
    bar_count = int(window["bar_count"])
    window_hash = str(window.get("content_hash") or "")

    # Caller may narrow, never expand.
    if caller_start_ts:
        if str(caller_start_ts) < start_ts:
            raise MarketSimError(
                "SPLIT_WINDOW_EXPANSION_FORBIDDEN",
                "caller start_ts precedes manifest window",
                http_status=400,
            )
        if str(caller_start_ts) > end_ts:
            raise MarketSimError(
                "SPLIT_WINDOW_INVALID",
                "caller start_ts after manifest end_ts",
                http_status=400,
            )
        start_ts = str(caller_start_ts)
    if caller_end_ts:
        if str(caller_end_ts) > end_ts:
            raise MarketSimError(
                "SPLIT_WINDOW_EXPANSION_FORBIDDEN",
                "caller end_ts exceeds manifest window",
                http_status=400,
            )
        if str(caller_end_ts) < start_ts:
            raise MarketSimError(
                "SPLIT_WINDOW_INVALID",
                "caller end_ts before effective start_ts",
                http_status=400,
            )
        end_ts = str(caller_end_ts)

    purge = int(payload.get("metadata", {}).get("purge_bars") or 0) if isinstance(payload.get("metadata"), dict) else 0
    return ResearchEpisodeBinding(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        split_manifest_id=manifest_id,
        split_manifest_hash=_manifest_integrity_hash(payload),
        split_role=role,
        start_ts=start_ts,
        end_ts=end_ts,
        start_index=start_index,
        end_index=end_index,
        bar_count=bar_count,
        window_content_hash=window_hash,
        dataset_content_hash=dataset_content_hash,
        embargo_bars=embargo,
        purge_bars=purge,
        strategy_id=str(strategy_id or ""),
        strategy_version=int(strategy_version or 0),
        objective_hash=str(objective_hash or ""),
        run_fingerprint=str(run_fingerprint or ""),
        source_id=str(source_id or ""),
    )


def split_refs_from_manifest(
    manifest: DatasetSplitManifest | dict[str, Any],
    *,
    source_id: str = "",
    strategy_id: str = "",
    strategy_version: int = 0,
    objective_hash: str = "",
) -> dict[str, dict[str, Any]]:
    """Build TRAIN/VAL/SEALED split refs for a learning run from one manifest."""
    refs: dict[str, dict[str, Any]] = {}
    for role in (SplitRole.TRAIN, SplitRole.VAL, SplitRole.SEALED):
        try:
            binding = resolve_research_episode_binding(
                manifest,
                split_role=role,
                source_id=source_id,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
                objective_hash=objective_hash,
                require_frozen=(role == SplitRole.SEALED),
            )
        except MarketSimError as exc:
            if exc.code in {"SPLIT_WINDOW_MISSING", "SPLIT_NOT_FROZEN"}:
                continue
            raise
        refs[role] = binding.as_split_ref()
    return refs
