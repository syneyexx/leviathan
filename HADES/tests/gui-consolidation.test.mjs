import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const REMOVED_TREES = [
  "components/hades/v3",
  "components/hades/v4",
  "components/hades/beta",
  "components/hades/beta-gui",
  "components/hades/beta2",
  "components/hades/obsidian",
  "components/hades/styles/v3",
  "components/hades/styles/v4",
  "components/hades/styles/beta",
  "components/hades/styles/beta-gui",
  "components/hades/styles/obsidian",
  "public/beta-reference",
  "public/beta2",
  "docs/BETA2_DASHBOARD.md",
  "docs/V3_INTERFACE.md",
  "tests/v3-template.test.mjs",
  "tests/v4-template.test.mjs",
  "tests/beta-template.test.mjs",
  "tests/beta-reference-master.test.mjs",
];

const CANONICAL_PAGES = [
  "chat",
  "research",
  "files",
  "memory",
  "models",
  "settings",
  "tasks",
  "coding-agent",
  "mission-control",
  "workflows",
  "agents",
  "media",
  "plugins",
  "mcp",
  "brain",
  "trading",
];

test("obsolete alternate interfaces are removed from the repository", () => {
  for (const tree of REMOVED_TREES) {
    assert.equal(existsSync(new URL(`../${tree}`, import.meta.url)), false, `obsolete tree still present: ${tree}`);
  }
});

test("main.tsx mounts the authoritative HadesApp only", async () => {
  const main = await read("main.tsx");
  assert.match(main, /from ["']@\/components\/hades\/hades-app["']/);
  assert.match(main, /<HadesApp\s*\/>/);
  assert.match(main, /styles\/lux\/index\.css/);
  assert.doesNotMatch(main, /V3TemplateGate/);
  assert.doesNotMatch(main, /V3App|V4App|BetaReferenceApp|BetaApp/);
});

test("Settings Interface offers Lux and FINALBETA", async () => {
  const settings = await read("components/hades/pages/settings-page.tsx");
  assert.match(settings, /HADES Lux/);
  assert.match(settings, /FINALBETA/);
  assert.doesNotMatch(settings, /HADES Classic/);
  assert.doesNotMatch(settings, /HADES Obsidian/);
  assert.doesNotMatch(settings, /HADES V3|HADES V4/);
});

test("canonical main routes remain declared in HadesApp", async () => {
  const app = await read("components/hades/hades-app.tsx");
  for (const page of CANONICAL_PAGES) {
    assert.ok(app.includes(`"${page}"`) || app.includes(`'${page}'`), `missing main route ${page}`);
  }
  assert.match(app, /LuxShell/);
  assert.match(app, /FinalBetaApp/);
});

test("documentation points to Lux as the product interface", async () => {
  const style = await read("docs/UI_STYLE_SYSTEM.md");
  const map = await read("docs/HADES_CODEBASE_MAP.md");
  assert.match(style, /Lux/);
  assert.doesNotMatch(style, /selectable HADES interface based on the approved light Alpine V3/);
  assert.doesNotMatch(map, /v3-template-gate/);
});
