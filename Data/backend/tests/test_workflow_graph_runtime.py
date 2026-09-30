"""Graph control-flow tests for WorkflowRuntime."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore
from Data.modules.workflows import (
    WorkflowDefinitionStatus,
    WorkflowEdgeDef,
    WorkflowExecutionState,
    WorkflowGraph,
    WorkflowNodeDef,
    WorkflowNodeKind,
    WorkflowRuntime,
    WorkflowState,
    WorkflowStepDef,
    WorkflowStore,
)
from Data.modules.workflows.variables import eval_predicate, resolve_value


class WorkflowGraphRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "g.db"
        artifacts = ArtifactStore(self.db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(self.db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="W", content="graph needle", source="t")
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        approvals.store.initialize()
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
        self.store = WorkflowStore(self.db)
        self.store.initialize()
        self.runtime = WorkflowRuntime(self.store, self.gateway)
        self.root = root
        self.note = root / "n.txt"
        self.note.write_text("hello-graph", encoding="utf-8")

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def _cap(self, node_id: str, path: str | None = None) -> WorkflowNodeDef:
        return WorkflowNodeDef(
            node_id=node_id,
            kind=WorkflowNodeKind.CAPABILITY,
            label=node_id,
            config={
                "capability_id": "file.read",
                "arguments": {"path": path or str(self.note)},
            },
        )

    def test_condition_true_and_false_branches(self) -> None:
        graph = WorkflowGraph(
            nodes=[
                WorkflowNodeDef(
                    node_id="t",
                    kind=WorkflowNodeKind.TRIGGER,
                    label="Manual",
                    config={"trigger_kind": "MANUAL"},
                ),
                WorkflowNodeDef(
                    node_id="cond",
                    kind=WorkflowNodeKind.CONDITION,
                    label="check",
                    config={"predicate": {"op": "equals", "left": "{{variables.flag}}", "right": True}},
                ),
                self._cap("yes_node"),
                WorkflowNodeDef(
                    node_id="no_node",
                    kind=WorkflowNodeKind.CAPABILITY,
                    label="no",
                    config={"capability_id": "file.read", "arguments": {"path": str(self.root / "missing")}},
                ),
            ],
            edges=[
                WorkflowEdgeDef(edge_id="t-c", source="t", target="cond"),
                WorkflowEdgeDef(edge_id="c-y", source="cond", target="yes_node", source_handle="true"),
                WorkflowEdgeDef(edge_id="c-n", source="cond", target="no_node", source_handle="false"),
            ],
        )
        definition = self.store.create_definition(
            name="branch",
            graph=graph,
            status=WorkflowDefinitionStatus.ACTIVE,
            variables=[],
        )
        # Patch input snapshot via create_execution
        ex = self.store.create_execution(
            workflow_id=definition.workflow_id,
            input_snapshot={"flag": True},
        )
        # Inject variable into version variables for context defaults — input_snapshot used.
        done = self.runtime.run(ex.execution_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)
        nodes = [r.get("node_id") for r in (self.store.get_execution(ex.execution_id).node_results or [])]
        self.assertIn("yes_node", nodes)
        self.assertNotIn("no_node", nodes)

        ex2 = self.store.create_execution(
            workflow_id=definition.workflow_id,
            input_snapshot={"flag": False},
        )
        done2 = self.runtime.run(ex2.execution_id)
        self.assertEqual(done2.state, WorkflowState.FAILED)  # no_node missing file
        nodes2 = [r.get("node_id") for r in (self.store.get_execution(ex2.execution_id).node_results or [])]
        self.assertIn("no_node", nodes2)
        self.assertNotIn("yes_node", nodes2)

    def test_bounded_loop_and_limit(self) -> None:
        graph = WorkflowGraph(
            nodes=[
                WorkflowNodeDef(node_id="t", kind=WorkflowNodeKind.TRIGGER, label="t", config={}),
                WorkflowNodeDef(
                    node_id="loop",
                    kind=WorkflowNodeKind.LOOP,
                    label="loop",
                    config={"max_iterations": 2, "while": {"op": "equals", "left": 1, "right": 1}},
                ),
                self._cap("body"),
                self._cap("after"),
            ],
            edges=[
                WorkflowEdgeDef(edge_id="t-l", source="t", target="loop"),
                WorkflowEdgeDef(edge_id="l-b", source="loop", target="body", source_handle="body"),
                WorkflowEdgeDef(edge_id="b-l", source="body", target="loop"),
                WorkflowEdgeDef(edge_id="l-a", source="loop", target="after", source_handle="done"),
            ],
        )
        # Cycle body→loop is intentional for LOOP primitive.
        from Data.modules.workflows.graph import validate_graph

        # validate_graph allows cycles that include loop nodes
        result = validate_graph(graph)
        self.assertTrue(result["ok"], result)
        definition = self.store.create_definition(name="loop", graph=graph, status=WorkflowDefinitionStatus.ACTIVE)
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        done = self.runtime.run(ex.execution_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)
        body_runs = [
            r
            for r in (self.store.get_execution(ex.execution_id).node_results or [])
            if r.get("node_id") == "body" and r.get("status") == "COMPLETED"
        ]
        self.assertEqual(len(body_runs), 2)

    def test_delay_zero_and_resume(self) -> None:
        graph = WorkflowGraph(
            nodes=[
                WorkflowNodeDef(node_id="t", kind=WorkflowNodeKind.TRIGGER, label="t", config={}),
                WorkflowNodeDef(
                    node_id="d",
                    kind=WorkflowNodeKind.DELAY,
                    label="delay",
                    config={"delay_seconds": 0},
                ),
                self._cap("after"),
            ],
            edges=[
                WorkflowEdgeDef(edge_id="t-d", source="t", target="d"),
                WorkflowEdgeDef(edge_id="d-a", source="d", target="after"),
            ],
        )
        definition = self.store.create_definition(name="delay", graph=graph)
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        done = self.runtime.run(ex.execution_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)

    def test_variable_binding(self) -> None:
        ctx = {"variables": {"topic": "markets"}, "nodes": {}, "inputs": {}, "trigger": {}, "execution": {}}
        self.assertEqual(resolve_value("hello {{variables.topic}}", ctx), "hello markets")
        self.assertTrue(eval_predicate({"op": "equals", "left": "{{variables.topic}}", "right": "markets"}, ctx))

    def test_illegal_cycle_rejected(self) -> None:
        from Data.modules.workflows.graph import validate_graph

        graph = WorkflowGraph(
            nodes=[
                WorkflowNodeDef(node_id="a", kind=WorkflowNodeKind.CAPABILITY, config={"capability_id": "file.read"}),
                WorkflowNodeDef(node_id="b", kind=WorkflowNodeKind.CAPABILITY, config={"capability_id": "file.read"}),
            ],
            edges=[
                WorkflowEdgeDef(edge_id="a-b", source="a", target="b"),
                WorkflowEdgeDef(edge_id="b-a", source="b", target="a"),
            ],
        )
        result = validate_graph(graph)
        self.assertFalse(result["ok"])

    def test_run_definition_creates_new_execution_each_time(self) -> None:
        definition = self.store.create_definition(
            name="multi",
            steps=[WorkflowStepDef(step_id="s1", capability_id="file.read", arguments={"path": str(self.note)})],
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        e1, _ = self.runtime.run_definition(definition.workflow_id)
        done1 = self.runtime.run(e1.execution_id)
        self.assertEqual(done1.state, WorkflowState.COMPLETED)
        e2, _ = self.runtime.run_definition(definition.workflow_id)
        self.assertNotEqual(e1.execution_id, e2.execution_id)
        done2 = self.runtime.run(e2.execution_id)
        self.assertEqual(done2.state, WorkflowState.COMPLETED)
        self.assertEqual(self.store.count_executions(workflow_id=definition.workflow_id), 2)
        # First execution remains completed / immutable identity
        self.assertEqual(self.store.get_execution(e1.execution_id).state, WorkflowExecutionState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
