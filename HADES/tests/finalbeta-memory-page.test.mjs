import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA memory page matches Geheugen reference layout", async () => {
  const page = await read("components/hades/finalbeta/pages/memory-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/memory.css");
  const index = await read("components/hades/styles/finalbeta/index.css");
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");

  assert.match(page, /useHadesMemory/);
  assert.match(page, /data-live="memory"/);
  assert.doesNotMatch(page, /mockMemories/);
  assert.match(page, /memory-page/);
  assert.match(page, /Context turns information into intelligence/);
  assert.match(page, /Recente herinneringen/);
  assert.match(page, /Geheugen categorieën/);
  assert.match(page, /Populaire tags/);
  assert.match(page, /Geheugen gezondheid/);
  assert.match(page, /Gekoppelde gesprekken/);
  assert.match(page, /Snelle acties/);
  assert.match(page, /Herinnering details/);
  assert.match(css, /\.fb-root \.memory-page/);
  assert.match(css, /\.fb-root \.memory-stats/);
  assert.match(css, /\.fb-root \.mem-row\.active/);
  assert.match(index, /@import "\.\/v2\/memory\.css"/);
  assert.match(app, /page === "memory"/);
});
