import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("Lux concept reference is present", async () => {
  assert.ok(existsSync(new URL("../docs/design/hades-lux-concept.png", import.meta.url)));
  assert.ok(existsSync(new URL("../docs/design/HADES_LUX_CONCEPT.md", import.meta.url)));
  const concept = await read("docs/design/HADES_LUX_CONCEPT.md");
  assert.match(concept, /Lux Atelier/);
});

test("BETA PRIMUS and BETA2 preview contracts are retired", () => {
  assert.equal(existsSync(new URL("../components/hades/beta-gui", import.meta.url)), false);
  assert.equal(existsSync(new URL("../components/hades/beta2", import.meta.url)), false);
  assert.equal(existsSync(new URL("../public/beta2", import.meta.url)), false);
  assert.equal(existsSync(new URL("../docs/BETA2_DASHBOARD.md", import.meta.url)), false);
});
