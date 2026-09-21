import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true },
});

test.after(async () => vite.close());

async function loadQuery() {
  return vite.ssrLoadModule("/hooks/use-hades-query.ts");
}

test("shouldAutoFetch respects enabled=false on visibility", async () => {
  const mod = await loadQuery();
  assert.equal(
    mod.shouldAutoFetch({ enabled: false, refetchOnVisibility: true, visibilityState: "visible" }),
    false,
  );
  assert.equal(
    mod.shouldAutoFetch({ enabled: true, refetchOnVisibility: true, visibilityState: "visible" }),
    true,
  );
  assert.equal(
    mod.shouldAutoFetch({ enabled: true, refetchOnVisibility: true, visibilityState: "hidden" }),
    false,
  );
});

test("multiple subscribers dedupe concurrent fetches", async () => {
  const mod = await loadQuery();
  mod.__hadesQueryTestUtils.resetCache();
  let calls = 0;
  const fetcher = async () => {
    calls += 1;
    await new Promise((r) => setTimeout(r, 30));
    return { ok: true, calls };
  };
  // Non-force concurrent callers must share one in-flight promise.
  const p1 = mod.__hadesQueryTestUtils.fetchEntry("dedupe", fetcher, 0, false);
  const p2 = mod.__hadesQueryTestUtils.fetchEntry("dedupe", fetcher, 0, false);
  const [a, b] = await Promise.all([p1, p2]);
  assert.equal(calls, 1);
  assert.deepEqual(a, b);
});

test("aborted/stale responses do not overwrite newer data", async () => {
  const mod = await loadQuery();
  mod.__hadesQueryTestUtils.resetCache();
  let resolveFirst;
  const first = new Promise((resolve) => {
    resolveFirst = resolve;
  });
  const p1 = mod.__hadesQueryTestUtils.fetchEntry(
    "race",
    async () => {
      await first;
      return "old";
    },
    0,
    true,
  );
  await new Promise((r) => setTimeout(r, 5));
  const p2 = mod.__hadesQueryTestUtils.fetchEntry("race", async () => "new", 0, true);
  resolveFirst();
  // Stale/aborted completion may resolve or reject; it must not win the cache.
  await Promise.allSettled([p1, p2]);
  assert.equal(await p2, "new");
  const entry = mod.__hadesQueryTestUtils.entryFor("race");
  assert.equal(entry.data, "new");
});

test("manual refetch works when enabled=false; invalidate marks needsRefetch", async () => {
  const mod = await loadQuery();
  mod.__hadesQueryTestUtils.resetCache();
  let calls = 0;
  const fetcher = async () => {
    calls += 1;
    return { n: calls };
  };
  // Explicit manual refetch contract — allowed regardless of enabled.
  const data = await mod.refetchHadesQuery("manual", fetcher, 0, true);
  assert.equal(data.n, 1);
  mod.invalidateHadesQuery("manual");
  const entry = mod.__hadesQueryTestUtils.entryFor("manual");
  assert.equal(entry.needsRefetch, true);
  assert.equal(entry.updatedAt, 0);
  // Auto gate still respects enabled=false.
  assert.equal(mod.shouldAutoFetch({ enabled: false, visibilityState: "visible" }), false);
});
