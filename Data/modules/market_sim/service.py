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
from .knowledge_snapshot import build_knowledge_snapshot
from .multi_engine import MultiAgentEngine
from .paper_broker import LocalPaperBroker, PaperSession, build_paper_broker, utc_now as paper_utc
from .providers import default_registry
from .roles import default_competition_agents, ensure_trading_agents_in_fleet
from .store import MarketSimStore, utc_now
from .strategy_eval import strategy_content_hash
from .types import (
    ACTIVE_RUN_STATUSES,
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
        self._bars_per_slice = 50
        self.default_initial_cash = 100_000.0
        self._dataset_service: Any | None = None
        self.worker = MarketSimWorker(
            store,
            self.engine,
            resolve_bars_path=self._resolve_bars_path,
            resolve_strategy=self._resolve_strategy_payload,
            bars_per_slice=self._bars_per_slice,
            multi_engine=self.multi_engine,
        )
        self._gym_sessions: dict[str, Any] = {}
        from .feed.runtime import FeedRuntime
        from .feed.store import MarketFeedStore

        self.feed_store = MarketFeedStore(store.db_path)
        try:
            self.feed_store.ensure_schema()
        except Exception:  # noqa: BLE001
            pass
        self.feed_runtime = FeedRuntime(
            emit=self._emit_feed_event,
            signal=self._emit_feed_signal,
            capture_root=Path(data.markets_root) / "_feed_capture",
        )
        from .portefeuille.service import PortfolioService

        self.portfolios = PortfolioService(store, providers=self.providers, plane=self)

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
        plane = cls(
            store,
            data,
            enabled=enabled,
            brain=brain,
            observability_emit=observability_emit,
        )
        ms = getattr(settings, "market_sim", None)
        bars = int(getattr(ms, "bars_per_slice", 50) or 50)
        cash = float(getattr(ms, "default_initial_cash", 100_000.0) or 100_000.0)
        plane.bars_per_slice = bars
        plane.default_initial_cash = cash
        plane.worker.bars_per_slice = bars
        return plane

    @property
    def bars_per_slice(self) -> int:
        return int(getattr(self, "_bars_per_slice", 50) or 50)

    @bars_per_slice.setter
    def bars_per_slice(self, value: int) -> None:
        self._bars_per_slice = max(1, int(value))
        if hasattr(self, "worker") and self.worker is not None:
            self.worker.bars_per_slice = self._bars_per_slice

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def _emit_feed_event(self, kind: str, payload: dict[str, Any]) -> None:
        if self._emit:
            try:
                self._emit(kind, payload)
            except Exception:  # noqa: BLE001
                pass

    def _emit_feed_signal(self, kind: str, payload: dict[str, Any]) -> None:
        # Soft signal path — observability only from control plane.
        self._emit_feed_event(kind, payload)

    def bind_dataset_service(self, dataset_service: Any) -> None:
        """Optional DatasetService for trajectory export bridge (P1C)."""
        self._dataset_service = dataset_service

    def export_gym_trajectory(
        self,
        run_id: str,
        *,
        dataset_name: str | None = None,
    ) -> dict[str, Any]:
        """Export sealed trajectory JSONL and optionally bridge into DatasetService."""
        self._require_enabled()
        from .dataset_bridge import export_trajectory_to_dataset
        from .trajectory import TrajectoryBuilder

        run = self._get_run(run_id)
        meta = dict(run.metadata or {})
        gym = self._gym_sessions.get(run_id)
        artifact = None
        if gym is not None and getattr(gym, "_trajectory", None) is not None:
            artifact = gym.seal_trajectory()
        elif meta.get("trajectory_id"):
            events = self.store.list_events(run_id, kind="gym_step", limit=50_000)
            builder = TrajectoryBuilder(
                run_id=run_id,
                split_role=str(meta.get("split_role") or "TRAIN"),
                reward_spec=dict(meta.get("reward_spec") or {}),
                input_fingerprint=str(meta.get("input_fingerprint") or ""),
            )
            for ev in events:
                payload = ev.get("payload") or {}
                builder.add_step(
                    observation=dict(payload.get("observation") or {}),
                    action=dict(payload.get("action") or {}),
                    reward=dict(payload.get("reward") or {}),
                    done=bool(payload.get("done")),
                    info=dict(payload.get("info") or {}),
                )
            if builder._steps:  # noqa: SLF001
                artifact = builder.seal(trajectory_id=str(meta.get("trajectory_id")))
        if artifact is None:
            raise MarketSimError(
                "TRAJECTORY_NOT_AVAILABLE",
                "no sealed gym trajectory for this run; complete a gym episode first",
                http_status=404,
            )
        root = Path(self.data.markets_root) / ".artifacts"
        return export_trajectory_to_dataset(
            artifact,
            artifacts_root=root,
            dataset_service=self._dataset_service,
            dataset_name=dataset_name,
        )

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
        # Avoid network probes on every status poll.
        caps = build_market_capabilities(
            feature_enabled=self.enabled,
            binance_reachable=False,
            local_paper=True,
        )
        provider_status = [
            {
                "provider_id": pid,
                "reachable": None,
                "detail": "probe_deferred",
                "license_note": getattr(p, "license_note", ""),
            }
            for pid, p in getattr(self.providers, "providers", {}).items()
        ]
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
        self.ensure_seed_fixtures()
        sources = self.data.scan(register=True)
        self._emit_event("market_data.scan", {"count": len(sources)})
        return [s.public_dict() for s in sources]

    def ensure_seed_fixtures(self) -> list[dict[str, Any]]:
        """Copy built-in OHLCV fixtures into markets_root when the tree is empty.

        Idempotent: if any CSV already exists under markets_root, no-op.
        Does not create runs — only seeds disk files for scan/register.
        """
        self._require_enabled()
        import shutil

        root = self.data.ensure_root()
        existing = [
            p
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in {".csv", ".txt", ".parquet"} and not p.name.startswith(".")
        ]
        if existing:
            return []
        fixtures = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "market_data"
        seeded: list[dict[str, Any]] = []
        if not fixtures.is_dir():
            return seeded
        for name, symbol, timeframe in (
            ("BTCUSDT_1h.csv", "BTCUSDT", "1h"),
            ("AAPL_1d.csv", "AAPL", "1D"),
        ):
            src = fixtures / name
            if not src.exists():
                continue
            dest = root / name
            shutil.copy(src, dest)
            source = self.data.register_file(name, symbol=symbol, timeframe=timeframe)
            source.metadata = {
                **(source.metadata or {}),
                "provider_id": "csv_local",
                "seeded": True,
            }
            self.store.upsert_source(source)
            seeded.append(source.public_dict())
        if seeded:
            self._emit_event("market_data.seeded", {"count": len(seeded)})
        return seeded

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
        from .code_strategy import assert_not_python_strategy
        from .strategy_lineage import attach_lineage_metadata

        now = utc_now()
        parameters = dict(parameters or {"fast_ma": 10, "slow_ma": 30, "lookback": 30})
        entry_rules = dict(entry_rules or {"kind": "ma_cross"})
        exit_rules = dict(exit_rules or {"kind": "ma_cross"})
        risk_rules = dict(risk_rules or {"max_position_pct": 25})
        required_timeframes = list(required_timeframes or ["1h"])
        brain_dependencies = list(brain_dependencies or ["knowledge", "memory", "neuro"])
        assert_not_python_strategy(entry_rules)
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
            metadata=attach_lineage_metadata(
                parent_version=None,
                parent_content_hash=None,
                changelog=changelog,
            ),
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
        from .code_strategy import assert_not_python_strategy
        from .strategy_lineage import attach_lineage_metadata

        assert_not_python_strategy(entry_rules)
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
            metadata=attach_lineage_metadata(
                parent_version=current.version,
                parent_content_hash=current.content_hash,
                changelog=changelog or f"v{new_version_num}",
            ),
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
        decision_cadence: str | None = None,
        stochastic_slippage: bool = False,
        game_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
        sizing_model: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        from .decision_cadence import CADENCE_EVERY_N_BARS, CADENCE_OFF, normalize_cadence

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
        # P3A / D31: no silent default multi-agent roster — agents must be explicit.
        agent_list = list(agents) if agents is not None else []
        every_n = max(1, int(deliberation_every_n))
        meta_in = dict(metadata or {})
        raw_cadence = (
            decision_cadence
            or meta_in.get("decision_cadence")
            or meta_in.get("decisionCadence")
        )
        if raw_cadence is None:
            cadence = CADENCE_EVERY_N_BARS if agent_list else CADENCE_OFF
        else:
            cadence = normalize_cadence(str(raw_cadence))
        now = utc_now()
        from .sizing import SizingModel

        sizing = SizingModel.from_dict(
            sizing_model or meta_in.get("sizing_model") or meta_in.get("sizingModel"),
            defaults={
                "kind": "risk_pct",
                "per_trade_risk_pct": per_trade_risk_pct,
                "max_position_pct": max_position_pct,
            },
        )
        sizing_payload = sizing.public_dict()
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
            deliberation_every_n=every_n,
            cash=initial_cash,
            equity=initial_cash,
            created_at=now,
            updated_at=now,
            sizing_model=sizing_payload,
            metadata={
                "stochastic_slippage": stochastic_slippage,
                **meta_in,
                **({"game_mode": game_mode} if game_mode else {}),
                "instrument_family": infer_family(source.symbol, metadata=source.metadata).value,
                "fill_schedule": "next_bar_open",
                "sizing_model": sizing_payload,
                "decision_cadence": cadence,
                "decisionCadence": cadence,
                "deliberation_every_n": every_n,
            },
        )
        self.store.create_run(run)
        # T1 reproducibility snapshot — proves as_of / dataset / strategy bindings.
        snap = build_knowledge_snapshot(
            run_id=run.run_id,
            as_of=run.start_ts or source.start_ts or now,
            market_dataset_id=(source.metadata or {}).get("dataset_id") or source.source_id,
            market_dataset_hash=source.content_hash,
            market_dataset_version=str((source.metadata or {}).get("dataset_version") or "1"),
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            random_seed=seed,
            risk_configuration={
                "max_position_pct": max_position_pct,
                "max_drawdown_pct": max_drawdown_pct,
                "per_trade_risk_pct": per_trade_risk_pct,
                "fee_bps": fee_bps,
                "slippage_bps": slippage_bps,
                "sizing_model": sizing_payload,
            },
            agents=list(agent_list or []),
            evaluation_window="RESEARCH",
            news_cutoff=run.start_ts or source.start_ts or now,
            memory_cutoff=run.start_ts or source.start_ts or now,
            created_at=now,
            source_path=source.path,
            symbol=source.symbol,
            timeframe=source.timeframe,
        )
        self.store.save_knowledge_snapshot(snap.public_dict())
        run.metadata = {
            **dict(run.metadata or {}),
            "knowledge_snapshot_hash": snap.snapshot_hash,
        }
        self.store.update_run(run)
        self._emit_event("run.created", {"run_id": run.run_id, "data_hash": run.data_hash})
        return run.public_dict()

    def import_market_dataset(
        self,
        path: str,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        seal: bool = False,
        role: str = "RESEARCH",
        provider: str = "csv_local",
    ) -> dict[str, Any]:
        self._require_enabled()
        result = self.data.import_and_validate(
            path,
            symbol=symbol,
            timeframe=timeframe,
            seal=seal,
            role=role,
            provider=provider,
        )
        self._emit_event(
            "market_data.imported",
            {
                "dataset_id": (result.get("dataset") or {}).get("dataset_id"),
                "sealed": seal,
            },
        )
        return result

    def seal_market_dataset(self, dataset_id: str, version: str, *, role: str = "SEALED_TEST") -> dict[str, Any]:
        self._require_enabled()
        sealed = self.data.seal_dataset(dataset_id, version, role=role)
        self._emit_event("market_data.sealed", {"dataset_id": dataset_id, "version": version, "role": role})
        return sealed

    def get_split_manifest(
        self,
        *,
        dataset_id: str | None = None,
        dataset_version: str | None = None,
        manifest_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        found = self.store.get_split_manifest(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            manifest_id=manifest_id,
        )
        if found is None:
            raise MarketSimError("SPLIT_MANIFEST_NOT_FOUND", "no split manifest", http_status=404)
        return found

    def bind_sealed_attempt(
        self,
        *,
        dataset_id: str,
        dataset_version: str,
        strategy_id: str,
        strategy_version: int,
        run_id: str,
        split_manifest_id: str | None = None,
        sealed_attempt_id: str | None = None,
    ) -> dict[str, Any]:
        """Bind or resume the single SEALED holdout attempt for a strategy version."""
        self._require_enabled()
        from .sealed_attempts import SealedAttemptBinder

        manifest_id = split_manifest_id
        if not manifest_id:
            manifest = self.store.get_split_manifest(
                dataset_id=dataset_id, dataset_version=dataset_version
            )
            if manifest is None:
                raise MarketSimError(
                    "SPLIT_MANIFEST_NOT_FOUND",
                    f"no frozen split for {dataset_id}@{dataset_version}",
                    http_status=404,
                )
            if not manifest.get("frozen"):
                raise MarketSimError(
                    "SPLIT_NOT_FROZEN",
                    "SEALED attempt requires frozen DatasetSplitManifest",
                    http_status=409,
                )
            if not manifest.get("sealed"):
                raise MarketSimError(
                    "SPLIT_NO_SEALED_WINDOW",
                    "manifest has no SEALED window",
                    http_status=409,
                )
            manifest_id = str(manifest["manifest_id"])
        binder = SealedAttemptBinder(self.store)
        attempt = binder.bind_or_resume(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            split_manifest_id=manifest_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            run_id=run_id,
            sealed_attempt_id=sealed_attempt_id,
        )
        return attempt.public_dict()

    def create_gym_episode(
        self,
        *,
        source_id: str,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
        split_role: str = "TRAIN",
        dataset_id: str | None = None,
        dataset_version: str | None = None,
        seed: int = 42,
        initial_cash: float = 100_000.0,
        mode: str = "interactive",
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a TradingGym episode (SimRun with gym metadata).

        mode=interactive → caller may gym_reset/gym_step in control plane.
        mode=complete → must be started via start_gym_episode (worker-owned).
        """
        self._require_enabled()
        from .gym import TradingGym, resolve_split_window
        from .split_manifest import SplitRole

        role = str(split_role or SplitRole.TRAIN).upper()
        start_ts = end_ts = None
        manifest = None
        if dataset_id and dataset_version:
            manifest = self.store.get_split_manifest(
                dataset_id=dataset_id, dataset_version=dataset_version
            )
            start_ts, end_ts = resolve_split_window(manifest, role)
            if role == SplitRole.SEALED and (not manifest or not manifest.get("frozen")):
                raise MarketSimError(
                    "SPLIT_NOT_FROZEN",
                    "SEALED gym episode requires frozen DatasetSplitManifest",
                    http_status=409,
                )

        created = self.create_run(
            source_id=source_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            start_ts=start_ts,
            end_ts=end_ts,
            seed=seed,
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            agents=[],  # single-agent gym
            metadata={
                **dict(metadata or {}),
                "gym": True,
                "gym_mode": str(mode or "interactive"),
                "split_role": role,
                "dataset_id": dataset_id,
                "dataset_version": dataset_version,
                "split_manifest_id": (manifest or {}).get("manifest_id") if manifest else None,
                "engine": "gym",
            },
        )
        run_id = created["run_id"]
        if str(mode).lower() == "interactive":
            run = self._get_run(run_id)
            gym = TradingGym(self.store, self.engine)
            bars_path = self._resolve_bars_path(run)
            strat = self._resolve_strategy_payload(run)
            obs = gym.reset(
                run,
                bars_path=bars_path,
                split_role=role,
                start_ts=start_ts,
                end_ts=end_ts,
                strategy_params=strat.get("parameters"),
                entry_rules=strat.get("entry_rules"),
                exit_rules=strat.get("exit_rules"),
            )
            self._gym_sessions[run_id] = gym
            return {
                "episode": run.public_dict(),
                "observation": obs.public_dict(),
                "mode": "interactive",
                "truth": {
                    "via_trading_gym": True,
                    "worker_owned_complete_episode": False,
                },
            }
        return {
            "episode": created,
            "observation": None,
            "mode": "complete",
            "truth": {
                "via_trading_gym": True,
                "worker_owned_complete_episode": True,
                "start_required": True,
            },
        }

    def gym_step(self, run_id: str, action: dict[str, Any] | None = None) -> dict[str, Any]:
        """Interactive single-step (control-plane STEPPING). Not for complete episodes."""
        self._require_enabled()
        from .gym import GymAction, TradingGym

        run = self._get_run(run_id)
        meta = dict(run.metadata or {})
        if not meta.get("gym"):
            raise MarketSimError("NOT_A_GYM_EPISODE", run_id, http_status=400)
        if str(meta.get("gym_mode") or "") == "complete" and run.status in {
            RunStatus.QUEUED.value,
            RunStatus.RUNNING.value,
            RunStatus.COMPLETED.value,
        }:
            raise MarketSimError(
                "GYM_COMPLETE_WORKER_OWNED",
                "complete episodes advance on market_sim worker; use get_run / results",
                http_status=409,
            )
        gym = self._gym_sessions.get(run_id)
        if gym is None:
            gym = TradingGym(self.store, self.engine)
            bars_path = self._resolve_bars_path(run)
            strat = self._resolve_strategy_payload(run)
            gym.reset(
                run,
                bars_path=bars_path,
                split_role=str(meta.get("split_role") or "TRAIN"),
                start_ts=run.start_ts or None,
                end_ts=run.end_ts or None,
                strategy_params=strat.get("parameters"),
                entry_rules=strat.get("entry_rules"),
                exit_rules=strat.get("exit_rules"),
            )
            self._gym_sessions[run_id] = gym
        result = gym.step(GymAction.from_dict(action))
        if result.done:
            self._gym_sessions.pop(run_id, None)
        return result.public_dict()

    def start_gym_episode(self, run_id: str) -> dict[str, Any]:
        """Queue a complete gym episode onto the market_sim worker (EXTERNAL_REQUIRED)."""
        self._require_enabled()
        run = self._get_run(run_id)
        meta = dict(run.metadata or {})
        if not meta.get("gym"):
            raise MarketSimError("NOT_A_GYM_EPISODE", run_id, http_status=400)
        if run.status in TERMINAL_RUN_STATUSES:
            raise MarketSimError("RUN_TERMINAL", f"Run already {run.status}")
        meta["gym_mode"] = "complete"
        run.metadata = meta
        run.status = RunStatus.QUEUED.value
        run.cancel_requested = False
        run.error = None
        self.store.update_run(run)

        if self._runners_externalized():
            if self.job_runtime is None:
                run.status = RunStatus.CREATED.value
                self.store.update_run(run)
                raise MarketSimError(
                    "TRADING_WORKER_UNAVAILABLE",
                    "complete gym episodes require market_sim worker / job_runtime; "
                    "refusing synchronous FastAPI fallback",
                    http_status=503,
                )
            job = self.enqueue_gym_episode(run.run_id, requested_by="market_sim.start_gym_episode")
            payload = run.public_dict()
            payload["job_id"] = getattr(job, "job_id", None)
            payload["execution"] = "EXTERNAL_REQUIRED"
            return payload

        # Non-externalized (dev/test): wake in-process worker — still not sync in request.
        self.worker.wake()
        out = run.public_dict()
        out["execution"] = "in_process_worker"
        return out

    def enqueue_gym_episode(
        self,
        simulation_id: str,
        *,
        parent_job_id: str | None = None,
        requested_by: str = "market_sim_service",
    ) -> Any:
        if self.job_runtime is None:
            raise MarketSimError(
                "TRADING_WORKER_UNAVAILABLE",
                "job_runtime not bound",
                http_status=503,
            )
        run = self.store.get_run(simulation_id)
        if run is None:
            raise MarketSimError("RUN_NOT_FOUND", simulation_id, http_status=404)
        gen = f"gym:{run.status}:{getattr(run, 'bar_index', None) or 0}:{run.updated_at or run.created_at}"
        idem = f"market_sim:gym_episode:{simulation_id}:{gen}"
        return self.job_runtime.enqueue(
            capability_id="market_sim.gym_episode",
            arguments={"simulation_id": simulation_id},
            requested_by=requested_by,
            idempotency_key=idem,
            domain="market_sim",
            domain_entity_type="market_sim_run",
            domain_entity_id=simulation_id,
            worker_pool="market_sim",
            parent_job_id=parent_job_id,
            root_job_id=parent_job_id,
            latency_class="background",
            metadata={"simulation_id": simulation_id, "generation": gen, "gym": True},
        )

    def run_gym_episode_on_worker(self, run_id: str) -> dict[str, Any]:
        """Execute a complete gym episode (called only from market_sim worker)."""
        from .gym import TradingGym

        run = self._get_run(run_id)
        meta = dict(run.metadata or {})
        if not meta.get("gym"):
            raise MarketSimError("NOT_A_GYM_EPISODE", run_id, http_status=400)
        gym = TradingGym(self.store, self.engine)
        strat = self._resolve_strategy_payload(run)
        bars_path = self._resolve_bars_path(run)
        result = gym.run_episode(
            run,
            bars_path=bars_path,
            split_role=str(meta.get("split_role") or "TRAIN"),
            start_ts=run.start_ts or None,
            end_ts=run.end_ts or None,
            strategy_params=strat.get("parameters"),
            entry_rules=strat.get("entry_rules") or {"kind": "hold"},
            exit_rules=strat.get("exit_rules") or {"kind": "hold"},
            # Default policy: hold — strategy-driven gym uses engine path via advance.
            policy=None,
        )
        self.store.add_event(
            run_id,
            kind="gym_episode_finished",
            payload={"steps": result.get("steps"), "status": result.get("status")},
        )
        return result

    def list_market_datasets(
        self,
        *,
        symbol: str | None = None,
        sealed: bool | None = None,
        role: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_dataset_versions(
            symbol=symbol, sealed=sealed, role=role, limit=limit
        )

    def get_run_knowledge_snapshots(self, run_id: str) -> list[dict[str, Any]]:
        self._require_enabled()
        self._get_run(run_id)  # validates existence
        return self.store.list_knowledge_snapshots(run_id)

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
        # Production: never fall back to Control Plane HTTP when workers are the
        # execution owner. Explicit PROVIDER_EXECUTION_UNAVAILABLE instead.
        from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
        from Data.modules.provider_io.facade import ProviderExecutionClient
        from Data.modules.provider_io.readiness import provider_io_workers_ready

        if not self._runners_externalized():
            # Explicit non-production / legacy in-process mode only.
            result = self.providers.import_to_csv(
                provider_id, symbol, timeframe, self.data.markets_root, limit=limit
            )
            executed_via = "control_plane_legacy_inline"
        else:
            if self.job_runtime is None:
                raise MarketSimError(
                    ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                    "job_runtime not bound; refusing Control Plane market fetch fallback",
                    http_status=503,
                )
            db_path = getattr(getattr(self.job_runtime, "store", None), "path", None)
            if not provider_io_workers_ready(db_path):
                raise MarketSimError(
                    ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                    "provider_io workers unavailable; refusing Control Plane market fetch fallback",
                    http_status=503,
                )
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
            executed_via = "provider_io"
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
            "executed_via": executed_via,
        }
        source.updated_at = utc_now()
        self.store.upsert_source(source)
        return {"import": result, "source": source.public_dict()}

    def market_capabilities(self) -> dict[str, Any]:
        return build_market_capabilities(feature_enabled=self.enabled)

    # --- Paper trading ---

    def _paper_broker(self, broker_id: str = "local_paper") -> Any:
        if broker_id not in self._paper_brokers:
            self._paper_brokers[broker_id] = build_paper_broker(
                broker_id, job_runtime=self.job_runtime
            )
        else:
            broker = self._paper_brokers[broker_id]
            if hasattr(broker, "bind_job_runtime"):
                broker.bind_job_runtime(self.job_runtime)
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
        now = utc_now()
        session_id = str(uuid.uuid4())
        # P4A: isolated per-session wallet — do not mutate shared broker.wallet
        if hasattr(broker, "wallet_for_session"):
            session_wallet = broker.wallet_for_session(session_id, initial_cash=initial_cash, create=True)
            wallet_payload = session_wallet.public_dict()
        else:
            wallet_payload = broker.account().get("wallet") if hasattr(broker, "account") else {}

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

        session = {
            "session_id": session_id,
            "status": "active",
            "broker_id": broker_id,
            "provider_id": provider_id,
            "symbol": symbol.upper(),
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "kill_switch": False,
            "feed_status": feed_status,
            "wallet": wallet_payload,
            "orders": [],
            "metadata": {
                "mode": "live_paper",
                "regime_match": match,
                "last_quote": quote,
                "feed_latency_ms": latency,
                "initial_cash": initial_cash,
                "isolated_wallet": True,
                "truth": {
                    "not_live_money": True,
                    "not_historical_backtest": True,
                    "paper_never_auto_approves_live": True,
                    "canonical_risk_guard": True,
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
            if hasattr(broker, "account"):
                try:
                    session["wallet"] = broker.account(session_id=session_id).get("wallet") or broker.account()
                except TypeError:
                    session["wallet"] = broker.account().get("wallet") or broker.account()
            elif hasattr(broker, "wallet_for_session") and session_id in getattr(broker, "sessions", {}):
                session["wallet"] = broker.sessions[session_id].public_dict()
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
        from .paper_forward import PaperForwardRunner
        from .risk_guard import RiskGuard, RiskLimits

        session = self.paper_session_state(session_id)
        if session.get("kill_switch"):
            raise MarketSimError("KILL_SWITCH", "Paper session kill switch armed", http_status=409)
        if session.get("status") != "active":
            raise MarketSimError("SESSION_NOT_ACTIVE", session.get("status") or "")
        allowed, feed_code = self._feed_allows_new_risk(session=session)
        if not allowed:
            raise MarketSimError(
                feed_code,
                f"Paper order blocked — feed health does not allow new risk ({feed_code})",
                http_status=409,
            )
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
        # P4A: canonical RiskGuard on every paper order path
        if hasattr(broker, "wallet_for_session"):
            wallet = broker.wallet_for_session(session_id, create=True)
        else:
            wallet = getattr(broker, "wallet", None)
        if wallet is None:
            raise MarketSimError("PAPER_WALLET_MISSING", session_id, http_status=500)
        runner = PaperForwardRunner(
            risk=RiskGuard(
                RiskLimits(
                    max_position_pct=25.0,
                    max_drawdown_pct=20.0,
                    per_trade_risk_pct=1.0,
                    kill_switch_armed=bool(session.get("kill_switch")),
                )
            )
        )
        decision = runner.step(
            wallet=wallet,
            symbol=session["symbol"],
            price=float(price),
            side=side,
            qty=qty,
            rationale="paper_place_order",
            metadata={"session_id": session_id},
        )
        if not decision.get("allowed"):
            raise MarketSimError(
                "RISK_VETO",
                decision.get("reason") or "RiskGuard blocked paper order",
                http_status=409,
            )
        sized_qty = float(decision.get("qty") or qty)
        order = broker.place(
            symbol=session["symbol"],
            side=side,
            qty=sized_qty,
            client_order_id=client_order_id or str(uuid.uuid4()),
            price_hint=float(price),
            session_id=session_id,
            metadata={
                "strategy_id": session.get("strategy_id"),
                "strategy_version": session.get("strategy_version"),
                "session_id": session_id,
                "risk": decision.get("risk"),
            },
        )
        orders = list(session.get("orders") or [])
        orders.append(order.public_dict())
        session["orders"] = orders
        session["wallet"] = broker.account(session_id=session_id).get("wallet") if hasattr(broker, "account") else {}
        session["updated_at"] = utc_now()
        self.store.upsert_paper_session(session)
        return {"order": order.public_dict(), "session": session, "risk": decision.get("risk")}

    def paper_forward_step(
        self,
        session_id: str,
        *,
        side: str = "HOLD",
        qty: float | None = None,
    ) -> dict[str, Any]:
        """One PaperForwardRunner step (RiskGuard + isolated wallet)."""
        self._require_enabled()
        from .paper_forward import PaperForwardRunner, new_paper_forward_state
        from .risk_guard import RiskGuard, RiskLimits

        session = self.paper_session_state(session_id)
        if session.get("kill_switch"):
            raise MarketSimError("KILL_SWITCH", "Paper session kill switch armed", http_status=409)
        allowed, feed_code = self._feed_allows_new_risk(session=session)
        if not allowed:
            return {
                "forward": (session.get("metadata") or {}).get("paper_forward") or {},
                "result": {
                    "allowed": False,
                    "action": "HOLD",
                    "blocked": True,
                    "code": feed_code,
                    "reason": f"Feed health blocks new risk ({feed_code})",
                },
                "session": session,
            }
        broker = self._paper_broker(session["broker_id"])
        quote = (session.get("metadata") or {}).get("last_quote") or {}
        price = quote.get("price")
        if price is None:
            raise MarketSimError("FEED_UNCERTAIN", "no quote for paper forward", http_status=409)
        wallet = broker.wallet_for_session(session_id, create=True) if hasattr(broker, "wallet_for_session") else broker.wallet
        runner = PaperForwardRunner(risk=RiskGuard(RiskLimits()))
        result = runner.step(
            wallet=wallet,
            symbol=session["symbol"],
            price=float(price),
            side=side,
            qty=qty,
        )
        meta = dict(session.get("metadata") or {})
        fwd = meta.get("paper_forward") or new_paper_forward_state(
            session_id=session_id, symbol=session["symbol"]
        ).public_dict()
        fwd["steps"] = int(fwd.get("steps") or 0) + 1
        fwd["checkpoint_step"] = fwd["steps"]
        fwd["last_decision"] = result
        fwd["last_risk"] = result.get("risk") or {}
        fwd["status"] = "RUNNING"
        fwd["updated_at"] = utc_now()
        meta["paper_forward"] = fwd
        session["metadata"] = meta
        if result.get("allowed") and result.get("action") == "order":
            placed = self.paper_place_order(
                session_id,
                side=str(result.get("side") or side),
                qty=float(result.get("qty") or qty or 0),
            )
            session = placed["session"]
            result["order"] = placed["order"]
        else:
            self.store.upsert_paper_session(session)
        return {"forward": fwd, "result": result, "session": session}

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

    # --- Paper Portefeuille (multi-asset capital book) ---

    def create_portfolio(self, **kwargs: Any) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.create_portfolio(**kwargs)

    def list_portfolios(self, *, limit: int = 50) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.portfolios.list_portfolios(limit=limit)

    def get_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.get_portfolio(portfolio_id)

    def patch_portfolio(self, portfolio_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.patch_portfolio(portfolio_id, patch)

    def start_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.start(portfolio_id)

    def pause_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.pause(portfolio_id)

    def resume_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.resume(portfolio_id)

    def stop_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.stop(portfolio_id)

    def portfolio_kill_switch(self, portfolio_id: str, *, armed: bool = True) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.kill_switch(portfolio_id, armed=armed)

    def portfolio_dashboard(self, portfolio_id: str, *, range_key: str = "YTD") -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.dashboard(portfolio_id, range_key=range_key)

    def portfolio_place_order(self, portfolio_id: str, **kwargs: Any) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.place_order(portfolio_id, **kwargs)

    def portfolio_close_position(
        self, portfolio_id: str, position_id: str, *, fraction: float = 1.0
    ) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.close_position(portfolio_id, position_id, fraction=fraction)

    def portfolio_close_positions(
        self, portfolio_id: str, position_ids: list[str]
    ) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.close_positions(portfolio_id, position_ids)

    def portfolio_performance(self, portfolio_id: str, *, range_key: str = "YTD") -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.performance(portfolio_id, range_key=range_key)

    def portfolio_save_allocations(
        self, portfolio_id: str, allocations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.save_allocations(portfolio_id, allocations)

    def portfolio_rebalance_preview(
        self, portfolio_id: str, orders: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.rebalance_preview(portfolio_id, orders)

    def portfolio_rebalance_execute(
        self, portfolio_id: str, orders: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.rebalance_execute(portfolio_id, orders)

    def portfolio_export(self, portfolio_id: str, *, fmt: str = "json") -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.export_report(portfolio_id, fmt=fmt)

    def portfolio_tick(self, portfolio_id: str, *, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.autonomous_tick(portfolio_id, decision=decision)

    def apply_portfolio_trading_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.apply_trading_decision(decision)

    def run_portfolio_orchestra_decision(self, portfolio_id: str) -> dict[str, Any]:
        """Map orchestra deliberation onto a structured TradingDecision for the portefeuille.

        Does not bypass RiskGuard — decisions are applied via place_order.
        """
        self._require_enabled()
        row = self.portfolios.get_portfolio(portfolio_id)
        orchestra_id = row.get("orchestra_id")
        if not orchestra_id:
            return {
                "decision_id": str(uuid.uuid4()),
                "portfolio_id": portfolio_id,
                "action": "HOLD",
                "symbol": row.get("benchmark_symbol") or "BTCUSDT",
                "rationale_summary": "No orchestra assigned",
            }
        # Prefer injecting a paper BUY proposal when equity is mostly cash (bootstrap).
        # Full orchestra deliberation remains available via TradingOrchestraService.
        cash = float(row.get("cash") or 0)
        equity = float(row.get("equity") or 0)
        symbol = str(row.get("benchmark_symbol") or "BTCUSDT")
        if equity > 0 and cash / equity > 0.85:
            notional = equity * 0.05
            try:
                marks, _ = self.portfolios.fetch_marks(self.store.get_portfolio(portfolio_id), symbols=[symbol])
                px = float(marks.get(symbol) or 0)
            except Exception:  # noqa: BLE001
                px = 0.0
            qty = (notional / px) if px > 0 else 0.0
            if qty > 0:
                return {
                    "decision_id": str(uuid.uuid4()),
                    "portfolio_id": portfolio_id,
                    "orchestra_id": orchestra_id,
                    "agent_id": "execution_agent",
                    "strategy_id": None,
                    "strategy_version": None,
                    "symbol": symbol,
                    "action": "BUY",
                    "requested_qty": qty,
                    "rationale_summary": "Bootstrap allocation — idle cash above 85%",
                    "created_at": utc_now(),
                }
        return {
            "decision_id": str(uuid.uuid4()),
            "portfolio_id": portfolio_id,
            "orchestra_id": orchestra_id,
            "action": "HOLD",
            "symbol": symbol,
            "rationale_summary": "Orchestra cycle — no actionable edge",
            "created_at": utc_now(),
        }

    # --- Realtime market feeds ---

    def list_feeds(self) -> list[dict[str, Any]]:
        self._require_enabled()
        live = {f["feed_id"]: f for f in self.feed_runtime.list_feeds()}
        for row in self.feed_store.list_sessions():
            live.setdefault(row["feed_id"], row)
        return list(live.values())

    def get_feed(self, feed_id: str) -> dict[str, Any]:
        self._require_enabled()
        try:
            session = self.feed_runtime.get(feed_id)
            return session.sub.public_dict()
        except MarketSimError:
            row = self.feed_store.get_session(feed_id)
            if row is None:
                raise MarketSimError("FEED_NOT_FOUND", feed_id, http_status=404)
            return row

    def feed_snapshot(self, feed_id: str) -> dict[str, Any]:
        self._require_enabled()
        try:
            return self.feed_runtime.snapshot(feed_id)
        except MarketSimError:
            row = self.feed_store.get_session(feed_id)
            if row is None:
                raise
            return {"subscription": row, "health": {"status": row.get("status")}, "symbols": {}}

    def feed_metrics(self, feed_id: str) -> dict[str, Any]:
        self._require_enabled()
        try:
            session = self.feed_runtime.get(feed_id)
            return {
                "feed_id": feed_id,
                "metrics": session.metrics.public_dict(),
                "health": session.health(),
            }
        except MarketSimError:
            cps = self.feed_store.list_checkpoints(feed_id, limit=1)
            if not cps:
                raise
            return {
                "feed_id": feed_id,
                "metrics": cps[0].get("metrics") or {},
                "checkpoint": cps[0],
            }

    def start_feed(
        self,
        *,
        provider_id: str = "binance_public",
        symbols: list[str],
        stream_kinds: list[str] | None = None,
        restart_policy: str = "MANUAL",
        capture_mode: str = "OFF",
        stale_after_seconds: float = 30.0,
        gap_recovery_enabled: bool = True,
        max_runtime_seconds: float = 3600.0,
        feed_id: str | None = None,
        license_note: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        if not symbols:
            raise MarketSimError("INVALID_REQUEST", "symbols required", http_status=400)
        session = self.feed_runtime.create_subscription(
            provider_id=provider_id,
            symbols=symbols,
            stream_kinds=stream_kinds,
            restart_policy=restart_policy,
            capture_mode=capture_mode,
            stale_after_seconds=stale_after_seconds,
            gap_recovery_enabled=gap_recovery_enabled,
            feed_id=feed_id,
            license_note=license_note,
            metadata=metadata,
        )
        sub = session.sub
        self.feed_store.upsert_session({**sub.public_dict(), "checkpoint": {}})

        from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
        from Data.modules.provider_io.facade import ProviderExecutionClient
        from Data.modules.provider_io.readiness import provider_io_workers_ready
        from .feed.types import FeedConnectionState

        payload = {
            "feed_id": sub.feed_id,
            "connection_id": sub.connection_id,
            "provider_id": provider_id,
            "symbols": list(sub.symbols),
            "stream_kinds": list(sub.stream_kinds),
            "gap_recovery_enabled": gap_recovery_enabled,
            "max_runtime_seconds": float(max_runtime_seconds),
            "db_path": str(self.store.db_path),
            "stale_after_seconds": stale_after_seconds,
        }

        if self._runners_externalized():
            if self.job_runtime is None:
                session.set_status(FeedConnectionState.FAILED, error="job_runtime not bound")
                raise MarketSimError(
                    ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                    "job_runtime not bound; refusing Control Plane WebSocket fallback",
                    http_status=503,
                )
            db_path = getattr(getattr(self.job_runtime, "store", None), "path", None)
            if not provider_io_workers_ready(db_path) and not self._market_feed_pool_ready(db_path):
                session.set_status(
                    FeedConnectionState.FAILED,
                    error="market_feed workers unavailable",
                )
                raise MarketSimError(
                    ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                    "market_feed/provider_io workers unavailable; refusing Control Plane WS fallback",
                    http_status=503,
                )
            client = ProviderExecutionClient(self.job_runtime)
            try:
                job = client.submit(
                    provider=provider_id,
                    capability="market.stream",
                    payload=payload,
                    credential_ref="none",
                    streaming=True,
                    latency_class="background",
                    requested_by="market_sim_service",
                    deadline_seconds=float(max_runtime_seconds),
                    metadata={"feed_id": sub.feed_id},
                )
            except ProviderError as exc:
                session.set_status(FeedConnectionState.FAILED, error=str(exc))
                raise MarketSimError(
                    exc.code.value,
                    str(exc),
                    http_status=503 if exc.retryable else 502,
                ) from exc
            sub.job_id = getattr(job, "job_id", None)
            session.set_status(FeedConnectionState.CONNECTING)
            self.feed_store.upsert_session({**sub.public_dict(), "checkpoint": {}})
            return {
                **sub.public_dict(),
                "job_id": sub.job_id,
                "executed_via": "market_feed",
            }

        # Non-externalized / tests: in-process fake ingest only — no real WS from FastAPI.
        session.set_status(FeedConnectionState.LIVE)
        self.feed_store.upsert_session({**sub.public_dict(), "checkpoint": {}})
        return {
            **sub.public_dict(),
            "executed_via": "inprocess_fake_ingest",
            "truth": {
                "no_control_plane_websocket": True,
                "market_data_only": True,
                "live_money": "BLOCKED",
            },
        }

    def _market_feed_pool_ready(self, db_path: Any) -> bool:
        del db_path
        try:
            from Data.modules.workers.pools import POOL_CATALOG

            return "market_feed" in POOL_CATALOG
        except Exception:  # noqa: BLE001
            return False

    def stop_feed(self, feed_id: str) -> dict[str, Any]:
        self._require_enabled()
        from Data.modules.provider_io.facade import ProviderExecutionClient
        from .feed.types import FeedConnectionState

        try:
            session = self.feed_runtime.get(feed_id)
        except MarketSimError:
            row = self.feed_store.get_session(feed_id)
            if row is None:
                raise
            row["status"] = FeedConnectionState.STOPPED.value
            row["updated_at"] = utc_now()
            self.feed_store.upsert_session(row)
            return row

        job_id = session.sub.job_id
        if self._runners_externalized() and self.job_runtime is not None:
            client = ProviderExecutionClient(self.job_runtime)
            try:
                client.submit(
                    provider=session.sub.provider_id,
                    capability="market.stream.stop",
                    payload={"feed_id": feed_id, "job_id": job_id},
                    credential_ref="none",
                    latency_class="interactive",
                    requested_by="market_sim_service",
                    deadline_seconds=30.0,
                )
            except Exception:  # noqa: BLE001
                pass
            if job_id and hasattr(self.job_runtime, "cancel"):
                try:
                    self.job_runtime.cancel(job_id)
                except Exception:  # noqa: BLE001
                    pass
        out = self.feed_runtime.stop(feed_id)
        try:
            checkpoint = self.feed_runtime.durable_checkpoint(feed_id)
        except MarketSimError:
            checkpoint = {}
        self.feed_store.upsert_session({**out, "checkpoint": checkpoint})
        return out

    def scan_batch(
        self,
        *,
        symbols: list[str] | None = None,
        provider_id: str = "binance_public",
        timeframe: str = "1m",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Batch scan local market sources and optionally refresh via provider import."""
        self._require_enabled()
        scanned = self.scan_market_data() if hasattr(self, "scan_market_data") else []
        results: list[dict[str, Any]] = []
        syms = [s.upper() for s in (symbols or [])]
        for source in scanned if isinstance(scanned, list) else []:
            pub = source if isinstance(source, dict) else (
                source.public_dict() if hasattr(source, "public_dict") else dict(source)
            )
            if isinstance(pub, dict):
                if syms and str(pub.get("symbol") or "").upper() not in syms:
                    continue
                results.append(pub)
        imports: list[dict[str, Any]] = []
        for sym in syms[:8]:
            try:
                imports.append(
                    self.import_provider_data(
                        provider_id=provider_id,
                        symbol=sym,
                        timeframe=timeframe,
                        limit=min(int(limit), 500),
                    )
                )
            except MarketSimError as exc:
                imports.append({"symbol": sym, "error": exc.public_dict()})
        return {
            "sources": results,
            "imports": imports,
            "provider_id": provider_id,
            "timeframe": timeframe,
            "executed_via": "market_sim.scan_batch",
        }

    def _feed_allows_new_risk(self, *, session: dict[str, Any] | None = None) -> tuple[bool, str]:
        meta = dict((session or {}).get("metadata") or {})
        feed_id = meta.get("feed_id") or (session or {}).get("feed_id")
        if not feed_id:
            return True, ""
        try:
            feed_session = self.feed_runtime.get(str(feed_id))
        except MarketSimError:
            return False, "MARKET_FEED_STALE"
        feed_session.check_stale()
        if not feed_session.allows_new_risk():
            health = feed_session.health()
            if health.get("gap_unresolved"):
                return False, "MARKET_FEED_GAP"
            return False, "MARKET_FEED_STALE"
        return True, ""

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

    # --- Research campaigns (P3B) ---

    def create_research_campaign(
        self,
        *,
        name: str,
        strategy_id: str,
        source_id: str,
        strategy_version: int | None = None,
        max_iterations: int = 10,
        seed: int = 42,
        hypothesis: str = "",
        acceptance_criteria: dict[str, Any] | None = None,
        autonomy_ceiling: str = "A2",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        from .research_campaign import new_campaign

        strat = self.store.get_strategy(strategy_id)
        if strat is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
        ver = self.store.get_strategy_version(strategy_id, strategy_version)
        if ver is None:
            raise MarketSimError("STRATEGY_VERSION_MISSING", strategy_id, http_status=404)
        source = self.data.get_source(source_id)
        if source.status != SourceStatus.READY.value:
            raise MarketSimError("SOURCE_NOT_READY", source_id, http_status=400)
        campaign = new_campaign(
            name=name,
            strategy_id=strategy_id,
            strategy_version=ver.version,
            source_id=source_id,
            max_iterations=max_iterations,
            seed=seed,
            hypothesis=hypothesis,
            acceptance_criteria=acceptance_criteria,
            autonomy_ceiling=autonomy_ceiling,
            as_of=source.start_ts or utc_now(),
            metadata=metadata,
        )
        self.store.upsert_research_campaign(campaign.public_dict())
        return campaign.public_dict()

    def get_research_campaign(self, campaign_id: str) -> dict[str, Any]:
        self._require_enabled()
        row = self.store.get_research_campaign(campaign_id)
        if row is None:
            raise MarketSimError("CAMPAIGN_NOT_FOUND", campaign_id, http_status=404)
        return row

    def list_research_campaigns(self, *, limit: int = 50) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_research_campaigns(limit=limit)

    def start_research_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Queue EXTERNAL_REQUIRED campaign on market_sim worker (no FastAPI sync fallback)."""
        self._require_enabled()
        row = self.get_research_campaign(campaign_id)
        if self.job_runtime is None:
            raise MarketSimError(
                "TRADING_WORKER_UNAVAILABLE",
                "ResearchCampaign requires external market_sim worker via JobRuntime",
                http_status=503,
            )
        row["status"] = "QUEUED"
        row["updated_at"] = utc_now()
        self.store.upsert_research_campaign(row)
        job = self.enqueue_research_campaign(campaign_id, requested_by="market_sim.start_research_campaign")
        row["job_id"] = getattr(job, "job_id", None) or (job.get("job_id") if isinstance(job, dict) else None)
        self.store.upsert_research_campaign(row)
        print(f"[JOB] ResearchCampaign '{row.get('name') or campaign_id[:8]}' ingepland", flush=True)
        return {"campaign": row, "job": job.public_dict() if hasattr(job, "public_dict") else dict(job or {})}

    def enqueue_research_campaign(
        self,
        campaign_id: str,
        *,
        requested_by: str = "market_sim",
    ) -> Any:
        if self.job_runtime is None:
            raise MarketSimError("TRADING_WORKER_UNAVAILABLE", "job_runtime unbound", http_status=503)
        row = self.get_research_campaign(campaign_id)
        gen = str(row.get("checkpoint_iteration") or 0)
        idem = f"market_sim:research_campaign:{campaign_id}:{gen}"
        return self.job_runtime.enqueue(
            capability_id="market_sim.research_campaign",
            arguments={"campaign_id": campaign_id},
            requested_by=requested_by,
            idempotency_key=idem,
            domain="market_sim",
            domain_entity_type="research_campaign",
            domain_entity_id=campaign_id,
            worker_pool="market_sim",
        )

    def run_research_campaign_on_worker(self, campaign_id: str) -> dict[str, Any]:
        """Execute/resume campaign iterations on the worker (checkpoint resume).

        Each trial completes only after a canonical gym/simulation episode commits
        metrics. Fabricated wins, all-trials-as-wins, and zero-risk promotion
        inputs are forbidden.
        """
        from .promotion import evaluate_promotion
        from .research_campaign import ResearchCampaign, advance_campaign_iteration
        from .scorecards import build_scorecard
        from .wfa import evaluate_acceptance_from_run

        row = self.get_research_campaign(campaign_id)
        campaign = ResearchCampaign(
            campaign_id=row["campaign_id"],
            name=row["name"],
            strategy_id=row["strategy_id"],
            strategy_version=int(row["strategy_version"]),
            source_id=row["source_id"],
            status=row["status"],
            max_iterations=int(row["max_iterations"]),
            checkpoint_iteration=int(row["checkpoint_iteration"]),
            current_iteration=int(row["current_iteration"]),
            seed=int(row["seed"]),
            hypothesis=row.get("hypothesis") or "",
            acceptance_criteria=dict(row.get("acceptance_criteria") or {}),
            trial_ids=list(row.get("trial_ids") or []),
            results=dict(row.get("results") or {}),
            scorecard=dict(row.get("scorecard") or {}),
            promotion=dict(row.get("promotion") or {}),
            autonomy_ceiling=row.get("autonomy_ceiling") or "A2",
            as_of=row.get("as_of") or "",
            job_id=row.get("job_id"),
            error=row.get("error") or "",
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
            metadata=dict(row.get("metadata") or {}),
        )
        start_from = campaign.checkpoint_iteration
        campaign.status = "RUNNING"
        self.store.upsert_research_campaign(campaign.public_dict())

        wins = 0
        measured_returns: list[float] = []
        measured_drawdowns: list[float] = []
        last_run_metrics: dict[str, Any] = {}
        last_run_id: str | None = None

        while campaign.checkpoint_iteration < campaign.max_iterations:
            it = campaign.checkpoint_iteration + 1
            trial_id = str(uuid.uuid4())
            trial_status = "failed"
            iteration_result: dict[str, Any] = {
                "status": "failed",
                "resumed_from": start_from,
                "simulation_executed": False,
            }
            try:
                episode = self.create_gym_episode(
                    source_id=campaign.source_id,
                    strategy_id=campaign.strategy_id,
                    strategy_version=campaign.strategy_version,
                    seed=campaign.seed + it,
                    mode="complete",
                    metadata={
                        "campaign_id": campaign.campaign_id,
                        "trial_id": trial_id,
                        "iteration": it,
                        "acceptance_criteria": campaign.acceptance_criteria,
                    },
                )
                run_id = str((episode.get("episode") or {}).get("run_id") or "")
                if not run_id:
                    raise MarketSimError("CAMPAIGN_TRIAL_NO_RUN", "gym episode missing run_id")
                sim_result = self.run_gym_episode_on_worker(run_id)
                run = self._get_run(run_id)
                metrics = dict(sim_result.get("metrics") or run.metrics or {})
                last_run_metrics = metrics
                last_run_id = run_id
                acceptance = evaluate_acceptance_from_run(
                    run.public_dict(),
                    criteria=campaign.acceptance_criteria
                    or {"min_trades": 1, "max_drawdown_pct": 100.0, "min_total_return_pct": -100.0},
                )
                accepted = bool(getattr(acceptance, "passed", False))
                if accepted:
                    wins += 1
                # Extract measured scalars for scorecard (never invent zeros as wins).
                def _metric_scalar(name: str, *alts: str) -> float | None:
                    for key in (name, *alts):
                        raw = metrics.get(key)
                        if isinstance(raw, dict):
                            if raw.get("value") is None:
                                continue
                            try:
                                return float(raw["value"])
                            except (TypeError, ValueError):
                                continue
                        if raw is None:
                            continue
                        try:
                            return float(raw)
                        except (TypeError, ValueError):
                            continue
                    return None

                ret = _metric_scalar("total_return", "total_return_pct")
                dd = _metric_scalar("max_drawdown", "max_drawdown_pct")
                if ret is not None:
                    measured_returns.append(ret)
                if dd is not None:
                    measured_drawdowns.append(dd)

                trial_status = "completed"
                iteration_result = {
                    "status": "ok" if accepted else "rejected",
                    "resumed_from": start_from,
                    "simulation_executed": True,
                    "run_id": run_id,
                    "accepted": accepted,
                    "acceptance": acceptance.public_dict()
                    if hasattr(acceptance, "public_dict")
                    else dict(acceptance),
                    "metrics": metrics,
                }
                self.store.append_trial(
                    {
                        "trial_id": trial_id,
                        "strategy_id": campaign.strategy_id,
                        "strategy_version": campaign.strategy_version,
                        "hypothesis": campaign.hypothesis or f"campaign iter {it}",
                        "proposer_agent_id": "research_campaign",
                        "data_hash": campaign.source_id,
                        "fingerprint": f"{campaign.campaign_id}:{it}:{campaign.seed}",
                        "status": trial_status,
                        "config": {
                            "campaign_id": campaign.campaign_id,
                            "iteration": it,
                            "run_id": run_id,
                        },
                        "split": {"role": "TRAIN"},
                        "results": {
                            "iteration": it,
                            "status": trial_status,
                            "run_id": run_id,
                            "accepted": accepted,
                            "metrics": metrics,
                            "simulation_executed": True,
                        },
                        "acceptance_criteria": campaign.acceptance_criteria,
                        "seed": campaign.seed + it,
                        "created_at": utc_now(),
                    }
                )
            except Exception as exc:  # noqa: BLE001 — persist failed trial, do not fabricate metrics
                iteration_result = {
                    "status": "failed",
                    "resumed_from": start_from,
                    "simulation_executed": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
                self.store.append_trial(
                    {
                        "trial_id": trial_id,
                        "strategy_id": campaign.strategy_id,
                        "strategy_version": campaign.strategy_version,
                        "hypothesis": campaign.hypothesis or f"campaign iter {it}",
                        "proposer_agent_id": "research_campaign",
                        "data_hash": campaign.source_id,
                        "fingerprint": f"{campaign.campaign_id}:{it}:{campaign.seed}",
                        "status": "failed",
                        "config": {"campaign_id": campaign.campaign_id, "iteration": it},
                        "split": {},
                        "results": {
                            "iteration": it,
                            "status": "failed",
                            "simulation_executed": False,
                            "error": str(exc),
                        },
                        "acceptance_criteria": campaign.acceptance_criteria,
                        "seed": campaign.seed + it,
                        "created_at": utc_now(),
                    }
                )

            advance_campaign_iteration(
                campaign,
                trial_id=trial_id,
                iteration_result=iteration_result,
            )
            self.store.upsert_research_campaign(campaign.public_dict())

        trials = len(campaign.trial_ids)
        # Scorecard from measured outcomes only — zeros are UNMEASURED when no metrics.
        total_return = sum(measured_returns) / len(measured_returns) if measured_returns else None
        max_drawdown = max(measured_drawdowns) if measured_drawdowns else None
        card = build_scorecard(
            agent_id="research_campaign",
            role="strategy_researcher",
            trials=trials,
            wins=wins,
            total_return=float(total_return) if total_return is not None else 0.0,
            max_drawdown=float(max_drawdown) if max_drawdown is not None else 1.0,
        )
        card_payload = card.public_dict()
        card_payload["measurement"] = {
            "wins_from_acceptance": True,
            "total_return": "MEASURED" if total_return is not None else "UNMEASURED",
            "max_drawdown": "MEASURED" if max_drawdown is not None else "UNMEASURED",
            "fabricated_zero_risk": False,
        }
        campaign.scorecard = card_payload

        promo_metrics = dict(last_run_metrics) if last_run_metrics else {}
        campaign.promotion = evaluate_promotion(
            run={"run_id": last_run_id or "", "metrics": promo_metrics, "metadata": {}}
            if last_run_id
            else None,
            metrics=promo_metrics or None,
            acceptance_criteria=campaign.acceptance_criteria
            or {"min_trades": 1, "max_drawdown_pct": 100.0, "min_total_return_pct": -100.0},
            current_level="A0",
            target_level=campaign.autonomy_ceiling,
        )
        # Incomplete simulation receipts → honest incomplete, never fabricated COMPLETED wins.
        executed = sum(
            1
            for it in (campaign.results.get("iterations") or [])
            if it.get("simulation_executed")
        )
        if executed == 0:
            campaign.status = "FAILED"
            campaign.error = "NO_EXECUTED_SIMULATION_RECEIPTS"
        else:
            campaign.status = "COMPLETED"
        campaign.updated_at = utc_now()
        campaign.metadata = {
            **dict(campaign.metadata),
            "executed_trials": executed,
            "accepted_wins": wins,
            "last_run_id": last_run_id,
        }
        self.store.upsert_research_campaign(campaign.public_dict())
        return campaign.public_dict()

    def readiness_ladder(self) -> dict[str, Any]:
        from .readiness import readiness_ladder

        return readiness_ladder()

