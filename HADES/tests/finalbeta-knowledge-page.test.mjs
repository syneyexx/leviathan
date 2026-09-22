import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA knowledge page matches Knowledge Library pixel mock", async () => {
  const page = await read("components/hades/finalbeta/pages/knowledge-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/knowledge-library-pixel.css");
  const mocks = await read("components/hades/finalbeta/mocks/knowledge-library-pixel.ts");
  const index = await read("components/hades/styles/finalbeta/index.css");

  assert.match(page, /export function KnowledgePage\(\{ onNavigate \}/);
  assert.match(page, /FinalBetaShell/);
  assert.match(page, /appClassName="klib-app"/);
  assert.match(page, /mainClassName="klib-main"/);
  assert.match(page, /page="knowledge"/);
  assert.match(page, /KNOWLEDGE LIBRARY|Knowledge Library/i);
  assert.match(page, /from ["']\.\.\/mocks\/knowledge-library-pixel["']/);
  assert.doesNotMatch(page, /useHadesKnowledge/);
  assert.doesNotMatch(page, /data-live="knowledge"/);

  assert.match(css, /\.fb-root \.klib-page|\.fb-root \.klib-app/);
  assert.match(index, /@import "\.\/v2\/knowledge-library-pixel\.css"/);

  assert.match(mocks, /482K|Kennisitems/i);
  assert.match(mocks, /VERZAMELEN|STRUCTUREREN/i);
});
