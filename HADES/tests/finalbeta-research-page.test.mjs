import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA research page is live ResearchRunner UI with shell preserved", async () => {
  const page = await read("components/hades/finalbeta/pages/research-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/research.css");
  const hook = await read("components/hades/features/research/hooks/useHadesResearch.ts");

  assert.match(page, /export function ResearchPage\(\{ onNavigate \}/);
  assert.match(page, /FinalBetaShell/);
  assert.match(page, /page="research"/);
  assert.match(page, /data-live="research"/);
  assert.match(page, /useHadesResearch/);
  assert.match(page, /Zoek, analyseer en verzamel betrouwbare informatie/);
  assert.match(page, /Nieuw onderzoek/);
  assert.match(page, /Research status/);
  assert.match(page, /Bronverdeling/);
  assert.match(hook, /hadesApi\.research/);
  assert.match(hook, /createResearch|hadesApi\.createResearch/);
  assert.match(hook, /applyResearchRobotsPolicy/);
  assert.doesNotMatch(page, /mockResearchResults/);
  assert.doesNotMatch(page, /RESEARCH_STATUS_CHECKS/);
  assert.doesNotMatch(page, /useState\("res1"\)/);

  assert.match(css, /\.fb-root \.research-page/);
});
