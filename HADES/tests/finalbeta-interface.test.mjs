import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const FINALBETA_PAGES = [
  "login", "dashboard", "chat", "coding", "tasks",
  "models", "model-training", "agents", "llm-stats",
  "dataset-management", "offline-datasets", "datasets",
  "media", "youtube", "tiktok", "instagram", "facebook",
  "media-queue", "media-viral", "media-calendar", "media-analytics", "media-library", "media-personas",
  "trading-simulation", "trading-strategies", "trading-marketdata", "trading-portfolio", "trading-paper", "trading-broker",
  "research", "brain", "memory", "knowledge", "evidence", "files",
  "performance", "tools", "mcp", "workflows",
  "settings-general", "settings-interface", "settings-llm-behavior", "settings-llm-studio",
  "settings-security", "settings-benchmarks", "settings-storage", "settings-python",
  "settings-console", "settings-logs", "settings-backups",
];

const HOOFDMENU_LABELS = [
  "Hades AI",
  "LLM",
  "Media Control",
  "TradingCenter",
  "Onderzoek & Kennis",
  "Plugin & Runtime",
  "Instellingen",
];

test("FINALBETA tree is isolated under components/hades/finalbeta", () => {
  assert.ok(existsSync(new URL("../components/hades/finalbeta/finalbeta-app.tsx", import.meta.url)));
  assert.ok(existsSync(new URL("../components/hades/finalbeta/shell/finalbeta-shell.tsx", import.meta.url)));
  assert.ok(existsSync(new URL("../components/hades/styles/finalbeta/index.css", import.meta.url)));
  assert.ok(existsSync(new URL("../components/hades/styles/finalbeta/v2/hades.css", import.meta.url)));
  assert.ok(existsSync(new URL("../components/hades/styles/finalbeta/v2/dashboard.css", import.meta.url)));
  assert.ok(existsSync(new URL("../components/hades/styles/finalbeta/v2/login.css", import.meta.url)));
  assert.ok(existsSync(new URL("../public/finalbeta/mountain-scene.png", import.meta.url)));
  assert.ok(existsSync(new URL("../public/finalbeta/login-hero.png", import.meta.url)));
});

test("FINALBETA pages and settings switch exist", async () => {
  const routes = await read("components/hades/finalbeta/routes.ts");
  for (const page of FINALBETA_PAGES) {
    assert.ok(routes.includes(`"${page}"`), `missing route id ${page}`);
  }
  assert.ok(existsSync(new URL("../components/hades/finalbeta/pages/finalbeta-settings-page.tsx", import.meta.url)));
  assert.ok(existsSync(new URL("../components/hades/finalbeta/pages/login-page.tsx", import.meta.url)));
  const settings = await read("components/hades/finalbeta/pages/finalbeta-settings-page.tsx");
  assert.match(settings, /FINALBETA/);
  assert.match(settings, /applyStyle\("lux"\)/);
});

test("FINALBETA HOOFDMENU and section SUBMENU are wired", async () => {
  const routes = await read("components/hades/finalbeta/routes.ts");
  const shell = await read("components/hades/finalbeta/shell/finalbeta-shell.tsx");
  assert.match(routes, /FINALBETA_HOOFDMENU/);
  assert.match(routes, /home:\s*"dashboard"/);
  assert.match(routes, /id:\s*"dashboard".*label:\s*"Dashboard"/s);
  assert.match(shell, /home:\s*"dashboard"/);
  assert.match(shell, /aria-label="Hoofdmenu"/);
  assert.match(shell, /aria-label="Submenu"/);
  for (const label of HOOFDMENU_LABELS) {
    assert.ok(routes.includes(label), `missing HOOFDMENU label ${label}`);
  }
  assert.match(routes, /llm-stats/);
  assert.match(routes, /dataset-management/);
  assert.match(routes, /offline-datasets/);
  assert.match(routes, /datasets/);
  assert.match(routes, /Statestieken/);
  assert.match(routes, /Dataset Management/);
  assert.match(routes, /Offline Datasets/);
  assert.match(routes, /label:\s*"Datasets"/);
  assert.match(routes, /label:\s*"Training"/);
  assert.doesNotMatch(routes, /label:\s*"Bestanden"/);
  assert.match(routes, /trading-simulation/);
  assert.match(routes, /settings-console/);
  assert.match(routes, /media-queue/);
  assert.match(routes, /model-training/);
  assert.ok(routes.includes('"youtube"'));
  assert.ok(routes.includes('"Chatten"') || routes.includes("Chatten"));
  assert.match(routes, /resolveFinalBetaPageId/);
  assert.match(routes, /mission-control.*tasks|return "tasks"/);
  assert.match(routes, /files.*datasets|return "datasets"/);
});

test("FINALBETA starts on login via hash default", async () => {
  const routes = await read("components/hades/finalbeta/routes.ts");
  assert.match(routes, /return "login"/);
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");
  assert.match(app, /LoginPage/);
  assert.match(app, /TasksPage/);
  assert.match(app, /ModelTrainingPage/);
  assert.match(app, /YoutubePage/);
  assert.match(app, /LlmStatsPage/);
  assert.match(app, /TradingSimulationPage/);
});

test("FINALBETA v2 styles stay scoped under .fb-root", async () => {
  const indexCss = await read("components/hades/styles/finalbeta/index.css");
  const tokensCss = await read("components/hades/styles/finalbeta/tokens.css");
  const contractCss = await read("components/hades/styles/finalbeta/contract.css");
  const hadesCss = await read("components/hades/styles/finalbeta/v2/hades.css");
  const dashCss = await read("components/hades/styles/finalbeta/v2/dashboard.css");
  const loginCss = await read("components/hades/styles/finalbeta/v2/login.css");
  assert.match(indexCss, /@import "\.\/tokens\.css"/);
  assert.match(indexCss, /@import "\.\/v2\/hades\.css"/);
  assert.match(indexCss, /@import "\.\/v2\/dashboard\.css"/);
  assert.match(indexCss, /@import "\.\/v2\/login\.css"/);
  assert.match(indexCss, /@import "\.\/contract\.css"/);
  assert.match(tokensCss, /--hades-panel-bg:\s*#001723/);
  assert.match(tokensCss, /--hades-border:\s*#013245/);
  assert.match(tokensCss, /--hades-gold:\s*#eab94f/i);
  assert.match(tokensCss, /--hades-cyan:\s*#3ac7ee/i);
  assert.match(tokensCss, /--hades-sidebar-width:\s*232px/);
  assert.match(contractCss, /\.fb-root \.card/);
  assert.match(hadesCss, /\.fb-root/);
  assert.match(hadesCss, /\/finalbeta\/mountain-scene\.png/);
  assert.match(dashCss, /\.fb-root/);
  assert.match(loginCss, /\/finalbeta\/login-hero\.png/);
  assert.doesNotMatch(hadesCss, /^:root\{/m);
});

test("HadesApp can mount FinalBetaApp without replacing Lux default", async () => {
  const app = await read("components/hades/hades-app.tsx");
  const style = await read("components/hades/ui-style.tsx");
  assert.match(app, /FinalBetaApp/);
  assert.match(app, /uiStyle === "finalbeta"/);
  assert.match(style, /"lux" \| "finalbeta"/);
  assert.match(style, /value === "finalbeta"/);
  assert.match(style, /return "lux"/);
});
