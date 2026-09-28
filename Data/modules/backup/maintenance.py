"""Canonical restore maintenance authority — quiescence proof for three-DB restore.

ONE coordinator for maintenance fencing. API may *request* restore; this module
must *prove* writers are drained/fenced before BackupService may replace DB files.
Caller booleans are not proof.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .service import (
    RESTORE_JOURNAL_NAME,
    RESTORE_NEW_SET_ACTIVE,
    RESTORE_OLD_SET_ACTIVE,
    RESTORE_RECOVERY_REQUIRED,
    utc_now,
)


class MaintenanceError(RuntimeError):
    """Fail-closed maintenance / quiescence error."""


# Server-side maintenance FSM (WAVE 21).
MAINT_NORMAL = "NORMAL"
MAINT_ENTERING = "ENTERING_MAINTENANCE"
MAINT_QUIESCING = "QUIESCING"
MAINT_QUIESCED = "QUIESCED"
MAINT_RESTORING = "RESTORING"
MAINT_VERIFYING = "VERIFYING"
MAINT_NEW_SET_ACTIVE = "NEW_SET_ACTIVE"
MAINT_OLD_SET_ACTIVE = "OLD_SET_ACTIVE"
MAINT_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

_ACTIVE_PROOF_STATES = frozenset({MAINT_QUIESCED, MAINT_RESTORING, MAINT_VERIFYING})

# Process-local registration so JobRuntime / CommitProducer can fence without a
# second orchestration runtime.
_PROCESS_COORDINATOR: "MaintenanceCoordinator | None" = None
_PROCESS_LOCK = threading.Lock()


def register_process_coordinator(coordinator: "MaintenanceCoordinator | None") -> None:
    global _PROCESS_COORDINATOR
    with _PROCESS_LOCK:
        _PROCESS_COORDINATOR = coordinator


def get_active_maintenance_coordinator() -> "MaintenanceCoordinator | None":
    with _PROCESS_LOCK:
        return _PROCESS_COORDINATOR


def _resolve_backup_root_for_fence() -> Path | None:
    """Best-effort backup root for cross-process durable fence reads."""
    import os

    raw = os.environ.get("LEVIATHAN_BACKUP_ROOT")
    if raw:
        return Path(raw)
    coord = get_active_maintenance_coordinator()
    if coord is not None:
        return Path(coord.backup_root)
    # Common default layout
    candidate = Path("Data/backend/data/backups")
    if candidate.is_dir():
        return candidate
    return None


def durable_writes_fenced(backup_root: Path | None = None) -> bool:
    """True when maintenance_state.json says writers are fenced (cross-process)."""
    root = backup_root or _resolve_backup_root_for_fence()
    if root is None:
        return False
    path = Path(root) / "maintenance_state.json"
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return True  # unreadable fence → fail closed
    state = str(payload.get("state") or "")
    if bool(payload.get("writesFenced")):
        return True
    if state in {
        MAINT_ENTERING,
        MAINT_QUIESCING,
        MAINT_QUIESCED,
        MAINT_RESTORING,
        MAINT_VERIFYING,
        MAINT_RECOVERY_REQUIRED,
    }:
        return True
    return False


def assert_writes_allowed(*, op: str = "write", backup_root: Path | None = None) -> None:
    """Fail closed when process coordinator OR durable maintenance fence is active."""
    coord = get_active_maintenance_coordinator()
    if coord is not None:
        coord.assert_writes_allowed(op=op)
        return
    if durable_writes_fenced(backup_root):
        raise MaintenanceError(
            f"writes rejected during durable maintenance fence (op={op})"
        )


@dataclass(frozen=True)
class MaintenanceProof:
    """Trusted token issued only after the coordinator reaches QUIESCED."""

    token: str
    proof_id: str
    issued_at: str
    expires_at_epoch: float
    state: str
    reason: str = "restore"

    def public_dict(self) -> dict[str, Any]:
        return {
            "proofId": self.proof_id,
            "issuedAt": self.issued_at,
            "expiresAtEpoch": self.expires_at_epoch,
            "state": self.state,
            "reason": self.reason,
            # token intentionally omitted from public surfaces
            "tokenPresent": bool(self.token),
        }


class MaintenanceCoordinator:
    """Single maintenance authority for BackupService restore cutover."""

    def __init__(
        self,
        *,
        backup_root: Path,
        job_runtime: Any | None = None,
        db_commit_fence: Callable[[], None] | None = None,
        quiesce_timeout_seconds: float = 30.0,
        proof_ttl_seconds: float = 120.0,
        drain_poll_seconds: float = 0.05,
    ) -> None:
        self.backup_root = Path(backup_root)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.job_runtime = job_runtime
        self.db_commit_fence = db_commit_fence
        self.quiesce_timeout_seconds = float(quiesce_timeout_seconds)
        self.proof_ttl_seconds = float(proof_ttl_seconds)
        self.drain_poll_seconds = float(drain_poll_seconds)
        self._lock = threading.RLock()
        self._state = MAINT_NORMAL
        self._writes_fenced = False
        self._secret = secrets.token_bytes(32)
        self._active_proof: MaintenanceProof | None = None
        self._last_error: str | None = None
        self._entered_at: str | None = None
        self._state_path = self.backup_root / "maintenance_state.json"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def writes_allowed(self) -> bool:
        with self._lock:
            return not self._writes_fenced

    def assert_writes_allowed(self, *, op: str = "write") -> None:
        if not self.writes_allowed():
            raise MaintenanceError(
                f"writes rejected during maintenance (op={op}, state={self.state})"
            )

    def public_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "writesFenced": self._writes_fenced,
                "writesAllowed": not self._writes_fenced,
                "enteredAt": self._entered_at,
                "lastError": self._last_error,
                "activeProof": (
                    self._active_proof.public_dict() if self._active_proof else None
                ),
                "truth": {
                    "callerBooleanIsNotMaintenanceProof": True,
                    "serverMustProveQuiescence": True,
                },
            }

    def enter_for_restore(
        self,
        *,
        timeout_seconds: float | None = None,
        reason: str = "restore",
    ) -> MaintenanceProof:
        """NORMAL → … → QUIESCED; issue proof. Fail closed on timeout (no DB replace)."""
        timeout = float(
            self.quiesce_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        with self._lock:
            # RECOVERY_REQUIRED may re-enter for operator-directed resume only;
            # lifespan still blocks normal boot via the restore journal gate.
            if self._state not in (
                MAINT_NORMAL,
                MAINT_OLD_SET_ACTIVE,
                MAINT_NEW_SET_ACTIVE,
                MAINT_RECOVERY_REQUIRED,
            ):
                if self._state in _ACTIVE_PROOF_STATES and self._active_proof is not None:
                    # Re-validate existing proof rather than nesting windows.
                    return self.verify_proof(self._active_proof)
                raise MaintenanceError(
                    f"Cannot enter maintenance from state={self._state}"
                )
            self._transition(MAINT_ENTERING)
            self._entered_at = utc_now()
            self._last_error = None
            self._writes_fenced = True
            self._persist_state()

        try:
            with self._lock:
                self._transition(MAINT_QUIESCING)
                self._persist_state()
            self._apply_external_fences()
            self._drain_until_quiesced(timeout=timeout)
            with self._lock:
                self._transition(MAINT_QUIESCED)
                proof = self._issue_proof(reason=reason)
                self._active_proof = proof
                self._persist_state()
                return proof
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)[:500]
                # Fail closed: release fence, do not hand out a proof.
                self._writes_fenced = False
                self._active_proof = None
                self._transition(MAINT_OLD_SET_ACTIVE)
                self._persist_state()
                # Allow retry from OLD_SET_ACTIVE / NORMAL path.
                self._transition(MAINT_NORMAL)
                self._persist_state()
            self._clear_external_fences()
            if isinstance(exc, MaintenanceError):
                raise
            raise MaintenanceError(f"Quiesce failed closed: {exc}") from exc

    def verify_proof(self, proof: MaintenanceProof | str | dict[str, Any] | None) -> MaintenanceProof:
        """Validate a coordinator-issued proof (not a client boolean)."""
        if proof is None:
            raise MaintenanceError(
                "Restore refused: trusted maintenance_proof from coordinator is required "
                "(caller maintenance_boundary boolean is not proof of quiescence)"
            )
        if isinstance(proof, bool):
            raise MaintenanceError(
                "Restore refused: boolean is not a maintenance proof"
            )
        if isinstance(proof, MaintenanceProof):
            candidate = proof
        elif isinstance(proof, str):
            with self._lock:
                active = self._active_proof
            if active is None or not hmac.compare_digest(active.token, proof):
                raise MaintenanceError("Restore refused: invalid maintenance_proof token")
            candidate = active
        elif isinstance(proof, dict):
            token = str(proof.get("token") or "")
            proof_id = str(proof.get("proof_id") or proof.get("proofId") or "")
            with self._lock:
                active = self._active_proof
            if active is None:
                raise MaintenanceError("Restore refused: no active maintenance proof")
            if token and not hmac.compare_digest(active.token, token):
                raise MaintenanceError("Restore refused: invalid maintenance_proof token")
            if proof_id and proof_id != active.proof_id:
                raise MaintenanceError("Restore refused: maintenance_proof id mismatch")
            if not token and not proof_id:
                raise MaintenanceError("Restore refused: empty maintenance_proof")
            candidate = active
        else:
            raise MaintenanceError("Restore refused: unrecognized maintenance_proof type")

        with self._lock:
            if self._state not in _ACTIVE_PROOF_STATES and self._state != MAINT_QUIESCED:
                # Allow verify only while quiesced / restoring / verifying.
                if self._state != MAINT_QUIESCED:
                    raise MaintenanceError(
                        f"Restore refused: maintenance state={self._state} is not quiesced"
                    )
            if self._active_proof is None or candidate.proof_id != self._active_proof.proof_id:
                raise MaintenanceError("Restore refused: maintenance_proof is not active")
            if not hmac.compare_digest(candidate.token, self._active_proof.token):
                raise MaintenanceError("Restore refused: maintenance_proof token mismatch")
            if time.time() > float(candidate.expires_at_epoch):
                raise MaintenanceError("Restore refused: maintenance_proof expired")
            if candidate.state != MAINT_QUIESCED and self._state == MAINT_QUIESCED:
                # Proof was issued at QUIESCED; state may advance after begin_restore.
                pass
            expected = self._mac(candidate.proof_id, candidate.expires_at_epoch, candidate.reason)
            if not hmac.compare_digest(candidate.token, expected):
                raise MaintenanceError("Restore refused: maintenance_proof integrity failure")
            return self._active_proof

    def begin_restore(self, proof: MaintenanceProof | str | dict[str, Any] | None) -> MaintenanceProof:
        verified = self.verify_proof(proof)
        with self._lock:
            if self._state not in (MAINT_QUIESCED, MAINT_RESTORING):
                raise MaintenanceError(
                    f"begin_restore requires QUIESCED, got {self._state}"
                )
            self._transition(MAINT_RESTORING)
            self._writes_fenced = True
            self._persist_state()
        return verified

    def mark_verifying(self) -> None:
        with self._lock:
            if self._state != MAINT_RESTORING:
                raise MaintenanceError(f"mark_verifying from invalid state={self._state}")
            self._transition(MAINT_VERIFYING)
            self._persist_state()

    def mark_new_set_active(self) -> None:
        with self._lock:
            self._transition(MAINT_NEW_SET_ACTIVE)
            self._persist_state()

    def mark_old_set_active(self) -> None:
        with self._lock:
            self._active_proof = None
            self._writes_fenced = False
            self._transition(MAINT_OLD_SET_ACTIVE)
            self._persist_state()
        self._clear_external_fences()

    def mark_recovery_required(self, *, error: str | None = None) -> None:
        with self._lock:
            self._active_proof = None
            # Keep fence until operator recovery — mixed revisions must not accept writes quietly.
            self._writes_fenced = True
            if error:
                self._last_error = error[:500]
            self._transition(MAINT_RECOVERY_REQUIRED)
            self._persist_state()

    def exit_to_normal(self) -> None:
        with self._lock:
            if self._state == MAINT_RECOVERY_REQUIRED:
                raise MaintenanceError(
                    f"Cannot exit to {MAINT_NORMAL} while {MAINT_RECOVERY_REQUIRED}"
                )
            self._active_proof = None
            self._writes_fenced = False
            self._last_error = None
            self._transition(MAINT_NORMAL)
            self._persist_state()
        self._clear_external_fences()

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def _clear_external_fences(self) -> None:
        runtime = self.job_runtime
        clear = getattr(runtime, "clear_maintenance_fence", None) if runtime else None
        if callable(clear):
            try:
                clear()
            except Exception:  # noqa: BLE001
                pass

    def _transition(self, new_state: str) -> None:
        self._state = new_state

    def _mac(self, proof_id: str, expires_at_epoch: float, reason: str) -> str:
        msg = f"{proof_id}|{expires_at_epoch:.3f}|{reason}".encode("utf-8")
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def _issue_proof(self, *, reason: str) -> MaintenanceProof:
        proof_id = secrets.token_hex(16)
        expires = time.time() + self.proof_ttl_seconds
        token = self._mac(proof_id, expires, reason)
        return MaintenanceProof(
            token=token,
            proof_id=proof_id,
            issued_at=utc_now(),
            expires_at_epoch=expires,
            state=MAINT_QUIESCED,
            reason=reason,
        )

    def _apply_external_fences(self) -> None:
        if self.db_commit_fence is not None:
            try:
                self.db_commit_fence()
            except Exception as exc:  # noqa: BLE001
                raise MaintenanceError(f"db_commit fence failed: {exc}") from exc
        runtime = self.job_runtime
        pause = getattr(runtime, "enter_maintenance_fence", None) if runtime else None
        if callable(pause):
            try:
                pause()
            except Exception as exc:  # noqa: BLE001
                raise MaintenanceError(f"JobRuntime fence failed: {exc}") from exc

    def _drain_until_quiesced(self, *, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        runtime = self.job_runtime
        while True:
            busy = self._runtime_busy(runtime)
            if not busy:
                return
            if time.monotonic() >= deadline:
                raise MaintenanceError(
                    f"Quiesce timed out after {timeout:.1f}s — fail closed, "
                    "refusing to replace DB files while writers may be active"
                )
            time.sleep(self.drain_poll_seconds)

    def _runtime_busy(self, runtime: Any | None) -> bool:
        if runtime is None:
            return False
        # Prefer explicit quiesced probe when present.
        probe = getattr(runtime, "maintenance_busy", None)
        if callable(probe):
            try:
                return bool(probe())
            except Exception:  # noqa: BLE001
                return True  # unproven → treat as busy (fail closed)
        # Heuristic: non-terminal queued/running jobs.
        try:
            from Data.modules.jobs.states import JobState

            active_states = {
                JobState.CREATED,
                JobState.QUEUED,
                JobState.RUNNING,
                JobState.RETRY_WAIT,
            }
            for state in active_states:
                listed = runtime.list(state=state, limit=1)
                if listed:
                    return True
        except Exception:  # noqa: BLE001
            return True
        return False

    def _persist_state(self) -> None:
        payload = {
            "state": self._state,
            "writesFenced": self._writes_fenced,
            "enteredAt": self._entered_at,
            "lastError": self._last_error,
            "updatedAt": utc_now(),
            "activeProofId": self._active_proof.proof_id if self._active_proof else None,
        }
        path = self._state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)


class RestoreStartupBlocked(RuntimeError):
    """Raised when lifespan must not open normal store/worker operation."""

    def __init__(self, message: str, *, journal: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.journal = journal or {}


def read_restore_journal(backup_root: Path) -> dict[str, Any] | None:
    path = Path(backup_root) / RESTORE_JOURNAL_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def journal_blocks_normal_startup(journal: dict[str, Any] | None) -> tuple[bool, str]:
    """Return (blocked, reason) for RECOVERY_REQUIRED or mixed cutover."""
    if not journal:
        return False, ""
    state = str(journal.get("state") or "")
    pending = list(journal.get("pending") or [])
    replaced = list(journal.get("replaced") or [])
    phase = str(journal.get("phase") or "")
    cleared = bool(journal.get("cleared_for_runtime"))

    if state == RESTORE_RECOVERY_REQUIRED or state == MAINT_RECOVERY_REQUIRED:
        return True, (
            f"restore journal state={RESTORE_RECOVERY_REQUIRED} — "
            "refusing normal startup against possibly mixed DB revisions"
        )

    # Mixed cutover: some domains replaced, others still pending.
    if pending and replaced:
        return True, (
            f"restore journal mixed cutover (replaced={replaced}, pending={pending}) — "
            f"state={state or 'unknown'}; refusing normal startup"
        )

    if phase.startswith("REPLACING_") or phase.startswith("RESUMING_"):
        return True, (
            f"restore journal mid-cutover phase={phase} — refusing normal startup"
        )

    if state == RESTORE_NEW_SET_ACTIVE and cleared:
        return False, ""
    if state in (RESTORE_OLD_SET_ACTIVE, RESTORE_NEW_SET_ACTIVE, "", MAINT_NORMAL):
        # OLD with no mixed markers is safe; NEW_SET without clear is still coherent set.
        return False, ""

    # Unknown non-terminal journal states fail closed.
    if state and state not in (
        RESTORE_OLD_SET_ACTIVE,
        RESTORE_NEW_SET_ACTIVE,
        MAINT_NORMAL,
        MAINT_OLD_SET_ACTIVE,
        MAINT_NEW_SET_ACTIVE,
    ):
        return True, (
            f"restore journal unrecognized/unsafe state={state} — refusing normal startup"
        )
    return False, ""


def assert_startup_allows_canonical_db_use(backup_root: Path) -> None:
    """Lifespan gate: block normal store/worker boot on recovery / mixed journal."""
    journal = read_restore_journal(backup_root)
    blocked, reason = journal_blocks_normal_startup(journal)
    if blocked:
        raise RestoreStartupBlocked(reason, journal=journal or {})
