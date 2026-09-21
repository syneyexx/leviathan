import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const luxCss = ["tokens.css", "shell.css", "pages-bridge.css", "index.css"];

test("ui_style defaults to lux and keeps motion", async () => {
  const database = await read("backend/database.py");
  const api = await read("lib/hades-api.ts");
  assert.match(database, /"ui_style"\s*:\s*"lux"/);
  assert.match(database, /"motion_level"/);
  assert.match(api, /ui_style: "lux"/);
  assert.match(api, /motion_level:/);
});

test("Lux style system is complete and imported", async () => {
  for (const file of luxCss) {
    const path = `components/hades/styles/lux/${file}`;
    assert.ok(existsSync(new URL(`../${path}`, import.meta.url)), `missing ${path}`);
  }
  const styles = await Promise.all(luxCss.map((file) => read(`components/hades/styles/lux/${file}`)));
  assert.match(styles.join("\n"), /--lux-gold/);
  assert.match(styles.join("\n"), /\.lux-shell/);
  assert.ok(existsSync(new URL("../components/hades/lux/lux-shell.tsx", import.meta.url)));
  const main = await read("main.tsx");
  assert.match(main, /styles\/lux\/index\.css/);
});

test("Interface tab documents Lux + FINALBETA and keeps motion control", async () => {
  const settingsPage = await read("components/hades/pages/settings-page.tsx");
  assert.match(settingsPage, /HADES Lux/);
  assert.match(settingsPage, /FINALBETA/);
  assert.match(settingsPage, /applyMotionLevel/);
  assert.match(settingsPage, /motion_level/);
  assert.doesNotMatch(settingsPage, /HADES Classic/);
  assert.doesNotMatch(settingsPage, /HADES Obsidian/);
  assert.doesNotMatch(settingsPage, /BETA 2/);
});

test("legacy Obsidian BETA BETA2 shells are removed", async () => {
  assert.equal(existsSync(new URL("../components/hades/obsidian", import.meta.url)), false);
  assert.equal(existsSync(new URL("../components/hades/beta-gui", import.meta.url)), false);
  assert.equal(existsSync(new URL("../components/hades/beta2", import.meta.url)), false);
  assert.equal(existsSync(new URL("../components/hades/styles/obsidian", import.meta.url)), false);
  assert.equal(existsSync(new URL("../components/hades/styles/beta-gui", import.meta.url)), false);
  assert.equal(existsSync(new URL("../public/beta2", import.meta.url)), false);
  assert.equal(existsSync(new URL("../docs/BETA2_DASHBOARD.md", import.meta.url)), false);
  const globals = await read("app/globals.css");
  assert.doesNotMatch(globals, /interface-preset-card--beta2/);
});

test("backend accepts lux, finalbeta and legacy ui_style values", async () => {
  const backend = await read("backend/main.py");
  const definitions = await read("backend/control/definitions.py");
  assert.match(backend, /Literal\["lux", "finalbeta", "classic", "obsidian", "beta", "beta2"\]/);
  assert.match(definitions, /"lux"/);
  assert.match(definitions, /"finalbeta"/);
});

test("HadesApp mounts LuxShell by default and can mount FinalBetaApp", async () => {
  const app = await read("components/hades/hades-app.tsx");
  assert.match(app, /LuxShell/);
  assert.match(app, /FinalBetaApp/);
  assert.doesNotMatch(app, /ObsidianShell|BetaShell|Beta2Shell/);
  assert.match(app, /group: "werk"/);
  assert.match(app, /group: "kennis"/);
  assert.match(app, /group: "systeem"/);
  for (const page of [
    "chat", "tasks", "mission-control", "workflows", "agents", "coding-agent", "research",
    "trading", "media", "plugins", "mcp", "brain", "models", "memory", "files", "settings",
  ]) {
    assert.ok(app.includes(`"${page}"`), `missing page ${page}`);
  }
});

test("Lux shell restores Classic shell capabilities without mock shells", async () => {
  const app = await read("components/hades/hades-app.tsx");
  const shell = await read("components/hades/lux/lux-shell.tsx");
  assert.match(app, /finishOnboarding/);
  assert.match(app, /onboardingOpen/);
  assert.match(app, /DialogTitle>Welkom bij HADES/);
  assert.match(shell, /lux-health-panel/);
  assert.match(shell, /healthOpen/);
  assert.match(shell, /health\.checks/);
  assert.match(shell, /Open Chat-diagnose/);
  const luxShellCss = await readFile(new URL("../components/hades/styles/lux/shell.css", import.meta.url), "utf8");
  assert.match(luxShellCss, /\.lux-topbar\s*\{[^}]*z-index:\s*30/s);
  assert.match(luxShellCss, /\.lux-health-panel/);
  assert.match(shell, /network_policy/);
  assert.match(shell, /Local core/);
  assert.match(shell, /Privé/);
  assert.match(shell, /lux-mobile-trigger/);
  assert.doesNotMatch(shell, /mockdata|Mock data|sample-only/i);
  assert.doesNotMatch(app, /BetaShell|ObsidianShell|Beta2Shell/);
});

test("UiStyleProvider supports lux and finalbeta", async () => {
  const provider = await read("components/hades/ui-style.tsx");
  assert.match(provider, /export type UiStyle = "lux" \| "finalbeta"/);
  assert.match(provider, /coerceUiStyle/);
  assert.match(provider, /dataset\.hadesStyle = uiStyle/);
  assert.match(provider, /finalbeta/);
});
