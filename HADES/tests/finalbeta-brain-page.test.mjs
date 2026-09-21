import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA brain page matches knowledge-graph reference layout", async () => {
  const page = await read("components/hades/finalbeta/pages/brain-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/brain.css");
  const index = await read("components/hades/styles/finalbeta/index.css");
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");
  const hook = await read("components/hades/features/brain/hooks/useHadesBrain.ts");

  assert.match(page, /brain-page/);
  assert.match(page, /data-live="brain"/);
  assert.match(page, /useHadesBrain/);
  assert.match(hook, /hadesApi\.brain/);
  assert.match(page, /Connections create clarity/);
  assert.match(page, /Brain Nodes/);
  assert.match(page, /Zoek in de brain/);
  assert.match(page, /brain-graph/);
  assert.match(page, /Node details/);
  assert.match(page, /Live sync actief/);
  assert.match(page, /Geen brain-nodes/);
  assert.doesNotMatch(page, /const CLUSTERS/);
  assert.doesNotMatch(page, /AI & Language Models/);
  assert.match(css, /\.fb-root \.brain-page/);
  assert.match(index, /@import "\.\/v2\/brain\.css"/);
  assert.match(app, /page === "brain"/);
});
