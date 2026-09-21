"""Controlled FastAPI lifespan helpers — not a second lifecycle manager.

``main.lifespan`` remains the single owner. These helpers keep startup/shutdown
steps ordered, testable, and free of hidden module-level side effects beyond
the runtime bag passed in by the caller.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class RuntimeBag:
    """Explicit runtime handles owned by the FastAPI lifespan."""

    database: Any
    platform_db: Any
    plugin_manager: Any
    runner: Any
    trading_bot: Any
    schedule_service: Any
    execution_leases: Any
    claim_register: Any
    shared_budget_pool: Any
    sync_model_gateway: Callable[[Any], None]
    build_research_runner: Callable[[], Any]
    build_trading_runner: Callable[[], Any]
    ensure_platform_services: Callable[[], None]
    init_control_service: Callable[[Any, Any], Any]
    data_root: Path
    control_service: Any = None
    research_runner: Any = None
    trading_runner: Any = None
    schedule_ticker: asyncio.Task[Any] | None = None
    native_runtime: Any = None
    notes: list[str] = field(default_factory=list)


def install_cross_store_integrity_triggers(database: Any, platform_db: Any) -> bool:
    """Install fail-closed invariants that span HADES' shared SQLite repositories.

    Core ``Database`` and ``PlatformDatabase`` intentionally point at the same
    SQLite file in production. Conversation learning stores knowledge under
    ``conversation:<id>``. Deleting a conversation must therefore forget that
    material in the *same transaction* as the primary row delete; performing a
    second repository call afterwards can leave a partially deleted state.

    Separate SQLite paths are a supported test/development topology and return
    ``False`` because a cross-store SQLite trigger is impossible there. Once
    both repositories point at the same file, however, missing schema or trigger
    installation errors are fatal: continuing would make conversation deletion
    appear successful without the required atomic knowledge-forget guarantee.

    The trigger removes searchable FTS/chunk material and marks the source as
    forgotten before SQLite permits the conversation row to disappear. Any
    trigger error aborts the DELETE and the core connection rolls back.
    """
    try:
        core_path = Path(getattr(database, "path")).resolve()
        platform_path = Path(getattr(platform_db, "path")).resolve()
    except Exception:
        return False
    if core_path != platform_path:
        return False

    with database.connection() as db:
        tables = {
            str(row[0])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('conversations','knowledge_sources','knowledge_chunks','knowledge_fts')"
            ).fetchall()
        }
        required = {"conversations", "knowledge_sources", "knowledge_chunks", "knowledge_fts"}
        if tables != required:
            missing = sorted(required - tables)
            raise RuntimeError(
                "Shared SQLite mist tabellen voor conversation-forget invariant: "
                + ", ".join(missing)
            )
        db.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS trg_hades_conversation_forget_knowledge
            BEFORE DELETE ON conversations
            FOR EACH ROW
            BEGIN
                DELETE FROM knowledge_fts
                WHERE chunk_id IN (
                    SELECT kc.id
                    FROM knowledge_chunks AS kc
                    JOIN knowledge_sources AS ks ON ks.id = kc.source_id
                    WHERE ks.uri = 'conversation:' || OLD.id
                );

                DELETE FROM knowledge_chunks
                WHERE source_id IN (
                    SELECT id FROM knowledge_sources
                    WHERE uri = 'conversation:' || OLD.id
                );

                UPDATE knowledge_sources
                SET status = 'forgotten'
                WHERE uri = 'conversation:' || OLD.id;
            END;
            """
        )
    return True


