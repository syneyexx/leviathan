"""Market simulation control plane — Core ownership / orchestration."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .brain_hooks import (
    BrainFacade,
    NullEvidence,
    NullKnowledge,
    NullMemory,
    adapt_evidence_store,
    adapt_knowledge_store,
    adapt_memory_store,
)
from .data_store import MarketDataStore
from .deliberation import DeliberationRuntime
from .engine import SimulationEngine
from .store import MarketSimStore, utc_now
from .strategy_eval import strategy_content_hash
from .types import (
    ACTIVE_RUN_STATUSES,
    AgentConfig,
    DEFAULT_AGENT_ROLES,
    MarketSimError,
    RunStatus,
    SimRun,
    SourceStatus,
    StrategyRecord,
    StrategyStatus,
    StrategyVersion,
    TERMINAL_RUN_STATUSES,
)
from .worker import MarketSimWorker


class MarketSimControlPlane:
    """Control plane: config, persistence, lifecycle. Execution → worker."""

    def __init__(
        self,
        store: MarketSimStore,
        data: MarketDataStore,
        *,
        enabled: bool = False,
        brain: BrainFacade | None = None,
        observability_emit: Any | None = None,
    ) -> None:
        self.store = store
        self.data = data
        self.enabled = enabled
        self.brain = brain or BrainFacade()
        self._emit = observability_emit
        self.engine = SimulationEngine(
            store,
            deliberation=DeliberationRuntime(self.brain),
        )
        self.worker = MarketSimWorker(
            store,
            self.engine,
            resolve_bars_path=self._resolve_bars_path,
            resolve_strategy=self._resolve_strategy_payload,
        )

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        *,
        db_path: Path | None = None,
        knowledge: Any | None = None,
        memory: Any | None = None,
        evidence: Any | None = None,
        neuro: Any | None = None,
        observability_emit: Any | None = None,
    ) -> "MarketSimControlPlane":
        path = Path(db_path or settings.database_path)
        store = MarketSimStore(path)
        store.initialize()
        markets_root = Path(settings.market_sim.markets_root)
        data = MarketDataStore(store, markets_root)
        brain = BrainFacade(
            knowledge=adapt_knowledge_store(knowledge) if knowledge is not None else NullKnowledge(),
            memory=adapt_memory_store(memory) if memory is not None else NullMemory(),
            evidence=adapt_evidence_store(evidence) if evidence is not None else NullEvidence(),
            neuro=neuro,
        )
        enabled = bool(settings.features.market_sim_enabled)
        return cls(
            store,
            data,
            enabled=enabled,
            brain=brain,
            observability_emit=observability_emit,
        )

    def start_background(self) -> None:
        if self.enabled:
            self.worker.start_background()

    def stop_background(self) -> None:
        self.worker.stop_background()

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise MarketSimError(
                "FEATURE_DISABLED",
                "Market sim feature flag is OFF (LEVIATHAN_FEATURE_MARKET_SIM)",
                http_status=503,
            )

    def _emit_event(self, name: str, payload: dict[str, Any]) -> None:
        if self._emit:
            try:
                self._emit("market_sim", name, payload=payload)
            except Exception:  # noqa: BLE001
                pass

    def status(self) -> dict[str, Any]:
        health = self.data.health()
        runs = self.store.list_runs(limit=50)
        active = sum(1 for r in runs if r.status in {s.value for s in ACTIVE_RUN_STATUSES})
        return {
            "enabled": self.enabled,
            "feature_flag": "LEVIATHAN_FEATURE_MARKET_SIM",
            "health": health,
            "active_runs": active,
            "worker": dict(self.worker.telemetry),
            "truth": {
                "paper_sim_only": True,
                "no_real_broker_orders": True,
                "external_worker_execution": True,
                "causality_enforced": True,
            },
        }

    # --- Market data ---

    def scan_market_data(self) -> list[dict[str, Any]]:
        self._require_enabled()
        sources = self.data.scan(register=True)
        self._emit_event("market_data.scan", {"count": len(sources)})
        return [s.public_dict() for s in sources]

    def list_market_data(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self._require_enabled()
        return [s.public_dict() for s in self.data.list_sources(status=status, limit=limit)]

    def get_market_data(self, source_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self.data.get_source(source_id).public_dict()

    def register_market_data(
        self,
        relative_path: str,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        source = self.data.register_file(relative_path, symbol=symbol, timeframe=timeframe)
        return source.public_dict()

    # --- Strategies ---

    def create_strategy(
        self,
        *,
        name: str,
        description: str = "",
        tags: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        entry_rules: dict[str, Any] | None = None,
        exit_rules: dict[str, Any] | None = None,
        risk_rules: dict[str, Any] | None = None,
        required_timeframes: list[str] | None = None,
        brain_dependencies: list[str] | None = None,
        changelog: str = "initial",
    ) -> dict[str, Any]:
        self._require_enabled()
        now = utc_now()
        parameters = dict(parameters or {"fast_ma": 10, "slow_ma": 30, "lookback": 30})
        entry_rules = dict(entry_rules or {"kind": "ma_cross"})
        exit_rules = dict(exit_rules or {"kind": "ma_cross"})
        risk_rules = dict(risk_rules or {"max_position_pct": 25})
        required_timeframes = list(required_timeframes or ["1h"])
        brain_dependencies = list(brain_dependencies or ["knowledge", "memory", "neuro"])
        content_hash = strategy_content_hash(
            parameters=parameters,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_rules=risk_rules,
            required_timeframes=required_timeframes,
            brain_dependencies=brain_dependencies,
        )
        strategy_id = str(uuid.uuid4())
        record = StrategyRecord(
            strategy_id=strategy_id,
            name=name.strip() or "untitled",
            description=description or "",
            status=StrategyStatus.ACTIVE.value,
            tags=list(tags or []),
            current_version=1,
            content_hash=content_hash,
            created_at=now,
            updated_at=now,
        )
        version = StrategyVersion(
            version_id=str(uuid.uuid4()),
            strategy_id=strategy_id,
            version=1,
            content_hash=content_hash,
            parameters=parameters,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_rules=risk_rules,
            required_timeframes=required_timeframes,
            brain_dependencies=brain_dependencies,
            created_at=now,
            changelog=changelog,
        )
        self.store.create_strategy(record, version)
        self._emit_event("strategy.created", {"strategy_id": strategy_id})
        return {
            "strategy": record.public_dict(),
            "version": version.public_dict(),
        }

    def version_strategy(
        self,
        strategy_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        entry_rules: dict[str, Any] | None = None,
        exit_rules: dict[str, Any] | None = None,
        risk_rules: dict[str, Any] | None = None,
        required_timeframes: list[str] | None = None,
        brain_dependencies: list[str] | None = None,
        changelog: str = "",
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        record = self.store.get_strategy(strategy_id)
        if record is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
        current = self.store.get_strategy_version(strategy_id)
        if current is None:
            raise MarketSimError("STRATEGY_VERSION_MISSING", strategy_id, http_status=404)
        parameters = dict(parameters if parameters is not None else current.parameters)
        entry_rules = dict(entry_rules if entry_rules is not None else current.entry_rules)
        exit_rules = dict(exit_rules if exit_rules is not None else current.exit_rules)
        risk_rules = dict(risk_rules if risk_rules is not None else current.risk_rules)
        required_timeframes = list(
            required_timeframes if required_timeframes is not None else current.required_timeframes
        )
        brain_dependencies = list(
            brain_dependencies if brain_dependencies is not None else current.brain_dependencies
        )
        content_hash = strategy_content_hash(
            parameters=parameters,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_rules=risk_rules,
            required_timeframes=required_timeframes,
            brain_dependencies=brain_dependencies,
        )
        now = utc_now()
        new_version_num = record.current_version + 1
        version = StrategyVersion(
            version_id=str(uuid.uuid4()),
            strategy_id=strategy_id,
            version=new_version_num,
            content_hash=content_hash,
            parameters=parameters,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_rules=risk_rules,
            required_timeframes=required_timeframes,
            brain_dependencies=brain_dependencies,
            created_at=now,
            changelog=changelog or f"v{new_version_num}",
        )
        record.current_version = new_version_num
        record.content_hash = content_hash
        record.updated_at = now
        if name is not None:
            record.name = name
        if description is not None:
            record.description = description
        if tags is not None:
            record.tags = tags
        self.store.update_strategy_head(record, version)
        return {"strategy": record.public_dict(), "version": version.public_dict()}

    def fork_strategy(self, strategy_id: str, *, name: str | None = None) -> dict[str, Any]:
        self._require_enabled()
        record = self.store.get_strategy(strategy_id)
        version = self.store.get_strategy_version(strategy_id)
        if record is None or version is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
        return self.create_strategy(
            name=name or f"{record.name} (fork)",
            description=record.description,
            tags=list(record.tags),
            parameters=dict(version.parameters),
            entry_rules=dict(version.entry_rules),
            exit_rules=dict(version.exit_rules),
            risk_rules=dict(version.risk_rules),
            required_timeframes=list(version.required_timeframes),
            brain_dependencies=list(version.brain_dependencies),
            changelog=f"fork of {strategy_id}@{version.version}",
        )

    def archive_strategy(self, strategy_id: str) -> dict[str, Any]:
        self._require_enabled()
        record = self.store.get_strategy(strategy_id)
        if record is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
        record.status = StrategyStatus.ARCHIVED.value
        record.updated_at = utc_now()
        # Re-save head without new version by creating identical version bump skipped —
        # update via version_strategy with same content would bump; use direct SQL via store.
        current = self.store.get_strategy_version(strategy_id)
        assert current is not None
        # Soft archive: store update through version with same hash but status change
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE market_strategies SET status=?, updated_at=? WHERE strategy_id=?",
                (record.status, record.updated_at, strategy_id),
            )
        return record.public_dict()

    def list_strategies(self, *, limit: int = 200) -> list[dict[str, Any]]:
        self._require_enabled()
        return [s.public_dict() for s in self.store.list_strategies(limit=limit)]

    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        self._require_enabled()
        record = self.store.get_strategy(strategy_id)
        if record is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
        versions = [v.public_dict() for v in self.store.list_strategy_versions(strategy_id)]
        return {"strategy": record.public_dict(), "versions": versions}

    # --- Runs ---

    def create_run(
        self,
        *,
        source_id: str,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
        start_ts: str | None = None,
        end_ts: str | None = None,
        seed: int = 42,
        speed: float = 1.0,
        initial_cash: float = 100_000.0,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        max_position_pct: float = 25.0,
        max_drawdown_pct: float = 20.0,
        per_trade_risk_pct: float = 1.0,
        agents: list[dict[str, Any]] | None = None,
        deliberation_every_n: int = 5,
        stochastic_slippage: bool = False,
    ) -> dict[str, Any]:
        self._require_enabled()
        source = self.data.get_source(source_id)
        if source.status != SourceStatus.READY.value:
            raise MarketSimError(
                "SOURCE_NOT_READY",
                f"Source status={source.status}: {source.validation_error}",
                http_status=400,
            )
        if strategy_id:
            strat = self.store.get_strategy(strategy_id)
            if strat is None:
                raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
            ver = self.store.get_strategy_version(strategy_id, strategy_version)
            if ver is None:
                raise MarketSimError("STRATEGY_VERSION_MISSING", strategy_id, http_status=404)
            strategy_version = ver.version
        agent_list = agents
        if agent_list is None:
            agent_list = [
                AgentConfig(
                    agent_id=f"agent-{role.value}",
                    role=role.value,
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    label=role.value.replace("_", " ").title(),
                ).public_dict()
                for role in DEFAULT_AGENT_ROLES
            ]
        now = utc_now()
        run = SimRun(
            run_id=str(uuid.uuid4()),
            status=RunStatus.CREATED.value,
            source_id=source_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            symbol=source.symbol,
            timeframe=source.timeframe,
            start_ts=start_ts or source.start_ts or "",
            end_ts=end_ts or source.end_ts or "",
            data_hash=source.content_hash,
            seed=seed,
            speed=max(0.1, min(10.0, float(speed))),
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            max_position_pct=max_position_pct,
            max_drawdown_pct=max_drawdown_pct,
            per_trade_risk_pct=per_trade_risk_pct,
            agents=agent_list,
            deliberation_every_n=max(1, int(deliberation_every_n)),
            cash=initial_cash,
            equity=initial_cash,
            created_at=now,
            updated_at=now,
            metadata={"stochastic_slippage": stochastic_slippage},
        )
        self.store.create_run(run)
        self._emit_event("run.created", {"run_id": run.run_id, "data_hash": run.data_hash})
        return run.public_dict()

    def start_run(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        run = self._get_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise MarketSimError("RUN_TERMINAL", f"Run already {run.status}")
        if run.status in {RunStatus.RUNNING.value, RunStatus.QUEUED.value}:
            return run.public_dict()
        run.status = RunStatus.QUEUED.value
        run.cancel_requested = False
        run.error = None
        self.store.update_run(run)
        self.worker.wake()
        return run.public_dict()

    def pause_run(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        run = self._get_run(run_id)
        if run.status not in {RunStatus.RUNNING.value, RunStatus.QUEUED.value, RunStatus.STEPPING.value}:
            raise MarketSimError("RUN_NOT_PAUSABLE", f"status={run.status}")
        run.status = RunStatus.PAUSED.value
        self.store.update_run(run)
        return run.public_dict()

    def step_run(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        run = self._get_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise MarketSimError("RUN_TERMINAL", f"Run already {run.status}")
        run.status = RunStatus.STEPPING.value
        self.store.update_run(run)
        self.worker.wake()
        # Synchronously process one slice for responsive UI / tests
        self.worker.process_next()
        return self._get_run(run_id).public_dict()

    def stop_run(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        run = self._get_run(run_id)
        run.cancel_requested = True
        if run.status not in TERMINAL_RUN_STATUSES:
            run.status = RunStatus.STOPPED.value
            run.finished_at = utc_now()
        self.store.update_run(run)
        self.worker.wake()
        return run.public_dict()

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self._get_run(run_id).public_dict()

    def list_runs(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self._require_enabled()
        return [r.public_dict() for r in self.store.list_runs(status=status, limit=limit)]

    def run_live_state(self, run_id: str, *, message_limit: int = 100, fill_limit: int = 100) -> dict[str, Any]:
        self._require_enabled()
        run = self._get_run(run_id)
        fills = [f.public_dict() for f in self.store.list_fills(run_id, limit=fill_limit)]
        messages = [m.public_dict() for m in self.store.list_messages(run_id, limit=message_limit)]
        equity = self.store.list_equity(run_id, limit=2000)
        return {
            "run": run.public_dict(),
            "fills": fills,
            "messages": messages,
            "equity": equity,
            "truth": {
                "causality_violations": run.causality_violations,
                "paper_sim_only": True,
            },
        }

    def run_results(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        state = self.run_live_state(run_id)
        run = state["run"]
        return {
            "run": run,
            "metrics": run.get("metrics") or {},
            "fills": state["fills"],
            "equity": state["equity"],
            "messages": state["messages"],
        }

    def _get_run(self, run_id: str) -> SimRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise MarketSimError("RUN_NOT_FOUND", run_id, http_status=404)
        return run

    def _resolve_bars_path(self, run: SimRun) -> str:
        source = self.data.get_source(run.source_id)
        return str(self.data.absolute_path_for(source))

    def _resolve_strategy_payload(self, run: SimRun) -> dict[str, Any]:
        if not run.strategy_id:
            return {
                "parameters": {"fast_ma": 10, "slow_ma": 30},
                "entry_rules": {"kind": "ma_cross"},
                "exit_rules": {"kind": "ma_cross"},
                "brain_dependencies": ["knowledge", "memory", "neuro"],
            }
        ver = self.store.get_strategy_version(run.strategy_id, run.strategy_version)
        if ver is None:
            raise MarketSimError("STRATEGY_VERSION_MISSING", run.strategy_id or "")
        return {
            "parameters": ver.parameters,
            "entry_rules": ver.entry_rules,
            "exit_rules": ver.exit_rules,
            "brain_dependencies": ver.brain_dependencies,
        }
