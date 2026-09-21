import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("F-08 FINALBETA shell status uses live health (not hardcoded OK)", async () => {
  const shell = await read("components/hades/finalbeta/shell/finalbeta-shell.tsx");
  const hook = await read("components/hades/finalbeta/hooks/use-shell-health.ts");
  assert.match(shell, /useShellHealth/);
  assert.match(shell, /data-shell-health/);
  assert.match(shell, /shellHealth\.label/);
  assert.doesNotMatch(shell, /All systems operational/);
  assert.match(hook, /hadesApi\.health/);
  assert.match(hook, /tone:\s*"ok"/);
  assert.match(hook, /tone:\s*"degraded"/);
  assert.match(hook, /tone:\s*"offline"/);
});

test("F-09 settings updated event name is a shared constant", async () => {
  const events = await read("components/hades/features/settings/settings-events.ts");
  const hook = await read("components/hades/features/settings/hooks/useHadesSettings.ts");
  const ui = await read("components/hades/ui-style.tsx");
  const app = await read("components/hades/hades-app.tsx");
  assert.match(events, /HADES_SETTINGS_UPDATED_EVENT\s*=\s*"hades-settings-updated"/);
  assert.match(hook, /HADES_SETTINGS_UPDATED_EVENT/);
  assert.doesNotMatch(hook, /hades:settings-updated/);
  assert.match(ui, /HADES_SETTINGS_UPDATED_EVENT/);
  assert.match(app, /HADES_SETTINGS_UPDATED_EVENT/);
});

test("F-09 classify: failed health maps to non-OK text label", async () => {
  // Pure classification contract from the hook source (no React runtime required).
  const hook = await read("components/hades/finalbeta/hooks/use-shell-health.ts");
  assert.match(hook, /label: loading \? "Laden…" : "Offline"/);
  assert.match(hook, /label: "Probleem"/);
  assert.match(hook, /"Degraded"/);
  assert.match(hook, /"Beperkt"/);
  assert.match(hook, /"Operationeel"/);
});
