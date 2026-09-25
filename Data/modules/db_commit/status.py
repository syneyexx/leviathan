"""DB Commit Coordinator status snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class DbCommitStatus:
    health: str
    worker_id: str
    worker_pid: int
    ready: bool
    draining: bool
    queue_depth: int
    pending_bytes: int
    oldest_pending_age_seconds: float
    inflight_commit_id: str
    last_applied_commit_id: str
    commit_count: int
    retry_count: int
    busy_count: int
    failed_count: int
    quarantine_count: int
    average_commit_latency_ms: float
    p95_commit_latency_ms: float | None
    apply_rate_per_minute: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "health": self.health,
            "workerId": self.worker_id,
            "workerPid": self.worker_pid,
            "ready": self.ready,
            "draining": self.draining,
            "queueDepth": self.queue_depth,
            "pendingBytes": self.pending_bytes,
            "oldestPendingAgeSeconds": self.oldest_pending_age_seconds,
            "inflightCommitId": self.inflight_commit_id,
            "lastAppliedCommitId": self.last_applied_commit_id,
            "commitCount": self.commit_count,
            "retryCount": self.retry_count,
            "busyCount": self.busy_count,
            "failedCount": self.failed_count,
            "quarantineCount": self.quarantine_count,
            "averageCommitLatencyMs": self.average_commit_latency_ms,
            "p95CommitLatencyMs": self.p95_commit_latency_ms,
            "applyRatePerMinute": self.apply_rate_per_minute,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
