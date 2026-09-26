"""Central SQLite persistence for market_sim (single leviathan.db)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    ClosedTrade,
    DeliberationMessage,
    MarketDataSource,
    MarketSimError,
    SimFill,
    SimRun,
    StrategyRecord,
    StrategyVersion,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class MarketSimStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            conn.close()


    def initialize(self) -> None:
        from Data.backend.migrations import MigrationRunner
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
        MigrationRunner(self.db_path).apply_all()

    # --- Sources ---

    def upsert_source(self, source: MarketDataSource) -> MarketDataSource:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_data_sources(
                    source_id, symbol, timeframe, kind, path, content_hash, status,
                    bar_count, start_ts, end_ts, byte_size, validation_error,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    timeframe=excluded.timeframe,
                    kind=excluded.kind,
                    path=excluded.path,
                    content_hash=excluded.content_hash,
                    status=excluded.status,
                    bar_count=excluded.bar_count,
                    start_ts=excluded.start_ts,
                    end_ts=excluded.end_ts,
                    byte_size=excluded.byte_size,
                    validation_error=excluded.validation_error,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    source.source_id,
                    source.symbol,
                    source.timeframe,
                    source.kind,
                    source.path,
                    source.content_hash,
                    source.status,
                    source.bar_count,
                    source.start_ts,
                    source.end_ts,
                    source.byte_size,
                    source.validation_error,
                    json.dumps(source.metadata),
                    source.created_at,
                    source.updated_at,
                ),
            )
            # Also unique on path — if another row owns the path, update that row.
            conn.execute(
                """
                UPDATE market_data_sources SET
                    symbol=?, timeframe=?, kind=?, content_hash=?, status=?,
                    bar_count=?, start_ts=?, end_ts=?, byte_size=?,
                    validation_error=?, metadata_json=?, updated_at=?
                WHERE path=? AND source_id!=?
                """,
                (
                    source.symbol,
                    source.timeframe,
                    source.kind,
                    source.content_hash,
                    source.status,
                    source.bar_count,
                    source.start_ts,
                    source.end_ts,
                    source.byte_size,
                    source.validation_error,
                    json.dumps(source.metadata),
                    source.updated_at,
                    source.path,
                    source.source_id,
                ),
            )
        return source

    def get_source(self, source_id: str) -> MarketDataSource | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_data_sources WHERE source_id=?",
                (source_id,),
            ).fetchone()
        return self._row_source(row) if row else None

    def get_source_by_path(self, path: str) -> MarketDataSource | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_data_sources WHERE path=?",
                (path,),
            ).fetchone()
        return self._row_source(row) if row else None

    def list_sources(self, *, status: str | None = None, limit: int = 200) -> list[MarketDataSource]:
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM market_data_sources WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM market_data_sources ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_source(r) for r in rows]

    def _row_source(self, row: sqlite3.Row) -> MarketDataSource:
        return MarketDataSource(
            source_id=row["source_id"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            kind=row["kind"],
            path=row["path"],
            content_hash=row["content_hash"],
            status=row["status"],
            bar_count=row["bar_count"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            byte_size=row["byte_size"],
            validation_error=row["validation_error"],
            metadata=_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Strategies ---

    def create_strategy(self, record: StrategyRecord, version: StrategyVersion) -> StrategyRecord:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_strategies(
                    strategy_id, name, description, status, tags_json, current_version,
                    content_hash, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.strategy_id,
                    record.name,
                    record.description,
                    record.status,
                    json.dumps(record.tags),
                    record.current_version,
                    record.content_hash,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.metadata),
                ),
            )
            self._insert_version(conn, version)
        return record

    def _insert_version(self, conn: sqlite3.Connection, version: StrategyVersion) -> None:
        conn.execute(
            """
            INSERT INTO market_strategy_versions(
                version_id, strategy_id, version, content_hash, parameters_json,
                entry_rules_json, exit_rules_json, risk_rules_json,
                required_timeframes_json, brain_dependencies_json,
                created_at, changelog, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.version_id,
                version.strategy_id,
                version.version,
                version.content_hash,
                json.dumps(version.parameters),
                json.dumps(version.entry_rules),
                json.dumps(version.exit_rules),
                json.dumps(version.risk_rules),
                json.dumps(version.required_timeframes),
                json.dumps(version.brain_dependencies),
                version.created_at,
                version.changelog,
                json.dumps(version.metadata),
            ),
        )

    def update_strategy_head(self, record: StrategyRecord, version: StrategyVersion) -> StrategyRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE market_strategies SET
                    name=?, description=?, status=?, tags_json=?, current_version=?,
                    content_hash=?, updated_at=?, metadata_json=?
                WHERE strategy_id=?
                """,
                (
                    record.name,
                    record.description,
                    record.status,
                    json.dumps(record.tags),
                    record.current_version,
                    record.content_hash,
                    record.updated_at,
                    json.dumps(record.metadata),
                    record.strategy_id,
                ),
            )
            self._insert_version(conn, version)
        return record

    def get_strategy(self, strategy_id: str) -> StrategyRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_strategies WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
        return self._row_strategy(row) if row else None

    def list_strategies(self, *, limit: int = 200) -> list[StrategyRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_strategies ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_strategy(r) for r in rows]

    def get_strategy_version(
        self, strategy_id: str, version: int | None = None
    ) -> StrategyVersion | None:
        with self.connect() as conn:
            if version is None:
                row = conn.execute(
                    """
                    SELECT * FROM market_strategy_versions
                    WHERE strategy_id=? ORDER BY version DESC LIMIT 1
                    """,
                    (strategy_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM market_strategy_versions
                    WHERE strategy_id=? AND version=?
                    """,
                    (strategy_id, version),
                ).fetchone()
        return self._row_strategy_version(row) if row else None

    def list_strategy_versions(self, strategy_id: str) -> list[StrategyVersion]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_strategy_versions
                WHERE strategy_id=? ORDER BY version DESC
                """,
                (strategy_id,),
            ).fetchall()
        return [self._row_strategy_version(r) for r in rows]

    def _row_strategy(self, row: sqlite3.Row) -> StrategyRecord:
        return StrategyRecord(
            strategy_id=row["strategy_id"],
            name=row["name"],
            description=row["description"],
            status=row["status"],
            tags=_loads(row["tags_json"], []),
            current_version=row["current_version"],
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=_loads(row["metadata_json"], {}),
        )

    def _row_strategy_version(self, row: sqlite3.Row) -> StrategyVersion:
        return StrategyVersion(
            version_id=row["version_id"],
            strategy_id=row["strategy_id"],
            version=row["version"],
            content_hash=row["content_hash"],
            parameters=_loads(row["parameters_json"], {}),
            entry_rules=_loads(row["entry_rules_json"], {}),
            exit_rules=_loads(row["exit_rules_json"], {}),
            risk_rules=_loads(row["risk_rules_json"], {}),
            required_timeframes=_loads(row["required_timeframes_json"], []),
            brain_dependencies=_loads(row["brain_dependencies_json"], []),
            created_at=row["created_at"],
            changelog=row["changelog"] or "",
            metadata=_loads(row["metadata_json"], {}),
        )

    # --- Runs ---

    def create_run(self, run: SimRun) -> SimRun:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_runs(
                    run_id, status, source_id, strategy_id, strategy_version,
                    symbol, timeframe, start_ts, end_ts, data_hash, seed, speed,
                    initial_cash, fee_bps, slippage_bps, max_position_pct,
                    max_drawdown_pct, per_trade_risk_pct, agents_json,
                    deliberation_every_n, clock_ts, bar_index, bar_count,
                    cash, equity, position_qty, realized_pnl, unrealized_pnl,
                    causality_violations, brain_hits, brain_misses,
                    metrics_json, error, worker_pid, cancel_requested,
                    created_at, updated_at, started_at, finished_at, metadata_json
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                self._run_params(run),
            )
        return run

    def _run_params(self, run: SimRun) -> tuple[Any, ...]:
        return (
            run.run_id,
            run.status,
            run.source_id,
            run.strategy_id,
            run.strategy_version,
            run.symbol,
            run.timeframe,
            run.start_ts,
            run.end_ts,
            run.data_hash,
            run.seed,
            run.speed,
            run.initial_cash,
            run.fee_bps,
            run.slippage_bps,
            run.max_position_pct,
            run.max_drawdown_pct,
            run.per_trade_risk_pct,
            json.dumps(run.agents),
            run.deliberation_every_n,
            run.clock_ts,
            run.bar_index,
            run.bar_count,
            run.cash,
            run.equity,
            run.position_qty,
            run.realized_pnl,
            run.unrealized_pnl,
            run.causality_violations,
            run.brain_hits,
            run.brain_misses,
            json.dumps(run.metrics),
            run.error,
            run.worker_pid,
            1 if run.cancel_requested else 0,
            run.created_at,
            run.updated_at,
            run.started_at,
            run.finished_at,
            json.dumps(run.metadata),
        )

    def update_run(self, run: SimRun) -> SimRun:
        run.updated_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE market_sim_runs SET
                    status=?, source_id=?, strategy_id=?, strategy_version=?,
                    symbol=?, timeframe=?, start_ts=?, end_ts=?, data_hash=?, seed=?, speed=?,
                    initial_cash=?, fee_bps=?, slippage_bps=?, max_position_pct=?,
                    max_drawdown_pct=?, per_trade_risk_pct=?, agents_json=?,
                    deliberation_every_n=?, clock_ts=?, bar_index=?, bar_count=?,
                    cash=?, equity=?, position_qty=?, realized_pnl=?, unrealized_pnl=?,
                    causality_violations=?, brain_hits=?, brain_misses=?,
                    metrics_json=?, error=?, worker_pid=?, cancel_requested=?,
                    updated_at=?, started_at=?, finished_at=?, metadata_json=?
                WHERE run_id=?
                """,
                (
                    run.status,
                    run.source_id,
                    run.strategy_id,
                    run.strategy_version,
                    run.symbol,
                    run.timeframe,
                    run.start_ts,
                    run.end_ts,
                    run.data_hash,
                    run.seed,
                    run.speed,
                    run.initial_cash,
                    run.fee_bps,
                    run.slippage_bps,
                    run.max_position_pct,
                    run.max_drawdown_pct,
                    run.per_trade_risk_pct,
                    json.dumps(run.agents),
                    run.deliberation_every_n,
                    run.clock_ts,
                    run.bar_index,
                    run.bar_count,
                    run.cash,
                    run.equity,
                    run.position_qty,
                    run.realized_pnl,
                    run.unrealized_pnl,
                    run.causality_violations,
                    run.brain_hits,
                    run.brain_misses,
                    json.dumps(run.metrics),
                    run.error,
                    run.worker_pid,
                    1 if run.cancel_requested else 0,
                    run.updated_at,
                    run.started_at,
                    run.finished_at,
                    json.dumps(run.metadata),
                    run.run_id,
                ),
            )
        return run

    def get_run(self, run_id: str) -> SimRun | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_sim_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        return self._row_run(row) if row else None

    def list_runs(self, *, status: str | None = None, limit: int = 100) -> list[SimRun]:
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM market_sim_runs WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM market_sim_runs ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_run(r) for r in rows]

    def claim_next_runnable(self) -> SimRun | None:
        """Claim one QUEUED or RUNNING (without fresh lease) run for the worker.

        Uses BEGIN IMMEDIATE so two workers cannot double-claim the same run.
        """
        import os

        pid = os.getpid()
        self.expire_stale_leases()
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM market_sim_runs
                WHERE status IN ('QUEUED', 'RUNNING', 'STEPPING')
                  AND (worker_pid IS NULL OR status='STEPPING')
                  AND cancel_requested=0
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            run = self._row_run(row)
            now = utc_now()
            cols = {r[1] for r in conn.execute("PRAGMA table_info(market_sim_runs)").fetchall()}
            if "lease_heartbeat_ts" in cols:
                cur = conn.execute(
                    "UPDATE market_sim_runs SET worker_pid=?, lease_heartbeat_ts=?, updated_at=? "
                    "WHERE run_id=? AND (worker_pid IS NULL OR worker_pid=? OR status='STEPPING')",
                    (pid, now, now, run.run_id, pid),
                )
            else:
                cur = conn.execute(
                    "UPDATE market_sim_runs SET worker_pid=?, updated_at=? "
                    "WHERE run_id=? AND (worker_pid IS NULL OR worker_pid=? OR status='STEPPING')",
                    (pid, now, run.run_id, pid),
                )
            if cur.rowcount == 0:
                conn.rollback()
                return None
            meta = dict(run.metadata or {})
            meta["lease_heartbeat_ts"] = now
            conn.execute(
                "UPDATE market_sim_runs SET metadata_json=? WHERE run_id=?",
                (json.dumps(meta), run.run_id),
            )
            conn.commit()
            run.worker_pid = pid
            run.metadata = meta
            return run
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def heartbeat_run_lease(self, run_id: str, *, worker_pid: int | None = None) -> bool:
        """Fresh heartbeat while holding a run. Returns False if lease not held by this worker."""
        import os

        pid = worker_pid if worker_pid is not None else os.getpid()
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT worker_pid, metadata_json FROM market_sim_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                return False
            held = row["worker_pid"]
            if held is not None and int(held) != int(pid):
                return False
            cols = {r[1] for r in conn.execute("PRAGMA table_info(market_sim_runs)").fetchall()}
            meta = _loads(row["metadata_json"], {})
            meta["lease_heartbeat_ts"] = now
            if "lease_heartbeat_ts" in cols:
                conn.execute(
                    "UPDATE market_sim_runs SET worker_pid=?, lease_heartbeat_ts=?, metadata_json=?, updated_at=? WHERE run_id=?",
                    (pid, now, json.dumps(meta), now, run_id),
                )
            else:
                conn.execute(
                    "UPDATE market_sim_runs SET worker_pid=?, metadata_json=?, updated_at=? WHERE run_id=?",
                    (pid, json.dumps(meta), now, run_id),
                )
        return True

    def expire_stale_leases(self, *, stale_after_seconds: int = 120) -> int:
        """Clear worker_pid on runs whose lease heartbeat is stale. Returns count expired."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=stale_after_seconds)).isoformat(timespec="seconds")
        expired = 0
        with self.connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(market_sim_runs)").fetchall()}
            rows = conn.execute(
                """
                SELECT run_id, worker_pid, metadata_json
                FROM market_sim_runs
                WHERE worker_pid IS NOT NULL
                  AND status IN ('QUEUED', 'RUNNING', 'STEPPING', 'PAUSED')
                """
            ).fetchall()
            for row in rows:
                meta = _loads(row["metadata_json"], {})
                hb = None
                if "lease_heartbeat_ts" in cols:
                    try:
                        hb = row["lease_heartbeat_ts"]
                    except (KeyError, IndexError):
                        hb = None
                hb = hb or meta.get("lease_heartbeat_ts")
                if not hb:
                    # No heartbeat yet — treat updated_at via metadata absence as stale only if old claim
                    continue
                if str(hb) < cutoff:
                    meta.pop("lease_heartbeat_ts", None)
                    if "lease_heartbeat_ts" in cols:
                        conn.execute(
                            "UPDATE market_sim_runs SET worker_pid=NULL, lease_heartbeat_ts=NULL, metadata_json=?, updated_at=? WHERE run_id=?",
                            (json.dumps(meta), utc_now(), row["run_id"]),
                        )
                    else:
                        conn.execute(
                            "UPDATE market_sim_runs SET worker_pid=NULL, metadata_json=?, updated_at=? WHERE run_id=?",
                            (json.dumps(meta), utc_now(), row["run_id"]),
                        )
                    expired += 1
        return expired

    def _row_run(self, row: sqlite3.Row) -> SimRun:
        meta = _loads(row["metadata_json"], {})
        sizing = meta.get("sizing_model") or meta.get("sizingModel") or {
            "kind": "risk_pct",
            "perTradeRiskPct": row["per_trade_risk_pct"],
            "maxPositionPct": row["max_position_pct"],
        }
        return SimRun(
            run_id=row["run_id"],
            status=row["status"],
            source_id=row["source_id"],
            strategy_id=row["strategy_id"],
            strategy_version=row["strategy_version"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            data_hash=row["data_hash"],
            seed=row["seed"],
            speed=row["speed"],
            initial_cash=row["initial_cash"],
            fee_bps=row["fee_bps"],
            slippage_bps=row["slippage_bps"],
            max_position_pct=row["max_position_pct"],
            max_drawdown_pct=row["max_drawdown_pct"],
            per_trade_risk_pct=row["per_trade_risk_pct"],
            agents=_loads(row["agents_json"], []),
            deliberation_every_n=row["deliberation_every_n"],
            clock_ts=row["clock_ts"],
            bar_index=row["bar_index"],
            bar_count=row["bar_count"],
            cash=row["cash"],
            equity=row["equity"],
            position_qty=row["position_qty"],
            realized_pnl=row["realized_pnl"],
            unrealized_pnl=row["unrealized_pnl"],
            causality_violations=row["causality_violations"],
            brain_hits=row["brain_hits"],
            brain_misses=row["brain_misses"],
            metrics=_loads(row["metrics_json"], {}),
            error=row["error"],
            worker_pid=row["worker_pid"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            metadata=meta,
            sizing_model=sizing if isinstance(sizing, dict) else {"kind": "risk_pct"},
        )

    # --- Fills / messages / equity ---

    def add_fill(self, fill: SimFill) -> SimFill:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_fills(
                    fill_id, run_id, bar_index, ts, side, qty, price, fee, slippage,
                    agent_id, rationale, status, created_at,
                    realized_delta, remaining_qty, order_type, fill_price_source,
                    observed_execution, decision_bar_index, intent_id, trade_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.fill_id,
                    fill.run_id,
                    fill.bar_index,
                    fill.ts,
                    fill.side,
                    fill.qty,
                    fill.price,
                    fill.fee,
                    fill.slippage,
                    fill.agent_id,
                    fill.rationale,
                    fill.status,
                    fill.created_at,
                    fill.realized_delta,
                    fill.remaining_qty,
                    fill.order_type,
                    fill.fill_price_source,
                    1 if fill.observed_execution else 0,
                    fill.decision_bar_index,
                    fill.intent_id,
                    fill.trade_id,
                ),
            )
        return fill

    def _fill_from_row(self, r: Any) -> SimFill:
        keys = set(r.keys()) if hasattr(r, "keys") else set()
        def _opt(name: str, default: Any = None) -> Any:
            if name not in keys:
                return default
            return r[name]

        return SimFill(
            fill_id=r["fill_id"],
            run_id=r["run_id"],
            bar_index=r["bar_index"],
            ts=r["ts"],
            side=r["side"],
            qty=r["qty"],
            price=r["price"],
            fee=r["fee"],
            slippage=r["slippage"],
            agent_id=r["agent_id"],
            rationale=r["rationale"],
            status=r["status"],
            created_at=r["created_at"],
            realized_delta=_opt("realized_delta"),
            remaining_qty=_opt("remaining_qty"),
            order_type=str(_opt("order_type") or "MARKET"),
            fill_price_source=str(_opt("fill_price_source") or "next_bar_open"),
            observed_execution=bool(_opt("observed_execution") or 0),
            decision_bar_index=_opt("decision_bar_index"),
            intent_id=_opt("intent_id"),
            trade_id=_opt("trade_id"),
        )

    def list_fills(self, run_id: str, *, limit: int = 500) -> list[SimFill]:
        """Return up to ``limit`` most recent fills in chronological order."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM market_sim_fills
                    WHERE run_id=?
                    ORDER BY bar_index DESC, created_at DESC
                    LIMIT ?
                ) sub
                ORDER BY bar_index ASC, created_at ASC
                """,
                (run_id, limit),
            ).fetchall()
        return [self._fill_from_row(r) for r in rows]

    def add_closed_trade(self, trade: ClosedTrade) -> ClosedTrade:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_closed_trades(
                    trade_id, run_id, instrument, strategy_id, strategy_version,
                    opened_at, closed_at, side, entry_quantity, exit_quantity,
                    avg_entry_price, avg_exit_price, gross_pnl, fees, slippage_cost,
                    net_pnl, holding_period_bars, partial_fill_count, close_reason,
                    open_bar_index, close_bar_index, agent_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.trade_id,
                    trade.run_id,
                    trade.instrument,
                    trade.strategy_id,
                    trade.strategy_version,
                    trade.opened_at,
                    trade.closed_at,
                    trade.side,
                    trade.entry_quantity,
                    trade.exit_quantity,
                    trade.avg_entry_price,
                    trade.avg_exit_price,
                    trade.gross_pnl,
                    trade.fees,
                    trade.slippage_cost,
                    trade.net_pnl,
                    trade.holding_period_bars,
                    trade.partial_fill_count,
                    trade.close_reason,
                    trade.open_bar_index,
                    trade.close_bar_index,
                    trade.agent_id,
                    json.dumps(trade.metadata),
                ),
            )
        return trade

    def list_closed_trades(self, run_id: str, *, limit: int = 500) -> list[ClosedTrade]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_closed_trades
                WHERE run_id=?
                ORDER BY close_bar_index ASC, closed_at ASC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [
            ClosedTrade(
                trade_id=r["trade_id"],
                run_id=r["run_id"],
                instrument=r["instrument"],
                strategy_id=r["strategy_id"],
                strategy_version=r["strategy_version"],
                opened_at=r["opened_at"],
                closed_at=r["closed_at"],
                side=r["side"],
                entry_quantity=r["entry_quantity"],
                exit_quantity=r["exit_quantity"],
                avg_entry_price=r["avg_entry_price"],
                avg_exit_price=r["avg_exit_price"],
                gross_pnl=r["gross_pnl"],
                fees=r["fees"],
                slippage_cost=r["slippage_cost"],
                net_pnl=r["net_pnl"],
                holding_period_bars=r["holding_period_bars"],
                partial_fill_count=r["partial_fill_count"],
                close_reason=r["close_reason"],
                open_bar_index=r["open_bar_index"],
                close_bar_index=r["close_bar_index"],
                agent_id=r["agent_id"],
                metadata=_loads(r["metadata_json"], {}),
            )
            for r in rows
        ]

    def add_message(self, msg: DeliberationMessage) -> DeliberationMessage:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_messages(
                    message_id, run_id, bar_index, ts, agent_id, role, kind,
                    content, proposal_json, confidence, brain_refs_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.message_id,
                    msg.run_id,
                    msg.bar_index,
                    msg.ts,
                    msg.agent_id,
                    msg.role,
                    msg.kind,
                    msg.content,
                    json.dumps(msg.proposal),
                    msg.confidence,
                    json.dumps(msg.brain_refs),
                    msg.created_at,
                ),
            )
        return msg

    def list_messages(self, run_id: str, *, limit: int = 500) -> list[DeliberationMessage]:
        """Return up to ``limit`` most recent messages in chronological order."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM market_sim_messages
                    WHERE run_id=?
                    ORDER BY bar_index DESC, created_at DESC
                    LIMIT ?
                ) sub
                ORDER BY bar_index ASC, created_at ASC
                """,
                (run_id, limit),
            ).fetchall()
        return [
            DeliberationMessage(
                message_id=r["message_id"],
                run_id=r["run_id"],
                bar_index=r["bar_index"],
                ts=r["ts"],
                agent_id=r["agent_id"],
                role=r["role"],
                kind=r["kind"],
                content=r["content"],
                proposal=_loads(r["proposal_json"], {}),
                confidence=r["confidence"],
                brain_refs=_loads(r["brain_refs_json"], []),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def add_equity_point(
        self, run_id: str, bar_index: int, ts: str, equity: float, cash: float, position_qty: float
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_equity(
                    point_id, run_id, bar_index, ts, equity, cash, position_qty, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), run_id, bar_index, ts, equity, cash, position_qty, utc_now()),
            )

    def list_equity(self, run_id: str, *, limit: int = 5000) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent equity points in chronological order."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT bar_index, ts, equity, cash, position_qty FROM (
                    SELECT bar_index, ts, equity, cash, position_qty
                    FROM market_sim_equity
                    WHERE run_id=?
                    ORDER BY bar_index DESC
                    LIMIT ?
                ) sub
                ORDER BY bar_index ASC
                """,
                (run_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_event(
        self,
        run_id: str,
        *,
        kind: str,
        payload: dict[str, Any] | None = None,
        bar_index: int | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_events(
                    event_id, run_id, bar_index, kind, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    run_id,
                    bar_index,
                    kind,
                    json.dumps(payload or {}),
                    utc_now(),
                ),
            )


    # --- Paper sessions / experiments / strategy memory (v34) ---

    def upsert_paper_session(self, session: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_paper_sessions(
                    session_id, status, broker_id, provider_id, symbol, strategy_id,
                    strategy_version, kill_switch, feed_status, wallet_json, orders_json,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status=excluded.status,
                    strategy_id=excluded.strategy_id,
                    strategy_version=excluded.strategy_version,
                    broker_id=excluded.broker_id,
                    provider_id=excluded.provider_id,
                    symbol=excluded.symbol,
                    kill_switch=excluded.kill_switch,
                    feed_status=excluded.feed_status,
                    wallet_json=excluded.wallet_json,
                    orders_json=excluded.orders_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    session["session_id"],
                    session["status"],
                    session["broker_id"],
                    session["provider_id"],
                    session["symbol"],
                    session.get("strategy_id"),
                    session.get("strategy_version"),
                    1 if session.get("kill_switch") else 0,
                    session.get("feed_status", "unknown"),
                    json.dumps(session.get("wallet") or {}),
                    json.dumps(session.get("orders") or []),
                    json.dumps(session.get("metadata") or {}),
                    session.get("created_at") or utc_now(),
                    session.get("updated_at") or utc_now(),
                ),
            )
        return session

    def get_paper_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_paper_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "session_id": row["session_id"],
            "status": row["status"],
            "broker_id": row["broker_id"],
            "provider_id": row["provider_id"],
            "symbol": row["symbol"],
            "strategy_id": row["strategy_id"],
            "strategy_version": row["strategy_version"],
            "kill_switch": bool(row["kill_switch"]),
            "feed_status": row["feed_status"],
            "wallet": _loads(row["wallet_json"], {}),
            "orders": _loads(row["orders_json"], []),
            "metadata": _loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_paper_sessions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT session_id FROM market_paper_sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            s = self.get_paper_session(r["session_id"])
            if s:
                out.append(s)
        return out

    def save_experiment(self, trial: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_experiments(
                    trial_id, strategy_id, strategy_version, hypothesis, proposer_agent_id,
                    data_hash, fingerprint, status, config_json, split_json, results_json,
                    acceptance_json, rejection_reason, seed, created_at, finished_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trial_id) DO UPDATE SET
                    strategy_version=excluded.strategy_version,
                    status=excluded.status,
                    results_json=excluded.results_json,
                    split_json=excluded.split_json,
                    acceptance_json=excluded.acceptance_json,
                    rejection_reason=excluded.rejection_reason,
                    finished_at=excluded.finished_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    trial["trial_id"],
                    trial["strategy_id"],
                    trial.get("strategy_version"),
                    trial["hypothesis"],
                    trial["proposer_agent_id"],
                    trial["data_hash"],
                    trial.get("fingerprint", ""),
                    trial["status"],
                    json.dumps(trial.get("config") or {}),
                    json.dumps(trial.get("split") or {}),
                    json.dumps(trial.get("results") or {}),
                    json.dumps(trial.get("acceptance_criteria") or {}),
                    trial.get("rejection_reason") or "",
                    trial.get("seed", 42),
                    trial.get("created_at") or utc_now(),
                    trial.get("finished_at"),
                    json.dumps(trial.get("metadata") or {}),
                ),
            )
        return trial

    def append_trial(self, trial: dict[str, Any]) -> dict[str, Any]:
        """Append-only Trial Ledger entry — never overwrites prior trial_id rows.

        Uses a new trial_id when colliding so the global ledger remains append-only.
        """
        import uuid as _uuid

        payload = dict(trial)
        existing = None
        tid = str(payload.get("trial_id") or "")
        if tid:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT trial_id FROM market_experiments WHERE trial_id=?",
                    (tid,),
                ).fetchone()
            if row:
                payload["trial_id"] = str(_uuid.uuid4())
                meta = dict(payload.get("metadata") or {})
                meta["supersedes_trial_id"] = tid
                meta["append_only"] = True
                payload["metadata"] = meta
        else:
            payload["trial_id"] = str(_uuid.uuid4())
        meta = dict(payload.get("metadata") or {})
        meta.setdefault("append_only", True)
        meta.setdefault("ledger", "global_trial_ledger")
        payload["metadata"] = meta
        return self.save_experiment(payload)

    def count_trials(self, *, strategy_id: str | None = None) -> int:
        with self.connect() as conn:
            if strategy_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM market_experiments WHERE strategy_id=?",
                    (strategy_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM market_experiments").fetchone()
        return int(row["c"] if row else 0)

    def list_experiments(self, *, strategy_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if strategy_id:
                rows = conn.execute(
                    "SELECT * FROM market_experiments WHERE strategy_id=? ORDER BY created_at DESC LIMIT ?",
                    (strategy_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM market_experiments ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "trial_id": r["trial_id"],
                "strategy_id": r["strategy_id"],
                "strategy_version": r["strategy_version"],
                "hypothesis": r["hypothesis"],
                "proposer_agent_id": r["proposer_agent_id"],
                "data_hash": r["data_hash"],
                "fingerprint": r["fingerprint"],
                "status": r["status"],
                "config": _loads(r["config_json"], {}),
                "split": _loads(r["split_json"], {}),
                "results": _loads(r["results_json"], {}),
                "acceptance_criteria": _loads(r["acceptance_json"], {}),
                "rejection_reason": r["rejection_reason"],
                "seed": r["seed"],
                "created_at": r["created_at"],
                "finished_at": r["finished_at"],
                "metadata": _loads(r["metadata_json"], {}),
            }
            for r in rows
        ]

    def find_experiment_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT trial_id FROM market_experiments WHERE fingerprint=? LIMIT 1",
                (fingerprint,),
            ).fetchone()
        if not row:
            return None
        trials = self.list_experiments(limit=1000)
        for t in trials:
            if t["trial_id"] == row["trial_id"]:
                return t
        return None

    def save_strategy_memory(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_strategy_memories(
                    memory_id, strategy_id, strategy_version, features_json, applicability_json,
                    outcome_summary, trial_id, available_at, created_at, rejected, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["memory_id"],
                    entry["strategy_id"],
                    entry["strategy_version"],
                    json.dumps(entry.get("features") or {}),
                    json.dumps(entry.get("applicability") or {}),
                    entry.get("outcome_summary") or "",
                    entry.get("trial_id"),
                    entry["available_at"],
                    entry.get("created_at") or utc_now(),
                    1 if entry.get("rejected") else 0,
                    json.dumps(entry.get("metadata") or {}),
                ),
            )
        return entry

    def list_strategy_memories(
        self, *, strategy_id: str | None = None, as_of_ts: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            sql = "SELECT * FROM market_strategy_memories WHERE 1=1"
            params: list[Any] = []
            if strategy_id:
                sql += " AND strategy_id=?"
                params.append(strategy_id)
            if as_of_ts:
                sql += " AND available_at<=?"
                params.append(as_of_ts)
            sql += " ORDER BY available_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "memory_id": r["memory_id"],
                "strategy_id": r["strategy_id"],
                "strategy_version": r["strategy_version"],
                "features": _loads(r["features_json"], {}),
                "applicability": _loads(r["applicability_json"], {}),
                "outcome_summary": r["outcome_summary"],
                "trial_id": r["trial_id"],
                "available_at": r["available_at"],
                "created_at": r["created_at"],
                "rejected": bool(r["rejected"]),
                "metadata": _loads(r["metadata_json"], {}),
            }
            for r in rows
        ]

    def list_events(self, run_id: str, *, kind: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if kind:
                rows = conn.execute(
                    """
                    SELECT * FROM market_sim_events
                    WHERE run_id=? AND kind=? ORDER BY created_at ASC LIMIT ?
                    """,
                    (run_id, kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM market_sim_events
                    WHERE run_id=? ORDER BY created_at ASC LIMIT ?
                    """,
                    (run_id, limit),
                ).fetchall()
        return [
            {
                "event_id": r["event_id"],
                "run_id": r["run_id"],
                "bar_index": r["bar_index"],
                "kind": r["kind"],
                "payload": _loads(r["payload_json"], {}),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # --- Sealed market datasets + knowledge snapshots (T1) ---

    def upsert_dataset_version(self, dataset: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_dataset_versions(
                    dataset_id, version, source_id, symbol, timeframe, venue,
                    instrument_family, provider, timezone, start_ts, end_ts,
                    bar_count, content_hash, adjustment_mode, quality_state,
                    quality_json, provenance_json, known_gaps_json, sealed,
                    sealed_at, path, parent_version, role, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id, version) DO UPDATE SET
                    source_id=excluded.source_id,
                    symbol=excluded.symbol,
                    timeframe=excluded.timeframe,
                    venue=excluded.venue,
                    instrument_family=excluded.instrument_family,
                    provider=excluded.provider,
                    timezone=excluded.timezone,
                    start_ts=excluded.start_ts,
                    end_ts=excluded.end_ts,
                    bar_count=excluded.bar_count,
                    content_hash=excluded.content_hash,
                    adjustment_mode=excluded.adjustment_mode,
                    quality_state=excluded.quality_state,
                    quality_json=excluded.quality_json,
                    provenance_json=excluded.provenance_json,
                    known_gaps_json=excluded.known_gaps_json,
                    sealed=excluded.sealed,
                    sealed_at=excluded.sealed_at,
                    path=excluded.path,
                    parent_version=excluded.parent_version,
                    role=excluded.role,
                    metadata_json=excluded.metadata_json
                """,
                (
                    dataset["dataset_id"],
                    dataset["version"],
                    dataset.get("source_id"),
                    dataset["symbol"],
                    dataset["timeframe"],
                    dataset.get("venue") or "",
                    dataset.get("instrument_family") or "",
                    dataset.get("provider") or "csv_local",
                    dataset.get("timezone") or "UTC",
                    dataset["start_ts"],
                    dataset["end_ts"],
                    int(dataset.get("bar_count") or 0),
                    dataset["content_hash"],
                    dataset.get("adjustment_mode") or "as_traded",
                    dataset.get("quality_state") or "READY",
                    json.dumps(dataset.get("quality") or {}),
                    json.dumps(dataset.get("provenance") or {}),
                    json.dumps(dataset.get("known_gaps") or []),
                    1 if dataset.get("sealed") else 0,
                    dataset.get("sealed_at"),
                    dataset["path"],
                    dataset.get("parent_version"),
                    dataset.get("role") or "RESEARCH",
                    dataset.get("created_at") or utc_now(),
                    json.dumps(dataset.get("metadata") or {}),
                ),
            )
        return dataset

    def get_dataset_version(self, dataset_id: str, version: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_dataset_versions WHERE dataset_id=? AND version=?",
                (dataset_id, version),
            ).fetchone()
        return self._row_dataset(row) if row else None

    def get_dataset_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_dataset_versions WHERE content_hash=? ORDER BY created_at DESC LIMIT 1",
                (content_hash,),
            ).fetchone()
        return self._row_dataset(row) if row else None

    def list_dataset_versions(
        self,
        *,
        dataset_id: str | None = None,
        symbol: str | None = None,
        sealed: bool | None = None,
        role: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            sql = "SELECT * FROM market_dataset_versions WHERE 1=1"
            params: list[Any] = []
            if dataset_id:
                sql += " AND dataset_id=?"
                params.append(dataset_id)
            if symbol:
                sql += " AND symbol=?"
                params.append(symbol.upper())
            if sealed is not None:
                sql += " AND sealed=?"
                params.append(1 if sealed else 0)
            if role:
                sql += " AND role=?"
                params.append(role)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        return [self._row_dataset(r) for r in rows]

    def _row_dataset(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "dataset_id": row["dataset_id"],
            "version": row["version"],
            "source_id": row["source_id"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "venue": row["venue"],
            "instrument_family": row["instrument_family"],
            "provider": row["provider"],
            "timezone": row["timezone"],
            "start_ts": row["start_ts"],
            "end_ts": row["end_ts"],
            "bar_count": row["bar_count"],
            "content_hash": row["content_hash"],
            "adjustment_mode": row["adjustment_mode"],
            "quality_state": row["quality_state"],
            "quality": _loads(row["quality_json"], {}),
            "provenance": _loads(row["provenance_json"], {}),
            "known_gaps": _loads(row["known_gaps_json"], []),
            "sealed": bool(row["sealed"]),
            "sealed_at": row["sealed_at"],
            "path": row["path"],
            "parent_version": row["parent_version"],
            "role": row["role"],
            "created_at": row["created_at"],
            "metadata": _loads(row["metadata_json"], {}),
        }

    def save_knowledge_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = snapshot.get("snapshot_id") or str(uuid.uuid4())
        created = snapshot.get("created_at") or utc_now()
        payload = dict(snapshot)
        payload["snapshot_id"] = snapshot_id
        payload["created_at"] = created
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_knowledge_snapshots(
                    snapshot_id, run_id, as_of, snapshot_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    payload["run_id"],
                    payload["as_of"],
                    payload.get("snapshot_hash") or "",
                    json.dumps(payload),
                    created,
                ),
            )
        return payload

    def get_knowledge_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_knowledge_snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        if not row:
            return None
        return _loads(row["payload_json"], {})

    def list_knowledge_snapshots(self, run_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM market_knowledge_snapshots
                WHERE run_id=? ORDER BY created_at DESC LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [_loads(r["payload_json"], {}) for r in rows]

    # --- P1A: DatasetSplitManifest + SEALED attempts ---

    def upsert_split_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_split_manifest(
            dataset_id=manifest["dataset_id"],
            dataset_version=manifest["dataset_version"],
        )
        if existing and existing.get("frozen"):
            # Frozen manifests are immutable — identical re-upsert is idempotent.
            if (
                existing.get("manifest_id") == manifest.get("manifest_id")
                and existing.get("train") == (manifest.get("train") or {})
                and existing.get("val") == manifest.get("val")
                and existing.get("sealed") == manifest.get("sealed")
            ):
                return existing
            raise MarketSimError(
                "SPLIT_MANIFEST_FROZEN",
                f"{manifest['dataset_id']}@{manifest['dataset_version']} split is frozen",
                http_status=409,
            )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_split_manifests(
                    manifest_id, dataset_id, dataset_version, dataset_content_hash,
                    train_json, val_json, sealed_json, train_frac, val_frac, sealed_frac,
                    embargo_bars, frozen, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id, dataset_version) DO UPDATE SET
                    manifest_id=excluded.manifest_id,
                    dataset_content_hash=excluded.dataset_content_hash,
                    train_json=excluded.train_json,
                    val_json=excluded.val_json,
                    sealed_json=excluded.sealed_json,
                    train_frac=excluded.train_frac,
                    val_frac=excluded.val_frac,
                    sealed_frac=excluded.sealed_frac,
                    embargo_bars=excluded.embargo_bars,
                    frozen=excluded.frozen,
                    metadata_json=excluded.metadata_json
                """,
                (
                    manifest["manifest_id"],
                    manifest["dataset_id"],
                    manifest["dataset_version"],
                    manifest.get("dataset_content_hash") or "",
                    json.dumps(manifest.get("train") or {}),
                    json.dumps(manifest.get("val")) if manifest.get("val") is not None else None,
                    json.dumps(manifest.get("sealed")) if manifest.get("sealed") is not None else None,
                    float(manifest.get("train_frac") or 0.0),
                    float(manifest.get("val_frac") or 0.0),
                    float(manifest.get("sealed_frac") or 0.0),
                    int(manifest.get("embargo_bars") or 0),
                    1 if manifest.get("frozen") else 0,
                    manifest.get("created_at") or utc_now(),
                    json.dumps(manifest.get("metadata") or {}),
                ),
            )
        return self.get_split_manifest(
            dataset_id=manifest["dataset_id"],
            dataset_version=manifest["dataset_version"],
        ) or manifest

    def get_split_manifest(
        self,
        *,
        dataset_id: str | None = None,
        dataset_version: str | None = None,
        manifest_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            if manifest_id:
                row = conn.execute(
                    "SELECT * FROM market_sim_split_manifests WHERE manifest_id=?",
                    (manifest_id,),
                ).fetchone()
            elif dataset_id and dataset_version:
                row = conn.execute(
                    "SELECT * FROM market_sim_split_manifests WHERE dataset_id=? AND dataset_version=?",
                    (dataset_id, dataset_version),
                ).fetchone()
            else:
                return None
        return self._row_split_manifest(row) if row else None

    def _row_split_manifest(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "manifest_id": row["manifest_id"],
            "dataset_id": row["dataset_id"],
            "dataset_version": row["dataset_version"],
            "dataset_content_hash": row["dataset_content_hash"],
            "train": _loads(row["train_json"], {}),
            "val": _loads(row["val_json"], None) if row["val_json"] else None,
            "sealed": _loads(row["sealed_json"], None) if row["sealed_json"] else None,
            "train_frac": float(row["train_frac"]),
            "val_frac": float(row["val_frac"]),
            "sealed_frac": float(row["sealed_frac"]),
            "embargo_bars": int(row["embargo_bars"]),
            "frozen": bool(row["frozen"]),
            "created_at": row["created_at"],
            "metadata": _loads(row["metadata_json"], {}),
        }

    def upsert_sealed_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_sealed_attempts(
                    sealed_attempt_id, dataset_id, dataset_version, split_manifest_id,
                    strategy_id, strategy_version, run_id, status, bound_at,
                    checkpoint_bar_index, completed_at, failure_reason, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sealed_attempt_id) DO UPDATE SET
                    status=excluded.status,
                    checkpoint_bar_index=excluded.checkpoint_bar_index,
                    completed_at=excluded.completed_at,
                    failure_reason=excluded.failure_reason,
                    metadata_json=excluded.metadata_json
                """,
                (
                    attempt["sealed_attempt_id"],
                    attempt["dataset_id"],
                    attempt["dataset_version"],
                    attempt.get("split_manifest_id") or "",
                    attempt["strategy_id"],
                    int(attempt.get("strategy_version") or 0),
                    attempt["run_id"],
                    attempt["status"],
                    attempt.get("bound_at") or utc_now(),
                    int(attempt.get("checkpoint_bar_index") or 0),
                    attempt.get("completed_at"),
                    attempt.get("failure_reason") or "",
                    json.dumps(attempt.get("metadata") or {}),
                ),
            )
        return attempt

    def get_sealed_attempt(self, sealed_attempt_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_sim_sealed_attempts WHERE sealed_attempt_id=?",
                (sealed_attempt_id,),
            ).fetchone()
        return self._row_sealed_attempt(row) if row else None

    def find_sealed_attempt(
        self,
        *,
        dataset_id: str,
        dataset_version: str,
        strategy_id: str,
        strategy_version: int,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM market_sim_sealed_attempts
                WHERE dataset_id=? AND dataset_version=? AND strategy_id=? AND strategy_version=?
                LIMIT 1
                """,
                (dataset_id, dataset_version, strategy_id, int(strategy_version)),
            ).fetchone()
        return self._row_sealed_attempt(row) if row else None

    def _row_sealed_attempt(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "sealed_attempt_id": row["sealed_attempt_id"],
            "dataset_id": row["dataset_id"],
            "dataset_version": row["dataset_version"],
            "split_manifest_id": row["split_manifest_id"],
            "strategy_id": row["strategy_id"],
            "strategy_version": int(row["strategy_version"]),
            "run_id": row["run_id"],
            "status": row["status"],
            "bound_at": row["bound_at"],
            "checkpoint_bar_index": int(row["checkpoint_bar_index"]),
            "completed_at": row["completed_at"],
            "failure_reason": row["failure_reason"] or "",
            "metadata": _loads(row["metadata_json"], {}),
        }

    # --- Research campaigns (P3B) ---

    def upsert_research_campaign(self, campaign: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_research_campaigns(
                    campaign_id, name, strategy_id, strategy_version, source_id, status,
                    max_iterations, checkpoint_iteration, current_iteration, seed,
                    hypothesis, acceptance_criteria_json, trial_ids_json, results_json,
                    scorecard_json, promotion_json, autonomy_ceiling, as_of, job_id,
                    error, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    max_iterations=excluded.max_iterations,
                    checkpoint_iteration=excluded.checkpoint_iteration,
                    current_iteration=excluded.current_iteration,
                    hypothesis=excluded.hypothesis,
                    acceptance_criteria_json=excluded.acceptance_criteria_json,
                    trial_ids_json=excluded.trial_ids_json,
                    results_json=excluded.results_json,
                    scorecard_json=excluded.scorecard_json,
                    promotion_json=excluded.promotion_json,
                    autonomy_ceiling=excluded.autonomy_ceiling,
                    as_of=excluded.as_of,
                    job_id=excluded.job_id,
                    error=excluded.error,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    campaign["campaign_id"],
                    campaign.get("name") or "",
                    campaign["strategy_id"],
                    int(campaign["strategy_version"]),
                    campaign["source_id"],
                    campaign.get("status") or "CREATED",
                    int(campaign.get("max_iterations") or 10),
                    int(campaign.get("checkpoint_iteration") or 0),
                    int(campaign.get("current_iteration") or 0),
                    int(campaign.get("seed") or 42),
                    campaign.get("hypothesis") or "",
                    json.dumps(campaign.get("acceptance_criteria") or {}),
                    json.dumps(campaign.get("trial_ids") or []),
                    json.dumps(campaign.get("results") or {}),
                    json.dumps(campaign.get("scorecard") or {}),
                    json.dumps(campaign.get("promotion") or {}),
                    campaign.get("autonomy_ceiling") or "A2",
                    campaign.get("as_of") or "",
                    campaign.get("job_id"),
                    campaign.get("error") or "",
                    campaign.get("created_at") or utc_now(),
                    campaign.get("updated_at") or utc_now(),
                    json.dumps(campaign.get("metadata") or {}),
                ),
            )
        return campaign

    def get_research_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_sim_research_campaigns WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
        return self._row_research_campaign(row)

    def list_research_campaigns(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_research_campaigns
                ORDER BY updated_at DESC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row_research_campaign(r) for r in rows if r]

    def _row_research_campaign(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "campaign_id": row["campaign_id"],
            "name": row["name"],
            "strategy_id": row["strategy_id"],
            "strategy_version": int(row["strategy_version"]),
            "source_id": row["source_id"],
            "status": row["status"],
            "max_iterations": int(row["max_iterations"]),
            "checkpoint_iteration": int(row["checkpoint_iteration"]),
            "current_iteration": int(row["current_iteration"]),
            "seed": int(row["seed"]),
            "hypothesis": row["hypothesis"] or "",
            "acceptance_criteria": _loads(row["acceptance_criteria_json"], {}),
            "trial_ids": _loads(row["trial_ids_json"], []),
            "results": _loads(row["results_json"], {}),
            "scorecard": _loads(row["scorecard_json"], {}),
            "promotion": _loads(row["promotion_json"], {}),
            "autonomy_ceiling": row["autonomy_ceiling"] or "A2",
            "as_of": row["as_of"] or "",
            "job_id": row["job_id"],
            "error": row["error"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": _loads(row["metadata_json"], {}),
        }

    # --- Agent labs (W16) ---

    def upsert_agent_lab(self, lab: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_agent_labs(
                    lab_id, name, status, outcome, strategy_id, strategy_version, source_id,
                    campaign_id, max_candidates, acceptance_json, candidates_json, lessons_json,
                    sealed_lineages_json, curriculum_json, job_id, error, created_at, updated_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lab_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    outcome=excluded.outcome,
                    strategy_id=excluded.strategy_id,
                    strategy_version=excluded.strategy_version,
                    source_id=excluded.source_id,
                    campaign_id=excluded.campaign_id,
                    max_candidates=excluded.max_candidates,
                    acceptance_json=excluded.acceptance_json,
                    candidates_json=excluded.candidates_json,
                    lessons_json=excluded.lessons_json,
                    sealed_lineages_json=excluded.sealed_lineages_json,
                    curriculum_json=excluded.curriculum_json,
                    job_id=excluded.job_id,
                    error=excluded.error,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    lab["lab_id"],
                    lab.get("name") or "",
                    lab.get("status") or "CREATED",
                    lab.get("outcome") or "IN_PROGRESS",
                    lab.get("strategy_id"),
                    lab.get("strategy_version"),
                    lab.get("source_id"),
                    lab.get("campaign_id"),
                    int(lab.get("max_candidates") or 10),
                    json.dumps(lab.get("acceptance") or {}),
                    json.dumps(lab.get("candidates") or []),
                    json.dumps(lab.get("lessons") or []),
                    json.dumps(lab.get("sealed_lineages_consumed") or {}),
                    json.dumps(lab.get("curriculum") or {}),
                    lab.get("job_id"),
                    lab.get("error") or "",
                    lab.get("created_at") or utc_now(),
                    lab.get("updated_at") or utc_now(),
                    json.dumps(lab.get("metadata") or {}),
                ),
            )
        return lab

    def get_agent_lab(self, lab_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_sim_agent_labs WHERE lab_id=?",
                (lab_id,),
            ).fetchone()
        return self._row_agent_lab(row)

    def list_agent_labs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_agent_labs
                ORDER BY updated_at DESC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row_agent_lab(r) for r in rows if r]

    def _row_agent_lab(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "lab_id": row["lab_id"],
            "name": row["name"] or "",
            "status": row["status"] or "CREATED",
            "outcome": row["outcome"] or "IN_PROGRESS",
            "strategy_id": row["strategy_id"],
            "strategy_version": row["strategy_version"],
            "source_id": row["source_id"],
            "campaign_id": row["campaign_id"],
            "max_candidates": int(row["max_candidates"] or 10),
            "acceptance": _loads(row["acceptance_json"], {}),
            "candidates": _loads(row["candidates_json"], []),
            "lessons": _loads(row["lessons_json"], []),
            "sealed_lineages_consumed": _loads(row["sealed_lineages_json"], {}),
            "curriculum": _loads(row["curriculum_json"], {}),
            "job_id": row["job_id"],
            "error": row["error"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": _loads(row["metadata_json"], {}),
            "truth": {
                "scientific_search_not_profit_hunting": True,
                "no_strategy_qualified_is_valid_pass": True,
                "live_trading": "BLOCKED",
            },
        }

    # --- Strategy Learning Runs ---

    def upsert_learning_run(self, run: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_learning_runs(
                    learning_run_id, lab_id, campaign_id, status, stage, strategy_id,
                    parent_strategy_version, source_id, algorithm, algorithm_version, seed,
                    current_generation, generation_budget, trial_budget, trials_used,
                    population_size, objective_hash, input_fingerprint, objective_json,
                    learner_state_json, candidates_json, generation_summaries_json,
                    split_refs_json, best_train_candidate, best_validation_candidate,
                    qualified_candidate, job_id, error, pause_requested, cancel_requested,
                    rng_state_json, created_at, updated_at, last_checkpoint_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(learning_run_id) DO UPDATE SET
                    lab_id=excluded.lab_id,
                    campaign_id=excluded.campaign_id,
                    status=excluded.status,
                    stage=excluded.stage,
                    strategy_id=excluded.strategy_id,
                    parent_strategy_version=excluded.parent_strategy_version,
                    source_id=excluded.source_id,
                    algorithm=excluded.algorithm,
                    algorithm_version=excluded.algorithm_version,
                    seed=excluded.seed,
                    current_generation=excluded.current_generation,
                    generation_budget=excluded.generation_budget,
                    trial_budget=excluded.trial_budget,
                    trials_used=excluded.trials_used,
                    population_size=excluded.population_size,
                    objective_hash=excluded.objective_hash,
                    input_fingerprint=excluded.input_fingerprint,
                    objective_json=excluded.objective_json,
                    learner_state_json=excluded.learner_state_json,
                    candidates_json=excluded.candidates_json,
                    generation_summaries_json=excluded.generation_summaries_json,
                    split_refs_json=excluded.split_refs_json,
                    best_train_candidate=excluded.best_train_candidate,
                    best_validation_candidate=excluded.best_validation_candidate,
                    qualified_candidate=excluded.qualified_candidate,
                    job_id=excluded.job_id,
                    error=excluded.error,
                    pause_requested=excluded.pause_requested,
                    cancel_requested=excluded.cancel_requested,
                    rng_state_json=excluded.rng_state_json,
                    updated_at=excluded.updated_at,
                    last_checkpoint_at=excluded.last_checkpoint_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    run["learning_run_id"],
                    run.get("lab_id"),
                    run.get("campaign_id"),
                    run.get("status") or "CREATED",
                    run.get("stage") or "CREATED",
                    run.get("strategy_id") or "",
                    int(run.get("parent_strategy_version") or 1),
                    run.get("source_id") or "",
                    run.get("algorithm") or "adaptive_evolutionary_strategy_search",
                    run.get("algorithm_version") or "1.0.0",
                    int(run.get("seed") or 42),
                    int(run.get("current_generation") or 0),
                    int(run.get("generation_budget") or 8),
                    int(run.get("trial_budget") or 96),
                    int(run.get("trials_used") or 0),
                    int(run.get("population_size") or 12),
                    run.get("objective_hash") or "",
                    run.get("input_fingerprint") or "",
                    json.dumps(run.get("objective_spec") or {}),
                    json.dumps(run.get("learner_state") or {}),
                    json.dumps(run.get("candidates") or []),
                    json.dumps(run.get("generation_summaries") or []),
                    json.dumps(
                        {
                            "train": run.get("train_split_ref") or {},
                            "val": run.get("validation_split_ref") or {},
                            "robustness": run.get("robustness_split_ref") or {},
                            "sealed": run.get("sealed_split_ref") or {},
                        }
                    ),
                    run.get("best_train_candidate"),
                    run.get("best_validation_candidate"),
                    run.get("qualified_candidate"),
                    run.get("job_id"),
                    run.get("error") or "",
                    1 if run.get("pause_requested") else 0,
                    1 if run.get("cancel_requested") else 0,
                    json.dumps(run.get("rng_state")),
                    run.get("created_at") or utc_now(),
                    run.get("updated_at") or utc_now(),
                    run.get("last_checkpoint_at") or "",
                    json.dumps(run.get("metadata") or {}),
                ),
            )
        return run

    def get_learning_run(self, learning_run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_sim_learning_runs WHERE learning_run_id=?",
                (learning_run_id,),
            ).fetchone()
        return self._row_learning_run(row)

    def get_learning_run_by_lab(self, lab_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM market_sim_learning_runs
                WHERE lab_id=?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (lab_id,),
            ).fetchone()
        return self._row_learning_run(row)

    def list_learning_runs(self, *, lab_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if lab_id:
                rows = conn.execute(
                    """
                    SELECT * FROM market_sim_learning_runs
                    WHERE lab_id=?
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (lab_id, max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM market_sim_learning_runs
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        return [self._row_learning_run(r) for r in rows if r]

    def _row_learning_run(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        splits = _loads(row["split_refs_json"], {})
        return {
            "learning_run_id": row["learning_run_id"],
            "lab_id": row["lab_id"],
            "campaign_id": row["campaign_id"],
            "status": row["status"] or "CREATED",
            "stage": row["stage"] or "CREATED",
            "strategy_id": row["strategy_id"],
            "parent_strategy_version": int(row["parent_strategy_version"] or 1),
            "source_id": row["source_id"],
            "algorithm": row["algorithm"],
            "algorithm_version": row["algorithm_version"],
            "seed": int(row["seed"] or 42),
            "current_generation": int(row["current_generation"] or 0),
            "generation_budget": int(row["generation_budget"] or 8),
            "trial_budget": int(row["trial_budget"] or 96),
            "trials_used": int(row["trials_used"] or 0),
            "population_size": int(row["population_size"] or 12),
            "objective_hash": row["objective_hash"] or "",
            "input_fingerprint": row["input_fingerprint"] or "",
            "objective_spec": _loads(row["objective_json"], {}),
            "learner_state": _loads(row["learner_state_json"], {}),
            "candidates": _loads(row["candidates_json"], []),
            "generation_summaries": _loads(row["generation_summaries_json"], []),
            "train_split_ref": dict(splits.get("train") or {}),
            "validation_split_ref": dict(splits.get("val") or {}),
            "robustness_split_ref": dict(splits.get("robustness") or {}),
            "sealed_split_ref": dict(splits.get("sealed") or {}),
            "best_train_candidate": row["best_train_candidate"],
            "best_validation_candidate": row["best_validation_candidate"],
            "qualified_candidate": row["qualified_candidate"],
            "job_id": row["job_id"],
            "error": row["error"] or "",
            "pause_requested": bool(row["pause_requested"]),
            "cancel_requested": bool(row["cancel_requested"]),
            "rng_state": _loads(row["rng_state_json"], None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_checkpoint_at": row["last_checkpoint_at"] or "",
            "metadata": _loads(row["metadata_json"], {}),
            "truth": {
                "adaptive_dsl_learning": True,
                "sealed_never_trains_learner": True,
                "live_trading": "BLOCKED",
            },
        }

    # --- Paper Portefeuille ---

    def upsert_portfolio(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_portfolios(
                    portfolio_id, name, status, mode, base_currency, broker_mode,
                    provider_id, benchmark_symbol, orchestra_id, initial_equity,
                    cash, reserved_cash, realized_pnl, unrealized_pnl, fees_paid,
                    equity, peak_equity, margin_used, gross_exposure, net_exposure,
                    kill_switch, shorting_enabled, sod_equity, sod_date, last_mark_at,
                    book_json, settings_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(portfolio_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    orchestra_id=excluded.orchestra_id,
                    cash=excluded.cash,
                    reserved_cash=excluded.reserved_cash,
                    realized_pnl=excluded.realized_pnl,
                    unrealized_pnl=excluded.unrealized_pnl,
                    fees_paid=excluded.fees_paid,
                    equity=excluded.equity,
                    peak_equity=excluded.peak_equity,
                    margin_used=excluded.margin_used,
                    gross_exposure=excluded.gross_exposure,
                    net_exposure=excluded.net_exposure,
                    kill_switch=excluded.kill_switch,
                    shorting_enabled=excluded.shorting_enabled,
                    sod_equity=excluded.sod_equity,
                    sod_date=excluded.sod_date,
                    last_mark_at=excluded.last_mark_at,
                    book_json=excluded.book_json,
                    settings_json=excluded.settings_json,
                    metadata_json=excluded.metadata_json,
                    benchmark_symbol=excluded.benchmark_symbol,
                    updated_at=excluded.updated_at
                """,
                (
                    row["portfolio_id"],
                    row["name"],
                    row.get("status") or "CREATED",
                    row.get("mode") or "PAPER",
                    row.get("base_currency") or "USD",
                    row.get("broker_mode") or "local_paper",
                    row.get("provider_id") or "binance_public",
                    row.get("benchmark_symbol") or "BTCUSDT",
                    row.get("orchestra_id"),
                    str(row.get("initial_equity") or "100000"),
                    str(row.get("cash") or "0"),
                    str(row.get("reserved_cash") or "0"),
                    str(row.get("realized_pnl") or "0"),
                    str(row.get("unrealized_pnl") or "0"),
                    str(row.get("fees_paid") or "0"),
                    str(row.get("equity") or "0"),
                    str(row.get("peak_equity") or "0"),
                    str(row.get("margin_used") or "0"),
                    str(row.get("gross_exposure") or "0"),
                    str(row.get("net_exposure") or "0"),
                    1 if row.get("kill_switch") else 0,
                    1 if row.get("shorting_enabled") else 0,
                    row.get("sod_equity"),
                    row.get("sod_date"),
                    row.get("last_mark_at"),
                    json.dumps(row.get("book_json") or {}),
                    json.dumps(row.get("settings") or {}),
                    json.dumps(row.get("metadata") or {}),
                    row.get("created_at") or utc_now(),
                    row.get("updated_at") or utc_now(),
                ),
            )
        return row

    def get_portfolio(self, portfolio_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_sim_portfolios WHERE portfolio_id=?",
                (portfolio_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_portfolio(row)

    def list_portfolios(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_sim_portfolios ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row_portfolio(r) for r in rows]

    def _row_portfolio(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "portfolio_id": row["portfolio_id"],
            "name": row["name"],
            "status": row["status"],
            "mode": row["mode"],
            "base_currency": row["base_currency"],
            "broker_mode": row["broker_mode"],
            "provider_id": row["provider_id"],
            "benchmark_symbol": row["benchmark_symbol"],
            "orchestra_id": row["orchestra_id"],
            "initial_equity": row["initial_equity"],
            "cash": row["cash"],
            "reserved_cash": row["reserved_cash"],
            "realized_pnl": row["realized_pnl"],
            "unrealized_pnl": row["unrealized_pnl"],
            "fees_paid": row["fees_paid"],
            "equity": row["equity"],
            "peak_equity": row["peak_equity"],
            "margin_used": row["margin_used"],
            "gross_exposure": row["gross_exposure"],
            "net_exposure": row["net_exposure"],
            "kill_switch": bool(row["kill_switch"]),
            "shorting_enabled": bool(row["shorting_enabled"]),
            "sod_equity": row["sod_equity"],
            "sod_date": row["sod_date"],
            "last_mark_at": row["last_mark_at"],
            "book_json": _loads(row["book_json"], {}),
            "settings": _loads(row["settings_json"], {}),
            "metadata": _loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def insert_portfolio_snapshot(self, snap: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_sim_portfolio_snapshots(
                    snapshot_id, portfolio_id, timestamp, equity, cash,
                    realized_pnl, unrealized_pnl, gross_exposure, net_exposure,
                    margin_used, drawdown, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap["snapshot_id"],
                    snap["portfolio_id"],
                    snap["timestamp"],
                    str(snap["equity"]),
                    str(snap["cash"]),
                    str(snap.get("realized_pnl") or "0"),
                    str(snap.get("unrealized_pnl") or "0"),
                    str(snap.get("gross_exposure") or "0"),
                    str(snap.get("net_exposure") or "0"),
                    str(snap.get("margin_used") or "0"),
                    str(snap.get("drawdown") or "0"),
                    json.dumps(snap.get("metadata") or {}),
                ),
            )
        return snap

    def list_portfolio_snapshots(self, portfolio_id: str, *, limit: int = 2000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_portfolio_snapshots
                WHERE portfolio_id=? ORDER BY timestamp ASC LIMIT ?
                """,
                (portfolio_id, max(1, int(limit))),
            ).fetchall()
        return [
            {
                "snapshot_id": r["snapshot_id"],
                "portfolio_id": r["portfolio_id"],
                "timestamp": r["timestamp"],
                "equity": r["equity"],
                "cash": r["cash"],
                "realized_pnl": r["realized_pnl"],
                "unrealized_pnl": r["unrealized_pnl"],
                "gross_exposure": r["gross_exposure"],
                "net_exposure": r["net_exposure"],
                "margin_used": r["margin_used"],
                "drawdown": r["drawdown"],
                "metadata": _loads(r["metadata_json"], {}),
            }
            for r in rows
        ]

    def latest_portfolio_snapshot(self, portfolio_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM market_sim_portfolio_snapshots
                WHERE portfolio_id=? ORDER BY timestamp DESC LIMIT 1
                """,
                (portfolio_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "snapshot_id": row["snapshot_id"],
            "portfolio_id": row["portfolio_id"],
            "timestamp": row["timestamp"],
            "equity": row["equity"],
            "cash": row["cash"],
            "metadata": _loads(row["metadata_json"], {}),
        }

    def insert_portfolio_transaction(self, tx: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO market_sim_portfolio_transactions(
                    transaction_id, portfolio_id, order_id, fill_id, decision_id,
                    symbol, side, qty, price, gross_notional, fees, net_cash_effect,
                    result, agent_id, orchestra_id, strategy_id, strategy_version,
                    risk_result_json, market_snapshot_id, timestamp, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx["transaction_id"],
                    tx["portfolio_id"],
                    tx.get("order_id"),
                    tx.get("fill_id"),
                    tx.get("decision_id"),
                    tx["symbol"],
                    tx["side"],
                    str(tx["qty"]),
                    str(tx["price"]),
                    str(tx.get("gross_notional") or "0"),
                    str(tx.get("fees") or "0"),
                    str(tx.get("net_cash_effect") or "0"),
                    tx.get("result") or "",
                    tx.get("agent_id"),
                    tx.get("orchestra_id"),
                    tx.get("strategy_id"),
                    tx.get("strategy_version"),
                    json.dumps(tx.get("risk_result") or {}),
                    tx.get("market_snapshot_id"),
                    tx.get("timestamp") or utc_now(),
                    json.dumps(tx.get("metadata") or {}),
                ),
            )
        return tx

    def list_portfolio_transactions(self, portfolio_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_portfolio_transactions
                WHERE portfolio_id=? ORDER BY timestamp DESC LIMIT ?
                """,
                (portfolio_id, max(1, int(limit))),
            ).fetchall()
        return [
            {
                "transaction_id": r["transaction_id"],
                "portfolio_id": r["portfolio_id"],
                "order_id": r["order_id"],
                "fill_id": r["fill_id"],
                "decision_id": r["decision_id"],
                "symbol": r["symbol"],
                "side": r["side"],
                "qty": r["qty"],
                "price": r["price"],
                "gross_notional": r["gross_notional"],
                "fees": r["fees"],
                "net_cash_effect": r["net_cash_effect"],
                "result": r["result"],
                "agent_id": r["agent_id"],
                "orchestra_id": r["orchestra_id"],
                "strategy_id": r["strategy_id"],
                "strategy_version": r["strategy_version"],
                "risk_result": _loads(r["risk_result_json"], {}),
                "timestamp": r["timestamp"],
                "metadata": _loads(r["metadata_json"], {}),
            }
            for r in rows
        ]

    def upsert_portfolio_order(self, order: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_portfolio_orders(
                    order_id, portfolio_id, client_order_id, symbol, side, qty, status,
                    fill_price, fee, reject_reason, decision_id, agent_id, orchestra_id,
                    strategy_id, strategy_version, risk_result_json, submitted_at,
                    updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status=excluded.status,
                    fill_price=excluded.fill_price,
                    fee=excluded.fee,
                    reject_reason=excluded.reject_reason,
                    risk_result_json=excluded.risk_result_json,
                    updated_at=excluded.updated_at
                """,
                (
                    order["order_id"],
                    order["portfolio_id"],
                    order["client_order_id"],
                    order["symbol"],
                    order["side"],
                    str(order["qty"]),
                    order["status"],
                    order.get("fill_price"),
                    str(order.get("fee") or "0"),
                    order.get("reject_reason") or "",
                    order.get("decision_id"),
                    order.get("agent_id"),
                    order.get("orchestra_id"),
                    order.get("strategy_id"),
                    order.get("strategy_version"),
                    json.dumps(order.get("risk_result") or {}),
                    order.get("submitted_at") or utc_now(),
                    order.get("updated_at") or utc_now(),
                    json.dumps(order.get("metadata") or {}),
                ),
            )
        return order

    def get_portfolio_order_by_client(
        self, portfolio_id: str, client_order_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM market_sim_portfolio_orders
                WHERE portfolio_id=? AND client_order_id=?
                """,
                (portfolio_id, client_order_id),
            ).fetchone()
        if not row:
            return None
        return {
            "order_id": row["order_id"],
            "portfolio_id": row["portfolio_id"],
            "client_order_id": row["client_order_id"],
            "symbol": row["symbol"],
            "side": row["side"],
            "qty": row["qty"],
            "status": row["status"],
            "fill_price": row["fill_price"],
            "fee": row["fee"],
            "reject_reason": row["reject_reason"],
            "decision_id": row["decision_id"],
            "agent_id": row["agent_id"],
            "orchestra_id": row["orchestra_id"],
            "strategy_id": row["strategy_id"],
            "strategy_version": row["strategy_version"],
            "risk_result": _loads(row["risk_result_json"], {}),
            "submitted_at": row["submitted_at"],
            "updated_at": row["updated_at"],
            "metadata": _loads(row["metadata_json"], {}),
        }

    def list_portfolio_orders(self, portfolio_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_portfolio_orders
                WHERE portfolio_id=? ORDER BY submitted_at DESC LIMIT ?
                """,
                (portfolio_id, max(1, int(limit))),
            ).fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "order_id": row["order_id"],
                    "portfolio_id": row["portfolio_id"],
                    "client_order_id": row["client_order_id"],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "qty": row["qty"],
                    "status": row["status"],
                    "fill_price": row["fill_price"],
                    "fee": row["fee"],
                    "reject_reason": row["reject_reason"],
                    "agent_id": row["agent_id"],
                    "strategy_id": row["strategy_id"],
                    "status_raw": row["status"],
                    "submitted_at": row["submitted_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return out

    def replace_portfolio_positions(self, portfolio_id: str, positions: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM market_sim_portfolio_positions WHERE portfolio_id=?",
                (portfolio_id,),
            )
            for p in positions:
                conn.execute(
                    """
                    INSERT INTO market_sim_portfolio_positions(
                        position_id, portfolio_id, symbol, asset_class, side, qty,
                        avg_entry_price, mark_price, market_value, cost_basis,
                        realized_pnl, unrealized_pnl, pnl_pct, fees, margin_used,
                        agent_id, orchestra_id, strategy_id, strategy_version,
                        opened_at, updated_at, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p["position_id"],
                        portfolio_id,
                        p["symbol"],
                        p.get("asset_class") or "crypto",
                        p.get("side") or "LONG",
                        str(p.get("qty") or "0"),
                        str(p.get("avg_entry_price") or "0"),
                        str(p.get("mark_price") or "0"),
                        str(p.get("market_value") or "0"),
                        str(p.get("cost_basis") or "0"),
                        str(p.get("realized_pnl") or "0"),
                        str(p.get("unrealized_pnl") or "0"),
                        str(p.get("pnl_pct") or "0"),
                        str(p.get("fees") or "0"),
                        str(p.get("margin_used") or "0"),
                        p.get("agent_id"),
                        p.get("orchestra_id"),
                        p.get("strategy_id"),
                        p.get("strategy_version"),
                        p.get("opened_at") or "",
                        p.get("updated_at") or utc_now(),
                        p.get("status") or "OPEN",
                        json.dumps(p.get("metadata") or {}),
                    ),
                )

    def upsert_portfolio_allocation(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_portfolio_allocations(
                    allocation_id, portfolio_id, kind, target_id, target_allocation_pct,
                    allocated_budget, current_attributed_equity, active, strategy_version,
                    agent_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(allocation_id) DO UPDATE SET
                    target_allocation_pct=excluded.target_allocation_pct,
                    allocated_budget=excluded.allocated_budget,
                    current_attributed_equity=excluded.current_attributed_equity,
                    active=excluded.active,
                    strategy_version=excluded.strategy_version,
                    agent_id=excluded.agent_id,
                    metadata_json=excluded.metadata_json
                """,
                (
                    row["allocation_id"],
                    row["portfolio_id"],
                    row["kind"],
                    row["target_id"],
                    float(row.get("target_allocation_pct") or 0),
                    str(row.get("allocated_budget") or "0"),
                    str(row.get("current_attributed_equity") or "0"),
                    1 if row.get("active", True) else 0,
                    row.get("strategy_version"),
                    row.get("agent_id"),
                    json.dumps(row.get("metadata") or {}),
                ),
            )
        return row

    def list_portfolio_allocations(self, portfolio_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_sim_portfolio_allocations WHERE portfolio_id=?",
                (portfolio_id,),
            ).fetchall()
        return [
            {
                "allocation_id": r["allocation_id"],
                "portfolio_id": r["portfolio_id"],
                "kind": r["kind"],
                "target_id": r["target_id"],
                "target_allocation_pct": float(r["target_allocation_pct"]),
                "allocated_budget": r["allocated_budget"],
                "current_attributed_equity": r["current_attributed_equity"],
                "active": bool(r["active"]),
                "strategy_version": r["strategy_version"],
                "agent_id": r["agent_id"],
                "metadata": _loads(r["metadata_json"], {}),
            }
            for r in rows
        ]

    def replace_portfolio_recommendations(
        self, portfolio_id: str, recs: list[dict[str, Any]]
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM market_sim_portfolio_recommendations WHERE portfolio_id=? AND status='PENDING'",
                (portfolio_id,),
            )
            for r in recs:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_sim_portfolio_recommendations(
                        recommendation_id, portfolio_id, type, target, reason,
                        current_value, target_value, impact, estimated_orders_json,
                        status, created_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["recommendation_id"],
                        portfolio_id,
                        r["type"],
                        r.get("target") or "",
                        r.get("reason") or "",
                        r.get("current_value") or "",
                        r.get("target_value") or "",
                        r.get("impact") or "MEDIUM",
                        json.dumps(r.get("estimated_orders") or []),
                        r.get("status") or "PENDING",
                        r.get("created_at") or utc_now(),
                        json.dumps(r.get("metadata") or {}),
                    ),
                )

    def list_portfolio_recommendations(self, portfolio_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_portfolio_recommendations
                WHERE portfolio_id=? ORDER BY created_at DESC LIMIT 20
                """,
                (portfolio_id,),
            ).fetchall()
        return [
            {
                "recommendation_id": r["recommendation_id"],
                "portfolio_id": r["portfolio_id"],
                "type": r["type"],
                "target": r["target"],
                "reason": r["reason"],
                "current_value": r["current_value"],
                "target_value": r["target_value"],
                "impact": r["impact"],
                "estimated_orders": _loads(r["estimated_orders_json"], []),
                "status": r["status"],
                "created_at": r["created_at"],
                "metadata": _loads(r["metadata_json"], {}),
            }
            for r in rows
        ]
