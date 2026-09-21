/**
 * Settings form helpers: Unlimited null must survive theme-only diffs.
 * Security policies (network/file/subprocess) must persist immediately.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = readFileSync(join(root, "components/hades/pages/settings-page.tsx"), "utf8");

test("toSettingsForm preserves null instead of coercing Unlimited", () => {
  assert.match(src, /incoming\[key\] === undefined/);
  assert.doesNotMatch(src, /incoming\[key\] === null \|\| incoming\[key\] === undefined/);
  assert.match(src, /diffSettingsPatch/);
  assert.match(src, /patchSettings/);
  assert.match(src, /configRevision/);
});

test("settings save uses sync refs to avoid stale Select→Save races", () => {
  assert.match(src, /settingsRef/);
  assert.match(src, /configRevisionRef/);
  assert.match(src, /const current = settingsRef\.current/);
  assert.match(src, /diffSettingsPatch\(baselineRef\.current, current\)/);
  assert.match(src, /Modelprofiel opgeslagen/);
});

test("network and sibling policies persist immediately via persistPolicy", () => {
  assert.match(src, /persistPolicy/);
  assert.match(src, /persistPolicy\("network_policy"/);
  assert.match(src, /persistPolicy\("file_read_policy"/);
  assert.match(src, /persistPolicy\("file_write_policy"/);
  assert.match(src, /persistPolicy\("subprocess_policy"/);
  assert.match(src, /Beleid '\$\{key\}' is niet bevestigd door de backend/);
});

test("volume truthiness fallback removed from chat settings load", () => {
  const chat = readFileSync(join(root, "components/hades/pages/chat-page.tsx"), "utf8");
  assert.doesNotMatch(chat, /Number\(values\.voice_tts_volume\)\s*\|\|\s*1/);
  assert.match(chat, /Number\(values\.voice_tts_volume \?\? 1\)/);
});

test("shell merges partial hades-settings-updated events", () => {
  const app = readFileSync(join(root, "components/hades/hades-app.tsx"), "utf8");
  assert.match(app, /setAppSettings\(\(prev\) => \(prev \? \{ \.\.\.prev, \.\.\.values \} :/);
});
