"""LEVIATHAN Signal Fabric — store, router, service, security, worker tests."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.agents import (
    AgentBlackboard,
    AgentFleetService,
    AgentFleetStore,
    AgentRuntime,
)
from Data.modules.agents.signals import (
    SignalFabricService,
    SignalStore,
    SignalType,
)
from Data.modules.agents.signals.envelope import AgentSignalDelivery
from Data.modules.agents.signals.policies import SignalAuthorizationPolicy, SignalPolicyError
from Data.modules.agents.signals.router import SignalRouter, SignalRouterError
from Data.modules.agents.signals.service import SignalFabricError
from Data.modules.agents.signals.types import (
    DeliveryState,
    RecipientType,
    SenderType,
    SignalPriority,
)
from Data.modules.analytics import AnalyticsService
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.memory import MemoryStore
from Data.modules.observations import ObservationStore
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


class SignalFabricBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "signals.db"
        MigrationRunner(self.db).apply_all()
        artifacts = ArtifactStore(self.db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(self.db, data_root=root / "corpus", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "corpus").mkdir(parents=True, exist_ok=True)
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        approvals.store.initialize()
        self.approvals = approvals
        obs = ObservationStore(self.db)
        obs.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
        )
        self.runtime = AgentRuntime(gateway=self.gateway, agents_enabled=True)
        self.fleet = AgentFleetService(AgentFleetStore(self.db), self.runtime)
        self.fleet.initialize(seed_defaults=True)
        self.store = SignalStore(self.db)
        self.store.initialize()
        self.fabric = SignalFabricService(
            self.store,
            fleet=self.fleet,
            enabled=True,
        )
        self.fleet.bind_signal_fabric(self.fabric)
        self.memory = MemoryStore(self.db)
        self.memory.initialize()
        self.fabric.bind_memory_store(self.memory)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def _agent(self, kind: str = "research"):
        return next(a for a in self.fleet.list_agents() if a.kind.value == kind)


class SignalStoreTests(SignalFabricBase):
    def test_migration_creates_tables(self) -> None:
        with self.store.connect() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        for name in (
            "agent_signals",
            "agent_signal_deliveries",
            "agent_signal_subscriptions",
            "agent_signal_dead_letters",
            "agent_signal_dedupe",
        ):
            self.assertIn(name, tables)

    def test_persist_list_filter(self) -> None:
        research = self._agent("research")
        coding = self._agent("coding")
        sig = self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=coding.agent_id,
            subject="finding A",
            payload={"claim": "x"},
            confidence=0.9,
            enqueue_delivery_job=False,
        )
        listed = self.store.list_signals(sender_id=research.agent_id, signal_type="FINDING")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].signal_id, sig.signal_id)

    def test_multi_recipient_mission_routing(self) -> None:
        orch = self._agent("orchestrator")
        mission = self.fleet.launch_mission(
            agent_id=orch.agent_id,
            request="plan",
            dry_run=True,
        )
        # Create a child so mission routing has multiple participants.
        child = self.fleet.launch_mission(
            agent_id=self._agent("research").agent_id,
            request="child",
            dry_run=True,
            parent_mission_id=mission.mission_id,
        )
        self.assertTrue(child.parent_mission_id)
        resolved = SignalRouter(self.fleet).resolve(
            recipient_type=RecipientType.MISSION,
            recipient_id=mission.mission_id,
            mission_id=mission.mission_id,
        )
        self.assertGreaterEqual(len(resolved), 1)

    def test_idempotency(self) -> None:
        research = self._agent("research")
        coding = self._agent("coding")
        a = self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=coding.agent_id,
            subject="once",
            idempotency_key="mission:node:finding",
            enqueue_delivery_job=False,
        )
        b = self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=coding.agent_id,
            subject="twice",
            idempotency_key="mission:node:finding",
            enqueue_delivery_job=False,
        )
        self.assertEqual(a.signal_id, b.signal_id)

    def test_concurrent_claim_safety(self) -> None:
        research = self._agent("research")
        coding = self._agent("coding")
        sig = self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=coding.agent_id,
            subject="claim-race",
            enqueue_delivery_job=False,
        )
        # Create extra pending deliveries manually for race.
        for _ in range(5):
            self.store.create_delivery(
                AgentSignalDelivery(
                    delivery_id=SignalStore.new_id("sdel"),
                    signal_id=sig.signal_id,
                    recipient_type=RecipientType.AGENT,
                    recipient_id=coding.agent_id,
                    resolved_agent_id=coding.agent_id,
                    state=DeliveryState.PENDING,
                )
            )
        claimed_ids: list[str] = []
        lock = threading.Lock()

        def worker(wid: str) -> None:
            got = self.store.claim_pending_deliveries(worker_id=wid, limit=10)
            with lock:
                claimed_ids.extend(d.delivery_id for d in got)

        threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(claimed_ids), len(set(claimed_ids)))


class SignalRouterTests(SignalFabricBase):
    def test_direct_role_capability_orchestrator(self) -> None:
        router = SignalRouter(self.fleet)
        research = self._agent("research")
        direct = router.resolve(
            recipient_type=RecipientType.AGENT,
            recipient_id=research.agent_id,
        )
        self.assertEqual(direct[0].resolved_agent_id, research.agent_id)

        # Role routing — research role
        role = router.resolve(recipient_type=RecipientType.ROLE, recipient_id="Information")
        self.assertTrue(role[0].resolved_agent_id)

        # Capability routing
        cap = router.resolve(
            recipient_type=RecipientType.CAPABILITY,
            recipient_id="knowledge.search",
        )
        self.assertTrue(cap[0].resolved_agent_id)

        orch = router.resolve(recipient_type=RecipientType.ORCHESTRATOR, recipient_id="orchestrator")
        self.assertTrue(orch[0].resolved_agent_id)

    def test_no_eligible_capability(self) -> None:
        router = SignalRouter(self.fleet)
        with self.assertRaises(SignalRouterError):
            router.resolve(
                recipient_type=RecipientType.CAPABILITY,
                recipient_id="totally.missing.capability.zzz",
            )

    def test_disabled_agent_direct_rejected(self) -> None:
        research = self._agent("research")
        self.fleet.set_enabled(research.agent_id, False)
        router = SignalRouter(self.fleet)
        with self.assertRaises(SignalRouterError):
            router.resolve(recipient_type=RecipientType.AGENT, recipient_id=research.agent_id)

    def test_deterministic_capability_tiebreak(self) -> None:
        router = SignalRouter(self.fleet)
        a = router.resolve(
            recipient_type=RecipientType.CAPABILITY,
            recipient_id="knowledge.search",
        )
        b = router.resolve(
            recipient_type=RecipientType.CAPABILITY,
            recipient_id="knowledge.search",
        )
        self.assertEqual(a[0].resolved_agent_id, b[0].resolved_agent_id)


class SignalSecurityTests(SignalFabricBase):
    def test_unauthorized_block_rejected(self) -> None:
        research = self._agent("research")
        with self.assertRaises(SignalFabricError) as ctx:
            self.fabric.publish(
                signal_type=SignalType.BLOCK,
                sender_type=SenderType.AGENT,
                sender_id=research.agent_id,
                recipient_type=RecipientType.AGENT,
                recipient_id=self._agent("coding").agent_id,
                subject="block",
                payload={"targetMissionId": "x"},
                enqueue_delivery_job=False,
            )
        self.assertEqual(ctx.exception.code, "SIGNAL_UNAUTHORIZED")

    def test_http_spoofed_sender_no_authority(self) -> None:
        with self.assertRaises(SignalFabricError):
            self.fabric.publish_http(
                {
                    "signalType": "BLOCK",
                    "senderId": "RiskAgent",
                    "recipientType": "AGENT",
                    "recipientId": self._agent("coding").agent_id,
                    "subject": "spoof",
                },
                operator=False,
            )

    def test_worker_mesh_forbidden(self) -> None:
        policy = SignalAuthorizationPolicy()
        with self.assertRaises(SignalPolicyError):
            policy.authorize_publish(
                signal_type=SignalType.FINDING,
                sender_type=SenderType.WORKER,
                sender_id="w1",
                recipient_type=RecipientType.WORKER,
                recipient_id="w2",
                system=False,
            )

    def test_signal_does_not_bypass_gateway(self) -> None:
        """Informational signals must not grant ExecutionGateway approvals."""
        research = self._agent("research")
        run_id = "run_bb_1"
        board = AgentBlackboard(run_id=run_id)
        self.fabric.register_blackboard(run_id, board)
        sig = self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=self._agent("coding").agent_id,
            subject="obs",
            payload={"claim": "safe"},
            run_id=run_id,
            confidence=0.8,
            enqueue_delivery_job=True,
        )
        self.assertTrue(sig.signal_id)
        # Signal Fabric never injects approval tokens — WRITE still gated.
        from Data.modules.function_runtime.types import SideEffect

        self.assertFalse(
            self.approvals.is_approved(
                "signal-fabric-forged",
                capability_id="file.write",
                side_effects=(SideEffect.WRITE,),
            )
        )
        self.assertTrue(sig.public_dict()["truth"]["side_effects_via_gateway_only"])
        self.assertTrue(sig.public_dict()["truth"]["signal_is_not_authority"])


class SignalLoopBudgetTests(SignalFabricBase):
    def test_max_hops(self) -> None:
        research = self._agent("research")
        with self.assertRaises(SignalFabricError) as ctx:
            self.fabric.publish(
                signal_type=SignalType.FINDING,
                sender_type=SenderType.AGENT,
                sender_id=research.agent_id,
                recipient_type=RecipientType.AGENT,
                recipient_id=self._agent("coding").agent_id,
                subject="hop",
                hop_count=8,
                max_hops=8,
                enqueue_delivery_job=False,
            )
        self.assertIn(ctx.exception.code, {"SIGNAL_MAX_HOPS", "MAX_HOPS_EXCEEDED"})

    def test_signal_budget(self) -> None:
        research = self._agent("research")
        coding = self._agent("coding")
        mission = self.fleet.launch_mission(
            agent_id=research.agent_id,
            request="budget",
            dry_run=True,
            metadata={"maxSignals": 3},
        )
        for i in range(3):
            self.fabric.publish(
                signal_type=SignalType.FINDING,
                sender_type=SenderType.AGENT,
                sender_id=research.agent_id,
                recipient_type=RecipientType.AGENT,
                recipient_id=coding.agent_id,
                subject=f"b{i}",
                mission_id=mission.mission_id,
                enqueue_delivery_job=False,
            )
        with self.assertRaises(SignalFabricError) as ctx:
            self.fabric.publish(
                signal_type=SignalType.FINDING,
                sender_type=SenderType.AGENT,
                sender_id=research.agent_id,
                recipient_type=RecipientType.AGENT,
                recipient_id=coding.agent_id,
                subject="overflow",
                mission_id=mission.mission_id,
                enqueue_delivery_job=False,
            )
        self.assertEqual(ctx.exception.code, "SIGNAL_BUDGET_EXCEEDED")


class SignalTaskHandoffTests(SignalFabricBase):
    def test_handoff_creates_one_mission_idempotent(self) -> None:
        orch = self._agent("orchestrator")
        coding = self._agent("coding")
        parent = self.fleet.launch_mission(
            agent_id=orch.agent_id,
            request="parent work",
            dry_run=True,
        )
        key = f"{parent.mission_id}:node_1:handoff"
        sig = self.fabric.publish(
            signal_type=SignalType.TASK_HANDOFF,
            sender_type=SenderType.AGENT,
            sender_id=orch.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=coding.agent_id,
            subject="handoff coding",
            payload={"request": "implement X", "dryRun": True},
            mission_id=parent.mission_id,
            trace_id=parent.trace_id,
            idempotency_key=key,
            enqueue_delivery_job=True,
        )
        # Second delivery of same signal action
        deliveries = self.store.list_deliveries(signal_id=sig.signal_id)
        self.assertTrue(deliveries)
        for d in deliveries:
            self.fabric.process_delivery(d.delivery_id, worker_id="test")
        # Force duplicate handler invocation
        for d in deliveries:
            self.fabric.process_delivery(d.delivery_id, worker_id="test2")

        children = [
            m
            for m in self.fleet.store.list_missions(limit=100)
            if m.parent_mission_id == parent.mission_id
            and (m.metadata or {}).get("signalFabricKey") == key
        ]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].trace_id or parent.trace_id, parent.trace_id or children[0].trace_id)


class SignalVerificationTests(SignalFabricBase):
    def test_verify_request_launches_evaluator_mission(self) -> None:
        coding = self._agent("coding")
        # Critic / specialist often has eval rights; use coding -> role evaluator via capability pick.
        # Seed a specialist with evaluation capability if needed.
        critic = next((a for a in self.fleet.list_agents() if "critic" in a.name.lower()), None)
        if critic is None:
            critic = self.fleet.create_agent(
                {
                    "name": "Evaluator",
                    "kind": "specialist",
                    "role": "evaluator",
                    "capabilities": ["evaluation", "verify"],
                }
            )
        parent = self.fleet.launch_mission(agent_id=coding.agent_id, request="code", dry_run=True)
        sig = self.fabric.publish(
            signal_type=SignalType.VERIFY_REQUEST,
            sender_type=SenderType.AGENT,
            sender_id=coding.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=critic.agent_id,
            subject="verify artifact",
            payload={
                "claim": "tests pass",
                "expectedChecks": ["unit"],
                "dryRun": True,
            },
            mission_id=parent.mission_id,
            artifact_refs=["artifact://demo"],
            enqueue_delivery_job=True,
        )
        for d in self.store.list_deliveries(signal_id=sig.signal_id):
            result = self.fabric.process_delivery(d.delivery_id)
            self.assertIn(result.get("status"), {"delivered", "failed", "expired"})
        missions = [
            m
            for m in self.fleet.store.list_missions(agent_id=critic.agent_id, limit=50)
            if (m.metadata or {}).get("parentSignalId") == sig.signal_id
        ]
        self.assertEqual(len(missions), 1)


class SignalBlackboardTests(SignalFabricBase):
    def test_finding_projects_not_heartbeat(self) -> None:
        research = self._agent("research")
        run_id = "bb_run"
        board = AgentBlackboard(run_id=run_id)
        self.fabric.register_blackboard(run_id, board)
        self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=self._agent("coding").agent_id,
            subject="finding one",
            run_id=run_id,
            confidence=0.77,
            enqueue_delivery_job=True,
        )
        findings = board.list(kind="finding")
        self.assertGreaterEqual(len(findings), 1)
        self.assertEqual(findings[0].provenance.get("signal_id") is not None, True)
        self.assertTrue(findings[0].metadata.get("signal_projection"))

        before = len(board.list(include_superseded=True))
        self.fabric.publish(
            signal_type=SignalType.HEARTBEAT,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.SYSTEM,
            recipient_id="system",
            subject="beat",
            run_id=run_id,
            priority=SignalPriority.TELEMETRY,
            enqueue_delivery_job=True,
        )
        after = len(board.list(include_superseded=True))
        self.assertEqual(before, after)


class SignalKnowledgeTests(SignalFabricBase):
    def test_unverified_candidate_not_canonical(self) -> None:
        research = self._agent("research")
        sig = self.fabric.publish(
            signal_type=SignalType.KNOWLEDGE_CANDIDATE,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.SYSTEM,
            recipient_id="knowledge",
            subject="hypothesis claim",
            payload={"claim": "maybe true", "verificationState": "hypothesis"},
            enqueue_delivery_job=True,
        )
        for d in self.store.list_deliveries(signal_id=sig.signal_id):
            result = self.fabric.process_delivery(d.delivery_id)
            hr = (result.get("handlerResult") or {})
            self.assertEqual(hr.get("status"), "held_unverified")


class SignalWorkerPoolTests(unittest.TestCase):
    def test_pool_and_capabilities_registered(self) -> None:
        self.assertIn("agent_signals", POOL_CATALOG)
        self.assertEqual(pool_for_capability("agent_signal.deliver"), "agent_signals")
        self.assertIn("agent_signal.deliver", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIn("agent_signal.retry", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIn("agent_signal.housekeeping", EXTERNAL_WORKER_CAPABILITIES)
        catalog = build_default_catalog()
        self.assertIsNotNone(catalog.get("agent_signal.deliver"))


class SignalDeliveryLifecycleTests(SignalFabricBase):
    def test_retry_then_dead_letter(self) -> None:
        research = self._agent("research")
        coding = self._agent("coding")
        sig = self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=coding.agent_id,
            subject="fail-path",
            enqueue_delivery_job=False,
        )
        d = self.store.list_deliveries(signal_id=sig.signal_id)[0]
        d.max_attempts = 2
        d.attempt_count = 2
        self.store.update_delivery(d)
        dead = self.fabric.delivery.record_failure(d, sig, error="boom", retryable=True)
        self.assertEqual(getattr(dead, "reason", None) or "", "retry_exhausted")
        letters = self.store.list_dead_letters()
        self.assertGreaterEqual(len(letters), 1)
        retried = self.fabric.retry_dead_letter(letters[0].dead_letter_id)
        self.assertEqual(retried.state, DeliveryState.PENDING)

    def test_crash_recovery_pending_survives(self) -> None:
        research = self._agent("research")
        sig = self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=self._agent("coding").agent_id,
            subject="durable",
            enqueue_delivery_job=False,
        )
        # Simulate process death before delivery — reopen store.
        store2 = SignalStore(self.db)
        pending = store2.list_deliveries(signal_id=sig.signal_id, state="PENDING")
        self.assertEqual(len(pending), 1)
        fabric2 = SignalFabricService(store2, fleet=self.fleet, enabled=True)
        result = fabric2.process_delivery(pending[0].delivery_id)
        self.assertEqual(result.get("status"), "delivered")

    def test_ack_and_chain(self) -> None:
        research = self._agent("research")
        coding = self._agent("coding")
        parent = self.fabric.publish(
            signal_type=SignalType.FINDING,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=coding.agent_id,
            subject="parent finding",
            enqueue_delivery_job=True,
        )
        child = self.fabric.publish(
            signal_type=SignalType.QUESTION,
            sender_type=SenderType.AGENT,
            sender_id=coding.agent_id,
            recipient_type=RecipientType.AGENT,
            recipient_id=research.agent_id,
            subject="clarify",
            parent_signal_id=parent.signal_id,
            correlation_id=parent.signal_id,
            enqueue_delivery_job=True,
        )
        chain = self.fabric.causal_chain(child.signal_id)
        self.assertEqual(chain["parent"]["signalId"], parent.signal_id)
        metrics = self.fabric.metrics(window_minutes=60)
        self.assertGreaterEqual(metrics["signalsTotal"], 2)
        graph = self.fabric.graph(window_hours=24)
        self.assertIn("edges", graph)


class SignalMemoryHonestyTests(SignalFabricBase):
    def test_memory_candidate_honest_status(self) -> None:
        research = self._agent("research")
        sig = self.fabric.publish(
            signal_type=SignalType.MEMORY_CANDIDATE,
            sender_type=SenderType.AGENT,
            sender_id=research.agent_id,
            recipient_type=RecipientType.SYSTEM,
            recipient_id="memory",
            subject="note",
            payload={"content": "remember this", "trust": "explicit"},
            enqueue_delivery_job=True,
        )
        for d in self.store.list_deliveries(signal_id=sig.signal_id):
            result = self.fabric.process_delivery(d.delivery_id)
            status = (result.get("handlerResult") or {}).get("status")
            self.assertIn(status, {"STORED", "PENDING", "UNSUPPORTED", "REJECTED_TRUST"})


if __name__ == "__main__":
    unittest.main()
