/**
 * SSR markup evidence for HADES voice UI controls (no mic required).
 */

import assert from "node:assert/strict";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true, hmr: false },
});
const { renderComponentToStaticMarkup } = await vite.ssrLoadModule("/tests/helpers/vite-ssr-renderer.tsx");

after(async () => vite.close());

test("VoiceComposerControls renders dictation and conversation actions", async () => {
  const { VoiceComposerControls } = await vite.ssrLoadModule("/components/hades/voice/voice-composer-controls.tsx");
  const html = renderComponentToStaticMarkup(VoiceComposerControls, {
    spokenAnswers: true,
    speaking: true,
    onToggleDictation: () => undefined,
    onStartConversation: () => undefined,
    onStopSpeaking: () => undefined,
    onSpokenAnswersChange: () => undefined,
  });
  assert.match(html, /Dictatie/);
  assert.match(html, /Spraakgesprek/);
  assert.match(html, /Stop spreken/);
  // Spoken-answers toggle lives in the chat title bar (no duplicate in composer).
  assert.doesNotMatch(html, /Gesproken antwoorden/);
});

test("VoicePanel renders interrupt and settings affordances", async () => {
  const { VoicePanel } = await vite.ssrLoadModule("/components/hades/voice/voice-panel.tsx");
  const html = renderComponentToStaticMarkup(VoicePanel, {
    status: "Spreekt",
    micActive: true,
    audioPlaying: true,
    modelGenerating: false,
    turnMode: "continuous",
    lastInterruptLatencyMs: 42,
    onInterrupt: () => undefined,
    onStop: () => undefined,
    onOpenSettings: () => undefined,
    onToggleOutputMute: () => undefined,
  });
  assert.match(html, /Spraakgesprek/);
  assert.match(html, /Onderbreek/);
  assert.match(html, /Instellingen/);
  assert.match(html, /42 ms/);
});

test("VoiceMessageActions renders replay without duplicating Voorlezen", async () => {
  const { VoiceMessageActions } = await vite.ssrLoadModule("/components/hades/voice/voice-message-actions.tsx");
  const html = renderComponentToStaticMarkup(VoiceMessageActions, {
    onSpeak: () => undefined,
    onReplay: () => undefined,
    onStop: () => undefined,
  });
  // Primary Voorlezen is owned by ChatPage; this strip only exposes replay/stop.
  assert.doesNotMatch(html, /Voorlezen/);
  assert.match(html, /Opnieuw afspelen/);
});
