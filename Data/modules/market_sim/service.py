"""Market simulation control plane — Core ownership / orchestration."""

from __future__ import annotations

import os
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
from .capabilities import build_market_capabilities
from .data_store import MarketDataStore
from .deliberation import DeliberationRuntime
from .engine import SimulationEngine
from .experiments import (
    evaluate_acceptance,
    market_features_from_closes,
    new_trial,
    strategy_matches_regime,
    trial_fingerprint,
    walk_forward_splits,
)
from .instruments import infer_family, spec_for_symbol
from .multi_engine import MultiAgentEngine
from .paper_broker import LocalPaperBroker, PaperSession, build_paper_broker, utc_now as paper_utc
from .providers import default_registry
from .roles import default_competition_agents, ensure_trading_agents_in_fleet
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
from .trading_live_guard import LiveTradingGuard


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
        job_runtime: Any | None = None,
    ) -> None:
        self.store = store
        self.data = data
        self.enabled = enabled
        self.brain = brain or BrainFacade()
        self._emit = observability_emit
        self.job_runtime = job_runtime
        self.engine = SimulationEngine(
            store,
            deliberation=DeliberationRuntime(self.brain),
        )
        self.multi_engine = MultiAgentEngine(store)
        self.providers = default_registry(data.markets_root)
        self._paper_brokers: dict[str, Any] = {}
        self._fleet = None
        self.live_guard = LiveTradingGuard()
        self.worker = MarketSimWorker(
            store,
            self.engine,
            resolve_bars_path=self._resolve_bars_path,
            resolve_strategy=self._resolve_strategy_payload,
            multi_engine=self.multi_engine,
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

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    @staticmethod
    def _runners_externalized() -> bool:
        ext = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "").strip().lower()
        if ext in {"1", "true", "yes", "on"}:
            return True
        if ext in {"0", "false", "no", "off"}:
            return False
        raw = (os.environ.get("LEVIATHAN_MARKET_SIM_RUNNER") or "").strip().lower()
        if raw in {"external", "worker", "process"}:
            return True
        if raw in {"inprocess", "thread", "api"}:
            return False
        try:
            from Data.modules.workers.settings import load_worker_settings

            return bool(load_worker_settings().externalize_api_runners)
        except Exception:  # noqa: BLE001
            return False

    def enqueue_advance(
        self,
        simulation_id: str,
        *,
        parent_job_id: str | None = None,
        root_job_id: str | None = None,
        requested_by: str = "market_sim_service",
    ) -> Any:
        """Enqueue durable market_sim.advance for an external worker."""
        if self.job_runtime is None:
            raise RuntimeError("job_runtime not bound; cannot enqueue market_sim.advance")
        run = self.store.get_run(simulation_id)
        if run is None:
            raise MarketSimError("RUN_NOT_FOUND", f"Unknown run: {simulation_id}", http_status=404)
        # Generation: bar cursor + status so continuations are idempotent per slice.
        gen = f"{run.status}:{getattr(run, 'bar_index', None) or 0}:{run.updated_at or run.created_at}"
        idem = f"market_sim:advance:{simulation_id}:{gen}"
        return self.job_runtime.enqueue(
            capability_id="market_sim.advance",
            arguments={"simulation_id": simulation_id},
            requested_by=requested_by,
            idempotency_key=idem,
            domain="market_sim",
            domain_entity_type="market_sim_run",
            domain_entity_id=simulation_id,
            worker_pool="market_sim",
            parent_job_id=parent_job_id,
            root_job_id=root_job_id or parent_job_id,
            latency_class="background",
            metadata={"simulation_id": simulation_id, "generation": gen},
        )

    def enqueue_queued_runs(self) -> list[str]:
        """Enqueue advance jobs for QUEUED/RUNNING/STEPPING runs (idempotent)."""
        job_ids: list[str] = []
        if self.job_runtime is None:
            return job_ids
        for run in self.store.list_runs(limit=100):
            if run.status not in {
                RunStatus.QUEUED.value,
                RunStatus.RUNNING.value,
                RunStatus.STEPPING.value,
            }:
                continue
            try:
                job = self.enqueue_advance(run.run_id)
                job_ids.append(job.job_id)
            except Exception:  # noqa: BLE001
                continue
        return job_ids

    def start_background(self) -> None:
        """Start in-process daemon, or enqueue durable jobs when externalized."""
        if not self.enabled:
            return
        if self._runners_externalized():
            if self.job_runtime is not None:
                self.enqueue_queued_runs()
            return
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
        caps = build_market_capabilities(
            feature_enabled=self.enabled,
            binance_reachable=False,  # avoid network on every status poll
            local_paper=True,
        )
        # Recompute reachability lightly from last provider status cache if any
        try:
            provider_status = self.providers.status_all()
        except Exception:  # noqa: BLE001
            provider_status = []
        binance_ok = any(
            p.get("provider_id") == "binance_public" and p.get("reachable") for p in provider_status
        )
        caps = build_market_capabilities(
            feature_enabled=self.enabled,
            binance_reachable=binance_ok,
            local_paper=True,
        )
        return {
            "enabled": self.enabled,
            "feature_flag": "LEVIATHAN_FEATURE_MARKET_SIM",
            "health": health,
            "active_runs": active,
            "worker": dict(self.worker.telemetry),
            "providers": provider_status,
            "capabilities": caps,
            "live_trading": self.live_guard.public_status(),
            "truth": {
                "paper_sim_only": True,
                "no_real_broker_orders": True,
                "worker_is_daemon_thread_by_default": True,
                "subprocess_entrypoint": "scripts/market_sim_worker.py",
                "causality_enforced": True,
                "next_bar_open_fills": True,
                "commit_reveal_multi_wallet": True,
                "ohlcv_not_orderbook": True,
                "profitable_backtest_is_not_proof": True,
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
        game_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
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
            metadata={
                "stochastic_slippage": stochastic_slippage,
                **(dict(metadata or {})),
                **({"game_mode": game_mode} if game_mode else {}),
                "instrument_family": infer_family(source.symbol, metadata=source.metadata).value,
                "fill_schedule": "next_bar_open",
            },
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
        if self._runners_externalized() and self.job_runtime is not None:
            self.enqueue_advance(run.run_id, requested_by="market_sim.start_run")
        else:
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
        if self._runners_externalized() and self.job_runtime is not None:
            self.enqueue_advance(run.run_id, requested_by="market_sim.step_run")
            return self._get_run(run_id).public_dict()
        self.worker.wake()
        # Synchronously process one slice for responsive UI / tests (in-process)
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

    def attach_fleet(self, fleet: Any) -> None:
        self._fleet = fleet
        if self.enabled and fleet is not None:
            ensure_trading_agents_in_fleet(fleet)

    # --- Providers / import ---

    def list_providers(self) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.providers.status_all()

    def import_provider_data(
        self,
        *,
        provider_id: str,
        symbol: str,
        timeframe: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        self._require_enabled()
        use_provider_io = False
        if self._runners_externalized() and self.job_runtime is not None:
            try:
                from Data.modules.provider_io.readiness import provider_io_workers_ready

                db_path = getattr(getattr(self.job_runtime, "store", None), "path", None)
                use_provider_io = provider_io_workers_ready(db_path)
            except Exception:  # noqa: BLE001
                use_provider_io = False
        if use_provider_io:
            from Data.modules.provider_io.errors import ProviderError
            from Data.modules.provider_io.facade import ProviderExecutionClient

            client = ProviderExecutionClient(self.job_runtime)
            try:
                exec_result = client.submit_and_wait(
                    provider=provider_id,
                    capability="market.fetch",
                    payload={
                        "provider_id": provider_id,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "limit": limit,
                        "markets_root": str(self.data.markets_root),
                    },
                    credential_ref="none",
                    latency_class="background",
                    requested_by="market_sim_service",
                    deadline_seconds=90.0,
                )
            except ProviderError as exc:
                raise MarketSimError(
                    exc.code.value,
                    str(exc),
                    http_status=503 if exc.retryable else 502,
                ) from exc
            if exec_result.status != "succeeded" or not isinstance(exec_result.structured, dict):
                err = (exec_result.error or {}).get("message") or "provider_io market fetch failed"
                code = (exec_result.error or {}).get("code") or "PROVIDER_UNAVAILABLE"
                raise MarketSimError(str(code), str(err), http_status=502)
            result = dict(exec_result.structured)
        else:
            result = self.providers.import_to_csv(
                provider_id, symbol, timeframe, self.data.markets_root, limit=limit
            )
        source = self.data.register_file(
            result["relative_path"],
            symbol=result["symbol"],
            timeframe=result["timeframe"],
        )
        # Enrich metadata
        source.metadata = {
            **dict(source.metadata or {}),
            "provider_id": provider_id,
            "license_note": result.get("license_note"),
            "dataset_version": "1",
            "kind": "ohlcv",
            "family": infer_family(symbol).value,
            "not_orderbook": True,
            "executed_via": "provider_io" if use_provider_io else "control_plane",
        }
        source.updated_at = utc_now()
        self.store.upsert_source(source)
        return {"import": result, "source": source.public_dict()}

    def market_capabilities(self) -> dict[str, Any]:
        return build_market_capabilities(feature_enabled=self.enabled)

    # --- Paper trading ---

    def _paper_broker(self, broker_id: str = "local_paper") -> Any:
        if broker_id not in self._paper_brokers:
            self._paper_brokers[broker_id] = build_paper_broker(broker_id)
        return self._paper_brokers[broker_id]

    def start_paper_session(
        self,
        *,
        symbol: str,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
        broker_id: str = "local_paper",
        provider_id: str = "binance_public",
        initial_cash: float = 100_000.0,
    ) -> dict[str, Any]:
        self._require_enabled()
        if strategy_id:
            ver = self.store.get_strategy_version(strategy_id, strategy_version)
            if ver is None:
                raise MarketSimError("STRATEGY_VERSION_MISSING", strategy_id, http_status=404)
            strategy_version = ver.version
            # Applicability check (honest)
            features = {"trend": "unknown", "volatility": "unknown", "regime": "unknown"}
            match = strategy_matches_regime(
                ver.metadata.get("applicability") or ver.risk_rules.get("applicability") or {},
                features,
            )
        else:
            match = {"matched": False, "reason": "no strategy bound"}

        broker = self._paper_broker(broker_id)
        if hasattr(broker, "wallet"):
            from .accounting import money
            broker.wallet.cash = money(initial_cash)
            broker.wallet.peak_equity = money(initial_cash)

        quote = None
        feed_status = "disconnected"
        latency = None
        try:
            provider = self.providers.get(provider_id)
            st = provider.status()
            latency = st.latency_ms
            feed_status = "live" if st.reachable else "disconnected"
            quote = provider.fetch_quote(symbol)
        except Exception as exc:  # noqa: BLE001
            feed_status = f"error:{exc}"

        now = utc_now()
        session = {
            "session_id": str(uuid.uuid4()),
            "status": "active",
            "broker_id": broker_id,
            "provider_id": provider_id,
            "symbol": symbol.upper(),
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "kill_switch": False,
            "feed_status": feed_status,
            "wallet": broker.account().get("wallet") if hasattr(broker, "account") else {},
            "orders": [],
            "metadata": {
                "mode": "live_paper",
                "regime_match": match,
                "last_quote": quote,
                "feed_latency_ms": latency,
                "truth": {
                    "not_live_money": True,
                    "not_historical_backtest": True,
                    "paper_never_auto_approves_live": True,
                },
            },
            "created_at": now,
            "updated_at": now,
        }
        self.store.upsert_paper_session(session)
        return session

    def paper_session_state(self, session_id: str) -> dict[str, Any]:
        self._require_enabled()
        session = self.store.get_paper_session(session_id)
        if session is None:
            raise MarketSimError("PAPER_SESSION_NOT_FOUND", session_id, http_status=404)
        # Refresh quote
        try:
            provider = self.providers.get(session["provider_id"])
            quote = provider.fetch_quote(session["symbol"])
            st = provider.status()
            session["feed_status"] = "live" if st.reachable else "disconnected"
            session["metadata"] = dict(session.get("metadata") or {})
            session["metadata"]["last_quote"] = quote
            session["metadata"]["feed_latency_ms"] = st.latency_ms
        except Exception as exc:  # noqa: BLE001
            session["feed_status"] = f"error:{exc}"
        broker = self._paper_brokers.get(session["broker_id"])
        if broker is not None:
            session["wallet"] = broker.account().get("wallet") or broker.account()
        session["updated_at"] = utc_now()
        self.store.upsert_paper_session(session)
        return session

    def paper_place_order(
        self,
        session_id: str,
        *,
        side: str,
        qty: float,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        session = self.paper_session_state(session_id)
        if session.get("kill_switch"):
            raise MarketSimError("KILL_SWITCH", "Paper session kill switch armed", http_status=409)
        if session.get("status") != "active":
            raise MarketSimError("SESSION_NOT_ACTIVE", session.get("status") or "")
        broker = self._paper_broker(session["broker_id"])
        quote = (session.get("metadata") or {}).get("last_quote") or {}
        price = quote.get("price")
        if price is None:
            # Refuse blind order when feed uncertain
            raise MarketSimError(
                "FEED_UNCERTAIN",
                "No live quote — refusing paper order (no blind resubmit)",
                http_status=409,
            )
        order = broker.place(
            symbol=session["symbol"],
            side=side,
            qty=qty,
            client_order_id=client_order_id or str(uuid.uuid4()),
            price_hint=float(price),
            metadata={
                "strategy_id": session.get("strategy_id"),
                "strategy_version": session.get("strategy_version"),
                "session_id": session_id,
            },
        )
        orders = list(session.get("orders") or [])
        orders.append(order.public_dict())
        session["orders"] = orders
        session["wallet"] = broker.account().get("wallet") or {}
        session["updated_at"] = utc_now()
        self.store.upsert_paper_session(session)
        return {"order": order.public_dict(), "session": session}

    def paper_kill_switch(self, session_id: str, *, armed: bool = True) -> dict[str, Any]:
        self._require_enabled()
        session = self.store.get_paper_session(session_id)
        if session is None:
            raise MarketSimError("PAPER_SESSION_NOT_FOUND", session_id, http_status=404)
        session["kill_switch"] = bool(armed)
        session["updated_at"] = utc_now()
        self.store.upsert_paper_session(session)
        return session

    def list_paper_sessions(self) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_paper_sessions()

    # --- Experiments / learning ---

    def propose_experiment(
        self,
        *,
        strategy_id: str,
        hypothesis: str,
        proposer_agent_id: str,
        source_id: str,
        acceptance_criteria: dict[str, Any] | None = None,
        seed: int = 42,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        source = self.data.get_source(source_id)
        from .ohlcv import load_ohlcv
        bars = load_ohlcv(str(self.data.absolute_path_for(source)))
        split = walk_forward_splits(source.start_ts or "", source.end_ts or "", bars)
        trial = new_trial(
            strategy_id=strategy_id,
            hypothesis=hypothesis,
            proposer_agent_id=proposer_agent_id,
            data_hash=source.content_hash,
            config=dict(config or {}),
            split=split,
            seed=seed,
            acceptance_criteria=acceptance_criteria,
            cost_model={"fee_bps": 5.0, "slippage_bps": 2.0},
            created_at=utc_now(),
        )
        fp = trial_fingerprint(trial)
        existing = self.store.find_experiment_fingerprint(fp)
        if existing and existing.get("status") == "rejected":
            raise MarketSimError(
                "HYPOTHESIS_ALREADY_REJECTED",
                f"Identical rejected trial {existing['trial_id']}: {existing.get('rejection_reason')}",
                http_status=409,
            )
        payload = trial.public_dict()
        payload["fingerprint"] = fp
        self.store.save_experiment(payload)
        return payload

    def complete_experiment(
        self,
        trial_id: str,
        *,
        metrics: dict[str, Any],
        strategy_version: int | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        trials = self.store.list_experiments(limit=500)
        trial = next((t for t in trials if t["trial_id"] == trial_id), None)
        if trial is None:
            raise MarketSimError("TRIAL_NOT_FOUND", trial_id, http_status=404)
        passed, reason = evaluate_acceptance(metrics, trial.get("acceptance_criteria") or {})
        trial["results"] = metrics
        trial["strategy_version"] = strategy_version
        trial["finished_at"] = utc_now()
        if passed:
            trial["status"] = "passed"
            trial["rejection_reason"] = ""
        else:
            trial["status"] = "rejected"
            trial["rejection_reason"] = reason
        self.store.save_experiment(trial)
        # Persist memory (available_at = now — not backdated into past decisions)
        self.store.save_strategy_memory(
            {
                "memory_id": str(uuid.uuid4()),
                "strategy_id": trial["strategy_id"],
                "strategy_version": strategy_version or 0,
                "features": (metrics.get("features") or {}),
                "applicability": (trial.get("config") or {}).get("applicability") or {},
                "outcome_summary": reason if not passed else "accepted on holdout",
                "trial_id": trial_id,
                "available_at": utc_now(),
                "created_at": utc_now(),
                "rejected": not passed,
            }
        )
        return trial

    def list_experiments(self, *, strategy_id: str | None = None) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_experiments(strategy_id=strategy_id)

    # --- Demo runners (equity + crypto) ---

    def run_market_demo(self, *, family: str, bars_limit: int = 120) -> dict[str, Any]:
        """Reproduceerbare demo: data → agents → commit-reveal → fills → wallets."""
        self._require_enabled()
        from pathlib import Path
        import shutil

        fixtures = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "market_data"
        if family == "crypto_spot":
            src_name = "BTCUSDT_1h.csv"
            symbol = "BTCUSDT"
            timeframe = "1h"
        elif family == "equity":
            src_name = "AAPL_1d.csv"
            symbol = "AAPL"
            timeframe = "1D"
        else:
            raise MarketSimError("FAMILY_NOT_SUPPORTED", family)

        src = fixtures / src_name
        if not src.exists():
            raise MarketSimError("FIXTURE_MISSING", str(src))
        dest = self.data.markets_root / src_name
        self.data.markets_root.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        source = self.data.register_file(src_name, symbol=symbol, timeframe=timeframe)
        source.metadata = {**(source.metadata or {}), "family": family, "provider_id": "csv_local"}
        self.store.upsert_source(source)

        strat = self.create_strategy(
            name=f"demo-{family}-ma",
            description=f"Demo strategy for {family}",
            tags=["demo", family],
            parameters={"fast_ma": 5, "slow_ma": 15, "lookback": 20},
            entry_rules={"kind": "ma_cross"},
            exit_rules={"kind": "ma_cross"},
            risk_rules={"max_position_pct": 25, "applicability": {"trends": ["up", "flat", "down"], "volatilities": ["low", "medium", "high"]}},
        )
        agents = default_competition_agents(initial_cash=50_000.0)
        run = self.create_run(
            source_id=source.source_id,
            strategy_id=strat["strategy"]["strategy_id"],
            seed=7,
            initial_cash=50_000.0,
            agents=agents,
            deliberation_every_n=3,
            game_mode="individual_competition",
            metadata={"multi_agent": True, "commit_reveal": True, "demo_family": family},
        )
        self.start_run(run["run_id"])
        # Drain until complete or bar cap
        for _ in range(max(20, bars_limit // 5 + 5)):
            if not self.worker.process_next():
                break
            fresh = self.store.get_run(run["run_id"])
            if fresh and fresh.status in TERMINAL_RUN_STATUSES:
                break
            if fresh and fresh.bar_index >= bars_limit:
                fresh.status = RunStatus.COMPLETED.value
                fresh.finished_at = utc_now()
                self.store.update_run(fresh)
                break

        live = self.run_live_state(run["run_id"], message_limit=200, fill_limit=200)
        events = self.store.list_events(run["run_id"], limit=500)
        commits = [e for e in events if e["kind"] in {"order_intent", "commit_reveal_round", "fill"}]
        return {
            "family": family,
            "source": source.public_dict(),
            "strategy": strat,
            "run": live["run"],
            "fills": live["fills"],
            "messages": live["messages"],
            "wallets": (live["run"].get("metadata") or {}).get("wallets"),
            "events_sample": commits[-30:],
            "capabilities": self.market_capabilities(),
            "truth": {
                "demo_reproducible": True,
                "commit_reveal": True,
                "per_agent_wallets": True,
                "next_bar_fills": True,
                "live_trading": False,
            },
        }