async def startup(rt: RuntimeBag) -> RuntimeBag:
    """Initialize persistence, recover interrupted work, start background tickers.

    Callers should prefer building the bag after ``ensure_platform_services`` so
    ``platform_db`` matches a swapped test database. Startup re-syncs anyway and
    refreshes bag handles when ensure returns a rebound store.
    """
    rt.database.initialize()
    rebound = rt.ensure_platform_services()
    if rebound is not None and rebound is not rt.platform_db:
        rt.platform_db = rebound
        # Plugin manager is rebound together with platform_db in main.ensure_platform_services.
        try:
            import main as main_mod

            rt.plugin_manager = main_mod.plugin_manager
            rt.trading_bot = main_mod.trading_bot
            rt.schedule_service = main_mod.schedule_service
            rt.data_root = Path(main_mod.data_root)
        except Exception:
            pass
    rt.control_service = rt.init_control_service(rt.database, rt.platform_db)
    rt.platform_db.initialize()
    try:
        if install_cross_store_integrity_triggers(rt.database, rt.platform_db):
            rt.notes.append("cross_store_integrity_triggers_ready")
        else:
            rt.notes.append("cross_store_integrity_triggers_unavailable")
    except Exception as exc:
        # On a shared production SQLite this invariant is part of the privacy
        # contract. Never continue startup after an installation/schema failure.
        rt.notes.append(f"cross_store_integrity_trigger_failed:{exc}")
        raise RuntimeError("Shared SQLite conversation-forget invariant kon niet worden geïnstalleerd") from exc
    rt.platform_db.recover_running_tool_calls()
    rt.plugin_manager.reconcile_services()

    # Deterministic DB path diagnostics — detect accidental multi-file writes.
    try:
        from execution_truth import format_db_startup_log, resolve_sqlite_paths
        import logging

        db_path = str(Path(getattr(rt.database, "path", rt.data_root / "hades.db")).resolve())
        paths = resolve_sqlite_paths(database_path=db_path, data_root=str(rt.data_root))
        logging.getLogger("hades.db").info(format_db_startup_log(paths))
        logging.getLogger("hades.db").info(
            "[DB] data_root=%s embeddings=%s artifacts=%s",
            paths.get("data_root"),
            paths.get("embedding_index"),
            paths.get("artifacts_root"),
        )
        print(format_db_startup_log(paths), flush=True)
        rt.notes.append(f"sqlite:{paths.get('sqlite_path')}")
    except Exception as exc:
        rt.notes.append(f"db_path_log_failed:{exc}")

    # Lease/fencing state is part of crash-recovery correctness. If its durable
    # snapshot cannot be loaded or reconciled, continuing would silently treat an
    # unknown execution state as empty and could let stale work resume unfenced.
    lease_path = rt.data_root / "execution_leases.json"
    try:
        rt.execution_leases.set_persist_path(lease_path)
        reclaimed = rt.execution_leases.reclaim_stale()
        restored = rt.execution_leases.restore_control_from_tasks(rt.database.list_tasks())
        if reclaimed or restored.get("paused") or restored.get("pause_requested"):
            rt.notes.append("leases_restored")
    except Exception as exc:
        rt.notes.append(f"lease_restore_failed:{exc}")
        raise RuntimeError("execution lease recovery failed; refusing startup") from exc

    # Claims use their own durable store. Preserve the historical fail-soft
    # attach behavior here; F-049 is specifically about execution fencing state.
    claim_path = rt.data_root / "claims.sqlite"
    try:
        rt.claim_register.set_db_path(claim_path)
    except Exception:
        rt.notes.append("claim_restore_skipped")

    settings = rt.control_service.global_values()
    concurrency = settings.get("max_concurrent_tasks")
    if concurrency is not None:
        rt.runner.set_concurrency(int(concurrency))
    rt.shared_budget_pool.configure(rt.control_service.shared_budget_config())
    rt.sync_model_gateway(settings)

    # Native companion (optional acceleration). Mode auto → start when binary present.
    try:
        from native_runtime import NativeRuntimeClient, configure_native_client, repo_root, set_native_client

        def _settings_getter() -> dict:
            try:
                return dict(rt.control_service.global_values() or {})
            except Exception:
                return {}

        native = configure_native_client(settings_getter=_settings_getter, repo=repo_root())
        rt.native_runtime = native
        mode = native.resolve_mode()
        if mode != "disabled":
            started = native.ensure_started()
            if started:
                rt.notes.append("native_runtime_started")
            elif mode == "enabled":
                rt.notes.append("native_runtime_missing")
            else:
                rt.notes.append("native_runtime_fallback")
        else:
            rt.notes.append("native_runtime_disabled")
        # Wire PluginManager executor without changing policy.
        attach = getattr(rt.plugin_manager, "set_native_runtime", None)
        if callable(attach):
            attach(native if native.status().connected else None)
    except Exception:
        rt.notes.append("native_runtime_init_skipped")

    rt.research_runner = rt.build_research_runner()
    rt.trading_runner = rt.build_trading_runner()

    for task_id in rt.database.recover_running_tasks():
        rt.runner.schedule(task_id)
    for project in rt.platform_db.list_research_projects():
        if project["status"] == "running":
            rt.platform_db.update_research_project(
                project["id"],
                status="queued",
                progress=0,
                error="Backend herstart; veilig hervat.",
            )
            rt.research_runner.schedule(project["id"])
    for run in rt.trading_bot.list_runs(100):
        if run["status"] == "running":
            rt.trading_bot.update_run(
                run["id"],
                status="queued",
                progress=0,
                error="Backend herstart; veilig hervat.",
            )
            rt.trading_runner.schedule(run["id"])
        elif run["status"] == "queued":
            rt.trading_runner.schedule(run["id"])

    rt.schedule_ticker = asyncio.create_task(rt.runner.schedule_ticker(), name="hades-schedule-ticker")

    # F-15: prune unbounded event tables when logging.retention_days is set.
    try:
        from retention import run_retention_job

        retention = await asyncio.to_thread(
            run_retention_job,
            database=rt.database,
            platform_db=rt.platform_db,
            settings=settings if isinstance(settings, dict) else {},
        )
        if retention.get("skipped"):
            rt.notes.append("retention_skipped")
        else:
            deleted = retention.get("deleted") or {}
            total = sum(int(v or 0) for v in deleted.values())
            rt.notes.append(f"retention_pruned:{total}")
    except Exception as exc:
        rt.notes.append(f"retention_failed:{type(exc).__name__}")

    return rt


