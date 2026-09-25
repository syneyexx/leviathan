"""Durable filesystem commit spool — correctness does not depend on IPC."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from Data.modules.common.atomic import atomic_write_bytes, ensure_dir
from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, path_under_root, safe_join

from .errors import (
    DbCommitBackpressureError,
    DbCommitSpoolUnavailableError,
    ForbiddenPayloadPathError,
    InvalidIntentError,
    PayloadHashMismatchError,
)
from .settings import DbCommitSettings
from .types import CommitIntent, CommitPriority, PRIORITY_RANK


SPOOL_DIRS = ("pending", "inflight", "applied", "failed", "quarantine")


@dataclass
class SpoolItem:
    path: Path
    intent: CommitIntent
    state: str


@dataclass
class SpoolStats:
    pending_count: int = 0
    pending_bytes: int = 0
    inflight_count: int = 0
    applied_count: int = 0
    failed_count: int = 0
    quarantine_count: int = 0
    oldest_pending_age_seconds: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "pendingCount": self.pending_count,
            "pendingBytes": self.pending_bytes,
            "inflightCount": self.inflight_count,
            "appliedCount": self.applied_count,
            "failedCount": self.failed_count,
            "quarantineCount": self.quarantine_count,
            "oldestPendingAgeSeconds": self.oldest_pending_age_seconds,
        }


class CommitSpool:
    def __init__(
        self,
        root: Path,
        *,
        settings: DbCommitSettings | None = None,
        allowed_payload_roots: Iterable[Path] | None = None,
    ) -> None:
        self.root = Path(root)
        self.settings = settings or DbCommitSettings()
        self.allowed_payload_roots = [Path(p).resolve() for p in (allowed_payload_roots or [])]
        self.ensure_dirs()

    def ensure_dirs(self) -> None:
        for name in SPOOL_DIRS:
            ensure_dir(self.root / name)

    def dir(self, name: str) -> Path:
        if name not in SPOOL_DIRS:
            raise ValueError(f"Unknown spool dir: {name}")
        return self.root / name

    def enqueue(
        self,
        intent: CommitIntent,
        *,
        allow_critical: bool = False,
        check_backpressure: bool = True,
    ) -> Path:
        self.ensure_dirs()
        if check_backpressure:
            self._enforce_backpressure(intent, allow_critical=allow_critical)
        try:
            payload = intent.to_json().encode("utf-8")
            dest = self.dir("pending") / f"{intent.commit_id}.json"
            atomic_write_bytes(dest, payload)
            return dest
        except OSError as exc:
            raise DbCommitSpoolUnavailableError(str(exc)) from exc

    def claim_next(self, *, now: float | None = None) -> SpoolItem | None:
        """Claim highest effective-priority pending intent into inflight."""
        candidates = list(self.iter_pending())
        if not candidates:
            return None
        now_ts = now if now is not None else time.time()
        candidates.sort(key=lambda item: self._effective_sort_key(item.intent, now_ts))
        item = candidates[0]
        inflight = self.dir("inflight") / item.path.name
        try:
            item.path.replace(inflight)
        except FileNotFoundError:
            return None
        return SpoolItem(path=inflight, intent=item.intent, state="inflight")

    def iter_pending(self) -> list[SpoolItem]:
        items: list[SpoolItem] = []
        for path in sorted(self.dir("pending").glob("*.json")):
            try:
                intent = self._load_intent(path)
            except InvalidIntentError:
                self.quarantine(path, reason="INVALID_INTENT")
                continue
            items.append(SpoolItem(path=path, intent=intent, state="pending"))
        return items

    def finalize_applied(self, item: SpoolItem) -> Path:
        dest = self.dir("applied") / item.path.name
        try:
            item.path.replace(dest)
        except FileNotFoundError:
            # Already moved
            dest = item.path
        return dest

    def mark_failed(self, item: SpoolItem, *, reason: str) -> Path:
        dest = self.dir("failed") / item.path.name
        meta = {
            "reason": reason,
            "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "intent": item.intent.to_dict(),
        }
        atomic_write_bytes(dest, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        try:
            item.path.unlink(missing_ok=True)
        except OSError:
            pass
        return dest

    def return_to_pending(self, item: SpoolItem) -> Path:
        dest = self.dir("pending") / item.path.name
        try:
            item.path.replace(dest)
        except FileNotFoundError:
            dest = item.path
        return dest

    def quarantine(self, path: Path, *, reason: str) -> Path:
        dest = self.dir("quarantine") / path.name
        try:
            meta = {
                "reason": reason,
                "quarantined_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "raw": path.read_text(encoding="utf-8", errors="replace")[:8_000],
            }
            atomic_write_bytes(dest, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
            path.unlink(missing_ok=True)
        except OSError:
            try:
                shutil.move(str(path), str(dest))
            except OSError:
                pass
        return dest

    def recover_inflight(self, *, receipt_applied: Callable[[CommitIntent], bool]) -> list[SpoolItem]:
        """Crash recovery: applied → finalize; else return to pending."""
        recovered: list[SpoolItem] = []
        for path in list(self.dir("inflight").glob("*.json")):
            try:
                intent = self._load_intent(path)
            except InvalidIntentError:
                self.quarantine(path, reason="INVALID_INTENT")
                continue
            item = SpoolItem(path=path, intent=intent, state="inflight")
            if receipt_applied(intent):
                self.finalize_applied(item)
            else:
                self.return_to_pending(item)
                recovered.append(
                    SpoolItem(
                        path=self.dir("pending") / path.name,
                        intent=intent,
                        state="pending",
                    )
                )
        return recovered

    def validate_payload(self, intent: CommitIntent) -> Path:
        if not intent.payload_ref:
            raise ForbiddenPayloadPathError("payload_ref required")
        path = Path(intent.payload_ref)
        if not path.is_absolute():
            # Relative refs resolve under spool parent / commit_payloads convention.
            path = (self.root.parent / "commit_payloads" / intent.payload_ref).resolve()
        else:
            path = path.resolve()
        if self.allowed_payload_roots:
            if not any(path_under_root(root, path) for root in self.allowed_payload_roots):
                raise ForbiddenPayloadPathError(f"payload outside allowed roots: {path}")
        if not path.is_file():
            raise ForbiddenPayloadPathError(f"payload missing: {path}")
        digest = sha256_file(path)
        if intent.payload_hash and digest != intent.payload_hash:
            raise PayloadHashMismatchError(
                f"expected {intent.payload_hash[:12]}… got {digest[:12]}…"
            )
        return path

    def stats(self) -> SpoolStats:
        pending_files = list(self.dir("pending").glob("*.json"))
        pending_bytes = 0
        oldest_age = 0.0
        now = time.time()
        for path in pending_files:
            try:
                pending_bytes += path.stat().st_size
                age = max(0.0, now - path.stat().st_mtime)
                oldest_age = max(oldest_age, age)
            except OSError:
                continue
        return SpoolStats(
            pending_count=len(pending_files),
            pending_bytes=pending_bytes,
            inflight_count=len(list(self.dir("inflight").glob("*.json"))),
            applied_count=len(list(self.dir("applied").glob("*.json"))),
            failed_count=len(list(self.dir("failed").glob("*.json"))),
            quarantine_count=len(list(self.dir("quarantine").glob("*.json"))),
            oldest_pending_age_seconds=oldest_age,
        )

    def retain(self) -> dict[str, int]:
        """Remove aged applied/failed entries per retention policy."""
        removed = {"applied": 0, "failed": 0}
        now = time.time()
        applied_ttl = float(self.settings.applied_retention_hours) * 3600.0
        failed_ttl = float(self.settings.spool_retention_hours) * 3600.0
        for path in list(self.dir("applied").glob("*.json")):
            try:
                if now - path.stat().st_mtime > applied_ttl:
                    path.unlink(missing_ok=True)
                    removed["applied"] += 1
            except OSError:
                continue
        for path in list(self.dir("failed").glob("*.json")):
            try:
                if now - path.stat().st_mtime > failed_ttl:
                    path.unlink(missing_ok=True)
                    removed["failed"] += 1
            except OSError:
                continue
        return removed

    def _enforce_backpressure(self, intent: CommitIntent, *, allow_critical: bool) -> None:
        stats = self.stats()
        count_ratio = stats.pending_count / max(1, self.settings.max_pending_count)
        bytes_ratio = stats.pending_bytes / max(1, self.settings.max_pending_bytes)
        hard = self.settings.hard_backpressure_threshold
        if count_ratio >= hard or bytes_ratio >= hard:
            critical = intent.operation in self.settings.critical_operations
            if not (allow_critical or critical):
                raise DbCommitBackpressureError(
                    f"pending={stats.pending_count} bytes={stats.pending_bytes}"
                )
        if stats.oldest_pending_age_seconds > self.settings.max_oldest_age_seconds:
            if intent.operation not in self.settings.critical_operations and not allow_critical:
                raise DbCommitBackpressureError("oldest pending age exceeded")

    def _effective_sort_key(self, intent: CommitIntent, now_ts: float) -> tuple[float, float, str]:
        """Lower is higher priority. Aging promotes old low-priority intents."""
        base = float(PRIORITY_RANK.get(intent.priority_enum(), 2))
        try:
            created = datetime.fromisoformat(intent.created_at.replace("Z", "+00:00"))
            age = max(0.0, now_ts - created.timestamp())
        except Exception:  # noqa: BLE001
            age = 0.0
        aging = float(self.settings.priority_aging_seconds) or 120.0
        effective = max(0.0, base - (age / aging) * 0.25)
        # Sequence: same sequence_key must respect sequence_number.
        seq = float(intent.sequence_number) if intent.sequence_key else 0.0
        return (effective, seq, intent.commit_id)

    def _load_intent(self, path: Path) -> CommitIntent:
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
            if not isinstance(data, dict):
                raise InvalidIntentError("intent root must be object")
            intent = CommitIntent.from_dict(data)
            if not intent.commit_id or not intent.operation or not intent.idempotency_key:
                raise InvalidIntentError("missing required fields")
            return intent
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise InvalidIntentError(str(exc)) from exc
