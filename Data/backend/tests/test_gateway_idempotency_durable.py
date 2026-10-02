"""Durable request-bound idempotency for ExecutionGateway (Phase 1.4)."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    SideEffect,
    build_default_catalog,
    execution_fingerprint,
)
from Data.modules.execution.idempotency import CapabilityIdempotencyStore
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore


class _CountingArtifactWriter:
    """Wraps ArtifactStore.create_from_bytes and counts invocations."""

    def __init__(self, inner: ArtifactStore) -> None:
        self.inner = inner
        self.calls = 0
        self._lock = threading.Lock()
        self.hold = threading.Event()
        self.entered = threading.Event()
        self.block_once = False

    def create_from_bytes(self, **kwargs: Any) -> Any:
        with self._lock:
            self.calls += 1
        if self.block_once:
            self.entered.set()
            self.hold.wait(timeout=5)
        return self.inner.create_from_bytes(**kwargs)


class GatewayDurableIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "idem.db"
        self.artifacts = ArtifactStore(self.db_path, self.root / "artifacts")
        self.artifacts.initialize()
        self.writer = _CountingArtifactWriter(self.artifacts)
        self.knowledge = KnowledgeStore(
            self.db_path,
            data_root=self.root / "corpus",
            chunk_max_chars=400,
            chunk_overlap=40,
        )
        self.knowledge.initialize()
        (self.root / "corpus").mkdir(parents=True, exist_ok=True)
        self.runtime = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db_path), PolicyEngine())
        self.approvals.store.initialize()
        self.observations = ObservationStore(self.db_path)
        self.observations.initialize()
        self.idem = CapabilityIdempotencyStore(self.db_path)
        self.idem.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.writer,
            approval_checker=self.approvals,
            observation_store=self.observations,
            idempotency_store=self.idem,
        )

    def tearDown(self) -> None:
        self.runtime.shutdown()
        self.tmp.cleanup()

    def _approve(self, *, arguments: dict[str, Any] | None = None) -> str:
        pending = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="test",
            arguments=arguments,
        )
        self.approvals.approve(pending.approval_id, decided_by="ops")
        return pending.approval_id

    def test_a_same_key_same_fingerprint_replays_terminal_success(self) -> None:
        args = {"content": "same", "filename": "a.txt"}
        approval_id = self._approve(arguments=args)
        key = "idem-a"
        first = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments=dict(args),
                approval_id=approval_id,
                idempotency_key=key,
            )
        )
        self.assertEqual(first.status, CapabilityStatus.COMPLETED)
        second = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments=dict(args),
                approval_id=approval_id,
                idempotency_key=key,
            )
        )
        self.assertEqual(second.status, CapabilityStatus.COMPLETED)
        self.assertTrue(second.telemetry.get("idempotent_replay"))
        self.assertEqual(self.writer.calls, 1)

    def test_b_same_key_same_fingerprint_in_flight_returns_identity(self) -> None:
        args = {"content": "inflight", "filename": "b.txt"}
        approval_id = self._approve(arguments=args)
        key = "idem-b"
        self.writer.block_once = True
        self.writer.hold.clear()
        self.writer.entered.clear()
        results: list[Any] = []

        def run() -> None:
            results.append(
                self.gateway.execute(
                    CapabilityRequest(
                        capability_id="artifact.create_text",
                        arguments=dict(args),
                        approval_id=approval_id,
                        idempotency_key=key,
                        request_id="req-inflight-1",
                    )
                )
            )

        t = threading.Thread(target=run)
        t.start()
        self.assertTrue(self.writer.entered.wait(timeout=3))
        # While first is in flight, second must not execute.
        second = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments=dict(args),
                approval_id=approval_id,
                idempotency_key=key,
                request_id="req-inflight-2",
            )
        )
        self.assertEqual(second.status, CapabilityStatus.REJECTED)
        self.assertEqual(second.telemetry.get("reason"), "idempotency_in_flight")
        self.assertEqual(second.telemetry.get("in_flight_request_id"), "req-inflight-1")
        self.writer.hold.set()
        t.join(timeout=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CapabilityStatus.COMPLETED)
        self.assertEqual(self.writer.calls, 1)

    def test_c_same_key_different_fingerprint_hard_conflict(self) -> None:
        args1 = {"content": "one", "filename": "c1.txt"}
        args2 = {"content": "two", "filename": "c2.txt"}
        approval_id = self._approve(arguments=args1)
        key = "idem-c"
        first = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments=dict(args1),
                approval_id=approval_id,
                idempotency_key=key,
            )
        )
        self.assertEqual(first.status, CapabilityStatus.COMPLETED)
        # Fresh approval for second args (first approval consumed).
        approval2 = self._approve(arguments=args2)
        conflict = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments=dict(args2),
                approval_id=approval2,
                idempotency_key=key,
            )
        )
        self.assertEqual(conflict.status, CapabilityStatus.REJECTED)
        self.assertEqual(conflict.telemetry.get("reason"), "idempotency_conflict")
        self.assertEqual(self.writer.calls, 1)

    def test_d_durable_unavailable_side_effects_fail_closed(self) -> None:
        gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime,
            artifact_store=self.writer,
            approval_checker=self.approvals,
            observation_store=None,
            idempotency_store=None,
        )
        args = {"content": "fail-closed", "filename": "d.txt"}
        approval_id = self._approve(arguments=args)
        result = gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments=dict(args),
                approval_id=approval_id,
                idempotency_key="idem-d",
            )
        )
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertEqual(result.telemetry.get("reason"), "idempotency_authority_unavailable")
        self.assertEqual(self.writer.calls, 0)

    def test_e_concurrent_duplicates_exactly_one_side_effect(self) -> None:
        args = {"content": "race", "filename": "e.txt"}
        approval_id = self._approve(arguments=args)
        key = "idem-e"
        barrier = threading.Barrier(8)
        results: list[Any] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait(timeout=5)
            out = self.gateway.execute(
                CapabilityRequest(
                    capability_id="artifact.create_text",
                    arguments=dict(args),
                    approval_id=approval_id,
                    idempotency_key=key,
                )
            )
            with lock:
                results.append(out)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(results), 8)
        completed = [r for r in results if r.status == CapabilityStatus.COMPLETED]
        # Exactly one real execution; others replay or in-flight reject then may replay.
        self.assertEqual(self.writer.calls, 1)
        self.assertGreaterEqual(len(completed), 1)
        # Terminal success can only reflect the single artifact write.
        success_ids = {
            (r.output or {}).get("artifact_id") or (r.output or {}).get("id")
            for r in completed
            if r.output
        }
        self.assertEqual(len(success_ids - {None}), 1)

    def test_f_process_restart_still_valid_via_db(self) -> None:
        args = {"content": "durable", "filename": "f.txt"}
        approval_id = self._approve(arguments=args)
        key = "idem-f"
        first = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments=dict(args),
                approval_id=approval_id,
                idempotency_key=key,
            )
        )
        self.assertEqual(first.status, CapabilityStatus.COMPLETED)
        gateway2 = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.writer,
            approval_checker=self.approvals,
            observation_store=ObservationStore(self.db_path),
            idempotency_store=CapabilityIdempotencyStore(self.db_path),
        )
        replay = gateway2.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments=dict(args),
                approval_id=approval_id,
                idempotency_key=key,
            )
        )
        self.assertEqual(replay.status, CapabilityStatus.COMPLETED)
        self.assertTrue(replay.telemetry.get("idempotent_replay"))
        self.assertEqual(replay.telemetry.get("idempotent_replay_source"), "capability_idempotency")
        self.assertEqual(self.writer.calls, 1)

    def test_fingerprint_stable_and_sensitive(self) -> None:
        a = CapabilityRequest(
            capability_id="artifact.create_text",
            arguments={"content": "x", "filename": "f.txt"},
            requested_by="api",
            approval_id="appr-1",
        )
        b = CapabilityRequest(
            capability_id="artifact.create_text",
            arguments={"content": "x", "filename": "f.txt"},
            requested_by="api",
            approval_id="appr-1",
        )
        c = CapabilityRequest(
            capability_id="artifact.create_text",
            arguments={"content": "y", "filename": "f.txt"},
            requested_by="api",
            approval_id="appr-1",
        )
        self.assertEqual(execution_fingerprint(a), execution_fingerprint(b))
        self.assertNotEqual(execution_fingerprint(a), execution_fingerprint(c))


class AtomicApprovalReservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "appr.db"
        self.artifacts = ArtifactStore(self.db_path, self.root / "artifacts")
        self.artifacts.initialize()
        self.writer = _CountingArtifactWriter(self.artifacts)
        self.runtime = FunctionRuntime(build_default_registry(), max_concurrency=4, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db_path), PolicyEngine())
        self.approvals.store.initialize()
        self.observations = ObservationStore(self.db_path)
        self.observations.initialize()
        self.idem = CapabilityIdempotencyStore(self.db_path)
        self.idem.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime,
            artifact_store=self.writer,
            approval_checker=self.approvals,
            observation_store=self.observations,
            idempotency_store=self.idem,
        )

    def tearDown(self) -> None:
        self.runtime.shutdown()
        self.tmp.cleanup()

    def test_race_only_one_thread_reaches_provider(self) -> None:
        args = {"content": "once", "filename": "race.txt"}
        pending = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="test",
            arguments=args,
            single_use=True,
        )
        self.approvals.approve(pending.approval_id, decided_by="ops")
        barrier = threading.Barrier(12)
        results: list[Any] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            barrier.wait(timeout=5)
            out = self.gateway.execute(
                CapabilityRequest(
                    capability_id="artifact.create_text",
                    arguments=dict(args),
                    approval_id=pending.approval_id,
                    idempotency_key=f"appr-race-{i}",
                )
            )
            with lock:
                results.append(out)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(self.writer.calls, 1)
        completed = [r for r in results if r.status == CapabilityStatus.COMPLETED]
        rejected = [r for r in results if r.status == CapabilityStatus.REJECTED]
        self.assertEqual(len(completed), 1)
        self.assertEqual(len(rejected), 11)
        record = self.approvals.get(pending.approval_id)
        assert record is not None
        from Data.modules.approvals import ApprovalStatus

        self.assertEqual(record.status, ApprovalStatus.CONSUMED)


class PlanHashDoesNotGrantPrivilegeTests(unittest.TestCase):
    def test_plan_hash_alone_does_not_allow_system_deps(self) -> None:
        from Data.modules.module_manager.external.executor import ExternalModuleExecutor

        seen: dict[str, Any] = {}

        class _Mgr:
            def install(self, module_id: str, **kwargs: Any) -> dict[str, Any]:
                seen["allow_system_deps"] = kwargs.get("allow_system_deps")
                seen["module_id"] = module_id
                return {"ok": True, "module_id": module_id}

            def register_job(self, *a: Any, **k: Any) -> None:
                return None

            def unregister_job(self, *a: Any, **k: Any) -> None:
                return None

        executor = ExternalModuleExecutor(_Mgr())  # type: ignore[arg-type]
        result = executor.execute_module_capability(
            "external.module.install",
            "external.module.install",
            {
                "module_id": "demo-mod",
                "plan_hash": "deadbeef" * 8,
                "allow_system_deps": True,  # client-supplied — must be ignored
            },
            request_id="r1",
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        self.assertFalse(seen.get("allow_system_deps"))

        seen.clear()
        result2 = executor.execute_module_capability(
            "external.module.install",
            "external.module.install",
            {
                "module_id": "demo-mod",
                "plan_hash": "deadbeef" * 8,
                "_trusted_authority": {"allow_system_deps": True, "approval_id": "a1"},
            },
            request_id="r2",
        )
        self.assertEqual(result2.status, CapabilityStatus.COMPLETED)
        self.assertTrue(seen.get("allow_system_deps"))

    def test_gateway_strips_client_allow_system_deps_without_operator_grant(self) -> None:
        """Client allow_system_deps + approved approval must NOT elevate without operator grant."""
        from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
        from Data.modules.execution import (
            CapabilityCatalog,
            CapabilityDefinition,
            CapabilityProviderKind,
            CapabilityRequest,
            CapabilityStatus,
            ExecutionGateway,
            SideEffect,
        )
        from Data.modules.module_manager.external.executor import ExternalModuleExecutor

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "a.db"
            store = ApprovalStore(db)
            service = ApprovalService(store, PolicyEngine())
            seen: dict[str, Any] = {}

            class _Mgr:
                def install(self, module_id: str, **kwargs: Any) -> dict[str, Any]:
                    seen["allow_system_deps"] = kwargs.get("allow_system_deps")
                    return {"ok": True, "module_id": module_id}

                def register_job(self, *a: Any, **k: Any) -> None:
                    return None

                def unregister_job(self, *a: Any, **k: Any) -> None:
                    return None

                def get(self, module_id: str) -> None:
                    return None

                def ensure_ready(self, module_id: str) -> dict[str, Any]:
                    return {"ready": True}

                def execute(self, *a: Any, **k: Any) -> Any:
                    raise AssertionError("install path should not call execute")

            catalog = CapabilityCatalog()
            catalog.register(
                CapabilityDefinition(
                    id="external.module.install",
                    name="install",
                    description="install",
                    side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
                    provider_kind=CapabilityProviderKind.MODULE,
                    provider_ref="external.module.install",
                    input_schema={"type": "object", "additionalProperties": True},
                    output_schema={"type": "object"},
                    available=True,
                    enabled=True,
                    metadata={"execution_class": "INLINE_SAFE"},
                )
            )
            gateway = ExecutionGateway(
                catalog,
                module_executor=ExternalModuleExecutor(_Mgr()),  # type: ignore[arg-type]
                approval_checker=service,
            )
            approval = service.request(
                capability_id="external.module.install",
                side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
                arguments={
                    "module_id": "demo-mod",
                    "plan_hash": "deadbeef" * 8,
                    # Even if client tried to put allow_system_deps in args, gateway strips it.
                },
            )
            # Approve WITHOUT operator grant.
            service.approve(approval.approval_id, decided_by="operator", allow_system_deps=False)
            result = gateway.execute(
                CapabilityRequest(
                    capability_id="external.module.install",
                    arguments={
                        "module_id": "demo-mod",
                        "plan_hash": "deadbeef" * 8,
                        "allow_system_deps": True,  # forge attempt
                    },
                    approval_id=approval.approval_id,
                )
            )
            self.assertEqual(result.status, CapabilityStatus.COMPLETED)
            self.assertFalse(seen.get("allow_system_deps"))

            # Fresh approval with operator grant.
            seen.clear()
            approval2 = service.request(
                capability_id="external.module.install",
                side_effects=(SideEffect.EXECUTE, SideEffect.WRITE),
                arguments={"module_id": "demo-mod", "plan_hash": "deadbeef" * 8},
            )
            service.approve(approval2.approval_id, decided_by="operator", allow_system_deps=True)
            result2 = gateway.execute(
                CapabilityRequest(
                    capability_id="external.module.install",
                    arguments={"module_id": "demo-mod", "plan_hash": "deadbeef" * 8},
                    approval_id=approval2.approval_id,
                )
            )
            self.assertEqual(result2.status, CapabilityStatus.COMPLETED)
            self.assertTrue(seen.get("allow_system_deps"))


class CanonicalModuleInvokePipelineTests(unittest.TestCase):
    def test_executor_forwards_cancel_progress_through_module_manager(self) -> None:
        from Data.modules.module_manager.external.executor import ExternalModuleExecutor
        from Data.modules.module_manager.types import ModuleResult

        seen: dict[str, Any] = {}

        class _Mgr:
            def ensure_ready(self, module_id: str) -> dict[str, Any]:
                return {"ready": True}

            def register_job(self, *a: Any, **k: Any) -> None:
                return None

            def unregister_job(self, *a: Any, **k: Any) -> None:
                return None

            def get(self, module_id: str) -> None:
                return None

            def execute(
                self,
                module_id: str,
                operation: str,
                arguments: Any = None,
                *,
                cancel_check: Any = None,
                progress: Any = None,
                expected_generation: Any = None,
            ) -> ModuleResult:
                seen["cancel_check"] = cancel_check
                seen["progress"] = progress
                seen["via"] = "module_manager.execute"
                return ModuleResult(
                    module_id=module_id,
                    operation=operation,
                    status="COMPLETED",
                    output={"ok": True},
                )

        executor = ExternalModuleExecutor(_Mgr())  # type: ignore[arg-type]
        cancel = lambda: False  # noqa: E731
        progress = lambda **kw: None  # noqa: E731
        result = executor.execute_module_capability(
            "mod.op",
            "module:demo",
            {"x": 1},
            request_id="r1",
            cancel_check=cancel,
            progress=progress,
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        self.assertEqual(seen.get("via"), "module_manager.execute")
        self.assertIs(seen.get("cancel_check"), cancel)
        self.assertIs(seen.get("progress"), progress)


if __name__ == "__main__":
    unittest.main()
