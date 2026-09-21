import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA coding page matches reference workspace layout shell", async () => {
  const page = await read("components/hades/finalbeta/pages/coding-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/coding.css");
  const index = await read("components/hades/styles/finalbeta/index.css");
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");

  assert.match(page, /coding-page/);
  assert.match(page, /Ontwikkel\. Bouw\. Automatiseer/);
  assert.match(page, /CodingTabBestanden/);
  assert.match(page, /CodingTabBranches/);
  assert.match(page, /CodingTabPullRequests/);
  assert.match(page, /CodingTabAgents/);
  assert.match(page, /CodingTabBuild/);
  assert.match(page, /CodingTabDeploy/);
  assert.match(page, /CodingTabSettings/);
  assert.match(page, /coding-full/);
  assert.match(page, /useCodingLive/);
  assert.match(page, /Taakuitvoering|Coding job|Repository/);
  assert.match(css, /\.fb-root \.coding-page/);
  assert.match(css, /\.fb-root \.coding-diff-body/);
  assert.match(css, /\.fb-root \.coding-terminal/);
  assert.match(css, /\.fb-root \.coding-app\.coding-full/);
  assert.match(index, /@import "\.\/v2\/coding\.css"/);
  assert.match(index, /@import "\.\/v2\/coding-tabs-a\.css"/);
  assert.match(index, /@import "\.\/v2\/coding-tabs-b\.css"/);
  assert.match(app, /page === "coding"/);
});

test("FINALBETA coding tabs export all panels", async () => {
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
