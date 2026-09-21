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

test("coding runtime core labels, parse, merge, terminal sets", async () => {
  const core = await vite.ssrLoadModule("/components/hades/features/coding/coding-runtime-core.ts");
  assert.equal(core.buildStatusLabel("verified"), "Geverifieerd");
  assert.equal(core.buildStatusTone("failed"), "danger");
  assert.deepEqual(core.parseArgv("python --version"), ["python", "--version"]);
  assert.deepEqual(core.parseEdits('[{"path":"a.py","action":"modify"}]')[0].path, "a.py");
  const merged = core.mergeJobEvents([{ id: "1", seq: 1 }], [
    { id: "1", seq: 1 },
    { id: "2", seq: 2 },
  ]);
  assert.equal(merged.length, 2);
  assert.ok(core.JOB_TERMINAL.has("verified"));
  assert.ok(core.JOB_SUCCESS.has("completed"));
  assert.equal(core.loopPhaseLabel("repair"), "Repair / fix");
  assert.match(core.formatOmnirouteRouting({ omniroute_used: true, routing_mode: "auto" }), /OmniRoute/);
  assert.equal(core.finalBetaCodingHash("abc"), "#/fb/coding?codingJob=abc");
});
