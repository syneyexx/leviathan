"""Wave 1 — workflow definition / version / execution separation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.workflows import (
    WorkflowDefinitionStatus,
    WorkflowExecutionState,
    WorkflowRuntime,
    WorkflowState,
    WorkflowStepDef,
    WorkflowStore,
)
from Data.modules.workflows.graph import steps_to_graph, validate_graph
from Data.modules.workflows.types import WorkflowNodeKind


class WorkflowDomainSeparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "wf.db"
        self.store = WorkflowStore(self.db)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_one_definition_many_executions(self) -> None:
        definition = self.store.create_definition(
            name="Research Pipeline",
            steps=[
                WorkflowStepDef(step_id="s1", capability_id="knowledge.search", arguments={"query": "x"}),
            ],
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        e1 = self.store.create_execution(workflow_id=definition.workflow_id, trigger_source="MANUAL")
        e2 = self.store.create_execution(workflow_id=definition.workflow_id, trigger_source="MANUAL")
        self.assertNotEqual(e1.execution_id, e2.execution_id)
        self.assertEqual(e1.workflow_id, definition.workflow_id)
        self.assertEqual(e1.state, WorkflowExecutionState.QUEUED)
        # Completing e1 must not alter definition status or e2.
        e1.state = WorkflowExecutionState.COMPLETED
        self.store.save_execution(e1)
        refreshed_def = self.store.get_definition(definition.workflow_id)
        assert refreshed_def is not None
        self.assertEqual(refreshed_def.status, WorkflowDefinitionStatus.ACTIVE)
        e2b = self.store.get_execution(e2.execution_id)
        assert e2b is not None
        self.assertEqual(e2b.state, WorkflowExecutionState.QUEUED)

    def test_version_pinning_and_noop_save(self) -> None:
        definition = self.store.create_definition(
            name="v",
            steps=[WorkflowStepDef(step_id="s1", capability_id="file.read", arguments={"path": "/tmp/a"})],
        )
        self.assertEqual(definition.current_version, 1)
        # No-op save should not bump version.
        same = self.store.save_definition(definition, create_version=True, change_summary="noop")
        self.assertEqual(same.current_version, 1)
        # Real change creates version 2.
        from Data.modules.workflows.types import WorkflowNodeDef, WorkflowGraph, WorkflowEdgeDef

        graph = definition.graph
        nodes = list(graph.nodes) + [
            WorkflowNodeDef(
                node_id="s2",
                kind=WorkflowNodeKind.CAPABILITY,
                label="file.read",
                config={"capability_id": "file.read", "arguments": {"path": "/tmp/b"}},
            )
        ]
        edges = list(graph.edges) + [
            WorkflowEdgeDef(edge_id="s1->s2", source="s1", target="s2"),
        ]
        definition.graph = WorkflowGraph(nodes=nodes, edges=edges)
        updated = self.store.save_definition(definition, change_summary="add step")
        self.assertEqual(updated.current_version, 2)
        e = self.store.create_execution(workflow_id=definition.workflow_id, version=1)
        self.assertEqual(e.workflow_version, 1)
        # Later definition bump must not rewrite pinned execution version.
        self.assertEqual(self.store.get_execution(e.execution_id).workflow_version, 1)

    def test_legacy_row_migration_preserves_execution_id(self) -> None:
        # Simulate a pre-separation workflows row.
        import sqlite3

        legacy_id = "legacy-wf-1"
        with sqlite3.connect(self.db) as conn:
            conn.row_factory = sqlite3.Row
            # Wipe auto-created schema tables content and insert legacy-shaped row.
            conn.execute("DELETE FROM workflows")
            conn.execute("DELETE FROM workflow_executions")
            conn.execute("DELETE FROM workflow_versions")
            conn.execute(
                """
                INSERT INTO workflows(
                    workflow_id, name, state, steps_json, created_at, updated_at,
                    current_step, run_id, step_results_json, error, metadata_json,
                    record_kind
                ) VALUES (?, 'old', 'COMPLETED', ?, '2024-01-01T00:00:00+00:00',
                          '2024-01-01T00:01:00+00:00', 1, NULL, ?, NULL, '{}', 'legacy')
                """,
                (
                    legacy_id,
                    json.dumps(
                        [
                            {
                                "step_id": "s1",
                                "capability_id": "knowledge.search",
                                "arguments": {"query": "q"},
                            }
                        ]
                    ),
                    json.dumps([{"step_id": "s1", "status": "COMPLETED"}]),
                ),
            )
            conn.commit()
        # Re-initialize triggers migration.
        store2 = WorkflowStore(self.db)
        store2.initialize()
        execution = store2.get_execution(legacy_id)
        self.assertIsNotNone(execution)
        assert execution is not None
        self.assertEqual(execution.state, WorkflowExecutionState.COMPLETED)
        record = store2.get(legacy_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.state, WorkflowState.COMPLETED)
        self.assertEqual(record.execution_id, legacy_id)
        definition = store2.get_definition(execution.workflow_id)
        self.assertIsNotNone(definition)

    def test_migration_runner_v60(self) -> None:
        runner = MigrationRunner(self.db)
        applied = runner.apply_all()
        self.assertIn(60, applied)
        # Idempotent
        again = runner.apply_all()
        self.assertEqual(again, [])

    def test_linear_steps_become_graph(self) -> None:
        steps = [
            WorkflowStepDef(step_id="a", capability_id="file.read", arguments={"path": "x"}),
            WorkflowStepDef(step_id="b", capability_id="knowledge.search", arguments={"query": "y"}),
        ]
        graph = steps_to_graph(steps)
        self.assertTrue(any(n.kind_value == "trigger" for n in graph.nodes))
        self.assertEqual(len([n for n in graph.nodes if n.kind_value == "capability"]), 2)
        result = validate_graph(graph)
        self.assertTrue(result["ok"])

    def test_duplicate_does_not_copy_executions_or_triggers(self) -> None:
        definition = self.store.create_definition(
            name="src",
            steps=[WorkflowStepDef(step_id="s1", capability_id="file.read", arguments={"path": "p"})],
            status=WorkflowDefinitionStatus.ACTIVE,
            trigger_bindings=[{"kind": "SCHEDULE", "schedule_id": "sched-1"}],
        )
        self.store.create_execution(workflow_id=definition.workflow_id)
        dup = self.store.duplicate_definition(definition.workflow_id)
        self.assertNotEqual(dup.workflow_id, definition.workflow_id)
        self.assertEqual(dup.status, WorkflowDefinitionStatus.INACTIVE)
        self.assertEqual(dup.trigger_bindings, [])
        self.assertEqual(self.store.count_executions(workflow_id=dup.workflow_id), 0)

    def test_legacy_create_still_runnable_via_runtime_record(self) -> None:
        from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
        from Data.modules.artifacts import ArtifactStore
        from Data.modules.execution import ExecutionGateway, build_default_catalog
        from Data.modules.function_runtime import FunctionRuntime, build_default_registry
        from Data.modules.knowledge import HybridRetriever, KnowledgeStore
        from Data.modules.observations import ObservationStore

        root = Path(self.tmp.name)
        artifacts = ArtifactStore(self.db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(self.db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="W", content="needle hello", source="t")
        fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        try:
            approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
            approvals.store.initialize()
            obs = ObservationStore(self.db)
            obs.initialize()
            gateway = ExecutionGateway(
                catalog=build_default_catalog(),
                function_runtime=fn,
                knowledge_retriever=HybridRetriever(knowledge),
                artifact_store=artifacts,
                approval_checker=approvals,
                observation_store=obs,
            )
            runtime = WorkflowRuntime(self.store, gateway)
            path = root / "n.txt"
            path.write_text("hello", encoding="utf-8")
            wf = runtime.create(
                name="demo",
                steps=[
                    WorkflowStepDef(step_id="s1", capability_id="file.read", arguments={"path": str(path)}),
                ],
            )
            # Same definition can be executed again via create_execution.
            definition_id = wf.definition_id
            assert definition_id
            done = runtime.run(wf.workflow_id)
            self.assertEqual(done.state, WorkflowState.COMPLETED)
            second = self.store.create_execution(workflow_id=definition_id, trigger_source="MANUAL")
            done2 = runtime.run(second.execution_id)
            self.assertEqual(done2.state, WorkflowState.COMPLETED)
            self.assertEqual(self.store.count_executions(workflow_id=definition_id), 2)
        finally:
            fn.shutdown()


if __name__ == "__main__":
    unittest.main()
