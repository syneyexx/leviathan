"""Local task scheduling with occurrence deduplication and catch-up limits."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import new_id, utc_now

SUPPORTED_FREQUENCIES = frozenset({"once", "daily", "weekly"})
MAX_CATCHUP = 1  # After long downtime, at most one missed occurrence fires.


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Onbekende tijdzone: {name}") from exc


def compute_next_run(
    *,
    frequency: str,
    timezone: str,
    run_at: str | None = None,
    time_of_day: str | None = None,
    weekday: int | None = None,
    after: datetime | None = None,
) -> str:
    """Return next ISO timestamp in UTC for the schedule."""
    if frequency not in SUPPORTED_FREQUENCIES:
        raise ValueError(f"Frequentie niet ondersteund: {frequency}")
    tz = resolve_timezone(timezone)
    now = after or datetime.now(UTC)
    local_now = now.astimezone(tz)

    if frequency == "once":
        if not run_at:
            raise ValueError("Eenmalige planning vereist run_at.")
        text = run_at.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        when = datetime.fromisoformat(text)
        if when.tzinfo is None:
            when = when.replace(tzinfo=tz)
        return when.astimezone(UTC).isoformat(timespec="seconds")

    hour, minute = 9, 0
    if time_of_day:
        parts = time_of_day.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0

    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if frequency == "daily":
        if candidate <= local_now:
            candidate = candidate + timedelta(days=1)
        # DST: ZoneInfo localize via replace keeps wall clock intent.
        return candidate.astimezone(UTC).isoformat(timespec="seconds")

    # weekly
    target_weekday = 0 if weekday is None else int(weekday) % 7
    days_ahead = (target_weekday - candidate.weekday()) % 7
    candidate = candidate + timedelta(days=days_ahead)
    if candidate <= local_now:
        candidate = candidate + timedelta(days=7)
    return candidate.astimezone(UTC).isoformat(timespec="seconds")


def preview_occurrences(
    *,
    frequency: str,
    timezone: str,
    run_at: str | None = None,
    time_of_day: str | None = None,
    weekday: int | None = None,
    count: int = 5,
    after: datetime | None = None,
) -> list[str]:
    cursor = after
    out: list[str] = []
    for _ in range(max(1, min(count, 20))):
        nxt = compute_next_run(
            frequency=frequency,
            timezone=timezone,
            run_at=run_at,
            time_of_day=time_of_day,
            weekday=weekday,
            after=cursor,
        )
        out.append(nxt)
        cursor = _parse_iso(nxt) + timedelta(seconds=1)
        if frequency == "once":
            break
    return out


class ScheduleService:
    def __init__(self, db: Any, inbox: Any | None = None, clock: Any | None = None) -> None:
        self.db = db
        self.inbox = inbox
        self._clock = clock or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def attach_schedule(
        self,
        task_id: str,
        *,
        frequency: str,
        timezone: str = "UTC",
        run_at: str | None = None,
        time_of_day: str | None = None,
        weekday: int | None = None,
        enabled: bool = True,
        catch_up: bool = True,
    ) -> dict[str, Any]:
        next_run = compute_next_run(
            frequency=frequency,
            timezone=timezone,
            run_at=run_at,
            time_of_day=time_of_day,
            weekday=weekday,
            after=self.now(),
        )
        preview = preview_occurrences(
            frequency=frequency,
            timezone=timezone,
            run_at=run_at,
            time_of_day=time_of_day,
            weekday=weekday,
            after=self.now(),
        )
        record = {
            "id": new_id("sched"),
            "task_id": task_id,
            "frequency": frequency,
            "timezone": timezone,
            "run_at": run_at,
            "time_of_day": time_of_day,
            "weekday": weekday,
            "enabled": bool(enabled),
            "paused": False,
            "catch_up": bool(catch_up),
            "next_run_at": next_run,
            "last_run_at": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "preview": preview,
        }
        saved = self.db.upsert_task_schedule(record)
        saved["preview"] = preview
        return saved

    def pause(self, schedule_id: str) -> dict[str, Any]:
        return self.db.update_task_schedule(schedule_id, paused=True, updated_at=utc_now())

    def resume(self, schedule_id: str) -> dict[str, Any]:
        item = self.db.get_task_schedule(schedule_id)
        if not item:
            raise KeyError(schedule_id)
        next_run = compute_next_run(
            frequency=item["frequency"],
            timezone=item["timezone"],
            run_at=item.get("run_at"),
            time_of_day=item.get("time_of_day"),
            weekday=item.get("weekday"),
            after=self.now(),
        )
        return self.db.update_task_schedule(schedule_id, paused=False, enabled=True, next_run_at=next_run, updated_at=utc_now())

    def disable(self, schedule_id: str) -> dict[str, Any]:
        return self.db.update_task_schedule(schedule_id, enabled=False, paused=True, updated_at=utc_now())

    def due_schedules(self) -> list[dict[str, Any]]:
        now = self.now().isoformat(timespec="seconds")
        return self.db.list_due_schedules(now)

    def claim_occurrence(self, schedule: dict[str, Any]) -> dict[str, Any] | None:
        """Atomically claim the next occurrence and advance its schedule."""
        if not schedule.get("enabled") or schedule.get("paused"):
            return None
        planned = schedule.get("next_run_at")
        if not planned:
            return None
        planned_dt = _parse_iso(planned)
        now = self.now()
        if planned_dt > now:
            return None

        occurrence_id = f"{schedule['id']}:{planned}"
        claimed_at = now.isoformat(timespec="seconds")
        updated_at = utc_now()

        next_run: str | None = None
        disable_after_claim = schedule["frequency"] == "once"
        if not disable_after_claim:
            # Skip unbounded backlog: jump from "now", not from every missed slot.
            base = now if schedule.get("catch_up") else planned_dt
            if schedule.get("catch_up") and (now - planned_dt) > timedelta(hours=24):
                # Long interruption: fire at most one, then schedule next after now.
                base = now
            next_run = compute_next_run(
                frequency=schedule["frequency"],
                timezone=schedule["timezone"],
                run_at=schedule.get("run_at"),
                time_of_day=schedule.get("time_of_day"),
                weekday=schedule.get("weekday"),
                after=base,
            )

        # Claim + advance is one SQLite transaction. The optimistic schedule
        # predicate prevents a stale due-list snapshot from claiming after a
        # concurrent pause/disable/reschedule. Any update error rolls back INSERT.
        with self.db.connection() as db:
            try:
                db.execute(
                    """INSERT INTO task_occurrences(
                           occurrence_id,schedule_id,task_id,planned_at,status,
                           result_summary,claimed_at,finished_at
                       ) VALUES(?,?,?,?,'claimed','',?,NULL)""",
                    (
                        occurrence_id,
                        schedule["id"],
                        schedule["task_id"],
                        planned,
                        claimed_at,
                    ),
                )
            except sqlite3.IntegrityError:
                return None

            if disable_after_claim:
                cursor = db.execute(
                    """UPDATE task_schedules
                       SET enabled=0,last_run_at=?,next_run_at=NULL,updated_at=?
                       WHERE id=? AND enabled=1 AND paused=0 AND next_run_at=?""",
                    (claimed_at, updated_at, schedule["id"], planned),
                )
            else:
                cursor = db.execute(
                    """UPDATE task_schedules
                       SET last_run_at=?,next_run_at=?,updated_at=?
                       WHERE id=? AND enabled=1 AND paused=0 AND next_run_at=?""",
                    (claimed_at, next_run, updated_at, schedule["id"], planned),
                )
            if cursor.rowcount != 1:
                raise RuntimeError("schedule_state_changed_before_claim_commit")

            row = db.execute(
                "SELECT * FROM task_occurrences WHERE occurrence_id=?",
                (occurrence_id,),
            ).fetchone()
        return dict(row) if row else None

    def mark_occurrence_finished(self, occurrence_id: str, *, status: str, result_summary: str = "") -> None:
        self.db.finish_task_occurrence(occurrence_id, status=status, result_summary=result_summary, finished_at=utc_now())
        if self.inbox is not None and status in {"failed", "needs_input", "completed"}:
            occ = self.db.get_task_occurrence(occurrence_id)
            if not occ:
                return
            kind = {"failed": "run_failed", "needs_input": "needs_input", "completed": "run_result"}[status]
            self.inbox.create(
                kind=kind,
                title=f"Geplande run {status}",
                body=result_summary or status,
                ref_type="task_occurrence",
                ref_id=occurrence_id,
                task_id=occ.get("task_id"),
                dedupe_key=f"occurrence:{occurrence_id}:{status}",
            )
