import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA coding page is live over shared runtime (no mock toast CTAs)", async () => {
  const page = await read("components/hades/finalbeta/pages/coding-page.tsx");
  const overzicht = await read("components/hades/finalbeta/pages/coding/tab-overzicht.tsx");
  const bestanden = await read("components/hades/finalbeta/pages/coding/tab-bestanden.tsx");
  const build = await read("components/hades/finalbeta/pages/coding/tab-build.tsx");
  const deploy = await read("components/hades/finalbeta/pages/coding/tab-deploy.tsx");
  const pr = await read("components/hades/finalbeta/pages/coding/tab-pull-requests.tsx");
  const branches = await read("components/hades/finalbeta/pages/coding/tab-branches.tsx");
  const settings = await read("components/hades/finalbeta/pages/coding/tab-settings.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/coding.css");
  const alias = await read("components/hades/finalbeta/hooks/use-coding-live.ts");

  assert.match(page, /useCodingLive/);
  assert.match(page, /CodingNewTaskDialog/);
  assert.match(page, /Connection lost — reconnecting/);
  assert.doesNotMatch(page, /data-toast/);
  assert.doesNotMatch(page, /\["Code analyseren", 100\]/);
  assert.match(overzicht, /coding\.recentJobs|recentJobs/);
  assert.match(overzicht, /Apply to source/);
  assert.match(bestanden, /loadWorkspaceTree|workspaceTree/);
  assert.match(bestanden, /searchSymbols|refreshSymbolIndex/);
  assert.match(build, /terminalRun|runTerminal/);
  assert.match(build, /runDebugDiagnose/);
  assert.match(deploy, /releaseConfidence|loadReleaseConfidence/);
  assert.match(deploy, /niet beschikbaar/);
  assert.match(pr, /PR-integratie niet beschikbaar/);
  assert.match(branches, /workspaceGitCommit|commitGit/);
  assert.match(branches, /niet beschikbaar/);
  assert.match(settings, /controlPatchSettings|saveControlPatch/);
  assert.match(settings, /niet van toepassing|Control Plane/);
  assert.match(alias, /useHadesCodingRuntime/);
  assert.match(css, /\.fb-root \.coding-dialog/);
  assert.match(css, /\.fb-root \.coding-page/);
});

test("FINALBETA coding tabs still export all panels", async () => {
  const barrel = await read("components/hades/finalbeta/pages/coding/index.ts");
  for (const name of [
    "CodingTabOverzicht",
    "CodingTabWijzigingen",
    "CodingTabBestanden",
    "CodingTabBranches",
    "CodingTabPullRequests",
    "CodingTabAgents",
    "CodingTabBuild",
    "CodingTabDeploy",
    "CodingTabSettings",
  ]) {
    assert.match(barrel, new RegExp(name));
  }
});
