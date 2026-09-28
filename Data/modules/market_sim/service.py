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
        hybrid_retriever: Any | None = None,
        staged_retriever: Any | None = None,
        brain_access: Any | None = None,
    ) -> "MarketSimControlPlane":
        if db_path is not None:
            path = Path(db_path)
        else:
            from Data.modules.common.database_domains import market_path_from_settings

            path = market_path_from_settings(settings)
        store = MarketSimStore(path)
        store.initialize()
        markets_root = Path(settings.market_sim.markets_root)
        data = MarketDataStore(store, markets_root)
        brain = BrainFacade(
            knowledge=adapt_knowledge_store(
                knowledge,
                hybrid_retriever=hybrid_retriever,
                staged_retriever=staged_retriever,
                brain_access=brain_access,
            )
            if knowledge is not None or hybrid_retriever is not None or brain_access is not None
            else NullKnowledge(),
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
        """Emit bounded trading lifecycle observability (category=trading/market_sim)."""
        # Durable in-process ring for tests / local operators (bounded).
        ring = getattr(self, "_lifecycle_events", None)
        if ring is None:
            self._lifecycle_events = []
            ring = self._lifecycle_events
        event = {
            "category": "trading",
            "subsystem": "market_sim",
            "name": str(name),
            "payload_keys": sorted(str(k) for k in dict(payload or {}).keys())[:32],
            "refs": {
                k: payload.get(k)
                for k in (
                    "run_id",
                    "learning_run_id",
                    "candidate_id",
                    "sealed_attempt_id",
                    "dataset_id",
                    "strategy_id",
                    "session_id",
                )
                if isinstance(payload, dict) and payload.get(k) is not None
            },
        }
        ring.append(event)
        if len(ring) > 500:
            del ring[: len(ring) - 500]
        if self._emit:
            try:
                self._emit("trading", name, payload=payload, subsystem="market_sim")
            except TypeError:
                try:
                    self._emit("market_sim", name, payload=payload)
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass

    def list_lifecycle_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Bounded trading lifecycle events for observability consumers/tests."""
        ring = list(getattr(self, "_lifecycle_events", []) or [])
        return ring[-max(1, int(limit)) :]

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
                "live_trading_blocked": True,
                "worker_fabric_pool": "market_sim",
                "worker_is_daemon_thread_by_default": False,
                "subprocess_entrypoint": "Data.modules.workers.entrypoints.market_sim",
                "causality_enforced": True,
                "next_bar_open_fills": True,
                "commit_reveal_multi_wallet": True,
                "ohlcv_not_orderbook": True,
                "profitable_backtest_is_not_proof": True,
                "qualification_authority_is_sole_scientific_owner": True,
            },
        }

    # --- Market data ---

    def scan_market_data(self) -> list[dict[str, Any]]:
        """Direct scan helper — production API must enqueue ``market_sim.data.scan``."""
        self._require_enabled()
        self.ensure_seed_fixtures()
        sources = self.data.scan(register=True)
        self._emit_event("market_data.scan", {"count": len(sources)})
        return [s.public_dict() for s in sources]

    def enqueue_market_data_scan(
        self,
        *,
        max_entries: int = 200,
        cursor: dict[str, Any] | None = None,
        deep_validate: bool = True,
        requested_by: str = "api.market_sim",
        parent_job_id: str | None = None,
    ) -> Any:
        self._require_enabled()
        if self.job_runtime is None:
            raise MarketSimError(
                "MARKET_DATA_WORKER_UNAVAILABLE",
                "JobRuntime required for market_sim.data.scan",
                http_status=503,
            )
        import uuid as _uuid

        return self.job_runtime.enqueue(
            capability_id="market_sim.data.scan",
            arguments={
                "max_entries": int(max_entries),
                "cursor": dict(cursor or {}),
                "deep_validate": bool(deep_validate),
                "register": True,
            },
            requested_by=requested_by,
            parent_job_id=parent_job_id,
            domain="market_sim",
            domain_entity_type="market_data_scan",
            domain_entity_id=str(self.data.markets_root),
            worker_pool="market_sim",
            resource_class="IO_HEAVY",
            latency_class="batch",
            idempotency_key=f"market_sim:data.scan:{_uuid.uuid4().hex[:10]}",
        )

    def enqueue_market_data_import(
        self,
        path: str,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        seal: bool = False,
        role: str = "RESEARCH",
        provider: str = "csv_local",
        requested_by: str = "api.market_sim",
    ) -> Any:
        self._require_enabled()
        if self.job_runtime is None:
            raise MarketSimError(
                "MARKET_DATA_WORKER_UNAVAILABLE",
                "JobRuntime required for market_sim.data.import",
                http_status=503,
            )
        import uuid as _uuid

        return self.job_runtime.enqueue(
            capability_id="market_sim.data.import",
            arguments={
                "path": path,
                "symbol": symbol,
                "timeframe": timeframe,
                "seal": seal,
                "role": role,
                "provider": provider,
            },
            requested_by=requested_by,
            domain="market_sim",
            domain_entity_type="market_data_import",
            domain_entity_id=str(path),
            worker_pool="market_sim",
            resource_class="IO_HEAVY",
            latency_class="batch",
            idempotency_key=f"market_sim:data.import:{_uuid.uuid4().hex[:10]}",
        )

    def enqueue_scan_batch(
        self,
        *,
        symbols: list[str] | None = None,
        provider_id: str = "binance_public",
        timeframe: str = "1m",
        limit: int = 100,
        requested_by: str = "api.market_sim",
    ) -> Any:
        self._require_enabled()
        if self.job_runtime is None:
            raise MarketSimError(
                "MARKET_SIM_WORKER_UNAVAILABLE",
                "JobRuntime required for market_sim.scan_batch",
                http_status=503,
            )
        import uuid as _uuid

        return self.job_runtime.enqueue(
            capability_id="market_sim.scan_batch",
            arguments={
                "symbols": list(symbols or []),
                "provider_id": provider_id,
                "timeframe": timeframe,
                "limit": int(limit),
            },
            requested_by=requested_by,
            domain="market_sim",
            domain_entity_type="market_sim_scan_batch",
            domain_entity_id=provider_id,
            worker_pool="market_sim",
            resource_class="IO_HEAVY",
            latency_class="batch",
            idempotency_key=f"market_sim:scan_batch:{_uuid.uuid4().hex[:10]}",
        )

    def enqueue_portfolio_tick(
        self,
        portfolio_id: str,
        *,
        requested_by: str = "api.market_sim",
        not_before: str | None = None,
        parent_job_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        self._require_enabled()
        if self.job_runtime is None:
            raise MarketSimError(
                "MARKET_SIM_WORKER_UNAVAILABLE",
                "JobRuntime required for market_sim.portfolio_tick",
                http_status=503,
            )
        key = idempotency_key or f"market_sim:portfolio_tick:{portfolio_id}:{not_before or 'now'}"
        return self.job_runtime.enqueue(
            capability_id="market_sim.portfolio_tick",
            arguments={"portfolio_id": portfolio_id, "not_before": not_before},
            requested_by=requested_by,
            parent_job_id=parent_job_id,
            domain="market_sim",
            domain_entity_type="market_sim_portfolio",
            domain_entity_id=portfolio_id,
            worker_pool="market_sim",
            latency_class="background",
            idempotency_key=key,
            metadata={"not_before": not_before} if not_before else None,
        )

    def enqueue_assurance_scan(self, *, requested_by: str = "api.market_sim") -> Any:
        self._require_enabled()
        if self.job_runtime is None:
            raise MarketSimError(
                "MARKET_SIM_WORKER_UNAVAILABLE",
                "JobRuntime required for market_sim.assurance.scan",
                http_status=503,
            )
        import uuid as _uuid

        return self.job_runtime.enqueue(
            capability_id="market_sim.assurance.scan",
            arguments={},
            requested_by=requested_by,
            domain="market_sim",
            domain_entity_type="market_sim_assurance",
            domain_entity_id="institutional",
            worker_pool="market_sim",
            resource_class="CPU_HEAVY",
            latency_class="batch",
            idempotency_key=f"market_sim:assurance:{_uuid.uuid4().hex[:10]}",
        )

    def run_market_data_scan_slice(
        self,
        *,
        max_entries: int = 200,
        cursor: dict[str, Any] | None = None,
        deep_validate: bool = True,
        register: bool = True,
    ) -> dict[str, Any]:
        self._require_enabled()
        self.ensure_seed_fixtures()
        result = self.data.scan_slice(
            register=register,
            max_entries=max_entries,
            cursor=cursor,
            deep_validate=deep_validate,
        )
        self._emit_event(
            "market_data.scan_slice",
            {"processed": result.get("processed"), "done": result.get("done")},
        )
        return {
            "sources": result.get("sources_public") or [],
            "processed": result.get("processed"),
            "done": result.get("done"),
            "cursor": result.get("cursor"),
            "remaining_estimate": result.get("remaining_estimate"),
            "truth": result.get("truth"),
        }

    def institutional_assurance_cached(self) -> dict[str, Any]:
        """Cheap status read — last cached assurance summary only."""
        cached = getattr(self, "_assurance_cache", None)
        if isinstance(cached, dict):
            return {
                **cached,
                "truth": {
                    **dict(cached.get("truth") or {}),
                    "status_does_not_run_assurance_scan": True,
                    "enqueue_market_sim_assurance_scan_to_refresh": True,
                },
            }
        return {
            "status": "UNMEASURED",
            "findings": [],
            "scannedFiles": 0,
            "truth": {
                "status_does_not_run_assurance_scan": True,
                "enqueue_market_sim_assurance_scan_to_refresh": True,
                "unexecuted_is_not_pass": True,
            },
        }

    def institutional_assurance(self) -> dict[str, Any]:
        """Direct assurance helper — production API must enqueue ``market_sim.assurance.scan``."""
        from .institutional_core.assurance import run_assurance

        report = run_assurance().public_dict()
        self._assurance_cache = report
        return report

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
        lineage_metadata: dict[str, Any] | None = None,
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
        meta = attach_lineage_metadata(
            parent_version=current.version,
            parent_content_hash=current.content_hash,
            changelog=changelog or f"v{new_version_num}",
        )
        if lineage_metadata:
            meta.update(dict(lineage_metadata))
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
            metadata=meta,
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
        sealed_attempt_id: str | None = None,
        objective_hash: str | None = None,
        require_split_binding: bool | None = None,
    ) -> dict[str, Any]:
        """Create a TradingGym episode (SimRun with gym metadata).

        mode=interactive → caller may gym_reset/gym_step in control plane.
        mode=complete → must be started via start_gym_episode (worker-owned).

        VAL/SEALED (and any caller that sets require_split_binding) MUST supply
        dataset_id/dataset_version so start/end come from the frozen manifest.
        SEALED always goes through SealedAttemptBinder — no bypass path.
        """
        self._require_enabled()
        from .gym import TradingGym, resolve_split_window
        from .sealed_attempts import SealedAttemptBinder, SealedAttemptStatus
        from .split_manifest import (
            ResearchEpisodeBinding,
            SplitRole,
            resolve_research_episode_binding,
        )

        role = str(split_role or SplitRole.TRAIN).upper()
        meta_in = dict(metadata or {})
        ds_id = dataset_id or meta_in.get("dataset_id")
        ds_ver = dataset_version or meta_in.get("dataset_version")
        # Resolve dataset lineage from source when learning/gym omit explicit ids.
        if (not ds_id or not ds_ver) and source_id:
            try:
                source = self.data.get_source(source_id)
                smeta = dict(source.metadata or {})
                ds_id = ds_id or smeta.get("dataset_id")
                ds_ver = ds_ver or smeta.get("dataset_version")
            except MarketSimError:
                pass

        must_bind = bool(
            require_split_binding
            if require_split_binding is not None
            else role in {SplitRole.VAL, "VALIDATION", SplitRole.SEALED}
            or meta_in.get("learning_run_id")
        )
        start_ts = end_ts = None
        manifest = None
        binding: ResearchEpisodeBinding | None = None
        if must_bind or (ds_id and ds_ver):
            if not ds_id or not ds_ver:
                raise MarketSimError(
                    "SPLIT_BINDING_REQUIRED",
                    f"{role} episodes require dataset_id + dataset_version bound to a split manifest",
                    http_status=400,
                )
            manifest = self.store.get_split_manifest(
                dataset_id=str(ds_id), dataset_version=str(ds_ver)
            )
            if manifest is None:
                raise MarketSimError(
                    "SPLIT_MANIFEST_NOT_FOUND",
                    f"no split manifest for {ds_id}@{ds_ver}",
                    http_status=404,
                )
            binding = resolve_research_episode_binding(
                manifest,
                split_role=role,
                strategy_id=str(strategy_id or ""),
                strategy_version=int(strategy_version or 0),
                objective_hash=str(objective_hash or meta_in.get("objective_hash") or ""),
                run_fingerprint=str(meta_in.get("run_fingerprint") or meta_in.get("input_fingerprint") or ""),
                source_id=source_id,
                require_frozen=(role == SplitRole.SEALED),
            )
            start_ts, end_ts = binding.start_ts, binding.end_ts
        elif ds_id and ds_ver:
            # legacy path kept only when must_bind is false and ids present
            manifest = self.store.get_split_manifest(
                dataset_id=str(ds_id), dataset_version=str(ds_ver)
            )
            start_ts, end_ts = resolve_split_window(manifest, role)

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
                **meta_in,
                "gym": True,
                "gym_mode": str(mode or "interactive"),
                "split_role": role,
                "dataset_id": ds_id,
                "dataset_version": ds_ver,
                "split_manifest_id": (
                    binding.split_manifest_id
                    if binding
                    else ((manifest or {}).get("manifest_id") if manifest else None)
                ),
                "split_binding": binding.public_dict() if binding else None,
                "engine": "gym",
            },
        )
        run_id = created["run_id"]

        sealed_attempt_payload = None
        if role == SplitRole.SEALED:
            if binding is None:
                raise MarketSimError(
                    "SPLIT_BINDING_REQUIRED",
                    "SEALED gym episode requires frozen DatasetSplitManifest binding",
                    http_status=409,
                )
            if not strategy_id:
                raise MarketSimError(
                    "SEALED_STRATEGY_REQUIRED",
                    "SEALED episodes require strategy_id + strategy_version",
                    http_status=400,
                )
            binder = SealedAttemptBinder(self.store)
            # Resume path: if an active attempt already exists for this strategy
            # version, refuse a new run and force resume of the bound run_id.
            existing = self.store.find_sealed_attempt(
                dataset_id=binding.dataset_id,
                dataset_version=binding.dataset_version,
                strategy_id=str(strategy_id),
                strategy_version=int(strategy_version or 0),
            )
            if existing and str(existing.get("status")) != SealedAttemptStatus.COMPLETED:
                resume_run = str(existing.get("run_id") or "")
                if resume_run and resume_run != run_id:
                    # Soft-delete the freshly created run; caller/worker must resume.
                    try:
                        run_obj = self._get_run(run_id)
                        run_obj.status = "CANCELLED"
                        run_obj.metadata = {
                            **dict(run_obj.metadata or {}),
                            "superseded_by_sealed_resume": True,
                            "resume_run_id": resume_run,
                            "sealed_attempt_id": existing.get("sealed_attempt_id"),
                        }
                        self.store.update_run(run_obj)
                    except Exception:  # noqa: BLE001
                        pass
                    raise MarketSimError(
                        "SEALED_ATTEMPT_BOUND_TO_OTHER_RUN",
                        f"attempt {existing.get('sealed_attempt_id')} bound to run {resume_run}, "
                        f"refusing new run {run_id}; resume the original run_id "
                        f"(resume_run_id={resume_run})",
                        http_status=409,
                    )
            attempt = binder.bind_or_resume(
                dataset_id=binding.dataset_id,
                dataset_version=binding.dataset_version,
                split_manifest_id=binding.split_manifest_id,
                strategy_id=str(strategy_id),
                strategy_version=int(strategy_version or 0),
                run_id=run_id,
                sealed_attempt_id=sealed_attempt_id or meta_in.get("sealed_attempt_id"),
                objective_hash=str(objective_hash or meta_in.get("objective_hash") or ""),
                metadata={
                    "source_id": source_id,
                    "learning_run_id": meta_in.get("learning_run_id"),
                    "candidate_id": meta_in.get("candidate_id"),
                    "objective_hash": str(objective_hash or meta_in.get("objective_hash") or ""),
                    "split_manifest_hash": binding.split_manifest_hash,
                },
            )
            binder.mark_running(attempt.sealed_attempt_id)
            sealed_attempt_payload = attempt.public_dict()
            run_obj = self._get_run(run_id)
            sm = dict(run_obj.metadata or {})
            sm["sealed_attempt_id"] = attempt.sealed_attempt_id
            sm["sealed_attempt"] = sealed_attempt_payload
            run_obj.metadata = sm
            self.store.update_run(run_obj)
            created = run_obj.public_dict()

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
                "split_binding": binding.public_dict() if binding else None,
                "sealed_attempt": sealed_attempt_payload,
                "truth": {
                    "via_trading_gym": True,
                    "worker_owned_complete_episode": False,
                    "split_binding_enforced": binding is not None,
                    "sealed_binder_enforced": role == SplitRole.SEALED,
                },
            }
        return {
            "episode": created,
            "observation": None,
            "mode": "complete",
            "split_binding": binding.public_dict() if binding else None,
            "sealed_attempt": sealed_attempt_payload,
            "truth": {
                "via_trading_gym": True,
                "worker_owned_complete_episode": True,
                "start_required": True,
                "split_binding_enforced": binding is not None,
                "sealed_binder_enforced": role == SplitRole.SEALED,
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
        from .policy import resolve_gym_policy, strategy_requires_policy
        from .sealed_attempts import SealedAttemptBinder, SealedAttemptStatus
        from .split_manifest import SplitRole, resolve_research_episode_binding

        run = self._get_run(run_id)
        meta = dict(run.metadata or {})
        if not meta.get("gym"):
            raise MarketSimError("NOT_A_GYM_EPISODE", run_id, http_status=400)

        role = str(meta.get("split_role") or "TRAIN").upper()
        sealed_attempt_id = meta.get("sealed_attempt_id")
        # Worker re-verifies split binding — caller cannot expand window via metadata.
        ds_id = meta.get("dataset_id")
        ds_ver = meta.get("dataset_version")
        if role in {SplitRole.VAL, "VALIDATION", SplitRole.SEALED} or meta.get("learning_run_id"):
            if not ds_id or not ds_ver:
                raise MarketSimError(
                    "SPLIT_BINDING_REQUIRED",
                    f"worker refused {role} episode without dataset split binding",
                    http_status=409,
                )
            manifest = self.store.get_split_manifest(
                dataset_id=str(ds_id), dataset_version=str(ds_ver)
            )
            if manifest is None:
                raise MarketSimError(
                    "SPLIT_MANIFEST_NOT_FOUND",
                    f"no split manifest for {ds_id}@{ds_ver}",
                    http_status=404,
                )
            binding = resolve_research_episode_binding(
                manifest,
                split_role=role,
                strategy_id=str(run.strategy_id or ""),
                strategy_version=int(run.strategy_version or 0),
                objective_hash=str(meta.get("objective_hash") or ""),
                source_id=run.source_id,
                require_frozen=(role == SplitRole.SEALED),
            )
            # Enforce exact manifest bounds (no expansion).
            if run.start_ts and str(run.start_ts) < binding.start_ts:
                raise MarketSimError(
                    "SPLIT_WINDOW_EXPANSION_FORBIDDEN",
                    "run start_ts precedes manifest TRAIN/VAL/SEALED window",
                    http_status=409,
                )
            if run.end_ts and str(run.end_ts) > binding.end_ts:
                raise MarketSimError(
                    "SPLIT_WINDOW_EXPANSION_FORBIDDEN",
                    "run end_ts exceeds manifest window",
                    http_status=409,
                )
            run.start_ts = binding.start_ts
            run.end_ts = binding.end_ts
            meta["split_binding"] = binding.public_dict()
            run.metadata = meta
            self.store.update_run(run)

        if role == SplitRole.SEALED:
            if not sealed_attempt_id:
                raise MarketSimError(
                    "SEALED_ATTEMPT_REQUIRED",
                    "SEALED worker episode requires sealed_attempt_id from SealedAttemptBinder",
                    http_status=409,
                )
            binder = SealedAttemptBinder(self.store)
            attempt_raw = self.store.get_sealed_attempt(str(sealed_attempt_id))
            if attempt_raw is None:
                raise MarketSimError("SEALED_ATTEMPT_NOT_FOUND", str(sealed_attempt_id), http_status=404)
            if str(attempt_raw.get("status")) == SealedAttemptStatus.COMPLETED:
                raise MarketSimError("SEALED_ALREADY_CONSUMED", str(sealed_attempt_id), http_status=409)
            if str(attempt_raw.get("run_id")) != run_id:
                raise MarketSimError(
                    "SEALED_ATTEMPT_BOUND_TO_OTHER_RUN",
                    f"attempt {sealed_attempt_id} bound to {attempt_raw.get('run_id')}",
                    http_status=409,
                )
            binder.mark_running(str(sealed_attempt_id), checkpoint_bar_index=int(run.bar_index or 0))

        gym = TradingGym(self.store, self.engine)
        strat = self._resolve_strategy_payload(run)
        bars_path = self._resolve_bars_path(run)
        content_hash = ""
        if run.strategy_id:
            ver = self.store.get_strategy_version(run.strategy_id, run.strategy_version)
            if ver is not None:
                content_hash = str(ver.content_hash or "")
        requires = strategy_requires_policy(strat, strategy_id=run.strategy_id)
        try:
            policy = resolve_gym_policy(
                strat,
                strategy_id=run.strategy_id,
                strategy_version=run.strategy_version,
                content_hash=content_hash,
                allow_missing_as_hold=not requires,
            )
        except MarketSimError:
            raise
        except Exception as exc:  # noqa: BLE001 — fail closed, never silent HOLD
            if role == SplitRole.SEALED and sealed_attempt_id:
                SealedAttemptBinder(self.store).fail(str(sealed_attempt_id), reason=str(exc))
            raise MarketSimError(
                "POLICY_LOAD_FAILED",
                f"cannot load strategy policy for gym episode: {exc}",
                http_status=400,
            ) from exc
        max_steps = meta.get("max_episode_bars") or meta.get("max_steps")
        try:
            result = gym.run_episode(
                run,
                bars_path=bars_path,
                split_role=role,
                start_ts=run.start_ts or None,
                end_ts=run.end_ts or None,
                strategy_params=strat.get("parameters"),
                entry_rules=strat.get("entry_rules") or {"kind": "hold"},
                exit_rules=strat.get("exit_rules") or {"kind": "hold"},
                policy=policy,
                require_policy=requires,
                policy_id=getattr(policy, "policy_id", None),
                max_steps=int(max_steps) if max_steps is not None else None,
            )
        except Exception as exc:
            if role == SplitRole.SEALED and sealed_attempt_id:
                SealedAttemptBinder(self.store).fail(str(sealed_attempt_id), reason=str(exc))
            raise
        if role == SplitRole.SEALED and sealed_attempt_id:
            SealedAttemptBinder(self.store).complete(str(sealed_attempt_id))
        self.store.add_event(
            run_id,
            kind="gym_episode_finished",
            payload={
                "steps": result.get("steps"),
                "status": result.get("status"),
                "policy": result.get("policy"),
                "non_hold_actions": result.get("non_hold_actions"),
                "split_role": role,
                "sealed_attempt_id": sealed_attempt_id,
            },
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
        params = dict(ver.parameters or {})
        meta = dict(run.metadata or {})
        # Robustness may apply a local parameter override without mutating lineage.
        override = meta.get("robustness_parameters") or meta.get("parameter_override")
        if isinstance(override, dict) and override:
            params.update(dict(override))
        return {
            "parameters": params,
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

    def _hydrate_paper_broker_session(self, session: dict[str, Any]) -> None:
        """Restore broker wallet/orders after process restart (W18)."""
        broker_id = str(session.get("broker_id") or "local_paper")
        broker = self._paper_broker(broker_id)
        if not hasattr(broker, "restore_session"):
            return
        sid = str(session.get("session_id") or "")
        if not sid:
            return
        sessions = getattr(broker, "sessions", {})
        if sid in sessions:
            # Still re-seed order idempotency index from durable orders.
            broker.restore_session(
                sid,
                wallet_payload=None,
                orders=list(session.get("orders") or []),
            )
            return
        broker.restore_session(
            sid,
            wallet_payload=session.get("wallet") if isinstance(session.get("wallet"), dict) else None,
            orders=list(session.get("orders") or []),
        )

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

    def _fetch_paper_quote(
        self,
        *,
        provider_id: str,
        symbol: str,
    ) -> tuple[dict[str, Any] | None, str, float | None]:
        """Fetch a single quote. Production: provider_io only. No Control-Plane urllib."""
        from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
        from Data.modules.provider_io.facade import ProviderExecutionClient
        from Data.modules.provider_io.readiness import provider_io_workers_ready

        symbol_u = symbol.upper().replace("/", "").replace("-", "")
        if not self._runners_externalized():
            provider = self.providers.get(provider_id)
            st = provider.status()
            quote = provider.fetch_quote(symbol_u)
            feed = "live" if st.reachable else "disconnected"
            return quote, feed, st.latency_ms

        if self.job_runtime is None:
            raise MarketSimError(
                ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                "job_runtime not bound; refusing Control Plane quote fallback",
                http_status=503,
            )
        db_path = getattr(getattr(self.job_runtime, "store", None), "path", None)
        if not provider_io_workers_ready(db_path):
            raise MarketSimError(
                ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                "provider_io workers unavailable; refusing Control Plane quote fallback",
                http_status=503,
            )
        client = ProviderExecutionClient(self.job_runtime)
        try:
            exec_result = client.submit_and_wait(
                provider=provider_id,
                capability="market.fetch",
                payload={
                    "provider_id": provider_id,
                    "symbol": symbol_u,
                    "timeframe": "1m",
                    "limit": 1,
                    "markets_root": str(self.data.markets_root),
                    "mode": "quote_only",
                    "include_bars": False,
                },
                credential_ref="none",
                latency_class="interactive",
                requested_by="market_sim_paper_quote",
                deadline_seconds=30.0,
            )
        except ProviderError as exc:
            raise MarketSimError(
                exc.code.value,
                str(exc),
                http_status=503 if exc.retryable else 502,
            ) from exc
        if exec_result.status != "succeeded" or not isinstance(exec_result.structured, dict):
            err = (exec_result.error or {}).get("message") or "provider_io quote failed"
            code = (exec_result.error or {}).get("code") or "PROVIDER_UNAVAILABLE"
            raise MarketSimError(str(code), str(err), http_status=502)
        structured = dict(exec_result.structured)
        quote = structured.get("quote") if isinstance(structured.get("quote"), dict) else None
        if quote is None and structured.get("bars"):
            last = structured["bars"][-1]
            quote = {"price": last.get("close"), "last": last.get("close"), "ts": last.get("ts")}
        latency = structured.get("latency_ms")
        return quote, "live" if quote else "disconnected", float(latency) if latency is not None else None

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
            quote, feed_status, latency = self._fetch_paper_quote(
                provider_id=provider_id, symbol=symbol
            )
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
        # W18: durable session → in-memory broker wallet/order index after restart.
        self._hydrate_paper_broker_session(session)
        # Refresh quote via provider_io when externalized (never Control-Plane urllib).
        try:
            quote, feed_status, latency = self._fetch_paper_quote(
                provider_id=str(session.get("provider_id") or "binance_public"),
                symbol=str(session["symbol"]),
            )
            session["feed_status"] = feed_status
            session["metadata"] = dict(session.get("metadata") or {})
            session["metadata"]["last_quote"] = quote
            session["metadata"]["feed_latency_ms"] = latency
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

    def resume_paper_sessions_for_strategy(
        self,
        strategy_id: str,
        *,
        strategy_version: int | None = None,
    ) -> dict[str, Any]:
        """Reload durable paper sessions for a saved strategy after process restart (W18).

        Uses ``market_paper_sessions`` (not in-memory PaperDeployment). Returns
        hydrated session states; does not invent fills or live routing.
        """
        self._require_enabled()
        sid = str(strategy_id or "").strip()
        if not sid:
            raise MarketSimError("STRATEGY_ID_REQUIRED", "strategy_id required", http_status=400)
        matched: list[dict[str, Any]] = []
        for row in self.store.list_paper_sessions(limit=200):
            if str(row.get("strategy_id") or "") != sid:
                continue
            if strategy_version is not None and row.get("strategy_version") != strategy_version:
                continue
            if str(row.get("status") or "") not in {"active", "paused", "RUNNING", "PAUSED"}:
                # Still hydrate stopped sessions for inspection, but mark not resumed.
                hydrated = self.paper_session_state(row["session_id"])
                matched.append({**hydrated, "resumed": False, "reason": "status_not_active"})
                continue
            hydrated = self.paper_session_state(row["session_id"])
            matched.append({**hydrated, "resumed": True})
        return {
            "strategy_id": sid,
            "strategy_version": strategy_version,
            "sessions": matched,
            "count": len(matched),
            "truth": {
                "durable_path": "market_paper_sessions",
                "paper_deployment_table": "PERSISTED",
                "paper_deployment_table_name": "market_paper_deployments",
                "paper_only": True,
                "live_money": "BLOCKED",
            },
        }

    # --- A3 shadow / A4 autonomous paper deployment loop ---

    def create_and_persist_paper_deployment(
        self,
        *,
        strategy_id: str,
        strategy_version: int | None = None,
        universe: list[str] | None = None,
        feed_id: str = "binance_public",
        mode: str = "shadow",
        risk_config: dict[str, Any] | None = None,
        sizing_config: dict[str, Any] | None = None,
        cadence: str = "every_n_bars",
        qualification_refs: dict[str, Any] | None = None,
        symbol: str | None = None,
        broker_id: str = "local_paper",
        provider_id: str | None = None,
        initial_cash: float = 100_000.0,
    ) -> dict[str, Any]:
        """Materialize PaperDeployment + durable paper session + loop state.

        Shadow mode: session exists for observe-only receipts (no orders).
        Autonomous paper mode: session may place paper orders under RiskGuard.
        """
        self._require_enabled()
        from .autonomous_paper_loop import (
            AUTONOMOUS_PAPER_MODE,
            SHADOW_MODE,
            attach_deployment,
            deployment_row_from_object,
            materialize_paper_deployment,
            new_loop_state,
        )
        from .strategy_asset import from_strategy_record

        if mode not in {SHADOW_MODE, AUTONOMOUS_PAPER_MODE}:
            raise MarketSimError("INVALID_DEPLOYMENT_MODE", f"mode={mode}", http_status=400)
        ver = self.store.get_strategy_version(strategy_id, strategy_version)
        if ver is None:
            raise MarketSimError("STRATEGY_VERSION_MISSING", strategy_id, http_status=404)
        record = self.store.get_strategy(strategy_id)
        if record is None:
            raise MarketSimError("STRATEGY_MISSING", strategy_id, http_status=404)
        # Promote DRAFT-looking assets to RESEARCH for deployability when already versioned.
        asset = from_strategy_record(record, version=ver)
        if asset.status == StrategyStatus.DRAFT.value:
            asset.status = StrategyStatus.RESEARCH.value
        univ = list(universe or asset.universe_constraints or [])
        sym = (symbol or (univ[0] if univ else None) or "BTCUSDT").upper()
        if sym not in univ:
            univ = [sym, *univ]
        provider = provider_id or feed_id
        deployment = materialize_paper_deployment(
            asset=asset,
            universe=univ,
            feed_id=feed_id,
            risk_config=risk_config,
            sizing_config=sizing_config,
            cadence=cadence,
            mode=mode,
            qualification_refs=qualification_refs,
        )
        session = self.start_paper_session(
            symbol=sym,
            strategy_id=strategy_id,
            strategy_version=ver.version,
            broker_id=broker_id,
            provider_id=provider,
            initial_cash=initial_cash,
        )
        meta = dict(session.get("metadata") or {})
        meta["mode"] = mode
        meta["deployment_id"] = deployment.deployment_id
        meta["simulated_capital"] = True
        session["metadata"] = meta
        if mode == SHADOW_MODE:
            # Shadow has no capital authority — mark observe-only.
            session["status"] = "active"
            meta["shadow_observe_only"] = True
            meta["no_paper_order_authority"] = True
        self.store.upsert_paper_session(session)

        loop = new_loop_state(strategy_id=strategy_id, strategy_version=ver.version)
        attach_deployment(loop, deployment)
        if mode == SHADOW_MODE:
            loop.shadow_session_id = session["session_id"]
            loop.stage = "SHADOW"
        else:
            loop.paper_session_id = session["session_id"]
            loop.stage = "AUTONOMOUS_PAPER"
        deployment.metadata = {
            **deployment.metadata,
            "session_id": session["session_id"],
            "loop_id": loop.loop_id,
        }
        deployment.status = "RUNNING"
        row = deployment_row_from_object(deployment)
        row["session_id"] = session["session_id"]
        row["loop_state_json"] = loop.public_dict()
        row["mode"] = mode
        self.store.upsert_paper_deployment(row)
        self._emit_event(
            "paper.deployment.created",
            {
                "deployment_id": deployment.deployment_id,
                "mode": mode,
                "session_id": session["session_id"],
                "strategy_id": strategy_id,
            },
        )
        return {
            "deployment": deployment.public_dict(),
            "session": session,
            "loop": loop.public_dict(),
            "truth": {
                "persisted": True,
                "table": "market_paper_deployments",
                "simulated_capital": True,
                "live_money": "BLOCKED",
                "shadow_no_orders": mode == SHADOW_MODE,
            },
        }

    def shadow_observe_step(
        self,
        deployment_id: str,
        *,
        signal_side: str = "HOLD",
        proposed_qty: float | None = None,
        risk_decision: str = "HOLD",
    ) -> dict[str, Any]:
        """A3 observe-only step — persists shadow observation, never places orders."""
        self._require_enabled()
        from .autonomous_paper_loop import (
            SHADOW_MODE,
            loop_state_from_dict,
            record_shadow_observation,
        )

        row = self.store.get_paper_deployment(deployment_id)
        if row is None:
            raise MarketSimError("PAPER_DEPLOYMENT_NOT_FOUND", deployment_id, http_status=404)
        if str(row.get("mode") or "") != SHADOW_MODE:
            raise MarketSimError(
                "NOT_SHADOW_DEPLOYMENT",
                f"deployment mode={row.get('mode')}",
                http_status=409,
            )
        if row.get("kill_switch"):
            raise MarketSimError("KILL_SWITCH", "deployment kill switch armed", http_status=409)
        loop = loop_state_from_dict(row.get("loop_state_json") or {})
        if loop is None:
            raise MarketSimError("LOOP_STATE_MISSING", deployment_id, http_status=500)
        session_id = row.get("session_id") or loop.shadow_session_id
        if not session_id:
            raise MarketSimError("SHADOW_SESSION_MISSING", deployment_id, http_status=409)
        session = self.paper_session_state(session_id)
        quote = (session.get("metadata") or {}).get("last_quote") or {}
        price = quote.get("price")
        obs = record_shadow_observation(
            loop,
            symbol=session["symbol"],
            signal_side=signal_side,
            proposed_qty=proposed_qty,
            risk_decision=risk_decision,
            hypothetical_price=float(price) if price is not None else None,
            feed_status=str(session.get("feed_status") or "unknown"),
            market_snapshot_ref=f"quote:{session.get('updated_at')}",
            metadata={"deployment_id": deployment_id, "no_order": True},
        )
        loop.shadow_session_id = session_id
        row["loop_state_json"] = loop.public_dict()
        row["updated_at"] = utc_now()
        meta = dict(row.get("metadata_json") or {})
        meta["last_shadow_observation"] = obs.public_dict()
        row["metadata_json"] = meta
        self.store.upsert_paper_deployment(row)
        return {
            "observation": obs.public_dict(),
            "loop": loop.public_dict(),
            "deployment_id": deployment_id,
            "truth": {"no_paper_order": True, "live_money": "BLOCKED"},
        }

    def promote_deployment_autonomy(
        self,
        deployment_id: str,
        *,
        target_level: str,
        sealed_attempt_id: str | None = None,
        min_shadow_observations: int = 5,
        min_paper_steps: int = 5,
        acceptance_criteria: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Promote A2→A3 or A3→A4 using resolved receipts only."""
        self._require_enabled()
        from .autonomous_paper_loop import evaluate_loop_promotion, loop_state_from_dict

        row = self.store.get_paper_deployment(deployment_id)
        if row is None:
            raise MarketSimError("PAPER_DEPLOYMENT_NOT_FOUND", deployment_id, http_status=404)
        loop = loop_state_from_dict(row.get("loop_state_json") or {})
        if loop is None:
            raise MarketSimError("LOOP_STATE_MISSING", deployment_id, http_status=500)
        result = evaluate_loop_promotion(
            loop,
            target_level=target_level,
            acceptance_criteria=acceptance_criteria,
            sealed_attempt_id=sealed_attempt_id,
            min_shadow_observations=min_shadow_observations,
            min_paper_steps=min_paper_steps,
        )
        row["loop_state_json"] = loop.public_dict()
        row["updated_at"] = utc_now()
        if result.get("promotable") and str(target_level).upper() == "A4":
            # Ensure an autonomous paper session exists (may promote shadow→paper capital).
            if not loop.paper_session_id:
                paper = self.create_and_persist_paper_deployment(
                    strategy_id=loop.strategy_id,
                    strategy_version=loop.strategy_version,
                    universe=list(row.get("universe_json") or []),
                    feed_id=str(row.get("feed_id") or "binance_public"),
                    mode="autonomous_paper",
                    qualification_refs={
                        "from_shadow_deployment_id": deployment_id,
                        "shadow_run_id": loop.shadow_session_id,
                    },
                    symbol=(row.get("universe_json") or [None])[0],
                )
                loop.paper_session_id = paper["session"]["session_id"]
                loop.deployment_id = paper["deployment"]["deployment_id"]
                row["loop_state_json"] = loop.public_dict()
                result["autonomous_paper_deployment"] = paper
        self.store.upsert_paper_deployment(row)
        return result

    def request_autonomous_step(
        self,
        deployment_id: str,
        *,
        side: str = "HOLD",
        qty: float | None = None,
        requested_by: str = "api",
    ) -> dict[str, Any]:
        """Enqueue one durable autonomous paper step (or run inline only when not externalized)."""
        self._require_enabled()
        if self._runners_externalized():
            if self.job_runtime is None:
                raise MarketSimError(
                    "TRADING_WORKER_UNAVAILABLE",
                    "job_runtime not bound; refusing inline autonomous paper step",
                    http_status=503,
                )
            # Occurrence identity: at most one active step per deployment+generation window.
            occurrence = f"{deployment_id}:{utc_now()[:16]}"
            job = self.job_runtime.enqueue(
                capability_id="market_sim.autonomous_step",
                arguments={
                    "deployment_id": deployment_id,
                    "side": side,
                    "qty": qty,
                },
                requested_by=requested_by,
                idempotency_key=f"market_sim:autonomous_step:{occurrence}",
                domain="market_sim",
                domain_entity_type="paper_deployment",
                domain_entity_id=deployment_id,
                worker_pool="market_sim",
                latency_class="interactive",
                resource_class="CPU_HEAVY",
            )
            return {
                "queued": True,
                "job_id": job.job_id,
                "deployment_id": deployment_id,
                "capability_id": "market_sim.autonomous_step",
                "truth": {"simulated_capital": True, "live_money": "BLOCKED"},
            }
        return self.autonomous_paper_step(deployment_id, side=side, qty=qty)

    def request_paper_forward_step(
        self,
        session_id: str,
        *,
        side: str = "HOLD",
        qty: float | None = None,
        requested_by: str = "api",
    ) -> dict[str, Any]:
        self._require_enabled()
        if self._runners_externalized():
            if self.job_runtime is None:
                raise MarketSimError(
                    "TRADING_WORKER_UNAVAILABLE",
                    "job_runtime not bound; refusing inline paper-forward step",
                    http_status=503,
                )
            occurrence = f"{session_id}:{utc_now()[:16]}"
            job = self.job_runtime.enqueue(
                capability_id="market_sim.paper_forward_step",
                arguments={"session_id": session_id, "side": side, "qty": qty},
                requested_by=requested_by,
                idempotency_key=f"market_sim:paper_forward:{occurrence}",
                domain="market_sim",
                domain_entity_type="paper_session",
                domain_entity_id=session_id,
                worker_pool="market_sim",
                latency_class="background",
                resource_class="CPU_HEAVY",
            )
            return {
                "queued": True,
                "job_id": job.job_id,
                "session_id": session_id,
                "capability_id": "market_sim.paper_forward_step",
            }
        return self.paper_forward_step(session_id, side=side, qty=qty)

    def request_chart_render_batch(
        self,
        specs: list[dict[str, Any]],
        *,
        batch_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        requested_by: str = "api",
    ) -> dict[str, Any]:
        """Enqueue a bounded chart render batch on market_sim (no ChartWorker)."""
        self._require_enabled()
        from .chart_batch import clamp_batch_limit

        batch_id = batch_id or str(uuid.uuid4())
        slice_limit = clamp_batch_limit(limit)
        if self._runners_externalized():
            if self.job_runtime is None:
                raise MarketSimError(
                    "TRADING_WORKER_UNAVAILABLE",
                    "job_runtime not bound; refusing inline chart batch",
                    http_status=503,
                )
            job = self.job_runtime.enqueue(
                capability_id="market_sim.chart.render_batch",
                arguments={
                    "batch_id": batch_id,
                    "specs": specs,
                    "offset": offset,
                    "limit": slice_limit,
                },
                requested_by=requested_by,
                idempotency_key=f"market_sim:chart_batch:{batch_id}:{offset}",
                domain="market_sim",
                domain_entity_type="chart_batch",
                domain_entity_id=batch_id,
                worker_pool="market_sim",
                latency_class="batch",
                resource_class="CPU_HEAVY",
            )
            return {
                "queued": True,
                "job_id": job.job_id,
                "batch_id": batch_id,
                "offset": offset,
                "limit": slice_limit,
                "total": len(specs),
            }
        from .chart_batch import render_chart_batch_slice

        return render_chart_batch_slice(
            specs, batch_id=batch_id, offset=offset, limit=slice_limit
        )

    def autonomous_paper_step(
        self,
        deployment_id: str,
        *,
        side: str = "HOLD",
        qty: float | None = None,
    ) -> dict[str, Any]:
        """A4 paper forward step with RiskGuard — records receipt on deployment loop.

        Canonical one-step mechanism. Production callers should use
        ``request_autonomous_step`` so the market_sim worker owns execution.
        """
        self._require_enabled()
        from .autonomous_paper_loop import (
            AUTONOMOUS_PAPER_MODE,
            assert_deployment_ready_for_orders,
            loop_state_from_dict,
        )
        from .paper_deployment import PaperDeployment, FeedHealth
        from .strategy_asset import ExecutionCompatibilityManifest

        row = self.store.get_paper_deployment(deployment_id)
        if row is None:
            raise MarketSimError("PAPER_DEPLOYMENT_NOT_FOUND", deployment_id, http_status=404)
        if str(row.get("mode") or "") not in {AUTONOMOUS_PAPER_MODE, "autonomous_paper"}:
            raise MarketSimError(
                "NOT_AUTONOMOUS_PAPER_DEPLOYMENT",
                f"mode={row.get('mode')}",
                http_status=409,
            )
        # Reconstruct minimal deployment for kill/feed checks
        fh_raw = row.get("feed_health_json")
        feed_health = None
        if isinstance(fh_raw, dict) and fh_raw.get("feed_id"):
            feed_health = FeedHealth(
                feed_id=str(fh_raw.get("feed_id") or row.get("feed_id") or ""),
                status=str(fh_raw.get("status") or "UNMEASURED"),
                last_tick_ts=fh_raw.get("last_tick_ts"),
                as_of=fh_raw.get("as_of"),
                staleness_seconds=fh_raw.get("staleness_seconds"),
                gap_count=int(fh_raw.get("gap_count") or 0),
                reconnect_count=int(fh_raw.get("reconnect_count") or 0),
                provenance=str(fh_raw.get("provenance") or ""),
            )
        deployment = PaperDeployment(
            deployment_id=row["deployment_id"],
            strategy_asset_id=row["strategy_asset_id"],
            strategy_version=int(row["strategy_version"]),
            compatibility=ExecutionCompatibilityManifest(),
            universe=list(row.get("universe_json") or []),
            feed_id=str(row.get("feed_id") or ""),
            risk_config=dict(row.get("risk_config_json") or {}),
            sizing_config=dict(row.get("sizing_config_json") or {}),
            cadence=str(row.get("cadence") or "every_n_bars"),
            env_fingerprint=str(row.get("env_fingerprint") or ""),
            status=str(row.get("status") or "RUNNING"),
            kill_switch=bool(row.get("kill_switch")),
            feed_health=feed_health,
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            metadata=dict(row.get("metadata_json") or {}),
        )
        assert_deployment_ready_for_orders(deployment)
        loop = loop_state_from_dict(row.get("loop_state_json") or {})
        if loop is None or not loop.paper_session_id:
            raise MarketSimError("PAPER_SESSION_MISSING", deployment_id, http_status=409)
        # Deterministic decision identity for this tick.
        decision_generation = int((row.get("metadata_json") or {}).get("decision_generation") or 0) + 1
        decision_id = f"{deployment_id}:{decision_generation}:{side}"
        stepped = self.paper_forward_step(loop.paper_session_id, side=side, qty=qty)
        receipt = {
            "step_id": decision_id,
            "decision_id": decision_id,
            "decision_generation": decision_generation,
            "checkpoint_step": (stepped.get("forward") or {}).get("checkpoint_step"),
            "allowed": (stepped.get("result") or {}).get("allowed"),
            "blocked": bool((stepped.get("result") or {}).get("blocked")),
            "side": side,
            "order": (stepped.get("result") or {}).get("order"),
            "filled": bool((stepped.get("result") or {}).get("order")),
            "at": utc_now(),
        }
        loop.paper_step_receipts.append(receipt)
        loop.stage = "AUTONOMOUS_PAPER"
        loop.updated_at = utc_now()
        meta = dict(row.get("metadata_json") or {})
        meta["decision_generation"] = decision_generation
        meta["last_decision_id"] = decision_id
        meta["next_tick_at"] = utc_now()
        row["loop_state_json"] = loop.public_dict()
        row["metadata_json"] = meta
        row["updated_at"] = utc_now()
        self.store.upsert_paper_deployment(row)
        return {
            "step": stepped,
            "receipt": receipt,
            "loop": loop.public_dict(),
            "truth": {"simulated_capital": True, "live_money": "BLOCKED"},
            "executed_via": "inline" if not self._runners_externalized() else "direct_worker",
        }

    def review_deployment_drift(
        self,
        deployment_id: str,
        *,
        baseline_metrics: dict[str, float],
        observed_metrics: dict[str, float],
        relative_threshold: float = 0.25,
        spawn_challenger: bool = True,
        spawn_research_lab: bool = True,
    ) -> dict[str, Any]:
        """Compare research expectation vs paper-forward; persist PAPER_OBSERVED lesson.

        When a drift ticket opens, optionally spawn an AUTONOMOUS_DISCOVERY lab linked to
        the original strategy + ticket. Does NOT auto-promote. Live remains BLOCKED.
        """
        self._require_enabled()
        from .autonomous_paper_loop import (
            loop_state_from_dict,
            review_loop_drift,
            spawn_challenger_from_drift,
        )

        row = self.store.get_paper_deployment(deployment_id)
        if row is None:
            raise MarketSimError("PAPER_DEPLOYMENT_NOT_FOUND", deployment_id, http_status=404)
        loop = loop_state_from_dict(row.get("loop_state_json") or {})
        if loop is None:
            raise MarketSimError("LOOP_STATE_MISSING", deployment_id, http_status=500)

        def _memory_writer(mem: Any) -> Any:
            return self.store.save_strategy_memory(mem)

        research_lab: dict[str, Any] | None = None

        def _research_requester(question: str) -> Any:
            nonlocal research_lab
            if not spawn_research_lab:
                return None
            meta = dict(row.get("metadata_json") or row.get("metadata") or {})
            payload = dict(row.get("payload_json") or row.get("payload") or {})
            source_id = (
                meta.get("source_id")
                or payload.get("source_id")
                or (loop.metadata or {}).get("source_id")
                if hasattr(loop, "metadata")
                else None
            )
            if not source_id:
                # Best-effort: prefer a READY market data source
                try:
                    ready = self.data.list_sources(status="READY", limit=1)
                    if ready:
                        source_id = ready[0].source_id if hasattr(ready[0], "source_id") else ready[0].get("source_id")
                except Exception:  # noqa: BLE001
                    source_id = None
            if not source_id:
                return {"error": "SOURCE_ID_MISSING_FOR_RESEARCH", "question": question}
            try:
                lab = self.create_agent_lab(
                    name=f"drift-research-{deployment_id[:8]}",
                    strategy_id=None,
                    source_id=str(source_id),
                    run_mode="AUTONOMOUS_DISCOVERY",
                    research_objective=str(question),
                    hypothesis=str(question),
                    metadata={
                        "origin": "continual_research_drift",
                        "deployment_id": deployment_id,
                        "original_strategy_id": loop.strategy_id,
                        "original_strategy_version": loop.strategy_version,
                        "does_not_auto_promote": True,
                        "live_trading": "BLOCKED",
                    },
                    enable_learning=True,
                )
                research_lab = lab
                return {
                    "lab_id": lab.get("lab_id"),
                    "hypothesis_id": lab.get("hypothesis_id")
                    or (lab.get("metadata") or {}).get("hypothesis_id"),
                    "run_mode": "AUTONOMOUS_DISCOVERY",
                    "linked_strategy_id": loop.strategy_id,
                    "does_not_auto_promote": True,
                    "live_trading": "BLOCKED",
                }
            except MarketSimError as exc:
                return {"error": exc.code, "detail": str(exc), "question": question}

        drift = review_loop_drift(
            loop,
            baseline_metrics=baseline_metrics,
            observed_metrics=observed_metrics,
            strategy_memory_writer=_memory_writer,
            research_requester=_research_requester if spawn_research_lab else None,
            relative_threshold=relative_threshold,
        )
        # Attach ticket id onto lab metadata when research was spawned
        if research_lab and isinstance(drift.get("persisted"), dict):
            req = (drift.get("persisted") or {}).get("researchRequest")
            ticket = drift.get("continualResearch") or {}
            if isinstance(req, dict) and req.get("lab_id") and ticket.get("ticketId"):
                try:
                    lab_row = self.store.get_agent_lab(str(req["lab_id"]))
                    if lab_row:
                        lab_row["metadata"] = {
                            **dict(lab_row.get("metadata") or {}),
                            "drift_ticket_id": ticket.get("ticketId"),
                            "original_strategy_id": loop.strategy_id,
                        }
                        self.store.upsert_agent_lab(lab_row)
                except Exception:  # noqa: BLE001
                    pass
        challenger = None
        if spawn_challenger and drift.get("status") == "DRIFT_DETECTED":
            challenger = spawn_challenger_from_drift(loop)
        row["loop_state_json"] = loop.public_dict()
        row["updated_at"] = utc_now()
        self.store.upsert_paper_deployment(row)
        return {
            "drift": drift,
            "challenger": challenger,
            "research_lab": research_lab,
            "loop": loop.public_dict(),
            "truth": {
                "does_not_auto_promote": True,
                "does_not_auto_disable_unless_policy": True,
                "live_money": "BLOCKED",
            },
        }

    def get_paper_deployment(self, deployment_id: str) -> dict[str, Any]:
        self._require_enabled()
        from .autonomous_paper_loop import deployment_from_row

        row = self.store.get_paper_deployment(deployment_id)
        if row is None:
            raise MarketSimError("PAPER_DEPLOYMENT_NOT_FOUND", deployment_id, http_status=404)
        public = deployment_from_row(row)
        public["loop"] = row.get("loop_state_json") or {}
        public["session_id"] = row.get("session_id")
        public["mode"] = row.get("mode")
        return public

    def list_paper_deployments(
        self,
        *,
        strategy_id: str | None = None,
        mode: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self._require_enabled()
        from .autonomous_paper_loop import deployment_from_row

        rows = self.store.list_paper_deployments(
            strategy_asset_id=strategy_id, mode=mode, limit=limit
        )
        out = []
        for row in rows:
            public = deployment_from_row(row)
            public["loop"] = row.get("loop_state_json") or {}
            public["session_id"] = row.get("session_id")
            public["mode"] = row.get("mode")
            out.append(public)
        return out

    def paper_deployment_kill_switch(
        self, deployment_id: str, *, armed: bool = True, reason: str = ""
    ) -> dict[str, Any]:
        self._require_enabled()
        row = self.store.get_paper_deployment(deployment_id)
        if row is None:
            raise MarketSimError("PAPER_DEPLOYMENT_NOT_FOUND", deployment_id, http_status=404)
        row["kill_switch"] = bool(armed)
        row["status"] = "KILLED" if armed else ("PAUSED" if row.get("status") == "KILLED" else row.get("status"))
        meta = dict(row.get("metadata_json") or {})
        meta["kill_reason"] = reason or ("armed" if armed else "disarmed")
        row["metadata_json"] = meta
        row["updated_at"] = utc_now()
        self.store.upsert_paper_deployment(row)
        # Mirror onto bound session
        if row.get("session_id"):
            try:
                self.paper_kill_switch(row["session_id"], armed=armed)
            except MarketSimError:
                pass
        return self.get_paper_deployment(deployment_id)

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

    def portfolio_flatten_all(self, portfolio_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self.portfolios.flatten_all(portfolio_id)

    def fetch_market_bars(
        self,
        *,
        provider_id: str,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 200,
    ) -> dict[str, Any]:
        """Read-path OHLCV for Paper Trading charts — never invents candles."""
        self._require_enabled()
        from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
        from Data.modules.provider_io.facade import ProviderExecutionClient
        from Data.modules.provider_io.readiness import provider_io_workers_ready

        symbol_u = symbol.upper().replace("/", "").replace("-", "")
        want = max(10, min(int(limit), 1000))
        bars: list[dict[str, Any]] = []
        quote: dict[str, Any] | None = None
        executed_via = "control_plane_legacy_inline"
        license_note = ""
        license_state = "PUBLIC_TERMS_APPLY"
        detail = ""

        if not self._runners_externalized():
            provider = self.providers.get(provider_id)
            license_note = getattr(provider, "license_note", "") or ""
            license_state = getattr(provider, "license_state", "PUBLIC_TERMS_APPLY")
            try:
                raw_bars = provider.fetch_historical(symbol_u, timeframe, limit=want)
                bars = [b.public_dict() for b in raw_bars]
                detail = f"{len(bars)} bars via {provider_id}"
            except MarketSimError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise MarketSimError("PROVIDER_UNAVAILABLE", str(exc), http_status=502) from exc
            try:
                quote = provider.fetch_quote(symbol_u)
            except Exception:  # noqa: BLE001
                quote = None
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
                        "symbol": symbol_u,
                        "timeframe": timeframe,
                        "limit": want,
                        "markets_root": str(self.data.markets_root),
                        "mode": "bars_only",
                        "include_bars": True,
                    },
                    credential_ref="none",
                    latency_class="interactive",
                    requested_by="market_sim_paper_chart",
                    deadline_seconds=60.0,
                )
            except ProviderError as exc:
                raise MarketSimError(
                    exc.code.value,
                    str(exc),
                    http_status=503 if exc.retryable else 502,
                ) from exc
            if exec_result.status != "succeeded" or not isinstance(exec_result.structured, dict):
                err = (exec_result.error or {}).get("message") or "provider_io market bars failed"
                code = (exec_result.error or {}).get("code") or "PROVIDER_UNAVAILABLE"
                raise MarketSimError(str(code), str(err), http_status=502)
            structured = dict(exec_result.structured)
            bars = list(structured.get("bars") or [])
            quote = structured.get("quote") if isinstance(structured.get("quote"), dict) else None
            license_note = str(structured.get("license_note") or "")
            license_state = str(structured.get("license_state") or "PUBLIC_TERMS_APPLY")
            executed_via = "provider_io"
            detail = f"{len(bars)} bars via provider_io/{provider_id}"

        last = bars[-1] if bars else None
        return {
            "symbol": symbol_u,
            "provider_id": provider_id,
            "timeframe": timeframe,
            "bars": bars,
            "count": len(bars),
            "quote": quote,
            "ohlc": (
                {
                    "open": last.get("open"),
                    "high": last.get("high"),
                    "low": last.get("low"),
                    "close": last.get("close"),
                    "volume": last.get("volume"),
                    "ts": last.get("ts"),
                }
                if last
                else None
            ),
            "license_note": license_note,
            "license_state": license_state,
            "executed_via": executed_via,
            "detail": detail,
            "truth": {
                "ohlcv_is_not_orderbook": True,
                "not_fabricated": True,
                "source": provider_id,
            },
        }

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
            from Data.modules.provider_io.market_feed_readiness import market_feed_workers_ready

            if not market_feed_workers_ready(db_path):
                session.set_status(
                    FeedConnectionState.FAILED,
                    error="market_feed workers unavailable",
                )
                raise MarketSimError(
                    ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                    "market_feed workers unavailable; refusing Control Plane WS fallback",
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
        """Registry-backed readiness — never treat catalog presence as READY."""
        from Data.modules.provider_io.market_feed_readiness import market_feed_workers_ready

        return market_feed_workers_ready(db_path)

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
        from .experiments import build_strategy_memory_record

        learned_at = utc_now()
        # Basic experiment acceptance is VALIDATION evidence — not SEALED.
        # Rejected validation lessons remain retrievable for critic/postmortem
        # (prefer_negative); they must never be tagged as sealed holdout.
        self.store.save_strategy_memory(
            build_strategy_memory_record(
                strategy_id=trial["strategy_id"],
                strategy_version=strategy_version or 0,
                features=(metrics.get("features") or {}),
                applicability=(trial.get("config") or {}).get("applicability") or {},
                outcome_summary=reason if not passed else "accepted on validation",
                trial_id=trial_id,
                available_at=learned_at,
                created_at=learned_at,
                rejected=not passed,
                origin="complete_experiment",
                epistemic_state="REJECTED" if not passed else "MEASURED",
                validation_stage="validation",
                extra_metadata={
                    "acceptance_reason": reason,
                    "evidence_class": "VALIDATION_EVIDENCE",
                },
            )
        )
        return trial

    def list_experiments(self, *, strategy_id: str | None = None) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_experiments(strategy_id=strategy_id)

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Load a research experiment/trial by id (trial_id)."""
        self._require_enabled()
        if hasattr(self.store, "get_experiment"):
            row = self.store.get_experiment(experiment_id)
            if row is not None:
                return row
        for trial in self.store.list_experiments(limit=5000):
            if str(trial.get("trial_id") or "") == str(experiment_id):
                return trial
        raise MarketSimError("EXPERIMENT_NOT_FOUND", experiment_id, http_status=404)

    def reproduce_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Reconstruct immutable inputs and re-run deterministically when provenance allows.

        Partial path: load original run + metadata hashes, re-execute via create_run+start,
        compare metrics/equity with explicit float tolerances. Never silently claims match
        when provenance is incomplete (blockers include REPRODUCIBILITY_INCOMPLETE).
        """
        self._require_enabled()
        trial = self.get_experiment(experiment_id)
        meta = dict(trial.get("metadata") or {})
        config = dict(trial.get("config") or {})
        results = dict(trial.get("results") or {})
        cost = dict(config.get("cost_model") or trial.get("cost_model") or {})

        tolerances = {
            "metric_abs": 1e-9,
            "equity_abs": 1e-6,
            "fill_price_abs": 1e-9,
            "fill_qty_abs": 1e-12,
        }

        original_run_id = (
            meta.get("run_id")
            or meta.get("original_run_id")
            or results.get("run_id")
            or config.get("run_id")
        )
        original_run: dict[str, Any] | None = None
        if original_run_id:
            try:
                original_run = self.get_run(str(original_run_id))
            except MarketSimError:
                original_run = None

        orig_meta = dict((original_run or {}).get("metadata") or {})
        source_id = (
            meta.get("source_id")
            or config.get("source_id")
            or (original_run or {}).get("source_id")
        )
        strategy_id = trial.get("strategy_id") or (original_run or {}).get("strategy_id")
        strategy_version = trial.get("strategy_version")
        if strategy_version is None and original_run is not None:
            strategy_version = original_run.get("strategy_version")
        seed = int(
            trial.get("seed")
            if trial.get("seed") is not None
            else (original_run or {}).get("seed")
            if original_run is not None
            else 42
        )
        data_hash = (
            trial.get("data_hash")
            or (original_run or {}).get("data_hash")
            or orig_meta.get("data_hash")
        )
        strategy_hash = (
            meta.get("strategy_hash")
            or config.get("strategy_hash")
            or orig_meta.get("strategy_hash")
            or results.get("strategy_hash")
        )
        orig_metrics_map = (original_run or {}).get("metrics")
        orig_metric_fp = None
        if isinstance(orig_metrics_map, dict):
            orig_metric_fp = orig_metrics_map.get("input_fingerprint")
        input_fingerprint = (
            meta.get("input_fingerprint")
            or orig_meta.get("input_fingerprint")
            or results.get("input_fingerprint")
            or orig_metric_fp
        )
        start_ts = (
            meta.get("start_ts")
            or config.get("start_ts")
            or (original_run or {}).get("start_ts")
            or (trial.get("split") or {}).get("design_start")
            or (trial.get("split") or {}).get("start_ts")
        )
        end_ts = (
            meta.get("end_ts")
            or config.get("end_ts")
            or (original_run or {}).get("end_ts")
            or (trial.get("split") or {}).get("holdout_end")
            or (trial.get("split") or {}).get("end_ts")
        )

        provenance = {
            "experiment_id": experiment_id,
            "trial_id": trial.get("trial_id"),
            "fingerprint": trial.get("fingerprint"),
            "data_hash": data_hash,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "strategy_hash": strategy_hash,
            "source_id": source_id,
            "seed": seed,
            "input_fingerprint": input_fingerprint,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "original_run_id": original_run_id,
            "code_version": trial.get("code_version") or meta.get("code_version"),
            "git_sha": meta.get("git_sha") or config.get("git_sha"),
        }

        missing: list[str] = []
        if not source_id:
            missing.append("source_id")
        if not strategy_id:
            missing.append("strategy_id")
        if not data_hash:
            missing.append("data_hash")
        if trial.get("seed") is None and (original_run is None or original_run.get("seed") is None):
            missing.append("seed")

        # If an original run exists, verify data_hash still matches source when resolvable.
        if source_id and data_hash:
            try:
                source = self.data.get_source(str(source_id))
                if source.content_hash and data_hash and source.content_hash != data_hash:
                    missing.append("data_hash_mismatch_vs_source")
            except MarketSimError:
                missing.append("source_unresolvable")

        if missing:
            return {
                "experiment_id": experiment_id,
                "reproduced": False,
                "match": False,
                "mismatches": [{"kind": "provenance", "field": m} for m in missing],
                "original_run_id": original_run_id,
                "replay_run_id": None,
                "tolerances": tolerances,
                "provenance": provenance,
                "blockers": ["REPRODUCIBILITY_INCOMPLETE", *missing],
                "truth": {
                    "silent_match_forbidden": True,
                    "partial_path": True,
                },
            }

        fee_bps = float(
            cost.get("fee_bps")
            if cost.get("fee_bps") is not None
            else (original_run or {}).get("fee_bps", 5.0)
        )
        slippage_bps = float(
            cost.get("slippage_bps")
            if cost.get("slippage_bps") is not None
            else (original_run or {}).get("slippage_bps", 2.0)
        )
        initial_cash = float(
            meta.get("initial_cash")
            or config.get("initial_cash")
            or (original_run or {}).get("initial_cash")
            or 100_000.0
        )
        agents = list(
            meta.get("agents")
            or config.get("agents")
            or (original_run or {}).get("agents")
            or []
        )
        deliberation_every_n = int(
            meta.get("deliberation_every_n")
            or config.get("deliberation_every_n")
            or (original_run or {}).get("deliberation_every_n")
            or 50
        )
        max_position_pct = float(
            (original_run or {}).get("max_position_pct")
            or config.get("max_position_pct")
            or 25.0
        )
        max_drawdown_pct = float(
            (original_run or {}).get("max_drawdown_pct")
            or config.get("max_drawdown_pct")
            or 20.0
        )
        per_trade_risk_pct = float(
            (original_run or {}).get("per_trade_risk_pct")
            or config.get("per_trade_risk_pct")
            or 1.0
        )

        replay = self.create_run(
            source_id=str(source_id),
            strategy_id=str(strategy_id),
            strategy_version=int(strategy_version) if strategy_version is not None else None,
            start_ts=str(start_ts) if start_ts else None,
            end_ts=str(end_ts) if end_ts else None,
            seed=seed,
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            max_position_pct=max_position_pct,
            max_drawdown_pct=max_drawdown_pct,
            per_trade_risk_pct=per_trade_risk_pct,
            agents=agents,
            deliberation_every_n=deliberation_every_n,
            metadata={
                "reproduce_of": experiment_id,
                "original_run_id": original_run_id,
                "strategy_hash": strategy_hash,
                "expected_input_fingerprint": input_fingerprint,
            },
        )
        replay_run_id = str(replay["run_id"])
        self.start_run(replay_run_id)
        # Drain in-process worker (tests / local). External workers may leave QUEUED.
        for _ in range(500):
            current = self.get_run(replay_run_id)
            if current["status"] in {
                RunStatus.COMPLETED.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
                RunStatus.STOPPED.value,
            }:
                break
            if hasattr(self.worker, "process_next"):
                self.worker.process_next()
            else:
                break

        replay_state = self.run_live_state(replay_run_id, message_limit=5000, fill_limit=5000)
        replay_run = replay_state["run"]
        mismatches: list[dict[str, Any]] = []

        if replay_run.get("status") != RunStatus.COMPLETED.value:
            mismatches.append(
                {
                    "kind": "status",
                    "field": "status",
                    "original": (original_run or {}).get("status") or results.get("status"),
                    "replay": replay_run.get("status"),
                }
            )

        # Compare terminal metrics when original available.
        orig_metrics = dict(results.get("metrics") or (original_run or {}).get("metrics") or {})
        replay_metrics = dict(replay_run.get("metrics") or {})
        for key in sorted(set(orig_metrics) | set(replay_metrics)):
            ov = orig_metrics.get(key)
            rv = replay_metrics.get(key)
            if isinstance(ov, dict) and "value" in ov:
                ov = ov.get("value")
            if isinstance(rv, dict) and "value" in rv:
                rv = rv.get("value")
            if ov is None or rv is None:
                if ov != rv and key in orig_metrics:
                    mismatches.append(
                        {"kind": "metric", "field": key, "original": ov, "replay": rv}
                    )
                continue
            try:
                if abs(float(ov) - float(rv)) > float(tolerances["metric_abs"]):
                    mismatches.append(
                        {
                            "kind": "metric",
                            "field": key,
                            "original": ov,
                            "replay": rv,
                            "tolerance": tolerances["metric_abs"],
                        }
                    )
            except (TypeError, ValueError):
                if ov != rv:
                    mismatches.append(
                        {"kind": "metric", "field": key, "original": ov, "replay": rv}
                    )

        # Equity trajectory comparison when original equity persisted.
        if original_run_id:
            try:
                orig_equity = self.store.list_equity(str(original_run_id), limit=5000)
            except Exception:  # noqa: BLE001
                orig_equity = []
            replay_equity = replay_state.get("equity") or []
            if orig_equity and replay_equity:
                if len(orig_equity) != len(replay_equity):
                    mismatches.append(
                        {
                            "kind": "equity",
                            "field": "length",
                            "original": len(orig_equity),
                            "replay": len(replay_equity),
                        }
                    )
                else:
                    for i, (a, b) in enumerate(zip(orig_equity, replay_equity)):
                        ae = float(a.get("equity") if isinstance(a, dict) else a)
                        be = float(b.get("equity") if isinstance(b, dict) else b)
                        if abs(ae - be) > float(tolerances["equity_abs"]):
                            mismatches.append(
                                {
                                    "kind": "equity",
                                    "field": f"index:{i}",
                                    "original": ae,
                                    "replay": be,
                                    "tolerance": tolerances["equity_abs"],
                                }
                            )
                            break

            # Fill sequence comparison (side/qty/price/bar_index).
            try:
                orig_fills = [
                    f.public_dict() if hasattr(f, "public_dict") else dict(f)
                    for f in self.store.list_fills(str(original_run_id), limit=5000)
                ]
            except Exception:  # noqa: BLE001
                orig_fills = []
            replay_fills = list(replay_state.get("fills") or [])
            if orig_fills:

                def _fill_key(f: dict[str, Any]) -> tuple:
                    return (
                        f.get("side"),
                        round(float(f.get("qty") or 0), 12),
                        round(float(f.get("price") or 0), 9),
                        f.get("bar_index"),
                    )

                if [_fill_key(f) for f in orig_fills] != [_fill_key(f) for f in replay_fills]:
                    mismatches.append(
                        {
                            "kind": "fills",
                            "field": "sequence",
                            "original_count": len(orig_fills),
                            "replay_count": len(replay_fills),
                        }
                    )

        # Input fingerprint check when both present.
        replay_fp = (replay_run.get("metadata") or {}).get("input_fingerprint") or (
            replay_metrics.get("input_fingerprint")
        )
        if input_fingerprint and replay_fp and str(input_fingerprint) != str(replay_fp):
            mismatches.append(
                {
                    "kind": "fingerprint",
                    "field": "input_fingerprint",
                    "original": input_fingerprint,
                    "replay": replay_fp,
                }
            )

        match = len(mismatches) == 0 and replay_run.get("status") == RunStatus.COMPLETED.value
        # Without original metrics/fills we can only claim reproduction executed, not match.
        if not orig_metrics and not original_run_id:
            match = False
            mismatches.append(
                {
                    "kind": "comparison",
                    "field": "original_artifacts",
                    "detail": "no original metrics/run to compare; reproduction executed only",
                }
            )

        return {
            "experiment_id": experiment_id,
            "reproduced": replay_run.get("status") == RunStatus.COMPLETED.value,
            "match": match,
            "mismatches": mismatches,
            "original_run_id": original_run_id,
            "replay_run_id": replay_run_id,
            "tolerances": tolerances,
            "provenance": {
                **provenance,
                "replay_input_fingerprint": replay_fp,
                "replay_data_hash": replay_run.get("data_hash"),
            },
            "blockers": [] if match else [m.get("kind") for m in mismatches],
            "truth": {
                "silent_match_forbidden": True,
                "partial_path": True,
                "compared_metrics_equity_fills": True,
            },
        }

    def create_qualification_run(
        self,
        *,
        strategy_id: str,
        strategy_version: int,
        strategy_hash: str,
        source_id: str,
        dataset_hash: str,
        git_sha: str,
        code_version: str,
        seed: int,
        trial_family_id: str,
        policy_id: str | None = None,
        policy: dict[str, Any] | None = None,
        experiment_id: str | None = None,
        learning_run_id: str | None = None,
        candidate_id: str | None = None,
        dataset_id: str | None = None,
        dataset_version_id: str | None = None,
        sealed_attempt_id: str | None = None,
        feature_pipeline_hash: str = "",
        execution_model_hash: str = "",
        cost_model_hash: str = "",
        risk_model_hash: str = "",
        sizing_model_hash: str = "",
        split_manifest_hash: str = "",
        dirty: bool = False,
        diff_hash: str = "",
        extra: dict[str, Any] | None = None,
        qualification_id: str | None = None,
        allow_inline_dev: bool = False,
        enqueue: bool = True,
        created_by: str = "market_sim.api",
    ) -> dict[str, Any]:
        """Create a QualificationAuthority run from immutable identifiers (never caller passed=true)."""
        self._require_enabled()
        from .qualification import (
            QualificationAuthority,
            QualificationContext,
            QualificationPolicy,
            default_institutional_policy,
        )

        # Reject caller authority booleans in extra.
        extra_clean = dict(extra or {})
        if extra_clean.pop("passed", None) is True or extra_clean.pop("qualified", None) is True:
            raise MarketSimError(
                "CALLER_BOOLEAN_NOT_AUTHORITY",
                "passed/qualified booleans are not accepted as qualification evidence",
                http_status=400,
            )

        if policy is not None:
            fields = {f.name for f in QualificationPolicy.__dataclass_fields__.values()}  # type: ignore[attr-defined]
            kwargs = {k: policy[k] for k in fields if k in policy}
            kwargs.setdefault("policy_id", policy_id or policy.get("policy_id") or f"qp_{uuid.uuid4().hex[:12]}")
            kwargs.setdefault("version", int(policy.get("version") or 1))
            kwargs.setdefault("name", policy.get("name") or "custom")
            pol = QualificationPolicy(**kwargs)  # type: ignore[arg-type]
        elif policy_id and hasattr(self.store, "get_qualification_policy"):
            stored = self.store.get_qualification_policy(policy_id)
            if stored is None:
                raise MarketSimError("POLICY_NOT_FOUND", policy_id, http_status=404)
            body = stored.get("policy_json") if isinstance(stored.get("policy_json"), dict) else stored
            fields = {f.name for f in QualificationPolicy.__dataclass_fields__.values()}  # type: ignore[attr-defined]
            kwargs = {k: body[k] for k in fields if k in body}
            kwargs.setdefault("policy_id", stored.get("policy_id") or policy_id)
            kwargs.setdefault("version", int(stored.get("version") or body.get("version") or 1))
            kwargs.setdefault("name", stored.get("name") or body.get("name") or "unnamed")
            pol = QualificationPolicy(**kwargs)  # type: ignore[arg-type]
        else:
            pol = default_institutional_policy(policy_id=policy_id)

        qid = qualification_id or f"qual_{uuid.uuid4().hex[:16]}"
        ctx = QualificationContext(
            qualification_id=qid,
            strategy_id=strategy_id,
            strategy_version=int(strategy_version),
            strategy_hash=strategy_hash,
            source_id=source_id,
            dataset_hash=dataset_hash,
            git_sha=git_sha,
            code_version=code_version,
            seed=int(seed),
            trial_family_id=trial_family_id,
            experiment_id=experiment_id,
            learning_run_id=learning_run_id,
            candidate_id=candidate_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            sealed_attempt_id=sealed_attempt_id,
            feature_pipeline_hash=feature_pipeline_hash,
            execution_model_hash=execution_model_hash,
            cost_model_hash=cost_model_hash,
            risk_model_hash=risk_model_hash,
            sizing_model_hash=sizing_model_hash,
            split_manifest_hash=split_manifest_hash,
            dirty=bool(dirty),
            diff_hash=diff_hash,
            extra=extra_clean,
        )
        auth = QualificationAuthority(plane=self, store=self.store)
        decision = auth.create_run(
            ctx,
            pol,
            created_by=created_by,
            idempotency_key=f"qualification:{qid}",
        )
        out = decision.public_dict()
        out["qualification_id"] = decision.qualification_id or qid

        if enqueue and self.job_runtime is not None:
            job_id = self.enqueue_qualification_run(out["qualification_id"])
            out["job_id"] = job_id
            out["status"] = out.get("state") or "QUEUED"
            out["queued"] = True
            return out

        if allow_inline_dev:
            evaluated = auth.evaluate(out["qualification_id"])
            result = evaluated.public_dict()
            result["evaluated_inline"] = True
            result["allow_inline_dev"] = True
            return result

        # Default: do not silently evaluate inline in production.
        out["queued"] = False
        out["warning"] = (
            "job_runtime unbound; qualification created but not evaluated. "
            "Pass allow_inline_dev=True for synchronous dev evaluation, or bind job_runtime."
        )
        out["status"] = out.get("state") or "QUEUED"
        return out

    def get_qualification_run(self, qualification_id: str) -> dict[str, Any]:
        self._require_enabled()
        from .qualification import QualificationAuthority

        auth = QualificationAuthority(plane=self, store=self.store)
        decision = auth.get(qualification_id)
        if decision is None:
            raise MarketSimError("QUALIFICATION_NOT_FOUND", qualification_id, http_status=404)
        row = self.store.get_qualification_run(qualification_id) if hasattr(self.store, "get_qualification_run") else None
        out = decision.public_dict()
        if row:
            out["row"] = row
            out["status"] = row.get("status") or out.get("state")
        return out

    def get_qualification_gates(self, qualification_id: str) -> dict[str, Any]:
        self._require_enabled()
        run = self.get_qualification_run(qualification_id)
        gates = []
        if hasattr(self.store, "list_qualification_gate_results"):
            gates = self.store.list_qualification_gate_results(qualification_id)
        else:
            gates = (run.get("gate_results") or [])
        return {
            "qualification_id": qualification_id,
            "gates": gates,
            "decision": run.get("qualified"),
            "state": run.get("state") or run.get("status"),
            "blockers": run.get("blockers") or [],
        }

    def cancel_qualification_run(self, qualification_id: str) -> dict[str, Any]:
        self._require_enabled()
        from .qualification import QualificationAuthority

        auth = QualificationAuthority(plane=self, store=self.store)
        try:
            decision = auth.cancel(qualification_id)
        except KeyError as exc:
            raise MarketSimError("QUALIFICATION_NOT_FOUND", qualification_id, http_status=404) from exc
        return decision.public_dict()

    def enqueue_qualification_run(self, qualification_id: str) -> str:
        """Enqueue durable QualificationAuthority evaluation; returns job id."""
        if self.job_runtime is None:
            raise MarketSimError(
                "TRADING_WORKER_UNAVAILABLE",
                "job_runtime not bound; cannot enqueue market_sim.qualification_run",
                http_status=503,
            )
        # Ensure run exists
        row = None
        if hasattr(self.store, "get_qualification_run"):
            row = self.store.get_qualification_run(qualification_id)
        if row is None:
            raise MarketSimError("QUALIFICATION_NOT_FOUND", qualification_id, http_status=404)
        job = self.job_runtime.enqueue(
            capability_id="market_sim.qualification_run",
            arguments={"qualification_id": qualification_id},
            idempotency_key=f"qualification:{qualification_id}",
            requested_by="market_sim",
            domain="market_sim",
            domain_entity_type="market_sim_qualification_run",
            domain_entity_id=qualification_id,
            worker_pool="market_sim",
        )
        job_id = getattr(job, "job_id", None) or (job.get("job_id") if isinstance(job, dict) else None) or str(job)
        return str(job_id)

    def get_dataset_certification(self, dataset_id: str, *, version: str | None = None) -> dict[str, Any]:
        self._require_enabled()
        cert = None
        if hasattr(self.store, "get_dataset_certification"):
            cert = self.store.get_dataset_certification(
                dataset_id=dataset_id,
                dataset_version_id=version,
            )
        if cert is None:
            raise MarketSimError(
                "CERTIFICATION_NOT_FOUND",
                f"no certification for dataset {dataset_id}",
                http_status=404,
            )
        return cert

    def evaluate_dataset_certification(
        self,
        dataset_id: str,
        *,
        dataset_version_id: str,
        dataset_hash: str,
        evidence: dict[str, Any] | None = None,
        source_id: str = "",
        data_type: str = "ohlcv",
    ) -> dict[str, Any]:
        """Server-side certification via certify_dataset_from_evidence — rejects caller certified=true."""
        self._require_enabled()
        from .institutional_core.data_governance import certify_dataset_from_evidence

        ev = dict(evidence or {})
        if ev.get("certified") is True and len([k for k in ev if k != "certified"]) == 0:
            raise MarketSimError(
                "CALLER_BOOLEAN_NOT_CERTIFICATION",
                "certified=true is not accepted as dataset certification authority",
                http_status=400,
            )
        cert = certify_dataset_from_evidence(
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            dataset_hash=dataset_hash,
            evidence=ev,
            source_id=source_id,
            data_type=data_type,
            certified_by="market_sim.api",
        )
        payload = cert.public_dict() if hasattr(cert, "public_dict") else dict(cert)
        # Persist when store supports it.
        if hasattr(self.store, "save_dataset_certification"):
            row = {
                "certification_id": payload.get("certificationId") or payload.get("certification_id"),
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "dataset_hash": dataset_hash,
                "data_type": data_type,
                "certification_state": payload.get("certificationState") or payload.get("certification_state"),
                "pit_state": payload.get("pitState") or payload.get("pit_state"),
                "survivorship_state": payload.get("survivorshipState") or payload.get("survivorship_state"),
                "revision_state": payload.get("revisionState") or payload.get("revision_state"),
                "corporate_action_state": payload.get("corporateActionState")
                or payload.get("corporate_action_state"),
                "source_id": source_id,
                "license_state": payload.get("licenseState") or payload.get("license_state"),
                "evidence": ev,
                "certification_hash": payload.get("certificationHash") or payload.get("certification_hash") or "",
                "certified_at": payload.get("certifiedAt") or payload.get("certified_at") or utc_now(),
                "certified_by": "market_sim.api",
            }
            self.store.save_dataset_certification(row)
            payload["persisted"] = True
        return payload

    def get_portfolio_strategy_risk(self, portfolio_id: str) -> dict[str, Any]:
        self._require_enabled()
        snap = None
        if hasattr(self.store, "latest_strategy_risk_snapshot"):
            snap = self.store.latest_strategy_risk_snapshot(portfolio_id)
        if snap is None:
            return {
                "portfolio_id": portfolio_id,
                "state": "UNMEASURED",
                "snapshot": None,
                "truth": {"no_fabricated_covariance": True},
            }
        return {"portfolio_id": portfolio_id, "snapshot": snap, "state": snap.get("state")}

    def get_execution_calibration(self, deployment_id: str) -> dict[str, Any]:
        self._require_enabled()
        dep = self.store.get_paper_deployment(deployment_id) if hasattr(self.store, "get_paper_deployment") else None
        if dep is None:
            raise MarketSimError("PAPER_DEPLOYMENT_NOT_FOUND", deployment_id, http_status=404)
        meta = dict(dep.get("metadata") or {})
        model_id = meta.get("execution_model_id") or dep.get("execution_model_id")
        cals: list[dict[str, Any]] = []
        if hasattr(self.store, "list_execution_calibrations"):
            if model_id:
                cals = self.store.list_execution_calibrations(execution_model_id=str(model_id), limit=50)
            else:
                # Filter by deployment id in source_deployment_ids
                all_cals = self.store.list_execution_calibrations(limit=200)
                cals = [
                    c
                    for c in all_cals
                    if deployment_id in (c.get("source_deployment_ids") or [])
                ]
        return {
            "deployment_id": deployment_id,
            "execution_model_id": model_id,
            "calibrations": cals,
            "state": cals[0].get("state") if cals else "UNMEASURED",
            "truth": {"no_single_sample_auto_disable": True},
        }

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

    def run_research_campaign_on_worker(
        self, campaign_id: str, *, max_iterations_this_job: int | None = None
    ) -> dict[str, Any]:
        """Execute/resume campaign iterations on the worker (checkpoint resume).

        Each trial completes only after a canonical gym/simulation episode commits
        metrics. Fabricated wins, all-trials-as-wins, and zero-risk promotion
        inputs are forbidden.

        When ``max_iterations_this_job`` is set, perform at most that many
        iterations then return with ``needs_continuation`` so the worker yields.
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

        wins = int((campaign.metadata or {}).get("accepted_wins") or 0)
        measured_returns: list[float] = list((campaign.metadata or {}).get("measured_returns") or [])
        measured_drawdowns: list[float] = list((campaign.metadata or {}).get("measured_drawdowns") or [])
        last_run_metrics: dict[str, Any] = dict((campaign.metadata or {}).get("last_run_metrics") or {})
        last_run_id: str | None = (campaign.metadata or {}).get("last_run_id")
        iterations_this_job = 0
        # Only slice when the worker explicitly requests a per-job bound.
        # Inline callers (max_iterations_this_job=None) run to completion.
        slice_limit = (
            max(1, int(max_iterations_this_job))
            if max_iterations_this_job is not None
            else None
        )

        while campaign.checkpoint_iteration < campaign.max_iterations:
            if slice_limit is not None and iterations_this_job >= slice_limit:
                campaign.status = "RUNNING"
                campaign.updated_at = utc_now()
                campaign.metadata = {
                    **dict(campaign.metadata),
                    "accepted_wins": wins,
                    "measured_returns": measured_returns[-32:],
                    "measured_drawdowns": measured_drawdowns[-32:],
                    "last_run_metrics": last_run_metrics,
                    "last_run_id": last_run_id,
                }
                self.store.upsert_research_campaign(campaign.public_dict())
                out = campaign.public_dict()
                out["needs_continuation"] = True
                out["iterations_this_job"] = iterations_this_job
                return out
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
                # Empty campaign criteria must not invent pass-all thresholds
                # (min_trades=1 / dd=100 / return=-100) that fabricate wins==trials.
                if campaign.acceptance_criteria:
                    acceptance = evaluate_acceptance_from_run(
                        run.public_dict(),
                        criteria=campaign.acceptance_criteria,
                    )
                    accepted = bool(getattr(acceptance, "passed", False))
                else:
                    acceptance = {
                        "passed": False,
                        "reason": "NO_ACCEPTANCE_CRITERIA",
                        "run_id": run_id,
                        "metrics": metrics,
                        "acceptance_criteria": {},
                        "truth": {"no_fabricated_pass_all_fallback": True},
                    }
                    accepted = False
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
            iterations_this_job += 1

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
            # Do not invent permissive criteria when campaign left them empty.
            acceptance_criteria=campaign.acceptance_criteria or {},
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
        out = campaign.public_dict()
        out["needs_continuation"] = False
        out["iterations_this_job"] = iterations_this_job
        return out

    def readiness_ladder(self) -> dict[str, Any]:
        from .readiness import readiness_ladder

        return readiness_ladder()

    # --- Agent lab control plane (W16) — wires agent_lab helpers to campaigns ---

    def create_agent_lab(
        self,
        *,
        name: str = "",
        strategy_id: str | None = None,
        source_id: str,
        strategy_version: int | None = None,
        max_candidates: int = 10,
        max_iterations: int = 3,
        seed: int = 42,
        hypothesis: str = "",
        acceptance_criteria: dict[str, Any] | None = None,
        autonomy_ceiling: str = "A1",
        metadata: dict[str, Any] | None = None,
        learning: dict[str, Any] | None = None,
        enable_learning: bool = True,
        run_mode: str = "SEED_EXISTING_STRATEGY",
        research_objective: str = "",
        enable_chart_vision: bool = False,
        model_budget: int = 6,
        agent_proposal_rate: float | None = None,
        research_scope: dict[str, Any] | None = None,
        dataset_bundle: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a durable lab bound to a research campaign + optional Strategy Learning Run.

        MODE A ``SEED_EXISTING_STRATEGY``: require ``strategy_id`` (current behavior).
        MODE B ``AUTONOMOUS_DISCOVERY``: create a research-lineage Strategy (hold root —
        identity for versioning only, never used as elite seed) and bootstrap a
        ResearchHypothesis from ``research_objective`` / ``hypothesis``.

        Optional ``research_scope`` / ``dataset_bundle`` (Wave 5) reference additional
        source_ids without duplicating data; single-source path remains default.
        """
        self._require_enabled()
        from .agent_lab import AcceptanceCriteria, LabOutcome, new_agent_lab
        from .features import FEATURE_PIPELINE_VERSION
        from .learning import create_learning_run
        from .learning_runtime import persist_learning_run
        from .learning_types import LearningObjectiveSpec, ResearchRunMode
        from .research_hypothesis import hypothesis_from_objective_brief
        from .research_scope import (
            objective_universe_from_scope,
            parse_research_scope,
            schedule_episodes_per_source,
        )

        mode = str(run_mode or ResearchRunMode.SEED_EXISTING_STRATEGY.value).upper().strip()
        if mode not in {
            ResearchRunMode.SEED_EXISTING_STRATEGY.value,
            ResearchRunMode.AUTONOMOUS_DISCOVERY.value,
        }:
            raise MarketSimError("INVALID_RUN_MODE", mode, http_status=400)

        sid = str(strategy_id or "").strip() or None
        if mode == ResearchRunMode.SEED_EXISTING_STRATEGY.value:
            if not sid:
                raise MarketSimError("STRATEGY_ID_REQUIRED", "strategy_id required for SEED_EXISTING_STRATEGY", http_status=400)
        elif mode == ResearchRunMode.AUTONOMOUS_DISCOVERY.value and not sid:
            short = str(uuid.uuid4())[:8]
            created = self.create_strategy(
                name=f"Research Lineage {short}",
                tags=["research_lineage_root", "autonomous_discovery"],
                entry_rules={
                    "version": 3,
                    "kind": "hold",
                    "metadata": {
                        "research_lineage_root": True,
                        "not_a_trading_seed": True,
                    },
                },
                exit_rules={"kind": "hold"},
                parameters={},
                changelog="autonomous discovery research lineage root — not a profitable seed",
            )
            sid = str((created.get("strategy") or {}).get("strategy_id") or "")
            if not sid:
                raise MarketSimError("RESEARCH_LINEAGE_CREATE_FAILED", "could not create lineage root", http_status=500)

        assert sid is not None
        strat = self.store.get_strategy(sid)
        if strat is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", sid, http_status=404)
        ver = self.store.get_strategy_version(sid, strategy_version)
        if ver is None:
            raise MarketSimError("STRATEGY_VERSION_MISSING", sid, http_status=404)
        source = self.data.get_source(source_id)
        if source.status != SourceStatus.READY.value:
            raise MarketSimError("SOURCE_NOT_READY", source_id, http_status=400)

        crit = dict(acceptance_criteria or {})
        learning_cfg = dict(learning or {})
        rate = (
            float(agent_proposal_rate)
            if agent_proposal_rate is not None
            else float(learning_cfg.get("agent_proposal_rate", 0.15))
        )
        acceptance = AcceptanceCriteria(
            min_trades=int(crit.get("min_trades", learning_cfg.get("min_trades", 1))),
            max_drawdown_pct=float(crit.get("max_drawdown_pct", learning_cfg.get("max_drawdown_pct", 100.0))),
            min_total_return_pct=crit.get("min_total_return_pct"),
            min_sharpe=crit.get("min_sharpe"),
            require_val_pass=bool(crit.get("require_val_pass", learning_cfg.get("require_val_pass", False))),
            require_robustness_pass=bool(
                crit.get("require_robustness_pass", learning_cfg.get("require_robustness_pass", False))
            ),
        )
        lab = new_agent_lab(
            acceptance=acceptance,
            max_candidates=max(1, int(max_candidates)),
            seed=int(seed),
        )
        objective_text = str(research_objective or hypothesis or "").strip()
        # Wave 5 — optional multi-asset/timeframe scope (references only)
        try:
            parsed_scope = parse_research_scope(
                research_scope=research_scope,
                dataset_bundle=dataset_bundle,
                metadata=metadata,
            )
        except ValueError as exc:
            raise MarketSimError("INVALID_RESEARCH_SCOPE", str(exc), http_status=400) from exc
        scope_public = parsed_scope.public_dict() if parsed_scope else None
        episode_schedule = []
        if parsed_scope and parsed_scope.dataset_bundle:
            try:
                available_ids = {s.source_id for s in self.data.list_sources(limit=5000)}
            except Exception:  # noqa: BLE001
                available_ids = {source_id}
            # Primary create source must remain available even if list fails partially
            available_ids.add(source_id)
            episode_schedule = [
                ep.public_dict()
                for ep in schedule_episodes_per_source(
                    parsed_scope.dataset_bundle,
                    available_source_ids=available_ids,
                )
            ]
        research_meta = {
            "lab_id": lab.lab_id,
            "run_mode": mode,
            "research_objective": objective_text,
            "enable_chart_vision": bool(enable_chart_vision),
            "model_budget": int(model_budget),
            "agent_proposal_rate": rate,
            "enable_research_cycle": True,
            **dict(metadata or {}),
        }
        if scope_public:
            research_meta["research_scope"] = scope_public
            research_meta["episode_schedule"] = episode_schedule
        campaign = self.create_research_campaign(
            name=name or f"lab-{lab.lab_id[:8]}",
            strategy_id=sid,
            strategy_version=ver.version,
            source_id=source_id,
            max_iterations=max(1, int(max_iterations)),
            seed=int(seed),
            hypothesis=hypothesis or objective_text,
            acceptance_criteria=acceptance.public_dict(),
            autonomy_ceiling=autonomy_ceiling,
            metadata=research_meta,
        )
        now = utc_now()
        payload = {
            "lab_id": lab.lab_id,
            "name": name or campaign["name"],
            "status": "CREATED",
            "outcome": LabOutcome.IN_PROGRESS.value,
            "strategy_id": sid,
            "strategy_version": ver.version,
            "source_id": source_id,
            "campaign_id": campaign["campaign_id"],
            "max_candidates": lab.max_candidates,
            "acceptance": acceptance.public_dict(),
            "candidates": [],
            "lessons": [],
            "sealed_lineages_consumed": {},
            "curriculum": lab.curriculum.public_dict(),
            "job_id": None,
            "error": "",
            "created_at": now,
            "updated_at": now,
            "metadata": {
                "seed": seed,
                "max_iterations": max(1, int(max_iterations)),
                "hypothesis": hypothesis or objective_text,
                "enable_learning": bool(enable_learning),
                "run_mode": mode,
                "research_objective": objective_text,
                "enable_chart_vision": bool(enable_chart_vision),
                "model_budget": int(model_budget),
                "agent_proposal_rate": rate,
                "enable_research_cycle": True,
                **dict(metadata or {}),
                **({"research_scope": scope_public, "episode_schedule": episode_schedule} if scope_public else {}),
            },
        }
        self.store.upsert_agent_lab(payload)
        if scope_public:
            self._emit_event(
                "research.scope.bound",
                {
                    "lab_id": lab.lab_id,
                    "edge_scope": scope_public.get("edge_scope"),
                    "source_ids": (scope_public.get("dataset_bundle") or {}).get("source_ids") or [source_id],
                    "episode_count": len(episode_schedule),
                },
            )

        # Bootstrap research hypothesis (Wave 2) — persisted before outcomes known
        hypothesis_id = None
        if objective_text or mode == ResearchRunMode.AUTONOMOUS_DISCOVERY.value:
            try:
                rh = hypothesis_from_objective_brief(
                    objective_text=objective_text
                    or "Search for positive net expectancy after costs via autonomous discovery.",
                    created_at=now,
                    lab_id=lab.lab_id,
                    symbols=[getattr(source, "symbol", "") or ""],
                    timeframes=[getattr(source, "timeframe", "") or "1h"],
                )
                saved = self.store.upsert_research_hypothesis(rh.public_dict())
                hypothesis_id = str(saved.get("hypothesis_id") or rh.hypothesis_id)
                payload["metadata"]["hypothesis_id"] = hypothesis_id
                self.store.upsert_agent_lab(payload)
                self._emit_event(
                    "research.hypothesis.proposed",
                    {"hypothesis_id": hypothesis_id, "lab_id": lab.lab_id, "run_mode": mode},
                )
            except MarketSimError:
                # Table missing / store unavailable — lab still usable without hyp persistence
                pass
            except Exception:  # noqa: BLE001
                pass

        learning_run_id = None
        if enable_learning:
            parent_family = str((ver.entry_rules or {}).get("kind") or "ma_cross")
            if mode == ResearchRunMode.AUTONOMOUS_DISCOVERY.value:
                # Lineage root is hold — do not bias family priors toward hold
                parent_family = None
            obj_raw = {
                "min_trades": acceptance.min_trades,
                "max_drawdown_pct": acceptance.max_drawdown_pct,
                "require_val_pass": acceptance.require_val_pass,
                "require_robustness_pass": acceptance.require_robustness_pass,
                "require_sealed_pass": bool(learning_cfg.get("require_sealed_pass", False)),
                "generation_budget": int(
                    learning_cfg.get("generation_budget")
                    or learning_cfg.get("max_generations")
                    or max(1, int(max_iterations))
                ),
                "trial_budget": int(learning_cfg.get("trial_budget") or learning_cfg.get("max_trials") or max_candidates * max(1, int(max_iterations))),
                "population_size": int(learning_cfg.get("population_size") or min(max_candidates, 12)),
                "elite_count": int(learning_cfg.get("elite_count") or 3),
                "seed": int(seed),
                "exploration_rate": float(learning_cfg.get("exploration_rate", 0.15)),
                "mutation_rate": float(learning_cfg.get("mutation_rate", 0.35)),
                "crossover_rate": float(learning_cfg.get("crossover_rate", 0.25)),
                "max_episode_bars": learning_cfg.get("max_episode_bars"),
                "universe": list(
                    learning_cfg.get("universe")
                    or objective_universe_from_scope(
                        parsed_scope,
                        fallback=list((metadata or {}).get("universe") or []),
                    )
                ),
                "metadata": {
                    "agent_proposal_rate": rate,
                    "run_mode": mode,
                    "enable_chart_vision": bool(enable_chart_vision),
                    "model_budget": int(model_budget),
                    "enable_research_cycle": True,
                    **(
                        {
                            "research_scope": scope_public,
                            "dataset_bundle": (scope_public or {}).get("dataset_bundle"),
                            "episode_schedule": episode_schedule,
                            "edge_scope": (scope_public or {}).get("edge_scope"),
                        }
                        if scope_public
                        else {}
                    ),
                },
            }
            # Merge fitness weights if provided
            if learning_cfg.get("fitness_weights"):
                obj_raw["fitness_weights"] = dict(learning_cfg["fitness_weights"])
            if learning_cfg.get("early_stop_rules"):
                obj_raw["early_stop_rules"] = dict(learning_cfg["early_stop_rules"])
            objective = LearningObjectiveSpec.from_dict(obj_raw)
            # Prior trials excluding SEALED
            prior_trials = []
            try:
                prior_trials = [
                    t
                    for t in self.store.list_experiments(strategy_id=sid, limit=50)
                    if str((t.get("split") or {}).get("role") or "").upper() != "SEALED"
                ]
            except Exception:  # noqa: BLE001
                prior_trials = []
            lrun = create_learning_run(
                lab_id=lab.lab_id,
                campaign_id=campaign["campaign_id"],
                strategy_id=sid,
                parent_strategy_version=ver.version,
                source_id=source_id,
                objective=objective,
                seed=int(seed),
                parent_family=parent_family,
                trial_history=prior_trials,
                lessons=list(payload.get("lessons") or []),
                feature_pipeline_version=str(FEATURE_PIPELINE_VERSION),
                now=now,
            )
            lrun.metadata = {
                **dict(lrun.metadata or {}),
                "run_mode": mode,
                "research_objective": objective_text,
                "enable_chart_vision": bool(enable_chart_vision),
                "model_budget": int(model_budget),
                "agent_proposal_rate": rate,
                "enable_research_cycle": True,
                "hypothesis_id": hypothesis_id,
            }
            if hypothesis_id:
                # Bind learning_run_id onto hypothesis after create
                pass
            persist_learning_run(self.store, lrun)
            learning_run_id = lrun.learning_run_id
            if hypothesis_id:
                try:
                    existing = self.store.get_research_hypothesis(hypothesis_id)
                    if existing:
                        existing["learning_run_id"] = learning_run_id
                        existing["updated_at"] = utc_now()
                        self.store.upsert_research_hypothesis(existing)
                except Exception:  # noqa: BLE001
                    pass
            payload["metadata"]["learning_run_id"] = learning_run_id
            self.store.upsert_agent_lab(payload)
            self._emit_event(
                "learning_run.created",
                {"learning_run_id": learning_run_id, "lab_id": lab.lab_id, "run_mode": mode},
            )

        out = self.get_agent_lab(lab.lab_id)
        if learning_run_id:
            out["learning_run_id"] = learning_run_id
            out["learning"] = self.get_learning_run(learning_run_id)
        if hypothesis_id:
            out["hypothesis_id"] = hypothesis_id
        return out

    def get_agent_lab(self, lab_id: str) -> dict[str, Any]:
        self._require_enabled()
        row = self.store.get_agent_lab(lab_id)
        if row is None:
            raise MarketSimError("LAB_NOT_FOUND", lab_id, http_status=404)
        if row.get("campaign_id"):
            try:
                camp = self.get_research_campaign(str(row["campaign_id"]))
                row = {
                    **row,
                    "campaign": {
                        "campaign_id": camp["campaign_id"],
                        "status": camp["status"],
                        "checkpoint_iteration": camp["checkpoint_iteration"],
                        "trial_ids": camp.get("trial_ids") or [],
                        "scorecard": camp.get("scorecard") or {},
                        "promotion": camp.get("promotion") or {},
                        "error": camp.get("error") or "",
                        "results": camp.get("results") or {},
                    },
                }
            except MarketSimError:
                pass
        learning_run_id = (row.get("metadata") or {}).get("learning_run_id")
        if learning_run_id:
            lrun = self.store.get_learning_run(str(learning_run_id))
            if lrun:
                row = {**row, "learning_run_id": learning_run_id, "learning": lrun}
        else:
            # Fallback: latest learning run for lab
            lrun = self.store.get_learning_run_by_lab(lab_id)
            if lrun:
                row = {
                    **row,
                    "learning_run_id": lrun["learning_run_id"],
                    "learning": lrun,
                }
        return row

    def list_agent_labs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_agent_labs(limit=limit)

    def start_agent_lab(self, lab_id: str) -> dict[str, Any]:
        """Start lab — prefers Strategy Learning Loop when a learning run is bound."""
        self._require_enabled()
        lab = self.get_agent_lab(lab_id)
        learning_run_id = lab.get("learning_run_id") or (lab.get("metadata") or {}).get("learning_run_id")
        enable_learning = bool((lab.get("metadata") or {}).get("enable_learning", True))

        lab_row = self.store.get_agent_lab(lab_id)
        if lab_row is None:
            raise MarketSimError("LAB_NOT_FOUND", lab_id, http_status=404)
        lab_row["status"] = "RUNNING"
        lab_row["updated_at"] = utc_now()
        lab_row["error"] = ""
        self.store.upsert_agent_lab(lab_row)

        if enable_learning and learning_run_id:
            return self.start_learning_run(str(learning_run_id))

        campaign_id = lab.get("campaign_id")
        if not campaign_id:
            raise MarketSimError("LAB_MISSING_CAMPAIGN", lab_id, http_status=409)

        if self.job_runtime is not None:
            started = self.start_research_campaign(str(campaign_id))
            lab_row["job_id"] = (started.get("campaign") or {}).get("job_id") or started.get("job", {}).get(
                "job_id"
            )
            lab_row["status"] = "QUEUED"
            self.store.upsert_agent_lab(lab_row)
            return {"lab": self.get_agent_lab(lab_id), "campaign_job": started}

        campaign = self.run_research_campaign_on_worker(str(campaign_id))
        return self._sync_lab_from_campaign(lab_id, campaign)

    def pause_agent_lab(self, lab_id: str) -> dict[str, Any]:
        self._require_enabled()
        lab = self.get_agent_lab(lab_id)
        if lab.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise MarketSimError("LAB_TERMINAL", f"status={lab.get('status')}", http_status=409)
        lab_row = self.store.get_agent_lab(lab_id)
        assert lab_row is not None
        lab_row["status"] = "PAUSED"
        lab_row["updated_at"] = utc_now()
        if lab_row.get("campaign_id"):
            camp = self.get_research_campaign(str(lab_row["campaign_id"]))
            if camp.get("status") not in {"COMPLETED", "FAILED", "CANCELLED"}:
                camp["status"] = "PAUSED"
                camp["updated_at"] = utc_now()
                self.store.upsert_research_campaign(camp)
        learning_run_id = lab.get("learning_run_id") or (lab_row.get("metadata") or {}).get("learning_run_id")
        if learning_run_id:
            try:
                self.pause_learning_run(str(learning_run_id))
            except MarketSimError:
                pass
        self.store.upsert_agent_lab(lab_row)
        return self.get_agent_lab(lab_id)

    def resume_agent_lab(self, lab_id: str) -> dict[str, Any]:
        self._require_enabled()
        lab = self.get_agent_lab(lab_id)
        if lab.get("status") not in {"PAUSED", "CREATED", "FAILED"}:
            if lab.get("status") in {"COMPLETED", "CANCELLED"}:
                raise MarketSimError("LAB_TERMINAL", f"status={lab.get('status')}", http_status=409)
        learning_run_id = lab.get("learning_run_id") or (lab.get("metadata") or {}).get("learning_run_id")
        if learning_run_id:
            lrun = self.store.get_learning_run(str(learning_run_id))
            if lrun and lrun.get("status") == "PAUSED":
                return self.resume_learning_run(str(learning_run_id))
        return self.start_agent_lab(lab_id)

    def cancel_agent_lab(self, lab_id: str) -> dict[str, Any]:
        self._require_enabled()
        from .agent_lab import LabOutcome

        lab = self.get_agent_lab(lab_id)
        lab_row = self.store.get_agent_lab(lab_id)
        assert lab_row is not None
        lab_row["status"] = "CANCELLED"
        lab_row["outcome"] = LabOutcome.NO_STRATEGY_QUALIFIED.value
        lab_row["updated_at"] = utc_now()
        if lab_row.get("campaign_id"):
            camp = self.get_research_campaign(str(lab_row["campaign_id"]))
            if camp.get("status") not in {"COMPLETED", "FAILED", "CANCELLED"}:
                camp["status"] = "CANCELLED"
                camp["updated_at"] = utc_now()
                self.store.upsert_research_campaign(camp)
        learning_run_id = lab.get("learning_run_id") or (lab_row.get("metadata") or {}).get("learning_run_id")
        if learning_run_id:
            try:
                self.cancel_learning_run(str(learning_run_id))
            except MarketSimError:
                pass
        self.store.upsert_agent_lab(lab_row)
        return self.get_agent_lab(lab_id)

    def _sync_lab_from_campaign(self, lab_id: str, campaign: dict[str, Any]) -> dict[str, Any]:
        from .agent_lab import (
            AcceptanceCriteria,
            LabOutcome,
            evaluate_candidate_pipeline,
            finalize_lab,
            new_agent_lab,
        )

        lab_row = self.store.get_agent_lab(lab_id)
        if lab_row is None:
            raise MarketSimError("LAB_NOT_FOUND", lab_id, http_status=404)

        acc_raw = dict(lab_row.get("acceptance") or {})
        lab = new_agent_lab(
            lab_id=lab_id,
            acceptance=AcceptanceCriteria(
                min_trades=int(acc_raw.get("min_trades", 1)),
                max_drawdown_pct=float(acc_raw.get("max_drawdown_pct", 100.0)),
                min_total_return_pct=acc_raw.get("min_total_return_pct"),
                min_sharpe=acc_raw.get("min_sharpe"),
                require_val_pass=bool(acc_raw.get("require_val_pass", False)),
                require_robustness_pass=bool(acc_raw.get("require_robustness_pass", False)),
                criteria_id=str(acc_raw.get("criteria_id") or ""),
            ),
            max_candidates=int(lab_row.get("max_candidates") or 10),
            seed=int((lab_row.get("metadata") or {}).get("seed") or 42),
        )

        iterations = list((campaign.get("results") or {}).get("iterations") or [])
        for idx, it in enumerate(iterations):
            if not it.get("simulation_executed"):
                continue
            metrics = dict(it.get("metrics") or {})
            # Normalize to explicit percent keys when fraction aliases are present.
            if "max_drawdown_pct" not in metrics and "max_drawdown" in metrics:
                raw = metrics["max_drawdown"]
                val = raw.get("value") if isinstance(raw, dict) else raw
                try:
                    metrics["max_drawdown_pct"] = float(val) * 100.0 if abs(float(val)) <= 1.0 else float(val)
                except (TypeError, ValueError):
                    pass
            if "total_return_pct" not in metrics and "total_return" in metrics:
                raw = metrics["total_return"]
                val = raw.get("value") if isinstance(raw, dict) else raw
                try:
                    metrics["total_return_pct"] = float(val) * 100.0 if abs(float(val)) <= 1.0 else float(val)
                except (TypeError, ValueError):
                    pass
            if "trade_count" not in metrics:
                metrics["trade_count"] = 0
            try:
                evaluate_candidate_pipeline(
                    lab,
                    strategy_id=str(lab_row.get("strategy_id") or campaign.get("strategy_id")),
                    strategy_version=int(lab_row.get("strategy_version") or campaign.get("strategy_version") or 1)
                    + idx,
                    hypothesis=str((lab_row.get("metadata") or {}).get("hypothesis") or f"iter {idx+1}"),
                    train_metrics=metrics,
                    val_metrics=metrics,
                    robustness_metrics=metrics,
                )
            except MarketSimError as exc:
                if exc.code == "CANDIDATE_BUDGET_EXHAUSTED":
                    break
                raise

        finalize_lab(lab)
        lab_row["candidates"] = [c.public_dict() for c in lab.candidates]
        lab_row["lessons"] = [l.public_dict() for l in lab.lessons]
        lab_row["outcome"] = lab.outcome
        lab_row["status"] = campaign.get("status") or "COMPLETED"
        lab_row["error"] = campaign.get("error") or ""
        lab_row["updated_at"] = utc_now()
        lab_row["metadata"] = {
            **dict(lab_row.get("metadata") or {}),
            "campaign_status": campaign.get("status"),
            "executed_trials": (campaign.get("metadata") or {}).get("executed_trials"),
            "accepted_wins": (campaign.get("metadata") or {}).get("accepted_wins"),
        }
        if lab.outcome == LabOutcome.NO_STRATEGY_QUALIFIED.value:
            lab_row["metadata"]["final_verdict"] = "NO_STRATEGY_QUALIFIED"
        self.store.upsert_agent_lab(lab_row)
        return self.get_agent_lab(lab_id)


    # --- Strategy Learning Loop control plane ---

    def get_learning_run(self, learning_run_id: str) -> dict[str, Any]:
        self._require_enabled()
        row = self.store.get_learning_run(learning_run_id)
        if row is None:
            raise MarketSimError("LEARNING_RUN_NOT_FOUND", learning_run_id, http_status=404)
        return row

    def list_learning_runs(self, *, lab_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_learning_runs(lab_id=lab_id, limit=limit)

    def start_learning_run(self, learning_run_id: str) -> dict[str, Any]:
        """Queue or execute a learning run (EXTERNAL_REQUIRED when JobRuntime bound)."""
        self._require_enabled()
        row = self.get_learning_run(learning_run_id)
        if row.get("status") in {"COMPLETED", "CANCELLED"}:
            raise MarketSimError("LEARNING_TERMINAL", f"status={row.get('status')}", http_status=409)
        row["pause_requested"] = False
        row["cancel_requested"] = False
        row["error"] = ""
        row["updated_at"] = utc_now()
        if self.job_runtime is not None:
            row["status"] = "QUEUED"
            row["stage"] = "QUEUED"
            self.store.upsert_learning_run(row)
            job = self.enqueue_learning_run(learning_run_id, requested_by="market_sim.start_learning_run")
            row["job_id"] = getattr(job, "job_id", None) or (job.get("job_id") if isinstance(job, dict) else None)
            self.store.upsert_learning_run(row)
            if row.get("lab_id"):
                lab = self.store.get_agent_lab(str(row["lab_id"]))
                if lab:
                    lab["status"] = "QUEUED"
                    lab["job_id"] = row["job_id"]
                    lab["updated_at"] = utc_now()
                    self.store.upsert_agent_lab(lab)
            self._emit_event("learning_run.started", {"learning_run_id": learning_run_id, "queued": True})
            return {"learning": self.get_learning_run(learning_run_id), "job": {"job_id": row["job_id"]}}

        result = self.run_learning_on_worker(learning_run_id)
        return {"learning": result, "lab": self.get_agent_lab(str(result["lab_id"])) if result.get("lab_id") else None}

    def pause_learning_run(self, learning_run_id: str) -> dict[str, Any]:
        self._require_enabled()
        row = self.get_learning_run(learning_run_id)
        if row.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise MarketSimError("LEARNING_TERMINAL", f"status={row.get('status')}", http_status=409)
        row["pause_requested"] = True
        row["status"] = "PAUSED"
        row["stage"] = "PAUSED"
        row["updated_at"] = utc_now()
        self.store.upsert_learning_run(row)
        self._emit_event("learning_run.paused", {"learning_run_id": learning_run_id})
        return self.get_learning_run(learning_run_id)

    def resume_learning_run(self, learning_run_id: str) -> dict[str, Any]:
        self._require_enabled()
        row = self.get_learning_run(learning_run_id)
        if row.get("status") not in {"PAUSED", "CREATED", "FAILED", "QUEUED"}:
            if row.get("status") in {"COMPLETED", "CANCELLED"}:
                raise MarketSimError("LEARNING_TERMINAL", f"status={row.get('status')}", http_status=409)
        row["pause_requested"] = False
        row["cancel_requested"] = False
        self.store.upsert_learning_run(row)
        self._emit_event("learning_run.resumed", {"learning_run_id": learning_run_id})
        return self.start_learning_run(learning_run_id)

    def cancel_learning_run(self, learning_run_id: str) -> dict[str, Any]:
        self._require_enabled()
        row = self.get_learning_run(learning_run_id)
        row["cancel_requested"] = True
        row["status"] = "CANCELLED"
        row["stage"] = "CANCELLED"
        row["updated_at"] = utc_now()
        self.store.upsert_learning_run(row)
        self._emit_event("learning_run.cancelled", {"learning_run_id": learning_run_id})
        return self.get_learning_run(learning_run_id)

    def enqueue_learning_run(
        self,
        learning_run_id: str,
        *,
        requested_by: str = "market_sim",
        parent_job_id: str | None = None,
    ) -> Any:
        if self.job_runtime is None:
            raise MarketSimError(
                "TRADING_WORKER_UNAVAILABLE",
                "learning runs require job_runtime / market_sim worker",
                http_status=503,
            )
        row = self.get_learning_run(learning_run_id)
        gen = str(row.get("current_generation") or 0)
        idem = f"market_sim:learning_run:{learning_run_id}:{gen}:{row.get('input_fingerprint') or ''}"
        return self.job_runtime.enqueue(
            capability_id="market_sim.learning_run",
            arguments={"learning_run_id": learning_run_id},
            requested_by=requested_by,
            idempotency_key=idem,
            domain="market_sim",
            domain_entity_type="market_sim_learning_run",
            domain_entity_id=learning_run_id,
            worker_pool="market_sim",
            parent_job_id=parent_job_id,
        )

    def run_learning_on_worker(
        self, learning_run_id: str, *, max_generations_this_job: int | None = None
    ) -> dict[str, Any]:
        """Execute/resume learning run (market_sim worker only)."""
        from .learning_runtime import run_learning_on_worker

        return run_learning_on_worker(
            self, learning_run_id, max_generations_this_job=max_generations_this_job
        )

    def get_lab_learning(self, lab_id: str) -> dict[str, Any]:
        lab = self.get_agent_lab(lab_id)
        learning = lab.get("learning")
        if not learning:
            raise MarketSimError("LEARNING_RUN_NOT_FOUND", lab_id, http_status=404)
        return {
            "lab_id": lab_id,
            "learning": learning,
            "truth": {
                "server_side_fitness": True,
                "no_mock_kpis": True,
                "live_trading": "BLOCKED",
            },
        }

    def get_lab_generations(self, lab_id: str) -> dict[str, Any]:
        data = self.get_lab_learning(lab_id)
        learning = data["learning"]
        return {
            "lab_id": lab_id,
            "learning_run_id": learning.get("learning_run_id"),
            "current_generation": learning.get("current_generation"),
            "generation_summaries": learning.get("generation_summaries") or [],
            "family_probabilities": (learning.get("learner_state") or {}).get("family_probabilities") or {},
        }

    def get_lab_candidates(self, lab_id: str) -> dict[str, Any]:
        data = self.get_lab_learning(lab_id)
        learning = data["learning"]
        return {
            "lab_id": lab_id,
            "learning_run_id": learning.get("learning_run_id"),
            "candidates": learning.get("candidates") or [],
            "qualified_candidate": learning.get("qualified_candidate"),
            "best_train_candidate": learning.get("best_train_candidate"),
            "best_validation_candidate": learning.get("best_validation_candidate"),
        }

    def explain_lab_candidate(self, lab_id: str, candidate_id: str) -> dict[str, Any]:
        """Structured evidence-only explainability for one lab candidate (Wave 27)."""
        self._require_enabled()
        from .candidate_explainability import explain_candidate

        lab = self.get_agent_lab(lab_id)
        learning = lab.get("learning")
        learning_run_id = lab.get("learning_run_id") or (lab.get("metadata") or {}).get("learning_run_id")
        if learning is None and learning_run_id:
            learning = self.store.get_learning_run(str(learning_run_id))
        explanation = explain_candidate(
            self.store,
            candidate_id=str(candidate_id),
            learning_run=learning if isinstance(learning, dict) else None,
            learning_run_id=str(learning_run_id) if learning_run_id else None,
        )
        return {
            "lab_id": lab_id,
            "candidate_id": candidate_id,
            "explanation": explanation,
            "liveTrading": "BLOCKED",
            "truth": {
                "evidence_only": True,
                "no_llm_storytelling": True,
                "live_trading": "BLOCKED",
            },
        }

    def get_lab_lessons(self, lab_id: str) -> dict[str, Any]:
        lab = self.get_agent_lab(lab_id)
        return {
            "lab_id": lab_id,
            "lessons": lab.get("lessons") or [],
            "truth": {"agent_proposed_is_not_proof": True},
        }

    def list_lab_hypotheses(self, lab_id: str, *, limit: int = 50) -> dict[str, Any]:
        self._require_enabled()
        lab = self.get_agent_lab(lab_id)
        hyps = self.store.list_research_hypotheses(lab_id=lab_id, limit=limit)
        return {
            "lab_id": lab_id,
            "hypotheses": hyps,
            "hypothesis_id": (lab.get("metadata") or {}).get("hypothesis_id"),
            "count": len(hyps),
        }

    def get_lab_perception(self, lab_id: str) -> dict[str, Any]:
        """Return latest research perception stored on learning-run / lab metadata."""
        self._require_enabled()
        lab = self.get_agent_lab(lab_id)
        meta = dict(lab.get("metadata") or {})
        perception = meta.get("latest_perception")
        learning_run_id = lab.get("learning_run_id") or meta.get("learning_run_id")
        if learning_run_id:
            lrun = self.store.get_learning_run(str(learning_run_id))
            if lrun:
                perception = (lrun.get("metadata") or {}).get("latest_perception") or perception
        return {
            "lab_id": lab_id,
            "perception": perception,
            "status": "MEASURED" if perception else "UNMEASURED",
        }

    def get_research_hypothesis(self, hypothesis_id: str) -> dict[str, Any]:
        self._require_enabled()
        row = self.store.get_research_hypothesis(hypothesis_id)
        if row is None:
            raise MarketSimError("HYPOTHESIS_NOT_FOUND", hypothesis_id, http_status=404)
        return row

    def list_strategy_families(self) -> dict[str, Any]:
        self._require_enabled()
        from .strategy_families import all_family_descriptors, research_generatable_families

        descriptors = [d.public_dict() for d in all_family_descriptors().values()]
        return {
            "families": descriptors,
            "generatable": list(research_generatable_families()),
            "count": len(descriptors),
        }

    # --- Institutional core surface (lazy imports; live trading stays BLOCKED) ---

    def institutional_gap_matrix(self) -> dict[str, Any]:
        from .institutional_core.gap_ledger import build_capability_gap_matrix

        return build_capability_gap_matrix().public_dict()

    def institutional_control_room(self) -> dict[str, Any]:
        from .institutional_core.runtime import get_institutional_runtime

        return get_institutional_runtime(self.store.db_path).control_room_snapshot(
            feature_enabled=self.enabled,
        )

    def institutional_api_catalog(self) -> dict[str, Any]:
        from .institutional_core.api_surface import api_catalog_public

        return api_catalog_public()

    def institutional_multi_asset(self) -> dict[str, Any]:
        from .institutional_core.multi_asset import build_multi_asset_truth_pack

        return build_multi_asset_truth_pack(feature_enabled=self.enabled).public_dict()

    def institutional_runtime(self) -> Any:
        from .institutional_core.runtime import get_institutional_runtime

        return get_institutional_runtime(self.store.db_path)

    def institutional_instruments(self) -> dict[str, Any]:
        rt = self.institutional_runtime()
        items = rt.repo.list_instruments()
        return {
            "items": items,
            "count": len(items),
            "truth": {"persisted": True, "source": "institutional_instruments"},
        }

    def institutional_portfolio_state(self, portfolio_id: str) -> dict[str, Any]:
        rt = self.institutional_runtime()
        return {
            "portfolioId": portfolio_id,
            "ibor": rt.reconstruct_portfolio_ibor(portfolio_id),
            "journal": rt.journal_balances(portfolio_id),
            "decisions": rt.repo.list_decision_packets(limit=50),
            "audit": rt.repo.verify_audit_chain(),
        }

    def institutional_run_reconciliation(
        self,
        left: Any,
        right: Any,
        *,
        domain: str = "generic",
        left_system: str = "left",
        right_system: str = "right",
        run_id: str | None = None,
        fields: list[str] | tuple[str, ...] | None = None,
        key_field: str = "id",
        numeric_tolerance: float = 0.0,
        allow_both_empty: bool = False,
        expected_population: int | None = None,
    ) -> dict[str, Any]:
        """Compare left/right maps or row lists; persist breaks; no silent auto-resolve."""
        def _as_rows(payload: Any) -> list[dict[str, Any]]:
            if payload is None:
                return []
            if isinstance(payload, list):
                return [dict(item) if isinstance(item, dict) else {"id": str(i), "value": item} for i, item in enumerate(payload)]
            if isinstance(payload, dict):
                rows: list[dict[str, Any]] = []
                for key, value in payload.items():
                    if isinstance(value, dict):
                        row = dict(value)
                        row.setdefault(key_field, key)
                        rows.append(row)
                    else:
                        rows.append({key_field: key, "value": value})
                return rows
            raise MarketSimError(
                "INVALID_RECONCILIATION_PAYLOAD",
                "left/right must be a map or list of row maps",
                http_status=400,
            )

        left_rows = _as_rows(left)
        right_rows = _as_rows(right)
        compare_fields = tuple(fields) if fields else ("value",)
        if fields is None and left_rows and right_rows:
            sample_keys = set(left_rows[0]) & set(right_rows[0]) - {key_field}
            if sample_keys:
                compare_fields = tuple(sorted(sample_keys))
        rt = self.institutional_runtime()
        return rt.run_and_persist_reconciliation(
            run_id=run_id,
            domain=str(domain or "generic"),
            left_system=str(left_system or "left"),
            right_system=str(right_system or "right"),
            left_rows=left_rows,
            right_rows=right_rows,
            fields=compare_fields,
            key_field=key_field,
            numeric_tolerance=float(numeric_tolerance or 0.0),
            allow_both_empty=bool(allow_both_empty),
            expected_population=expected_population,
        )
