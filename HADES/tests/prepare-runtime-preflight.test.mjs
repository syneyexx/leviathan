import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MIN_NODE_VERSION,
  MIN_PYTHON_VERSION,
  checkCurrentRuntimes,
  parseVersion,
  versionAtLeast,
} from "../tools/check_runtime_versions.mjs";

test("runtime version parser handles Node and Python version output", () => {
  assert.deepEqual(parseVersion("22.13.0"), [22, 13, 0]);
  assert.deepEqual(parseVersion("Python 3.11.9"), [3, 11, 9]);
  assert.deepEqual(parseVersion("Python 3.12"), [3, 12, 0]);
  assert.equal(parseVersion("not-a-version"), null);
});

test("runtime minimum comparison rejects unsupported HADES runtimes", () => {
  assert.equal(versionAtLeast([22, 12, 9], MIN_NODE_VERSION), false);
  assert.equal(versionAtLeast([22, 13, 0], MIN_NODE_VERSION), true);
  assert.equal(versionAtLeast([23, 0, 0], MIN_NODE_VERSION), true);
  assert.equal(versionAtLeast([3, 10, 99], MIN_PYTHON_VERSION), false);
  assert.equal(versionAtLeast([3, 11, 0], MIN_PYTHON_VERSION), true);
  assert.equal(versionAtLeast([3, 12, 0], MIN_PYTHON_VERSION), true);
});

test("current release-test host satisfies the declared HADES runtime minimums", () => {
  const result = checkCurrentRuntimes();
  assert.equal(result.ok, true, result.message || "runtime preflight failed");
});

test("PREPARE_HADES validates PATH runtimes before install and the reused backend venv", async () => {
  const prepare = await readFile(new URL("../PREPARE_HADES.bat", import.meta.url), "utf8");
  const versionChecks = [...prepare.matchAll(/node tools\\check_runtime_versions\.mjs/g)];
  const firstCheckIndex = prepare.indexOf("node tools\\check_runtime_versions.mjs");
  const installIndex = prepare.indexOf("npm ci");

  assert.equal(versionChecks.length, 2, "PREPARE_HADES must validate both PATH and backend-venv runtimes");
  assert.ok(firstCheckIndex >= 0, "PREPARE_HADES must invoke the shared runtime version preflight");
  assert.ok(installIndex >= 0, "PREPARE_HADES must retain npm ci dependency installation");
  assert.ok(firstCheckIndex < installIndex, "PATH runtime versions must be checked before dependency installation");
  assert.match(prepare, /set "HADES_PYTHON=backend\\\.venv\\Scripts\\python\.exe"/);
});

test("PREPARE_HADES runs the documented frontend setup gates and does not claim full release verification", async () => {
  const prepare = await readFile(new URL("../PREPARE_HADES.bat", import.meta.url), "utf8");

  assert.match(prepare, /call npm run typecheck/);
  assert.match(prepare, /call npm run lint/);
  assert.match(prepare, /call npm run build/);
  assert.match(prepare, /call npm run test:frontend:release/);
  assert.match(prepare, /Voor de canonical volledige releaseverificatie: VERIFY_HADES\.bat/);
  assert.doesNotMatch(prepare, /HADES is voorbereid EN geverifieerd/);
});
