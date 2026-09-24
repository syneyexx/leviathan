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
    DeliberationMessage,
    MarketDataSource,
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
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        from Data.backend.migrations import MigrationRunner

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
        """Claim one QUEUED or RUNNING (without worker) run for the worker."""
        with self.connect() as conn:
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
                return None
            run = self._row_run(row)
            conn.execute(
                "UPDATE market_sim_runs SET worker_pid=?, updated_at=? WHERE run_id=?",
                (1, utc_now(), run.run_id),
            )
            run.worker_pid = 1
            return run

    def _row_run(self, row: sqlite3.Row) -> SimRun:
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
            metadata=_loads(row["metadata_json"], {}),
        )

    # --- Fills / messages / equity ---

    def add_fill(self, fill: SimFill) -> SimFill:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_sim_fills(
                    fill_id, run_id, bar_index, ts, side, qty, price, fee, slippage,
                    agent_id, rationale, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
        return fill

    def list_fills(self, run_id: str, *, limit: int = 500) -> list[SimFill]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_fills
                WHERE run_id=? ORDER BY bar_index ASC, created_at ASC LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [
            SimFill(
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
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_sim_messages
                WHERE run_id=? ORDER BY bar_index ASC, created_at ASC LIMIT ?
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
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT bar_index, ts, equity, cash, position_qty
                FROM market_sim_equity
                WHERE run_id=? ORDER BY bar_index ASC LIMIT ?
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
                    status=excluded.status,
                    results_json=excluded.results_json,
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
