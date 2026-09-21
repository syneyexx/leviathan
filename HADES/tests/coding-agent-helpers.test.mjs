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

test("coding-agent helpers preserve status labels and tones", async () => {
  const helpers = await vite.ssrLoadModule("/components/hades/coding-agent-helpers.ts");
  assert.equal(helpers.dash(""), "—");
  assert.equal(helpers.buildStatusLabel("verified"), "Geverifieerd");
  assert.equal(helpers.buildStatusLabel("pause_requested"), "Pauze aangevraagd");
  assert.equal(helpers.buildStatusTone("verified"), "success");
  assert.equal(helpers.buildStatusTone("pause_requested"), "warning");
  assert.equal(helpers.buildStatusTone("failed"), "danger");
  assert.equal(helpers.loopPhaseLabel("apply_edits"), "Apply edits");
});

test("coding-agent helpers parse argv/edits and collect logs", async () => {
  const helpers = await vite.ssrLoadModule("/components/hades/coding-agent-helpers.ts");
  assert.deepEqual(helpers.parseArgv("python --version"), ["python", "--version"]);
  assert.deepEqual(helpers.parseArgv('["a","b"]'), ["a", "b"]);
  assert.deepEqual(helpers.parseEdits('[{"path":"x.py","action":"create"}]'), [{ path: "x.py", action: "create" }]);
  const logs = helpers.collectBuildLogs({
    report: { attempts: 2 },
    error: "boom",
    test_results: [
      { suite: "unittest", status: "failed", command: ["python", "-m", "unittest"], stdout: "out", stderr: "err" },
    ],
  });
  assert.match(logs, /Pogingen: 2/);
  assert.match(logs, /Fout: boom/);
  assert.match(logs, /test 1: unittest/);
});
