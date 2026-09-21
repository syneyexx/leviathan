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

async function loadMerge() {
  return vite.ssrLoadModule("/components/hades/features/chat/live-execution-merge.ts");
}

test("mergeChatToolCalls upserts by call_id across status transitions", async () => {
  const { mergeChatToolCalls } = await loadMerge();
  const started = mergeChatToolCalls([], [{
    call_id: "abc123",
    tool_name: "hades.fs_read",
    status: "started",
  }]);
  const running = mergeChatToolCalls(started, [{
    call_id: "abc123",
    tool_name: "hades.fs_read",
    status: "running",
  }]);
  const completed = mergeChatToolCalls(running, [{
    call_id: "abc123",
    tool_name: "hades.fs_read",
    status: "completed",
    summary: "ok",
  }]);

  assert.equal(completed.length, 1);
  assert.equal(completed[0].call_id, "abc123");
  assert.equal(completed[0].status, "completed");
  assert.equal(completed[0].summary, "ok");
  assert.equal(completed[0].tool_name, "hades.fs_read");
});

test("mergeChatToolCalls keeps same tool_name with different call_ids as separate invocations", async () => {
  const { mergeChatToolCalls } = await loadMerge();
  const merged = mergeChatToolCalls(
    [{ call_id: "A", tool_name: "hades.fs_read", status: "completed" }],
    [{ call_id: "B", tool_name: "hades.fs_read", status: "started" }],
  );
  assert.equal(merged.length, 2);
  assert.deepEqual(merged.map((row) => row.call_id), ["A", "B"]);
});

test("mergeChatToolCalls does not collapse missing call_id rows by tool_name", async () => {
  const { mergeChatToolCalls } = await loadMerge();
  const merged = mergeChatToolCalls(
    [{ tool_name: "hades.fs_read", status: "started" }],
    [{ tool_name: "hades.fs_read", status: "completed" }],
  );
  assert.equal(merged.length, 2);
  assert.equal(merged[0].status, "started");
  assert.equal(merged[1].status, "completed");
});

test("mergeChatToolCalls applies the 30-invocation cap after reconciliation", async () => {
  const { mergeChatToolCalls, LIVE_TOOL_CALL_LIMIT } = await loadMerge();
  assert.equal(LIVE_TOOL_CALL_LIMIT, 30);
  const seed = Array.from({ length: 28 }, (_, index) => ({
    call_id: `seed-${index}`,
    tool_name: "hades.fs_read",
    status: "completed",
  }));
  // Three status updates for one new call must count as one invocation.
  let tools = mergeChatToolCalls(seed, [{ call_id: "new", tool_name: "hades.fs_read", status: "started" }]);
  tools = mergeChatToolCalls(tools, [{ call_id: "new", tool_name: "hades.fs_read", status: "running" }]);
  tools = mergeChatToolCalls(tools, [{ call_id: "new", tool_name: "hades.fs_read", status: "completed" }]);
  tools = mergeChatToolCalls(tools, [{ call_id: "extra", tool_name: "hades.fs_read", status: "started" }]);
  tools = mergeChatToolCalls(tools, [{ call_id: "extra", tool_name: "hades.fs_read", status: "completed" }]);

  assert.equal(tools.length, 30);
  assert.equal(tools.filter((row) => row.call_id === "new").length, 1);
  assert.equal(tools.filter((row) => row.call_id === "extra").length, 1);
  assert.equal(tools[0].call_id, "seed-0");
  // Blind append+slice(-30) would have dropped early seeds when status rows piled up.
  assert.ok(tools.some((row) => row.call_id === "seed-0"));
});

test("mergeLiveExecutionEvents dedupes by sequence and keeps newer copy", async () => {
  const { mergeLiveExecutionEvents } = await loadMerge();
  const first = mergeLiveExecutionEvents([], [
    { type: "tool_status", sequence: 1, payload: { call_id: "a", status: "started" } },
    { type: "route_chosen", sequence: 2, payload: { target: "direct" } },
  ]);
  const second = mergeLiveExecutionEvents(first, [
    { type: "tool_status", sequence: 1, payload: { call_id: "a", status: "completed" } },
    { type: "model_usage", sequence: 3, payload: { kind: "estimate" } },
  ]);

  assert.equal(second.length, 3);
  assert.equal(second[0].sequence, 1);
  assert.equal(second[0].payload?.status, "completed");
  assert.equal(second[1].sequence, 2);
  assert.equal(second[2].sequence, 3);
});

test("mergeLiveExecutionEvents does not collapse unsequenced events with matching type/text", async () => {
  const { mergeLiveExecutionEvents } = await loadMerge();
  const merged = mergeLiveExecutionEvents(
    [{ type: "note", payload: { text: "same" } }],
    [{ type: "note", payload: { text: "same" } }],
  );
  assert.equal(merged.length, 2);
});

test("mergeLiveExecutionEvents applies the 40-event cap after deduplication", async () => {
  const { mergeLiveExecutionEvents, LIVE_EVENT_LIMIT } = await loadMerge();
  assert.equal(LIVE_EVENT_LIMIT, 40);
  const seed = Array.from({ length: 39 }, (_, index) => ({
    type: "tick",
    sequence: index + 1,
  }));
  let events = mergeLiveExecutionEvents(seed, [
    { type: "tick", sequence: 40 },
    { type: "tick", sequence: 40 }, // duplicate sequence must not consume an extra slot
    { type: "tick", sequence: 41 },
  ]);
  assert.equal(events.length, 40);
  assert.equal(events[0].sequence, 2);
  assert.equal(events[events.length - 1].sequence, 41);
  assert.equal(events.filter((event) => event.sequence === 40).length, 1);
});
