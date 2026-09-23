/**
 * Deterministic save-coordinator tests — controllable promises, no timing guesses.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { FILES } from "../js/constants.js";
import { createStore } from "../js/state.js";
import { createSaveCoordinator, SaveState } from "../js/save.js";

function makeCtx(apiSave) {
  const files = Object.fromEntries(FILES.map((f) => [f, "base-css"]));
  const store = createStore({
    files: { ...files },
    saved: { ...files },
    dirtyFiles: Object.fromEntries(FILES.map((f) => [f, false])),
    content: { version: 3, entries: {}, nodes: [], components: [], revision: 0 },
    contentDirty: false,
  });
  const calls = [];
  const ctx = {
    store,
    content: {
      ensure: () => store.getState().content,
      syncNodesFromDom: () => {},
      setStatus: () => {},
    },
    api: {
      saveTransaction: async (payload) => {
        calls.push(JSON.parse(JSON.stringify(payload)));
        return apiSave(payload, calls.length);
      },
    },
  };
  const save = createSaveCoordinator(ctx);
  save.adoptServer({ revision: 0, hash: "hash0" });
  return { store, save, calls, ctx };
}

function controllable() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test("P0-A: queued snapshot uses newly acknowledged server base", async () => {
  const gates = [controllable(), controllable()];
  let gateIdx = 0;
  const { save, calls, store } = makeCtx(async (payload) => {
    const g = gates[gateIdx++];
    await g.promise;
    return { revision: Number(payload.baseRevision) + 1, hash: `hash${Number(payload.baseRevision) + 1}` };
  });

  save.markDirty();
  store.setState({ content: { ...store.getState().content, entries: { "node:a": { text: "1" } } } });
  const p1 = save.saveAll();

  save.markDirty();
  store.setState({ content: { ...store.getState().content, entries: { "node:a": { text: "2" } } } });
  const p2 = save.saveAll();

  // First request still in flight — second is queued with stale capture, but run() must re-stamp
  assert.equal(calls.length, 1);
  assert.equal(calls[0].baseRevision, 0);
  assert.equal(calls[0].baseHash, "hash0");

  gates[0].resolve();
  await p1;

  // Allow microtask drain of queued run
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(calls.length, 2);
  assert.equal(calls[1].baseRevision, 1, "queued save must use ack revision 1, not 0");
  assert.equal(calls[1].baseHash, "hash1");

  gates[1].resolve();
  await p2;
  assert.equal(save.getState().serverRevision, 2);
  assert.equal(save.getState().acknowledgedLocalGeneration, 2);
  assert.equal(save.isDirty(), false);
});

test("P0-A: three queued calls coalesce; all waiters resolve on latest ack", async () => {
  const gate = controllable();
  let releases = 0;
  const { save, calls, store } = makeCtx(async (payload) => {
    if (releases === 0) {
      await gate.promise;
    }
    releases += 1;
    return { revision: Number(payload.baseRevision) + 1, hash: `h${Number(payload.baseRevision) + 1}` };
  });

  save.markDirty();
  const a = save.saveAll();
  save.markDirty();
  const b = save.saveAll();
  save.markDirty();
  store.setState({
    content: { ...store.getState().content, entries: { "node:x": { text: "final" } } },
  });
  const c = save.saveAll();

  assert.equal(calls.length, 1, "only one in-flight while active");
  gate.resolve();

  const [ra, rb, rc] = await Promise.all([a, b, c]);
  assert.equal(ra.ok, true);
  assert.equal(rb.ok, true);
  assert.equal(rc.ok, true);
  // Active + one coalesced queued drain
  assert.ok(calls.length <= 2, `expected ≤2 network saves, got ${calls.length}`);
  assert.equal(calls[calls.length - 1].content.entries["node:x"].text, "final");
  assert.equal(save.isDirty(), false);
});

test("P0-A: server revision unrelated to local edit count; latest gen clean", async () => {
  const { save, store } = makeCtx(async () => ({ revision: 100, hash: "server-100" }));

  save.markDirty();
  save.markDirty();
  save.markDirty();
  assert.equal(save.getState().localGeneration, 3);
  store.setState({
    content: { ...store.getState().content, entries: { "node:a": { text: "x" } } },
  });

  await save.saveAll();
  assert.equal(save.getState().serverRevision, 100);
  assert.equal(save.getState().acknowledgedLocalGeneration, 3);
  assert.equal(save.getState().localGeneration, 3);
  assert.equal(save.isDirty(), false, "batched local edits must be clean after one ack");
});

test("P0-A: A→B→A CSS during save keeps acknowledged baseline correct", async () => {
  const gate = controllable();
  const { save, store, calls } = makeCtx(async (payload) => {
    await gate.promise;
    return { revision: 1, hash: "after" };
  });

  const file = FILES[0];
  store.setState({ files: { ...store.getState().files, [file]: "A" } });
  save.markDirty();
  const p = save.saveAll();

  // Mutate to B then back to A while save in flight
  store.setState({ files: { ...store.getState().files, [file]: "B" } });
  save.markDirty();
  store.setState({ files: { ...store.getState().files, [file]: "A" } });
  save.markDirty();

  gate.resolve();
  await p;
  await Promise.resolve();
  await Promise.resolve();

  // First snap had A; after ack, live buffer is also A → clean for that file path
  // If a queued drain ran with generation 3, it should also complete
  let guard = 0;
  while (save.getState().busy && guard++ < 10) await Promise.resolve();
  if (save.getState().queued || save.isDirty()) {
    await save.saveAll();
  }
  assert.equal(store.getState().files[file], "A");
  assert.equal(save.getState().acknowledgedFiles[file], "A");
  assert.equal(save.isDirty(), false);
  assert.ok(calls.length >= 1);
});

test("P0-A: transport failure rejects and does not auto-drain queued", async () => {
  let shouldFail = true;
  const gate = controllable();
  const { save, calls } = makeCtx(async () => {
    await gate.promise;
    if (shouldFail) {
      const err = Object.assign(new Error("offline"), { status: 0 });
      throw err;
    }
    return { revision: 1, hash: "ok" };
  });

  save.markDirty();
  const p1 = save.saveAll();
  save.markDirty();
  const p2 = save.saveAll();

  gate.resolve();
  await assert.rejects(p1, /offline/);
  await assert.rejects(p2, /offline/);
  assert.equal(save.getState().drainPaused, true);
  assert.equal(save.getState().saveState, SaveState.OFFLINE);
  assert.equal(calls.length, 1, "queued must not auto-start after failure");
});

test("P0-A: conflict pauses drain; force retry resumes with fresh base", async () => {
  const gates = [controllable(), controllable()];
  let n = 0;
  const { save, calls } = makeCtx(async (payload) => {
    const g = gates[n++];
    await g.promise;
    if (n === 1) {
      throw Object.assign(new Error("conflict"), { status: 409, payload: { error: "conflict" } });
    }
    return { revision: Number(payload.baseRevision) + 1, hash: "recovered" };
  });

  save.markDirty();
  const p1 = save.saveAll();
  save.markDirty();
  const p2 = save.saveAll();

  gates[0].resolve();
  await assert.rejects(p1);
  await assert.rejects(p2);
  assert.equal(save.getState().drainPaused, true);
  assert.equal(calls.length, 1);

  // Simulate user resolving external conflict by adopting new server meta
  save.adoptServer({ revision: 5, hash: "external" });
  save.markDirty();
  const retry = save.clearConflictAndRetry();
  gates[1].resolve();
  await retry;
  assert.equal(calls[1].baseRevision, 5);
  assert.equal(calls[1].baseHash, "external");
  assert.equal(save.getState().drainPaused, false);
});

test("P0-A: queued caller waits for its generation ack, not merely active completion", async () => {
  const gates = [controllable(), controllable()];
  let n = 0;
  const order = [];
  const { save } = makeCtx(async (payload) => {
    const idx = n++;
    await gates[idx].promise;
    return { revision: idx + 1, hash: `h${idx + 1}` };
  });

  save.markDirty();
  const p1 = save.saveAll().then((r) => {
    order.push("p1");
    return r;
  });
  save.markDirty();
  const p2 = save.saveAll().then((r) => {
    order.push("p2");
    return r;
  });

  // Finish first — p1 may resolve; p2 must NOT resolve until second drain acks
  gates[0].resolve();
  await p1;
  assert.ok(!order.includes("p2"), "p2 must still be waiting for its generation");

  await Promise.resolve();
  await Promise.resolve();
  gates[1].resolve();
  await p2;
  assert.deepEqual(order, ["p1", "p2"]);
});

test("existing: save coordinator keeps dirty when edits continue during save", async () => {
  const gate = controllable();
  const { save, store } = makeCtx(async () => {
    await gate.promise;
    return { revision: 1, hash: "abc" };
  });
  save.markDirty();
  const p = save.saveAll();
  store.setState({ contentDirty: true });
  save.markDirty();
  gate.resolve();
  await p;
  assert.equal(save.isDirty(), true);
  assert.equal(save.getState().localGeneration > save.getState().acknowledgedLocalGeneration, true);
});
