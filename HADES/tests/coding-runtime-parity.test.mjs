import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const CODING_API_METHODS = [
  "buildPlan",
  "buildRun",
  "buildFromGoal",
  "buildFromGoalAsync",
  "buildJobsList",
  "buildOmnirouteStatus",
  "buildJobGet",
  "buildJobEvents",
  "buildJobCancel",
  "buildJobPause",
  "buildJobResume",
  "buildJobRedirect",
  "buildJobsRecover",
  "buildApply",
  "buildConflicts",
  "buildPreview",
  "buildRestore",
  "terminalRun",
  "searchSymbols",
  "refreshSymbols",
  "workspaceTree",
  "workspacePreview",
  "workspaceOpenExternal",
  "workspaceGitStatus",
  "workspaceGitCommit",
  "codeDefinition",
  "codeReferences",
  "codeOutline",
  "debugDiagnose",
  "releaseConfidence",
  "releaseConfidenceSmoke",
  "gen2EvalHumanRating",
  "controlValues",
  "controlPatchSettings",
];

test("coding runtime parity: shared hook consumes Coding-relevant hadesApi methods", async () => {
  const runtime = await read("components/hades/features/coding/hooks/useHadesCodingRuntime.ts");
  const matrix = await read("docs/architecture/finalbeta-coding-parity-matrix.md");
  const missing = [];
  for (const method of CODING_API_METHODS) {
    if (!runtime.includes(`hadesApi.${method}`) && !runtime.includes(`hadesApi.${method}(`)) {
      // controlPatchSettings / recover / outline must be present
      missing.push(method);
    }
  }
  assert.deepEqual(missing, [], `Missing API usage in shared runtime: ${missing.join(", ")}`);
  assert.match(matrix, /Missing \| 0/);
  assert.match(matrix, /NOT APPLICABLE — no GitHub PR API/);
  assert.match(matrix, /no `\/workspace\/git\/branch/);
});

test("FINALBETA Coding is canonical consumer of shared runtime", async () => {
  const page = await read("components/hades/finalbeta/pages/coding-page.tsx");
  const alias = await read("components/hades/finalbeta/hooks/use-coding-live.ts");
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");
  const card = await read("components/hades/features/chat/CodingCard.tsx");
  assert.match(alias, /useHadesCodingRuntime as useCodingLive/);
  assert.match(page, /useCodingLive/);
  assert.match(app, /#\/coding-agent/);
  assert.match(app, /#\/fb\/coding/);
  assert.match(card, /\/fb\/coding\?codingJob=/);
});
