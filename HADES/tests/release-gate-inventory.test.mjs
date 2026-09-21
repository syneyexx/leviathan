import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { discoverFrontendReleaseTests } from "../tools/run_frontend_release_tests.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TEST_DIR = join(ROOT, "tests");

test("frontend release inventory has one canonical source and cannot silently drift", () => {
  const filesOnDisk = readdirSync(TEST_DIR, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".test.mjs"))
    .map((entry) => relative(ROOT, join(TEST_DIR, entry.name)).replaceAll("\\", "/"))
    .sort();

  assert.deepEqual(discoverFrontendReleaseTests(), filesOnDisk);
  assert.ok(filesOnDisk.includes("tests/gui-consolidation.test.mjs"));
  assert.ok(filesOnDisk.includes("tests/brain-hardening.test.mjs"));
  assert.ok(filesOnDisk.includes("tests/settings-unlimited-contracts.test.mjs"));
  assert.ok(filesOnDisk.includes("tests/brain-gateway.test.mjs"));
  assert.ok(filesOnDisk.includes("tests/release-gate-inventory.test.mjs"));

  const packageJson = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));
  assert.equal(
    packageJson.scripts["test:frontend:release"],
    "node tools/run_frontend_release_tests.mjs",
  );
  assert.match(packageJson.scripts.test, /npm run test:frontend:release/);
  assert.equal(packageJson.scripts["contracts:openapi"], "python tools/export_openapi.py");
  assert.equal(packageJson.scripts["contracts:check"], "python tools/export_openapi.py --check");

  const runner = readFileSync(join(ROOT, "tools", "run_frontend_release_tests.mjs"), "utf8");
  assert.match(
    runner,
    /--test-concurrency=1/,
    "Vite-backed release test files share one project root and must not run concurrently",
  );

  const verifier = readFileSync(join(ROOT, "verify_hades.py"), "utf8");
  assert.match(verifier, /tools\/run_frontend_release_tests\.mjs/);
  assert.doesNotMatch(verifier, /node_tests\s*=/);
});

test("CI delegates the native full-release gate to the canonical verifier", () => {
  const workflow = readFileSync(join(ROOT, ".github", "workflows", "release-gates.yml"), "utf8");
  const verifier = readFileSync(join(ROOT, "verify_hades.py"), "utf8");

  assert.match(verifier, /_native_build_and_ctest\(\)/);
  assert.match(workflow, /run: python verify_hades\.py/);
  assert.doesNotMatch(workflow, /Native configure\/build\/ctest/);
  assert.doesNotMatch(workflow, /cmake -S native -B native\/build-release-gate/);
});
