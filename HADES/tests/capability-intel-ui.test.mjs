import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("capability intelligence UI lives only on the main interface", async () => {
  const plugins = await read("components/hades/pages/plugins-page-core.tsx");
  const groups = await read("components/hades/features/plugins/PluginCapabilityGroups.tsx");
  const chat = await read("components/hades/features/chat/ContextTurnPanel.tsx");
  const api = await read("lib/api/plugins.ts");
  assert.match(plugins, /PluginCapabilityGroups/);
  assert.match(groups, /capability-groups/);
  assert.match(chat, /Capability intelligence/);
  assert.match(chat, /mutation_owner|composed/);
  assert.match(api, /capability-intel\/plugins/);
  assert.equal(existsSync(new URL("../components/hades/v3", import.meta.url)), false);
  assert.equal(existsSync(new URL("../components/hades/beta", import.meta.url)), false);
});

test("main plugin page still owns product plugin lifecycle", async () => {
  const plugins = await read("components/hades/pages/plugins-page-core.tsx");
  assert.match(plugins, /hadesApi\.plugins/);
  assert.match(plugins, /invokePlugin/);
});
