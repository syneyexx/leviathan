import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (rel) => readFile(new URL(`../${rel}`, import.meta.url), "utf8");

function createStreamCoalescer(options) {
  const intervalMs = options.intervalMs ?? 40;
  const schedule = options.schedule;
  let committed = "";
  let pending = "";
  let first = true;
  let timer = null;
  const metrics = { incomingDeltas: 0, commits: 0, firstCommitImmediate: false };
  const emit = (reason) => {
    if (timer) {
      timer.cancel();
      timer = null;
    }
    committed += pending;
    pending = "";
    metrics.commits += 1;
    options.onCommit(committed, { reason });
  };
  return {
    pushDelta(delta) {
      if (!delta) return;
      metrics.incomingDeltas += 1;
      if (first) {
        first = false;
        metrics.firstCommitImmediate = true;
        pending += delta;
        emit("first");
        return;
      }
      pending += delta;
      if (!timer) {
        timer = schedule(() => {
          timer = null;
          if (pending) emit("interval");
        }, intervalMs);
      }
    },
    flush(reason) {
      if (pending || reason === "terminal" || reason === "cancel") emit(reason);
    },
    snapshot() {
      return committed + pending;
    },
    metrics() {
      return { ...metrics };
    },
  };
}

test("stream coalescer keeps first delta immediate and groups the rest", () => {
  const scheduled = [];
  const commits = [];
  const coalescer = createStreamCoalescer({
    intervalMs: 40,
    schedule: (fn, ms) => {
      scheduled.push({ fn, ms });
      return { cancel() { scheduled.length = 0; } };
    },
    onCommit: (text, meta) => commits.push({ text, reason: meta.reason }),
  });
  coalescer.pushDelta("Hel");
  coalescer.pushDelta("lo");
  coalescer.pushDelta(" world");
  assert.equal(commits.length, 1);
  assert.equal(commits[0].reason, "first");
  assert.equal(commits[0].text, "Hel");
  assert.equal(scheduled.length, 1);
  scheduled[0].fn();
  assert.equal(commits.at(-1).text, "Hello world");
  coalescer.flush("terminal");
  assert.equal(coalescer.snapshot(), "Hello world");
  const metrics = coalescer.metrics();
  assert.equal(metrics.incomingDeltas, 3);
  assert.ok(metrics.commits >= 2);
  assert.equal(metrics.firstCommitImmediate, true);
});

test("production stream coalescer and poll constants match the measured policy", async () => {
  const coalesce = await read("lib/stream-coalesce.ts");
  const polls = await read("lib/ui-poll-intervals.ts");
  assert.match(coalesce, /STREAM_COMMIT_INTERVAL_MS = 40/);
  assert.match(coalesce, /export function createStreamCoalescer/);
  assert.match(polls, /PLUGIN_DEPENDENCY_POLL_MS = 2500/);
  assert.match(polls, /RESEARCH_ACTIVE_POLL_MS = 4000/);
  assert.match(polls, /TASKS_ACTIVE_POLL_MS = 4000/);
  assert.match(polls, /CHAT_USAGE_POLL_IDLE_MS = 12000/);
  assert.match(polls, /CHAT_USAGE_POLL_ACTIVE_MS = 2000/);
});
