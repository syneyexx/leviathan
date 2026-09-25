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
from .strategy_eval import strategy_content_hash, validate_strategy_document
from .strategy_dsl import (
    family_template,
    is_dsl_v2_document,
    unwrap_dsl_spec,
)
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
        self.execution_gateway = None
        self.secrets_broker = None
        self.engine = SimulationEngine(
            store,
            deliberation=DeliberationRuntime(self.brain),
        )
        self.multi_engine = MultiAgentEngine(store)
        self.providers = default_registry(data.markets_root)
        self._paper_brokers: dict[str, Any] = {}
        self._fleet = None
        self.live_guard = LiveTradingGuard()
        from .risk_engine_v2 import RiskEngineV2

        self.risk_engine = RiskEngineV2(store=store)
        self._paper_forward = None
        self._shadow_live = None
        self._audit_events: list[dict[str, Any]] = []
        self._bars_per_slice = 50
        self.default_initial_cash = 100_000.0
        self.worker = MarketSimWorker(
            store,
            self.engine,
            resolve_bars_path=self._resolve_bars_path,
            resolve_strategy=self._resolve_strategy_payload,
            bars_per_slice=self._bars_per_slice,
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
        store = getattr(job_runtime, "store", None) if job_runtime is not None else None
        if hasattr(self.worker, "bind_job_store"):
            self.worker.bind_job_store(store)

    def bind_execution_gateway(self, gateway: Any | None) -> None:
        self.execution_gateway = gateway

    def bind_secrets_broker(self, secrets_broker: Any | None) -> None:
        self.secrets_broker = secrets_broker

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
                # Prefer trading category (G49); keep market_sim as subsystem tag in payload.
                enriched = {**payload, "subsystem": "market_sim"}
                self._emit("trading", name, payload=enriched)
            except Exception:  # noqa: BLE001
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
        externalized = self._runners_externalized()
        jobstore_default = bool(externalized and self.job_runtime is not None)
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
                "worker_is_daemon_thread_by_default": not jobstore_default,
                "default_path_jobstore_lease": jobstore_default,
                "subprocess_entrypoint": "scripts/market_sim_worker.py",
                "causality_enforced": True,
                "next_bar_open_fills": True,
                "commit_reveal_multi_wallet": True,
                "ohlcv_not_orderbook": True,
                "profitable_backtest_is_not_proof": True,
                "mutations_via_execution_gateway": self.execution_gateway is not None,
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
        dsl_spec: dict[str, Any] | None = None,
        family: str | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        now = utc_now()
        parameters = dict(parameters or {"fast_ma": 10, "slow_ma": 30, "lookback": 30})
        entry_rules = dict(entry_rules or {"kind": "ma_cross"})
        exit_rules = dict(exit_rules or {"kind": "ma_cross"})
        risk_rules = dict(risk_rules or {"max_position_pct": 25})
        required_timeframes = list(required_timeframes or ["1h"])
        brain_dependencies = list(brain_dependencies or ["knowledge", "memory", "neuro"])

        compiled = None
        if dsl_spec is not None:
            compiled = validate_strategy_document(dsl_spec)
        elif family:
            dsl_spec = family_template(family)
            compiled = validate_strategy_document(dsl_spec)
        else:
            unwrapped = unwrap_dsl_spec(entry_rules)
            if unwrapped is not None:
                dsl_spec = unwrapped
                compiled = validate_strategy_document(dsl_spec)
            elif is_dsl_v2_document(entry_rules):
                compiled = validate_strategy_document(entry_rules)
                dsl_spec = dict(entry_rules)

        if compiled is not None and dsl_spec is not None:
            # Persist DSL as entry_rules document + metadata pointer
            entry_rules = {
                "kind": "dsl_v2",
                "dsl_version": compiled.dsl_version,
                "content_hash": compiled.content_hash,
                "family": compiled.family,
                "spec": compiled.public_dict(),
            }
            exit_rules = {"kind": "dsl_v2", "mirrors_entry": True}
            parameters = {
                **parameters,
                "dsl_version": compiled.dsl_version,
                "family": compiled.family,
            }
            if compiled.required_timeframes:
                required_timeframes = list(compiled.required_timeframes)
            if compiled.brain_dependencies:
                brain_dependencies = list(compiled.brain_dependencies)
            risk_rules = {**risk_rules, **compiled.risk_conditions}

        content_hash = strategy_content_hash(
            parameters=parameters,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_rules=risk_rules,
            required_timeframes=required_timeframes,
            brain_dependencies=brain_dependencies,
            dsl_spec=dsl_spec,
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
            metadata={
                "dsl_version": compiled.dsl_version if compiled else 1,
                "family": (compiled.family if compiled else (entry_rules.get("kind") or "ma_cross")),
            },
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
            metadata={
                "dsl_spec": dsl_spec,
                "compiled_hash": compiled.content_hash if compiled else None,
            },
        )
        self.store.create_strategy(record, version)
        self._emit_event("strategy.created", {"strategy_id": strategy_id, "dsl": compiled is not None})
        return {
            "strategy": record.public_dict(),
            "version": version.public_dict(),
            "compiled": compiled.public_dict() if compiled else None,
        }

    def validate_strategy_dsl(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Reject invalid DSL before simulation."""
        self._require_enabled()
        compiled = validate_strategy_document(spec)
        return {"valid": True, "compiled": compiled.public_dict()}

    def strategy_family_template(self, family: str, *, symbol: str = "BTCUSDT", timeframe: str = "1h") -> dict[str, Any]:
        self._require_enabled()
        spec = family_template(family, symbol=symbol, timeframe=timeframe)
        compiled = validate_strategy_document(spec)
        return {"family": family, "spec": spec, "compiled": compiled.public_dict()}

    def list_strategy_families(self) -> dict[str, Any]:
        self._require_enabled()
        from .strategy_dsl import STRATEGY_FAMILIES

        return {"families": sorted(STRATEGY_FAMILIES), "dsl_version": 2}

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
        dsl_spec: dict[str, Any] | None = None,
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

        compiled = None
        if dsl_spec is None:
            dsl_spec = unwrap_dsl_spec(entry_rules, metadata=current.metadata if entry_rules == current.entry_rules else None)
            # If caller passed a fresh DSL document as entry_rules
            if dsl_spec is None and is_dsl_v2_document(entry_rules):
                dsl_spec = dict(entry_rules)
        if dsl_spec is not None:
            compiled = validate_strategy_document(dsl_spec)
            entry_rules = {
                "kind": "dsl_v2",
                "dsl_version": compiled.dsl_version,
                "content_hash": compiled.content_hash,
                "family": compiled.family,
                "spec": compiled.public_dict(),
            }
            exit_rules = {"kind": "dsl_v2", "mirrors_entry": True}
            parameters = {
                **parameters,
                "dsl_version": compiled.dsl_version,
                "family": compiled.family,
            }
            if compiled.required_timeframes:
                required_timeframes = list(compiled.required_timeframes)
            if compiled.brain_dependencies:
                brain_dependencies = list(compiled.brain_dependencies)
            risk_rules = {**risk_rules, **compiled.risk_conditions}
            record.metadata = {
                **dict(record.metadata or {}),
                "dsl_version": compiled.dsl_version,
                "family": compiled.family,
            }

        content_hash = strategy_content_hash(
            parameters=parameters,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_rules=risk_rules,
            required_timeframes=required_timeframes,
            brain_dependencies=brain_dependencies,
            dsl_spec=dsl_spec,
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
            metadata={
                "dsl_spec": dsl_spec,
                "compiled_hash": compiled.content_hash if compiled else None,
            },
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
        return {
            "strategy": record.public_dict(),
            "version": version.public_dict(),
            "compiled": compiled.public_dict() if compiled else None,
        }

    def fork_strategy(self, strategy_id: str, *, name: str | None = None) -> dict[str, Any]:
        self._require_enabled()
        record = self.store.get_strategy(strategy_id)
        version = self.store.get_strategy_version(strategy_id)
        if record is None or version is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
        dsl_spec = unwrap_dsl_spec(version.entry_rules, metadata=version.metadata)
        return self.create_strategy(
            name=name or f"{record.name} (fork)",
            description=record.description,
            tags=list(record.tags),
            parameters=dict(version.parameters),
            entry_rules=dict(version.entry_rules) if dsl_spec is None else None,
            exit_rules=dict(version.exit_rules) if dsl_spec is None else None,
            risk_rules=dict(version.risk_rules),
            required_timeframes=list(version.required_timeframes),
            brain_dependencies=list(version.brain_dependencies),
            changelog=f"fork of {strategy_id}@{version.version}",
            dsl_spec=dsl_spec,
        )

    def archive_strategy(self, strategy_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self.promote_strategy(strategy_id, to_status=StrategyStatus.ARCHIVED.value)

    def promote_strategy(
        self,
        strategy_id: str,
        *,
        to_status: str,
        reason: str = "",
        decided_by: str = "operator",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Explicit promotion/degradation state transition (G31 / T15) — never silent."""
        from .lifecycle import assert_lifecycle_transition

        self._require_enabled()
        record = self.store.get_strategy(strategy_id)
        if record is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
        target = str(to_status or "").upper()
        assert_lifecycle_transition(record.status, target)
        now = utc_now()
        event = self.store.append_promotion_event(
            {
                "event_id": str(uuid.uuid4()),
                "strategy_id": strategy_id,
                "from_status": record.status,
                "to_status": target,
                "reason": reason or "",
                "decided_by": decided_by,
                "evidence": evidence or {},
                "created_at": now,
            }
        )
        record.status = target
        record.updated_at = now
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE market_strategies SET status=?, updated_at=? WHERE strategy_id=?",
                (record.status, record.updated_at, strategy_id),
            )
        payload = record.public_dict()
        payload["promotion"] = event
        return payload

    def recall_strategy_memories(
        self,
        *,
        strategy_id: str | None = None,
        as_of_ts: str,
        features: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        from .strategy_library import StrategyLibrary

        self._require_enabled()
        return StrategyLibrary(self.store).recall(
            strategy_id=strategy_id,
            as_of_ts=as_of_ts,
            features=features,
            limit=limit,
        )

    def list_strategy_lessons(
        self,
        *,
        strategy_id: str | None = None,
        as_of_ts: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        from .strategy_library import StrategyLibrary

        self._require_enabled()
        return StrategyLibrary(self.store).lessons(
            strategy_id=strategy_id, as_of_ts=as_of_ts, limit=limit
        )

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
        if not agent_list:
            # T10: multi-agent competition uses role presets from backend (not UI hardcodes).
            gm = (game_mode or "").lower()
            meta_mode = str((metadata or {}).get("engine") or "").lower()
            if gm in {"individual_competition", "multi_agent"} or meta_mode in {
                "multi",
                "multi_agent",
                "individual_competition",
            }:
                from .roles import default_competition_agents

                per_agent = float(initial_cash) / 2.0 if float(initial_cash) > 0 else 50_000.0
                agent_list = default_competition_agents(initial_cash=per_agent)
            else:
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

    def run_builder_options(self) -> dict[str, Any]:
        """T10 / G42 — run configuration options for the Trading Center UI."""
        self._require_enabled()
        from .roles import default_competition_agents

        return {
            "engines": [
                {
                    "id": "multi_agent",
                    "label": "Multi-agent competition",
                    "game_mode": "individual_competition",
                    "default_agents": default_competition_agents(initial_cash=50_000.0),
                },
                {
                    "id": "single",
                    "label": "Single strategy engine",
                    "game_mode": None,
                    "default_agents": None,
                },
            ],
            "initial_cash_presets": [10_000.0, 50_000.0, 100_000.0, 250_000.0],
            "speeds": [1, 2, 5],
            "truth": {
                "agents_from_backend_presets": True,
                "ui_must_not_hardcode_agent_ids": True,
                "live_series_are_recent_tail": True,
            },
        }

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
        # Recent-tail loaders (newest N, re-ordered chronologically) — not oldest-first.
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
                "live_series_recent_tail": True,
                "fill_limit": fill_limit,
                "message_limit": message_limit,
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
                broker_id,
                job_runtime=self.job_runtime,
                secrets_broker=self.secrets_broker,
            )
        else:
            broker = self._paper_brokers[broker_id]
            if hasattr(broker, "bind_job_runtime"):
                broker.bind_job_runtime(self.job_runtime)
            if hasattr(broker, "bind_secrets_broker"):
                broker.bind_secrets_broker(self.secrets_broker)
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
        # T9 / D18: per-session wallet — never reset a shared broker wallet.
        if hasattr(broker, "wallet_for_session"):
            # session_id assigned below; create wallet after id is known
            pass

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
        session_id = str(uuid.uuid4())
        wallet_public: dict[str, Any] = {}
        if hasattr(broker, "wallet_for_session"):
            wallet = broker.wallet_for_session(session_id, initial_cash=initial_cash)
            wallet_public = wallet.public_dict()
        elif hasattr(broker, "wallet"):
            # Legacy brokers without per-session support (should not be local_paper).
            from .accounting import money

            broker.wallet.cash = money(initial_cash)
            broker.wallet.peak_equity = money(initial_cash)
            wallet_public = broker.account().get("wallet") if hasattr(broker, "account") else {}

        # T14 — never label paper as ambiguous "LIVE"; distinguish local vs broker paper.
        bid = str(broker_id or "").lower()
        if bid in {"local_paper", "paper", "replay"}:
            execution_mode = "LOCAL PAPER"
        else:
            execution_mode = "BROKER PAPER"
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
            "wallet": wallet_public,
            "orders": [],
            "execution_mode": execution_mode,
            "mode": execution_mode,
            "metadata": {
                "mode": "live_paper",
                "execution_mode": execution_mode,
                "regime_match": match,
                "last_quote": quote,
                "feed_latency_ms": latency,
                "initial_cash": initial_cash,
                "truth": {
                    "not_live_money": True,
                    "not_historical_backtest": True,
                    "paper_never_auto_approves_live": True,
                    "per_session_wallet": True,
                    "live_money_blocked": True,
                    "same_kernel_as_shadow": True,
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
        # Refresh quote (GET-ish refresh for runners; routes that must be side-effect free
        # should use get_paper_session_readonly).
        try:
            provider = self.providers.get(session["provider_id"])
            quote = provider.fetch_quote(session["symbol"])
            session["metadata"] = dict(session.get("metadata") or {})
            session["metadata"]["last_quote"] = quote
            st = provider.status()
            session["feed_status"] = "live" if st.reachable else "disconnected"
            session["metadata"]["feed_latency_ms"] = st.latency_ms
            from .reconciliation import data_quality_watchdog

            session["metadata"]["watchdog"] = data_quality_watchdog(
                feed_status=session["feed_status"],
                feed_latency_ms=st.latency_ms,
                stale=False if session["feed_status"] == "live" else True,
            )
        except Exception as exc:  # noqa: BLE001
            session["feed_status"] = f"error:{exc}"
            session["metadata"] = dict(session.get("metadata") or {})
            from .reconciliation import data_quality_watchdog

            session["metadata"]["watchdog"] = data_quality_watchdog(
                feed_status=session["feed_status"],
                feed_latency_ms=(session.get("metadata") or {}).get("feed_latency_ms"),
                stale=True,
            )
        broker = self._paper_broker(session["broker_id"])
        if hasattr(broker, "wallet_for_session"):
            session["wallet"] = broker.wallet_for_session(session_id).public_dict()
        elif hasattr(broker, "account"):
            try:
                session["wallet"] = broker.account(session_id=session_id).get("wallet") or broker.account()
            except TypeError:
                session["wallet"] = broker.account().get("wallet") or broker.account()
        session["updated_at"] = utc_now()
        self.store.upsert_paper_session(session)
        return session

    def get_paper_session_readonly(self, session_id: str) -> dict[str, Any]:
        """GET-safe session fetch — no quote refresh / no writes (G32)."""
        self._require_enabled()
        session = self.store.get_paper_session(session_id)
        if session is None:
            raise MarketSimError("PAPER_SESSION_NOT_FOUND", session_id, http_status=404)
        return session

    def paper_place_order(
        self,
        session_id: str,
        *,
        side: str,
        qty: float,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        from .audit_ledger import append_audit_event
        from .reconciliation import data_quality_watchdog

        self._require_enabled()
        session = self.paper_session_state(session_id)
        if session.get("kill_switch") or self.risk_engine.kill.global_armed:
            raise MarketSimError("KILL_SWITCH", "Paper session kill switch armed", http_status=409)
        if session.get("status") != "active":
            raise MarketSimError("SESSION_NOT_ACTIVE", session.get("status") or "")
        watchdog = (session.get("metadata") or {}).get("watchdog") or data_quality_watchdog(
            feed_status=session.get("feed_status") or "unknown",
            feed_latency_ms=(session.get("metadata") or {}).get("feed_latency_ms"),
        )
        if watchdog.get("action") in {"pause", "halt"}:
            raise MarketSimError(
                "FEED_STALE" if "stale" in str(watchdog.get("reasons")) else "FEED_UNCERTAIN",
                f"watchdog:{watchdog.get('action')}:{','.join(watchdog.get('reasons') or [])}",
                http_status=409,
            )
        broker = self._paper_broker(session["broker_id"])
        quote = (session.get("metadata") or {}).get("last_quote") or {}
        price = quote.get("price")
        if price is None:
            raise MarketSimError(
                "FEED_UNCERTAIN",
                "No live quote — refusing paper order (no blind resubmit)",
                http_status=409,
            )
        # Risk Engine v2 on every order path (G34).
        if hasattr(broker, "wallet_for_session"):
            wallet = broker.wallet_for_session(session_id)
        else:
            wallet = broker.wallet
        coid = client_order_id or str(uuid.uuid4())
        now = utc_now()
        append_audit_event(
            self._audit_events,
            kind="intent",
            payload={"side": side, "qty": qty, "client_order_id": coid, "price": price},
            created_at=now,
            session_id=session_id,
        )
        decision = self.risk_engine.evaluate_order(
            side=side,
            qty=qty,
            price=float(price),
            wallet=wallet,
            strategy_id=session.get("strategy_id"),
            metadata={"session_id": session_id, "now": now},
            session_id=session_id,
        )
        append_audit_event(
            self._audit_events,
            kind="risk_decision",
            payload=decision.public_dict(),
            created_at=now,
            session_id=session_id,
        )
        if not decision.allowed:
            raise MarketSimError("RISK_REJECTED", decision.reason, http_status=409)
        sized = float(decision.sized_qty) if decision.sized_qty else float(qty)
        append_audit_event(
            self._audit_events,
            kind="broker_call",
            payload={"broker_id": session["broker_id"], "client_order_id": coid, "qty": sized},
            created_at=now,
            session_id=session_id,
        )
        place_kwargs = {
            "symbol": session["symbol"],
            "side": side,
            "qty": sized,
            "client_order_id": coid,
            "price_hint": float(price),
            "metadata": {
                "strategy_id": session.get("strategy_id"),
                "strategy_version": session.get("strategy_version"),
                "session_id": session_id,
            },
        }
        try:
            order = broker.place(**place_kwargs, session_id=session_id)
        except TypeError:
            order = broker.place(**place_kwargs)
        append_audit_event(
            self._audit_events,
            kind="fill",
            payload=order.public_dict(),
            created_at=utc_now(),
            session_id=session_id,
        )
        if hasattr(self.store, "append_trading_audit_event"):
            for ev in self._audit_events[-4:]:
                try:
                    self.store.append_trading_audit_event(ev)
                except Exception:  # noqa: BLE001
                    pass
        orders = list(session.get("orders") or [])
        orders.append(order.public_dict())
        session["orders"] = orders
        if hasattr(broker, "wallet_for_session"):
            session["wallet"] = broker.wallet_for_session(session_id).public_dict()
        else:
            session["wallet"] = broker.account().get("wallet") or {}
        session["updated_at"] = utc_now()
        self.store.upsert_paper_session(session)
        return {"order": order.public_dict(), "session": session, "risk": decision.public_dict()}

    def paper_kill_switch(self, session_id: str, *, armed: bool = True) -> dict[str, Any]:
        from .audit_ledger import append_audit_event

        self._require_enabled()
        session = self.store.get_paper_session(session_id)
        if session is None:
            raise MarketSimError("PAPER_SESSION_NOT_FOUND", session_id, http_status=404)
        session["kill_switch"] = bool(armed)
        session["updated_at"] = utc_now()
        if armed:
            self.risk_engine.arm_global_kill("paper session kill switch", now=session["updated_at"])
        append_audit_event(
            self._audit_events,
            kind="kill_switch",
            payload={"armed": armed, "session_id": session_id},
            created_at=session["updated_at"],
            session_id=session_id,
        )
        self.store.upsert_paper_session(session)
        return session

    def list_paper_sessions(self) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_paper_sessions()

    def _paper_forward_runner(self) -> Any:
        if self._paper_forward is None:
            from .paper_forward import PaperForwardRunner

            self._paper_forward = PaperForwardRunner(self)
        return self._paper_forward

    def start_paper_forward(
        self,
        session_id: str,
        *,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        return self._paper_forward_runner().start(
            session_id=session_id,
            now=utc_now(),
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )

    def paper_forward_tick(self, runner_id: str, *, side: str | None = None) -> dict[str, Any]:
        self._require_enabled()
        return self._paper_forward_runner().tick(runner_id, now=utc_now(), side=side)

    def paper_forward_pause(self, runner_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self._paper_forward_runner().pause(runner_id, now=utc_now())

    def paper_forward_resume(self, runner_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self._paper_forward_runner().resume(runner_id, now=utc_now())

    def get_paper_forward(self, runner_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self._paper_forward_runner().get(runner_id)

    def reconcile_paper_session(
        self,
        session_id: str,
        *,
        shadow_fills: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from .audit_ledger import append_audit_event
        from .reconciliation import reconcile_shadow_ledger

        self._require_enabled()
        session = self.get_paper_session_readonly(session_id)
        primary = list(session.get("orders") or [])
        shadow = list(shadow_fills or [])
        report = reconcile_shadow_ledger(
            primary_fills=primary, shadow_fills=shadow, created_at=utc_now()
        )
        append_audit_event(
            self._audit_events,
            kind="reconciliation",
            payload=report,
            created_at=report["created_at"],
            session_id=session_id,
        )
        if hasattr(self.store, "save_paper_reconciliation"):
            self.store.save_paper_reconciliation(report)
        return report

    def compute_paper_drift(
        self,
        *,
        paper_equity: list[float],
        backtest_equity: list[float],
        band_pct: float = 5.0,
    ) -> dict[str, Any]:
        from .reconciliation import drift_vs_backtest

        self._require_enabled()
        return drift_vs_backtest(
            paper_equity=paper_equity,
            backtest_equity=backtest_equity,
            band_pct=band_pct,
            created_at=utc_now(),
        )

    def risk_engine_status(self) -> dict[str, Any]:
        self._require_enabled()
        return self.risk_engine.public_dict()

    def risk_human_reset(
        self, *, human_token: str, strategy_id: str | None = None
    ) -> dict[str, Any]:
        self._require_enabled()
        kill = self.risk_engine.human_reset_kill(
            now=utc_now(), strategy_id=strategy_id, human_token=human_token
        )
        return kill.public_dict()

    def risk_loosen_limits(
        self, patch: dict[str, Any], *, approval_id: str | None
    ) -> dict[str, Any]:
        self._require_enabled()
        limits = self.risk_engine.loosen_limits(patch, approval_id=approval_id, now=utc_now())
        from dataclasses import asdict

        return asdict(limits)

    def verify_trading_audit(self) -> dict[str, Any]:
        from .audit_ledger import verify_audit_chain

        self._require_enabled()
        events = list(self._audit_events)
        if hasattr(self.store, "list_trading_audit_events"):
            stored = self.store.list_trading_audit_events(limit=10_000)
            if stored:
                events = stored
        return verify_audit_chain(events)

    def _shadow_live_runner(self) -> Any:
        if self._shadow_live is None:
            from .shadow_live import ShadowLiveRunner

            self._shadow_live = ShadowLiveRunner(self)
        return self._shadow_live

    def start_shadow_live(
        self,
        *,
        symbol: str,
        provider_id: str = "binance_public",
        strategy_id: str | None = None,
        strategy_version: int | None = None,
    ) -> dict[str, Any]:
        """T13 — Shadow Live: observe current market, decide, NO broker order."""
        self._require_enabled()
        return self._shadow_live_runner().start(
            symbol=symbol,
            now=utc_now(),
            provider_id=provider_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )

    def shadow_live_decide(
        self,
        session_id: str,
        *,
        side: str,
        qty: float,
        rationale: str = "",
    ) -> dict[str, Any]:
        self._require_enabled()
        return self._shadow_live_runner().decide(
            session_id, side=side, qty=qty, now=utc_now(), rationale=rationale
        )

    def shadow_live_attach_outcome(
        self,
        session_id: str,
        decision_id: str,
        *,
        realized_price: float,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        return self._shadow_live_runner().attach_outcome(
            session_id,
            decision_id,
            realized_price=realized_price,
            now=utc_now(),
            detail=detail,
        )

    def get_shadow_live(self, session_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self._shadow_live_runner().get(session_id)

    def compute_strategy_drift(
        self,
        *,
        expected_returns: list[float],
        actual_returns: list[float],
        band: float = 0.05,
    ) -> dict[str, Any]:
        """T15 — paper/shadow vs historical expectation drift."""
        from .lifecycle import compute_performance_drift

        self._require_enabled()
        return compute_performance_drift(
            expected_returns=expected_returns,
            actual_returns=actual_returns,
            band=band,
        )

    def export_trading_training_bridge(
        self,
        decisions: list[dict[str, Any]] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """T16 — export verified trading trajectories into VerifiedExperience."""
        from .training_bridge import export_verified_trading_trajectories

        self._require_enabled()
        items = list(decisions or [])
        if session_id and not items:
            session = self.get_shadow_live(session_id)
            items = list(session.get("decisions") or [])
        return export_verified_trading_trajectories(items)

    def security_posture(self) -> dict[str, Any]:
        """G48 — live flag off by default; TradingStub/LiveBroker refuse."""
        import os

        from .brokers import LiveBroker
        from Data.modules.trading.stub import TradingStub

        live_flag = os.environ.get("LEVIATHAN_FEATURE_TRADING_LIVE", "").strip().lower()
        live_enabled = live_flag in {"1", "true", "yes"}
        stub = TradingStub().place_order(symbol="BTC", side="BUY", quantity=1)
        live = LiveBroker()
        live_status = live.account()
        return {
            "live_flag_env": live_flag or "(unset)",
            "live_feature_enabled": live_enabled,
            "live_trading_available": "BLOCKED",
            "trading_stub_refuses": not stub.accepted,
            "live_broker": live_status.get("status"),
            "live_guard": self.live_guard.public_status(),
            "truth": {
                "live_flag_off_by_default": not live_enabled,
                "no_secret_in_repo": True,
                "live_broker_unsupported": True,
            },
        }

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
        metrics: dict[str, Any] | None = None,
        strategy_version: int | None = None,
        run_id: str | None = None,
        run_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        trials = self.store.list_experiments(limit=500)
        trial = next((t for t in trials if t["trial_id"] == trial_id), None)
        if trial is None:
            raise MarketSimError("TRIAL_NOT_FOUND", trial_id, http_status=404)

        ids: list[str] = []
        seen: set[str] = set()
        for candidate in ([str(run_id)] if run_id else []) + [str(r) for r in (run_ids or []) if r]:
            if candidate and candidate not in seen:
                seen.add(candidate)
                ids.append(candidate)
        if not ids:
            raise MarketSimError(
                "ACCEPTANCE_REQUIRES_RUN_IDS",
                "complete_experiment requires run_id/run_ids for sealed evidence",
                http_status=400,
            )

        # Prefer run-derived metrics over caller-supplied fabrications (G21 / D11).
        run_metrics = self._metrics_from_runs(ids)
        effective = dict(run_metrics)
        if metrics:
            # Caller may annotate extras (features) but core measured keys come from runs.
            for k, v in metrics.items():
                if k not in effective:
                    effective[k] = v

        try:
            seals = self.store.seal_acceptance_runs(ids, trial_id=trial_id)
        except ValueError as exc:
            raise MarketSimError("ACCEPTANCE_SEAL_REUSED", str(exc), http_status=409) from exc

        passed, reason = evaluate_acceptance(
            effective,
            trial.get("acceptance_criteria") or {},
            run_ids=ids,
            require_run_ids=True,
        )
        trial["results"] = {
            **effective,
            "acceptance_run_ids": ids,
            "acceptance_seals": seals,
        }
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
                "features": (effective.get("features") or {}),
                "applicability": (trial.get("config") or {}).get("applicability") or {},
                "outcome_summary": reason if not passed else "accepted on holdout",
                "trial_id": trial_id,
                "available_at": utc_now(),
                "created_at": utc_now(),
                "rejected": not passed,
            }
        )
        return trial

    def _metrics_from_runs(self, run_ids: list[str]) -> dict[str, Any]:
        """Load sealed-evidence metrics from completed simulation runs."""
        if not run_ids:
            raise MarketSimError("ACCEPTANCE_REQUIRES_RUN_IDS", "empty run_ids", http_status=400)
        merged: dict[str, Any] = {"runs": [], "trade_count": {"status": "MEASURED", "value": 0}}
        trades = 0
        returns: list[float] = []
        drawdowns: list[float] = []
        for rid in run_ids:
            run = self.store.get_run(rid)
            if run is None:
                raise MarketSimError("RUN_NOT_FOUND", rid, http_status=404)
            m = dict(run.metrics or {})
            merged["runs"].append({"run_id": rid, "status": run.status, "metrics": m})
            tc = m.get("trade_count")
            if isinstance(tc, dict):
                trades += int(tc.get("value") or 0)
            tr = m.get("total_return")
            if isinstance(tr, dict) and tr.get("value") is not None:
                returns.append(float(tr["value"]))
            dd = m.get("max_drawdown")
            if isinstance(dd, dict) and dd.get("value") is not None:
                drawdowns.append(float(dd["value"]))
            # Carry first run's detailed metrics as base; overwrite with aggregates below.
            for k, v in m.items():
                if k not in merged:
                    merged[k] = v
        merged["trade_count"] = {"status": "MEASURED", "value": trades}
        if returns:
            mean_ret = sum(returns) / len(returns)
            merged["total_return"] = {"status": "MEASURED", "value": mean_ret}
        if drawdowns:
            merged["max_drawdown"] = {"status": "MEASURED", "value": max(drawdowns)}
        if len(run_ids) == 1 and merged["runs"][0]["metrics"]:
            # Single-run: use that run's metrics verbatim (still tagged with run id).
            base = dict(merged["runs"][0]["metrics"])
            base["trade_count"] = merged["trade_count"]
            base["runs"] = merged["runs"]
            return base
        return merged

    def list_experiments(self, *, strategy_id: str | None = None) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_experiments(strategy_id=strategy_id)

    # --- Research campaigns (T7 / G25) ---

    def create_research_campaign(
        self,
        *,
        strategy_id: str,
        hypothesis: str,
        proposer_agent_id: str = "human",
        source_id: str | None = None,
        seed: int = 42,
        config: dict[str, Any] | None = None,
        acceptance_criteria: dict[str, Any] | None = None,
        n_bars: int | None = None,
    ) -> dict[str, Any]:
        from .research_campaign import ResearchCampaignController, new_campaign

        self._require_enabled()
        strat = self.store.get_strategy(strategy_id)
        if strat is None:
            raise MarketSimError("STRATEGY_NOT_FOUND", strategy_id, http_status=404)
        data_hash = ""
        bars_n = n_bars
        if source_id:
            source = self.data.get_source(source_id)
            data_hash = source.content_hash
            if bars_n is None and source.bar_count:
                bars_n = int(source.bar_count)
        campaign = new_campaign(
            strategy_id=strategy_id,
            hypothesis=hypothesis,
            proposer_agent_id=proposer_agent_id,
            source_id=source_id,
            data_hash=data_hash,
            seed=seed,
            config=config,
            acceptance_criteria=acceptance_criteria,
            n_bars=bars_n,
            created_at=utc_now(),
        )
        return ResearchCampaignController(self.store).create(campaign)

    def get_research_campaign(self, campaign_id: str) -> dict[str, Any]:
        from .research_campaign import ResearchCampaignController

        self._require_enabled()
        return ResearchCampaignController(self.store).get(campaign_id)

    def list_research_campaigns(
        self, *, strategy_id: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_research_campaigns(
            strategy_id=strategy_id, status=status, limit=limit
        )

    def start_research_campaign(self, campaign_id: str) -> dict[str, Any]:
        from .research_campaign import ResearchCampaignController

        self._require_enabled()
        return ResearchCampaignController(self.store).start(campaign_id, now=utc_now())

    def pause_research_campaign(self, campaign_id: str) -> dict[str, Any]:
        from .research_campaign import ResearchCampaignController

        self._require_enabled()
        return ResearchCampaignController(self.store).pause(campaign_id, now=utc_now())

    def resume_research_campaign(self, campaign_id: str) -> dict[str, Any]:
        from .research_campaign import ResearchCampaignController

        self._require_enabled()
        return ResearchCampaignController(self.store).resume(campaign_id, now=utc_now())

    def advance_research_campaign(
        self, campaign_id: str, *, trial_id: str | None = None
    ) -> dict[str, Any]:
        from .research_campaign import ResearchCampaignController

        self._require_enabled()
        return ResearchCampaignController(self.store).advance(
            campaign_id, now=utc_now(), trial_id=trial_id
        )

    def cancel_research_campaign(self, campaign_id: str) -> dict[str, Any]:
        from .research_campaign import ResearchCampaignController

        self._require_enabled()
        return ResearchCampaignController(self.store).cancel(campaign_id, now=utc_now())

    # --- TradingGym / scorecards / readiness / export / gap (T8) ---

    def _gym_sessions(self) -> dict[str, Any]:
        sessions = getattr(self, "_gym_session_map", None)
        if sessions is None:
            sessions = {}
            self._gym_session_map = sessions
        return sessions

    def create_gym_episode(
        self,
        *,
        bars_path: str | None = None,
        source_id: str | None = None,
        curriculum_stage: str = "trend",
        seed: int = 42,
        start_index: int = 0,
        end_index: int | None = None,
        initial_cash: float = 100_000.0,
        dataset_id: str | None = None,
        dataset_version: str | None = None,
    ) -> dict[str, Any]:
        from .gym import (
            can_enter_curriculum_stage,
            load_gym_from_path,
            new_episode_spec,
        )

        self._require_enabled()
        dataset = None
        if dataset_id and dataset_version:
            dataset = self.store.get_dataset_version(dataset_id, dataset_version)
            from .gym import assert_not_sealed_dataset

            assert_not_sealed_dataset(dataset)

        path = bars_path
        symbol = ""
        timeframe = "1h"
        data_hash = ""
        if source_id:
            source = self.data.get_source(source_id)
            path = str(self.data.markets_root / source.relative_path)
            symbol = source.symbol or ""
            timeframe = source.timeframe or "1h"
            data_hash = source.content_hash or ""
        if not path:
            raise MarketSimError("GYM_BARS_REQUIRED", "bars_path or source_id required")

        # Curriculum gating from prior completed episodes.
        prior = None
        eps = self.store.list_gym_episodes(limit=20)
        completed_stages = {e["curriculum_stage"] for e in eps if e.get("status") == "completed"}
        if completed_stages:
            # Highest completed stage by catalog order.
            from .gym import CURRICULUM_STAGES

            for stage in reversed(CURRICULUM_STAGES):
                if stage in completed_stages:
                    prior = stage
                    break
        if not can_enter_curriculum_stage(prior, curriculum_stage):
            raise MarketSimError(
                "CURRICULUM_GATED",
                f"Cannot enter stage {curriculum_stage!r} from prior {prior!r}",
                http_status=409,
            )

        spec = new_episode_spec(
            bars_path=path,
            data_hash=data_hash,
            source_id=source_id,
            curriculum_stage=curriculum_stage,
            seed=seed,
            start_index=start_index,
            end_index=end_index,
            initial_cash=initial_cash,
            timeframe=timeframe,
            symbol=symbol,
            created_at=utc_now(),
            dataset=dataset,
        )
        self.store.save_gym_episode_spec(spec.public_dict())
        gym = load_gym_from_path(spec, store=self.store)
        obs = gym.reset()
        self._gym_sessions()[gym.episode_id] = gym
        return {
            "episode": gym.episode_public_dict(),
            "observation": obs.public_dict(),
            "spec": spec.public_dict(),
        }

    def gym_step(self, episode_id: str, *, action: str) -> dict[str, Any]:
        self._require_enabled()
        gym = self._gym_sessions().get(episode_id)
        if gym is None:
            raise MarketSimError("GYM_EPISODE_NOT_ACTIVE", episode_id, http_status=404)
        result = gym.step(action)
        return {
            "episode": gym.episode_public_dict(),
            **result.public_dict(),
        }

    def get_gym_episode(self, episode_id: str) -> dict[str, Any]:
        self._require_enabled()
        gym = self._gym_sessions().get(episode_id)
        if gym is not None:
            return gym.episode_public_dict()
        row = self.store.get_gym_episode(episode_id)
        if row is None:
            raise MarketSimError("GYM_EPISODE_NOT_FOUND", episode_id, http_status=404)
        return row

    def list_gym_curriculum(self) -> list[dict[str, Any]]:
        self._require_enabled()
        rows = self.store.list_curriculum_stages()
        if rows:
            return rows
        from .gym import curriculum_catalog

        return curriculum_catalog()

    def create_agent_scorecard(
        self,
        *,
        agent_id: str,
        equity: list[float],
        agent_version: str = "v1",
        regime: str = "all",
        year: int | None = None,
        violations: dict[str, int] | None = None,
        token_cost: int = 0,
        latency_ms: float = 0.0,
        n_episodes: int = 1,
        timeframe: str = "1h",
    ) -> dict[str, Any]:
        from .scorecards import build_agent_scorecard

        self._require_enabled()
        card = build_agent_scorecard(
            agent_id=agent_id,
            agent_version=agent_version,
            equity=equity,
            regime=regime,
            year=year,
            violations=violations,
            token_cost=token_cost,
            latency_ms=latency_ms,
            n_episodes=n_episodes,
            timeframe=timeframe,
            created_at=utc_now(),
        )
        payload = card.public_dict()
        self.store.save_agent_scorecard(payload)
        return payload

    def list_agent_scorecards(
        self, *, agent_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_agent_scorecards(agent_id=agent_id, limit=limit)

    def get_agent_readiness(self, agent_id: str) -> dict[str, Any]:
        from .scorecards import readiness_public_dict

        self._require_enabled()
        row = self.store.get_agent_readiness(agent_id)
        if row is not None:
            return {**readiness_public_dict(
                agent_id=agent_id,
                level=row["level"],
                measurement=row.get("measurement") or "UNMEASURED",
                reason=row.get("reason") or "",
                updated_at=row.get("updated_at") or "",
            ), "evidence": row.get("evidence") or {}}
        return readiness_public_dict(agent_id=agent_id, level="A0", measurement="UNMEASURED")

    def set_agent_readiness(
        self,
        agent_id: str,
        *,
        level: str,
        measurement: str = "UNMEASURED",
        reason: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .scorecards import can_advance_readiness, parse_readiness_level, readiness_public_dict

        self._require_enabled()
        current = self.store.get_agent_readiness(agent_id)
        cur_level = (current or {}).get("level") or "A0"
        decision = can_advance_readiness(
            cur_level, level, evidence={"measurement": measurement, **(evidence or {})}
        )
        if not decision["allowed"]:
            raise MarketSimError(
                "READINESS_ADVANCE_BLOCKED",
                ",".join(decision["reasons"]),
                http_status=409,
            )
        parsed = parse_readiness_level(level)
        now = utc_now()
        saved = self.store.save_agent_readiness(
            {
                "agent_id": agent_id,
                "level": parsed.value,
                "measurement": measurement,
                "reason": reason,
                "evidence": evidence or {},
                "updated_at": now,
            }
        )
        return {
            **readiness_public_dict(
                agent_id=agent_id,
                level=parsed.value,
                measurement=measurement,
                reason=reason,
                updated_at=now,
            ),
            "evidence": saved.get("evidence") or {},
            "decision": decision,
        }

    def export_gym_trajectory(
        self,
        episode_id: str,
        *,
        dest_path: str | None = None,
        sealed_windows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from pathlib import Path

        from .trajectory_export import (
            build_preference_pairs,
            build_trajectory_records,
            export_trajectories_jsonl,
        )

        self._require_enabled()
        episode = self.get_gym_episode(episode_id)
        if episode.get("status") != "completed":
            raise MarketSimError(
                "EPISODE_NOT_VERIFIED",
                "Only completed episodes export verified trajectories",
                http_status=409,
            )
        records = build_trajectory_records(episode, verified=True)
        pairs = build_preference_pairs(records)
        root = Path(dest_path) if dest_path else (self.data.markets_root.parent / "gym_exports")
        dest = root / f"trajectory-{episode_id}.jsonl"
        exported = export_trajectories_jsonl(
            records, dest, sealed_windows=sealed_windows
        )
        traj_id = str(__import__("uuid").uuid4())
        saved = {
            "trajectory_id": traj_id,
            "episode_id": episode_id,
            "path": exported["path"],
            "content_hash": exported["content_hash"],
            "record_count": exported["record_count"],
            "contamination": exported["contamination"],
            "preference_pairs": len(pairs),
            "created_at": utc_now(),
            "truth": exported["truth"],
        }
        self.store.save_training_trajectory(saved)
        return saved

    def create_sim_real_gap_report(
        self,
        *,
        sim_fills: list[dict[str, Any]],
        paper_fills: list[dict[str, Any]],
        calibration_source_ids: list[str] | None = None,
        evaluation_source_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from .sim_real_gap import compute_sim_real_gap

        self._require_enabled()
        report = compute_sim_real_gap(
            sim_fills=sim_fills,
            paper_fills=paper_fills,
            calibration_source_ids=calibration_source_ids,
            evaluation_source_ids=evaluation_source_ids,
            created_at=utc_now(),
        )
        self.store.save_sim_real_gap_report(report)
        return report

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

