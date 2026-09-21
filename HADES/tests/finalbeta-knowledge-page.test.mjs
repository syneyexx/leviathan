import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA knowledge page matches Knowledge Library reference layout", async () => {
  const page = await read("components/hades/finalbeta/pages/knowledge-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/knowledge.css");
  const mocks = await read("components/hades/finalbeta/mocks/knowledge.ts");

  assert.match(page, /useHadesKnowledge/);
  assert.match(page, /data-live="knowledge"/);
  assert.doesNotMatch(page, /mockKnowledgeDocs/);
  assert.match(page, /export function KnowledgePage\(\{ onNavigate \}/);
  assert.match(page, /FinalBetaShell/);
  assert.match(page, /appClassName="knowledge-app"/);
  assert.match(page, /mainClassName="knowledge-main"/);
  assert.match(page, /page="knowledge"/);
  assert.match(page, /Knowledge Library/);
  assert.match(page, /Knowledge organized today, intelligence tomorrow/);
  assert.match(page, /From information to intelligence/);
  assert.match(page, /Totaal documenten|KNOWLEDGE_STATS/);
  assert.match(page, /Collecties/);
  assert.match(page, /Opslaggebruik|KNOWLEDGE_STORAGE/);
  assert.match(page, /Documenten/);
  assert.match(page, /Uploaden/);
  assert.match(page, /Map aanmaken/);
  assert.match(page, /Export/);
  assert.match(page, /AI-samenvatting/);
  assert.match(page, /Broncollectie/);
  assert.match(page, /Acties/);
  assert.match(page, /KNOWLEDGE_ACTIONS/);
  assert.match(page, /selected\.name|selectedId/);
  assert.match(mocks, /Verwijderen/);

  assert.match(css, /\.fb-root \.knowledge-page/);
  assert.match(css, /\.fb-root \.knowledge-app/);
  assert.match(css, /\.fb-root \.knowledge-stats/);
  assert.match(css, /\.fb-root \.knowledge-split/);
  assert.match(css, /\.fb-root \.knowledge-col-item\.active/);
  assert.match(css, /\.fb-root \.knowledge-table/);
  assert.match(css, /\.fb-root \.knowledge-action-grid/);
  assert.match(css, /\.fb-root \.knowledge-insp-quote/);

  assert.match(mocks, /EU_AI_Act_final\.pdf/);
  assert.match(mocks, /1\.236|1236/);
  assert.match(mocks, /42\.8 GB/);
  assert.match(mocks, /EU & Regulering/);
  assert.match(mocks, /Herschrijven samenvatting/);
  assert.equal((mocks.match(/id: "d\d+"/g) || []).length >= 10, true);
  assert.equal((mocks.match(/label: "/g) || []).length >= 13, true);
});
