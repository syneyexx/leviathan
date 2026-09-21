import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "vite";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true },
});

test.after(async () => {
  await vite.close();
});

async function loadCore() {
  return vite.ssrLoadModule("/components/hades/features/chat/chat-runtime-core.ts");
}

test("resolveConversationModelId never inherits previous conversation model", async () => {
  const core = await loadCore();
  assert.equal(core.resolveConversationModelId("model-a", "default"), "model-a");
  assert.equal(core.resolveConversationModelId(null, "default"), "default");
  assert.equal(core.resolveConversationModelId(undefined, "default"), "default");
  assert.equal(core.resolveConversationModelId(null, ""), "");
  // Switching from A(custom) → B(null) must resolve default, not A's id.
  const previousUiModel = "model-a";
  const conversationB = null;
  const activeDefault = "default-model";
  assert.equal(
    core.resolveConversationModelId(conversationB, activeDefault),
    "default-model",
  );
  assert.notEqual(
    core.resolveConversationModelId(conversationB, activeDefault),
    previousUiModel,
  );
});

test("draft attachment helpers preserve artifact ids", async () => {
  const core = await loadCore();
  const restored = core.draftAttachmentsFromIds(["art-1", "art-2"]);
  assert.deepEqual(
    restored.map((item) => item.artifact_id),
    ["art-1", "art-2"],
  );
  assert.deepEqual(core.attachmentIdsFromPending(restored), ["art-1", "art-2"]);
  // Editing text is UI-side; saving must still send the same ids.
  assert.deepEqual(core.attachmentIdsFromPending(restored), ["art-1", "art-2"]);
});

test("validateAttachmentBatch enforces canonical limits", async () => {
  const core = await loadCore();
  assert.equal(core.CHAT_MAX_ATTACHMENTS, 10);
  assert.equal(core.CHAT_MAX_ATTACHMENT_BYTES, 20 * 1024 * 1024);
  assert.equal(core.validateAttachmentBatch(0, [{ name: "a.txt", size: 10 }]).ok, true);
  assert.equal(core.validateAttachmentBatch(10, [{ name: "a.txt", size: 10 }]).ok, false);
  assert.equal(
    core.validateAttachmentBatch(0, [{ name: "big.bin", size: 21 * 1024 * 1024 }]).ok,
    false,
  );
});

test("collectUnifiedStopTargets covers work/coding/research and skips terminals", async () => {
  const core = await loadCore();
  const targets = core.collectUnifiedStopTargets({
    linkedRuns: [
      { id: "1", conversation_id: "c", run_id: "w1", run_type: "work", status: "running", created_at: "", updated_at: "" },
      { id: "2", conversation_id: "c", run_id: "k1", run_type: "coding", status: "running", created_at: "", updated_at: "" },
      { id: "3", conversation_id: "c", run_id: "r1", run_type: "research", status: "running", created_at: "", updated_at: "" },
      { id: "4", conversation_id: "c", run_id: "done", run_type: "work", status: "completed", created_at: "", updated_at: "" },
    ],
    codingJobIds: ["k2"],
    researchProjectIds: ["r2"],
    codingStatuses: { k2: "running" },
    researchStatuses: { r2: "failed" },
  });
  const keys = targets.map((t) => `${t.engine}:${t.run_id}`).sort();
  assert.deepEqual(keys, ["coding:k1", "coding:k2", "research:r1", "work:w1"].sort());
});

test("shouldIgnoreCancelledCompletion blocks late success after stop", async () => {
  const core = await loadCore();
  const cancelled = new Set(["req-1"]);
  assert.equal(core.shouldIgnoreCancelledCompletion("req-1", cancelled, "completed"), true);
  assert.equal(core.shouldIgnoreCancelledCompletion("req-1", cancelled, "cancelled"), false);
  assert.equal(core.shouldIgnoreCancelledCompletion("req-2", cancelled, "completed"), false);
});

test("shouldApplyStreamToSelection isolates conversations and requests", async () => {
  const core = await loadCore();
  assert.equal(
    core.shouldApplyStreamToSelection({
      selectedConversationId: "b",
      runConversationId: "a",
      requestId: "r1",
      activeRequestId: "r1",
    }),
    false,
  );
  assert.equal(
    core.shouldApplyStreamToSelection({
      selectedConversationId: "a",
      runConversationId: "a",
      requestId: "r1",
      activeRequestId: "r1",
    }),
    true,
  );
  assert.equal(
    core.shouldApplyStreamToSelection({
      selectedConversationId: "a",
      runConversationId: "a",
      requestId: "r-old",
      activeRequestId: "r-new",
    }),
    false,
  );
});

test("mapSendResultToExecution preserves runtime fields", async () => {
  const core = await loadCore();
  const mapped = core.mapSendResultToExecution(
    {
      execution_status: "completed",
      linked_task_id: "task-1",
      run_id: "run-9",
      route: { target: "work", profile: "high", require_verification: true },
      executed_route: { actual_target: "work", verification_called: true, notes: ["ok"] },
      tools: [{ tool_name: "shell" }],
      tool_cards: [{ id: "t1" }],
      retrieval: { context_budget: { used_chars: 400, max_chars: 8000 } },
      grounding: { citations: 2 },
      verification_display: "verified",
      result_artifact_id: "art-9",
      acceptance_checklist: [{ criterion: "done", met: true }],
      persistence: [{ kind: "memory" }],
      reasoning_profile: "adaptive",
    },
    "client-req",
  );
  assert.equal(mapped.status, "completed");
  assert.equal(mapped.linked_task_id, "task-1");
  assert.equal(mapped.run_id, "run-9");
  assert.equal(mapped.target, "work");
  assert.equal(mapped.verification, true);
  assert.equal(mapped.verification_expected, true);
  assert.equal(mapped.tools?.length, 1);
  assert.equal(mapped.result_artifact_id, "art-9");
  assert.equal(mapped.verification_display, "verified");
  assert.deepEqual(mapped.acceptance_checklist, [{ criterion: "done", met: true }]);
});

test("scopePendingApprovals scopes to conversation", async () => {
  const core = await loadCore();
  const items = [
    { id: "1", status: "pending", conversation_id: "a" },
    { id: "2", status: "pending", conversation_id: "b" },
    { id: "3", status: "approved", conversation_id: "a" },
    { id: "4", status: "pending" },
  ];
  const scoped = core.scopePendingApprovals(items, "a");
  assert.deepEqual(
    scoped.map((item) => item.id),
    ["1", "4"],
  );
});

test("markCardsCancelled leaves terminal cards alone", async () => {
  const core = await loadCore();
  const next = core.markCardsCancelled([
    { status: "running" },
    { status: "completed" },
    { status: "FAILED" },
  ]);
  assert.deepEqual(
    next.map((item) => item.status),
    ["cancelled", "completed", "FAILED"],
  );
});