async def shutdown(rt: RuntimeBag) -> None:
    """Drain workers; best-effort cancel of the schedule ticker."""
    if rt.schedule_ticker is not None:
        rt.schedule_ticker.cancel()
        try:
            await rt.schedule_ticker
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        rt.schedule_ticker = None
    await rt.runner.shutdown()
    if rt.research_runner:
        await rt.research_runner.shutdown()
    if rt.trading_runner:
        await rt.trading_runner.shutdown()
    # Stop native companion after workers drain so in-flight process.run can finish.
    try:
        native = rt.native_runtime
        if native is not None:
            native.shutdown()
            rt.notes.append("native_runtime_stopped")
        attach = getattr(rt.plugin_manager, "set_native_runtime", None)
        if callable(attach):
            attach(None)
    except Exception:
        rt.notes.append("native_runtime_shutdown_skipped")
    # Release claims.sqlite so Windows TemporaryDirectory cleanup can delete it.
    try:
        from sqlite_runtime import wal_owner

        wal_owner.truncate_file(rt.database.path)
        platform_path = getattr(rt.platform_db, "path", None)
        if platform_path and str(platform_path) != str(rt.database.path):
            wal_owner.truncate_file(platform_path)
    except Exception:
        rt.notes.append("wal_truncate_skipped")
    try:
        if rt.claim_register is None:
            pass
        else:
            detach = getattr(rt.claim_register, "detach", None)
            if callable(detach):
                detach()
            elif hasattr(rt.claim_register, "set_db_path"):
                rt.claim_register.set_db_path(None)
    except Exception:
        rt.notes.append("claim_detach_skipped")
