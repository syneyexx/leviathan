/**
 * FINALBETA Coding repair contracts: model_id plumbing, failure reasons, preflight, terminals.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function read(rel) {
  return fs.readFileSync(path.join(root, rel), "utf8");
}

test("submitBuild passes model_id on sync and async goal paths", () => {
  const src = read("components/hades/features/coding/hooks/useHadesCodingRuntime.ts");
  assert.match(src, /buildFromGoalAsync\(\{[\s\S]*model_id:\s*resolvedModelId/);
  assert.match(src, /buildFromGoal\(\{[\s\S]*model_id:\s*resolvedModelId/);
});

test("JOB_TERMINAL includes honest mutation failure statuses", () => {
  const src = read("components/hades/features/coding/coding-runtime-core.ts");
  for (const status of [
    "no_change",
    "implementation_missing",
    "model_output_invalid",
    "model_unavailable",
  ]) {
    assert.match(src, new RegExp(`"${status}"`));
  }
});

test("default test suite is auto", () => {
  const src = read("components/hades/features/coding/hooks/useHadesCodingRuntime.ts");
  assert.match(src, /useState<CodingTestSuite>\("auto"\)/);
});

test("extractCodingFailureReason and preflight exist for FINALBETA UI", () => {
  const core = read("components/hades/features/coding/coding-runtime-core.ts");
  assert.match(core, /export function extractCodingFailureReason/);
  assert.match(core, /export function evaluateCodingPreflightClient/);
  assert.match(core, /Geen bruikbaar Coding-model beschikbaar/);
  assert.match(core, /Analyze-only: deze taak mag geen bestanden wijzigen/);

  const dialog = read("components/hades/finalbeta/pages/coding/dialogs/new-task-dialog.tsx");
  assert.match(dialog, /coding-preflight/);
  assert.match(dialog, /coding\.preflight/);

  const overview = read("components/hades/finalbeta/pages/coding/tab-overzicht.tsx");
  assert.match(overview, /codingFailureReason/);
});

test("attachJob does not wipe persisted job identity on transient failure", () => {
  const src = read("components/hades/features/coding/hooks/useHadesCodingRuntime.ts");
  // Must keep identity; must not clear active job on catch.
  assert.match(src, /Transient fetch failure must not destroy persisted active-job identity/);
  const catchIdx = src.indexOf("Transient fetch failure");
  const window = src.slice(catchIdx, catchIdx + 250);
  assert.doesNotMatch(window, /persistActiveJobId\(null\)/);
  assert.doesNotMatch(window, /setActiveJobId\(null\)/);
});

test("polling effect does not depend on mutable jobEventCursor", () => {
  const src = read("components/hades/features/coding/hooks/useHadesCodingRuntime.ts");
  assert.match(src, /jobEventCursorRef/);
  assert.match(
    src,
    /}, \[activeJobId, jobObserving, refreshRecentJobs\]\);/,
  );
});
