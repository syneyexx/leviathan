"""Tasks / Work Runtime / run-events HTTP routes extracted from main.py (Wave 2)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lm_studio import cancel_lm_run
from reasoning.atomic_budget import shared_budget_pool
from reasoning.events import run_event_bus
from reasoning.specialists import SPECIALISTS

__all__ = [
    "TaskControlInput",
    "TaskCreate",
    "mount_work_routes",
]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=100_000)
    agent: str = Field(default="auto", min_length=1, max_length=80)
    priority: Literal["low", "normal", "high"] = "normal"
    model_id: str | None = Field(default=None, max_length=300)
    auto_start: bool = True
    schedule: dict[str, Any] | None = None


class TaskControlInput(BaseModel):
    action: Literal["pause", "resume", "redirect", "retry_step", "status"] = "status"
    plan_version: int | None = Field(default=None, ge=1, le=10_000)
    instruction: str | None = Field(default=None, max_length=20_000)
    step_id: str | None = Field(default=None, max_length=80)


def mount_work_routes(ctx: dict[str, Any]) -> APIRouter:
    router = APIRouter(tags=["work"])

    class _Svc:
        def __getattr__(self, name: str) -> Any:
            return ctx[name]

        def get(self, name: str, default: Any = None) -> Any:
            return ctx.get(name, default)

    s = _Svc()

    def _ensure() -> None:
        ensure = s.get("ensure_platform_services")
        if callable(ensure):
            ensure()

    @router.get("/tasks")
    async def tasks() -> list[dict[str, Any]]:
        return s.database.list_tasks()

    @router.post("/tasks", status_code=status.HTTP_201_CREATED)
    async def create_task(values: TaskCreate) -> dict[str, Any]:
        agent_id = s.route_agent(values.prompt, values.agent)
        item = s.database.create_task(values.title, values.prompt, agent_id, values.priority, values.model_id)
        schedule_info = None
        if values.schedule:
            try:
                schedule_info = s.schedule_service.attach_schedule(
                    item["id"],
                    frequency=str(values.schedule.get("frequency") or "once"),
                    timezone=str(values.schedule.get("timezone") or "UTC"),
                    run_at=values.schedule.get("run_at"),
                    time_of_day=values.schedule.get("time_of_day"),
                    weekday=values.schedule.get("weekday"),
                    enabled=bool(values.schedule.get("enabled", True)),
                    catch_up=bool(values.schedule.get("catch_up", True)),
                )
                item = {
                    **item,
                    "schedule": schedule_info,
                    "schedule_note": "Lokale planning voert alleen uit terwijl de HADES-backend draait.",
                }
                if not values.auto_start:
                    return item
                # Scheduled tasks should not also auto-start immediately unless requested.
                if values.schedule.get("run_now"):
                    s.runner.schedule(item["id"])
                return item
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if values.auto_start:
            s.runner.schedule(item["id"])
        if schedule_info:
            item = {**item, "schedule": schedule_info}
        return item

    @router.get("/tasks/{task_id}/events")
    async def task_events(task_id: str) -> list[dict[str, Any]]:
        if not s.database.get_task(task_id):
            raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        return s.database.task_events(task_id)

    @router.get("/tasks/{task_id}/work")
    async def task_work(task_id: str) -> dict[str, Any]:
        _ensure()
        if not s.database.get_task(task_id):
            raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        summary = s.platform_db.work_summary(task_id)
        steps = summary.get("steps") or []
        try:
            from reasoning.plan_scheduler import execution_waves

            normalized = [{**step, "step_id": step.get("step_key") or step.get("id")} for step in steps]
            waves = execution_waves(normalized)
        except Exception:
            waves = []
        return {**summary, "waves": waves}

    @router.post("/tasks/{task_id}/run")
    async def run_task(task_id: str) -> dict[str, Any]:
        item = s.database.get_task(task_id)
        if not item:
            raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        if item["status"] != "queued":
            raise HTTPException(status_code=409, detail="Alleen een wachtende taak kan worden gestart.")
        s.runner.schedule(task_id)
        return item

    @router.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str) -> dict[str, Any]:
        item = s.database.get_task(task_id)
        if not item:
            raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        if item["status"] == "running":
            if not s.runner.cancel(task_id):
                raise HTTPException(status_code=409, detail="De lopende taak kon niet worden geannuleerd.")
            # Belt-and-suspenders: await LM cancel so the HTTP response reflects stopped clients (F-16).
            try:
                await cancel_lm_run(task_id)
            except Exception:
                pass
            return s.database.get_task(task_id) or item
        try:
            cancelled = s.database.cancel_task(task_id)
            if cancelled:
                try:
                    await cancel_lm_run(task_id)
                except Exception:
                    pass
            return cancelled or item
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/tasks/{task_id}/retry")
    async def retry_task(task_id: str) -> dict[str, Any]:
        _ensure()
        try:
            item = s.database.retry_task(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not item:
            raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        s.platform_db.clear_work_state(task_id)
        s.database.add_task_event(task_id, "info", "Vorige Work-plan/checkpoints gewist voor een schone retry.")
        s.runner.schedule(task_id)
        return item

    @router.post("/tasks/{task_id}/resume-checkpoint")
    async def resume_task_checkpoint(task_id: str) -> dict[str, Any]:
        """Resume durable work from the latest checkpoint without wiping completed steps."""
        _ensure()
        item = s.database.get_task(task_id)
        if not item:
            raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        if item["status"] not in {"failed", "cancelled", "completed", "queued"}:
            raise HTTPException(status_code=409, detail="Alleen gestopte of wachtende taken kunnen vanaf checkpoint hervatten.")
        checkpoint = s.platform_db.latest_work_checkpoint(task_id)
        steps = s.platform_db.work_steps(task_id)
        if not checkpoint and not steps:
            raise HTTPException(status_code=409, detail="Geen checkpoint of work-stappen om te hervatten.")
        if item["status"] != "queued":
            try:
                item = s.database.retry_task(task_id)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if not item:
                raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        interrupted = s.platform_db.reset_interrupted_work_steps(task_id)
        failed = s.platform_db.reset_failed_work_steps_for_resume(task_id)
        s.platform_db.add_work_checkpoint(
            task_id,
            {
                "phase": "resume_requested",
                "prior_checkpoint_id": checkpoint.get("id") if checkpoint else None,
                "prior_phase": (checkpoint or {}).get("state", {}).get("phase") if checkpoint else None,
                "reset_interrupted": interrupted,
                "reset_failed": failed,
                "kept_completed": sum(1 for step in steps if step.get("status") == "completed"),
            },
        )
        s.database.add_task_event(
            task_id,
            "info",
            f"Hervatten vanaf checkpoint (completed behouden; {failed} failed/cancelled opnieuw in wachtrij).",
        )
        s.runner.schedule(task_id)
        return {
            "task": s.database.get_task(task_id) or item,
            "checkpoint": s.platform_db.latest_work_checkpoint(task_id),
            "work": s.platform_db.work_summary(task_id),
            "resumed": True,
        }

    @router.post("/tasks/{task_id}/control")
    async def control_task(task_id: str, values: TaskControlInput) -> dict[str, Any]:
        _ensure()
        item = s.database.get_task(task_id)
        if not item:
            raise HTTPException(status_code=404, detail="Taak niet gevonden.")
        try:
            if values.action == "status":
                events = [event.to_dict() for event in run_event_bus.history(task_id)]
                work = {
                    "steps": s.platform_db.work_steps(task_id),
                    "checkpoint": s.platform_db.latest_work_checkpoint(task_id),
                }
                return {
                    "task": item,
                    "control_state": item.get("control_state") or "active",
                    "plan_version": item.get("plan_version") or 1,
                    "paused": task_id in s.runner._paused_task_ids,
                    "events": events[-50:],
                    "work": work,
                    "budget_pool": shared_budget_pool.snapshot(),
                }
            if values.action == "pause":
                return {"task": s.runner.pause(task_id), "action": "pause"}
            if values.action == "resume":
                return {"task": s.runner.resume(task_id), "action": "resume"}
            if values.action == "redirect":
                if not (values.instruction or "").strip():
                    raise HTTPException(status_code=422, detail="instruction is verplicht voor redirect.")
                return {
                    "task": s.runner.redirect(task_id, values.instruction or "", plan_version=values.plan_version),
                    "action": "redirect",
                }
            if values.action == "retry_step":
                if not values.step_id:
                    raise HTTPException(status_code=422, detail="step_id is verplicht voor retry_step.")
                step = next(
                    (
                        row
                        for row in s.platform_db.work_steps(task_id)
                        if row["id"] == values.step_id or row.get("step_key") == values.step_id
                    ),
                    None,
                )
                if not step:
                    raise HTTPException(status_code=404, detail="Stap niet gevonden.")
                s.platform_db.update_work_step(
                    step["id"], status="queued", error="Gerichte heruitvoering aangevraagd.", output=""
                )
                s.database.add_task_event(task_id, "info", f"Stap opnieuw gepland: {step['title']}")
                if item["status"] in {"failed", "cancelled", "completed"}:
                    s.database.retry_task(task_id)
                    s.runner.schedule(task_id)
                return {"task": s.database.get_task(task_id), "action": "retry_step", "step_id": step["id"]}
        except KeyError:
            raise HTTPException(status_code=404, detail="Taak niet gevonden.") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=f"Onbekende actie: {values.action}")

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        """Abort inflight LM Studio httpx for this chat/work run. Does not auto-allow tools."""
        result = await cancel_lm_run(run_id)
        try:
            await run_event_bus.emit(run_id, "cancelled", {"reason": "user_cancel"})
        except Exception:
            pass
        return result

    @router.get("/runs/{run_id}/events")
    async def run_events(run_id: str, after: int = Query(default=0, ge=0)) -> dict[str, Any]:
        events = [event.to_dict() for event in run_event_bus.history(run_id, after_sequence=after)]
        # After restart the in-memory buffer may be empty — fall back to durable Gen2 storage.
        if not events:
            try:
                _ensure()
                gen2 = s.get("gen2")
                if gen2 is not None:
                    durable = gen2.store.list_run_events(run_id, after_sequence=after)
                    events = [
                        {
                            "event_id": item.get("id"),
                            "run_id": run_id,
                            "type": item.get("event_type"),
                            "timestamp": item.get("timestamp"),
                            "sequence": item.get("sequence"),
                            "payload": item.get("payload") or {},
                            "provisional": False,
                        }
                        for item in durable
                    ]
            except Exception:
                pass
        latest = run_event_bus.latest(run_id)
        latest_seq = latest.sequence if latest else after
        if events:
            latest_seq = max(latest_seq, max(int(e.get("sequence") or 0) for e in events))
        return {
            "run_id": run_id,
            "events": events,
            "latest_sequence": latest_seq,
            "cursor": {"after_sequence": after, "kind": "sequence"},
        }

    @router.get("/runs/{run_id}/events/stream")
    async def run_events_stream(run_id: str, after: int = Query(default=0, ge=0)) -> StreamingResponse:
        """SSE stream for live tool timeline / progress (Chat, Tasks, Research)."""

        async def event_generator():
            # Atomically subscribe + seed history to avoid gaps between replay and live.
            queue = await run_event_bus.subscribe(run_id, after_sequence=after)
            # If memory was empty (post-restart), seed durable history once before live wait.
            try:
                _ensure()
                gen2 = s.get("gen2")
                if gen2 is not None and run_event_bus.latest(run_id) is None:
                    for item in gen2.store.list_run_events(run_id, after_sequence=after):
                        payload = {
                            "event_id": item.get("id"),
                            "run_id": run_id,
                            "type": item.get("event_type"),
                            "timestamp": item.get("timestamp"),
                            "sequence": item.get("sequence"),
                            "payload": item.get("payload") or {},
                            "provisional": False,
                        }
                        yield f"id: {payload['event_id']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        if payload.get("type") in {"final_outcome", "error", "cancelled"}:
                            return
            except Exception:
                pass
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=25.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if item is None:
                        break
                    yield item.to_sse()
                    if item.type in {"final_outcome", "error", "cancelled"}:
                        break
                    if item.provisional and (item.payload or {}).get("resync_required"):
                        # Client should re-fetch /events?after=… — surface and continue.
                        continue
            finally:
                await run_event_bus.unsubscribe(run_id, queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/specialists")
    async def list_specialists() -> dict[str, Any]:
        _ensure()
        enabled = {item["id"]: item for item in s.platform_db.list_agents()}
        items = []
        for contract in SPECIALISTS.values():
            row = enabled.get(contract.agent_id, {})
            items.append(
                {
                    **contract.to_dict(),
                    "enabled": bool(row.get("enabled", not contract.planned_only)),
                    "db_profile": row,
                }
            )
        return {"items": items, "router": "specialist contracts + deterministic services"}

    @router.get("/runs/{run_id}/inspection")
    async def run_inspection(run_id: str) -> dict[str, Any]:
        """Developer-facing compact execution inspection from real persisted data."""
        _ensure()
        task = s.database.get_task(run_id)
        conversation = s.database.get_conversation(run_id)
        events = [event.to_dict() for event in run_event_bus.history(run_id)]
        payload: dict[str, Any] = {
            "run_id": run_id,
            "events": events[-100:],
            "budget_pool": shared_budget_pool.snapshot(),
        }
        if task:
            steps = s.platform_db.work_steps(run_id)
            checkpoint = s.platform_db.latest_work_checkpoint(run_id)
            payload.update(
                {
                    "kind": "task",
                    "task": task,
                    "steps": steps,
                    "checkpoint": checkpoint,
                    "task_events": s.database.task_events(run_id),
                }
            )
        if conversation:
            payload.update(
                {
                    "kind": payload.get("kind") or "conversation",
                    "conversation": conversation,
                    "working_state": conversation.get("working_state"),
                    "messages": s.database.list_messages(run_id)[-20:],
                }
            )
        if not task and not conversation:
            raise HTTPException(status_code=404, detail="Run niet gevonden als taak of gesprek.")
        return payload

    return router
