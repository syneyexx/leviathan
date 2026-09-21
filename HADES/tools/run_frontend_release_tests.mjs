#!/usr/bin/env node

import { readdirSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TEST_DIR = join(ROOT, "tests");

/**
 * Return the deterministic frontend release-test inventory.
 *
 * Policy: every top-level tests/*.test.mjs file is release-required. Tests that
 * need live providers, host hardware, credentials, or other optional capability
 * must live outside this directory and be invoked by an explicit host/eval gate.
 */
export function discoverFrontendReleaseTests() {
  return readdirSync(TEST_DIR, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".test.mjs"))
    .map((entry) => relative(ROOT, join(TEST_DIR, entry.name)).replaceAll("\\", "/"))
    .sort();
}

export function runFrontendReleaseTests() {
  const tests = discoverFrontendReleaseTests();
  if (tests.length === 0) {
    console.error("[release] No frontend release tests discovered under tests/*.test.mjs");
    return 2;
  }

  console.log(`[release] Running ${tests.length} canonical frontend release test files:`);
  for (const test of tests) {
    console.log(`  - ${test}`);
  }

  // Several canonical test files intentionally create a Vite middleware/SSR
  // server against the same project root. Running those files concurrently lets
  // independent Vite instances race over the dependency optimizer cache and HMR
  // websocket (24678), which can invalidate module graphs mid-render and produce
  // false React hook failures. File-level serialization removes that shared-state
  // race; individual tests inside each file still use Node's normal concurrency.
  const completed = spawnSync(process.execPath, ["--test", "--test-concurrency=1", ...tests], {
    cwd: ROOT,
    stdio: "inherit",
  });

  if (completed.error) {
    console.error("[release] Failed to start Node test runner:", completed.error.message);
    return 2;
  }
  return completed.status ?? 2;
}

const invokedDirectly = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) {
  process.exitCode = runFrontendReleaseTests();
}
