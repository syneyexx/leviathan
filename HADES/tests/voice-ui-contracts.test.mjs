/**
 * Browser/source contracts for HADES voice UI wiring.
 * Controlled-audio E2E (Playwright + fake MediaStream) belongs on the Windows host;
 * this suite locks UI contracts so mic/speak/session controls cannot silently regress.
 */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("Chat exposes dictation, spoken answers, conversation, stop, and read-aloud controls", async () => {
  const chat = await read("components/hades/pages/chat-page.tsx");
  const composer = await read("components/hades/voice/voice-composer-controls.tsx");
  const actions = await read("components/hades/voice/voice-message-actions.tsx");
  const panel = await read("components/hades/voice/voice-panel.tsx");
  assert.match(composer, /Dictatie/);
  assert.match(composer, /Spraakgesprek/);
  assert.match(composer, /Gesproken antwoorden/);
  assert.match(composer, /Stop spreken/);
  assert.match(actions, /Voorlezen/);
  assert.match(actions, /Opnieuw afspelen/);
  assert.match(panel, /Mic dempen|Microfoon dempen|Mic aan/);
  assert.match(panel, /Audio dempen|Audio aan/);
  assert.match(panel, /Instellingen/);
  assert.match(chat, /VoiceComposerControls/);
  assert.match(chat, /VoiceMessageActions/);
  assert.match(chat, /VoicePanel/);
  assert.match(chat, /useVoiceDictation/);
  assert.match(chat, /useVoiceSession/);
  assert.match(chat, /useVoicePlayback/);
  // Spoken answers must not speak provisional stream text.
  assert.match(chat, /assistant_message\.content/);
  assert.doesNotMatch(chat, /playback\.speak\(lastExecution\.stream_text/);
  // Spraakgesprek speaks finals even when the Gesproken antwoorden toggle is off.
  // Prefer spokenAnswersRef.current inside async send handlers (avoids stale closure).
  assert.match(chat, /spokenAnswersRef\.current \|\| inVoiceSession/);
  assert.match(chat, /voice_barge_in|voiceBargeIn/);
  assert.match(chat, /voiceWakeWord|voice_wake_word_enabled/);
  assert.match(chat, /holdPushToTalk/);
  // Dictation mode must follow turn-mode setting (no tautology).
  assert.match(chat, /mode:\s*voiceTurnMode === "auto" \? "continuous" : "push_to_talk"/);
  assert.doesNotMatch(chat, /voiceTurnMode === "auto" \? "continuous" : "continuous"/);
  assert.match(chat, /idleTimeoutSeconds|voiceIdleTimeoutSeconds/);
  assert.match(chat, /voiceSpeakStyle|preferBrowserTts|voiceTtsVoice/);
});

test("Dictation toggle uses continuous VAD; session honors turn mode and wake/barge-in", async () => {
  const dictation = await read("hooks/use-voice-dictation.ts");
  const session = await read("hooks/use-voice-session.ts");
  assert.match(dictation, /continuous/);
  assert.match(dictation, /holdPushToTalk/);
  assert.match(session, /wakeWordEnabled/);
  assert.match(session, /voiceWakeProbe|wakeArmedRef/);
  assert.match(session, /bargeIn/);
  assert.match(session, /setMuted\(true\)/);
});

test("Audio capture enforces user gesture, secure context, and echo constraints", async () => {
  const capture = await read("lib/hades-voice/audio-capture.ts");
  assert.match(capture, /getUserMedia/);
  assert.match(capture, /isSecureContext/);
  assert.match(capture, /echoCancellation/);
  assert.match(capture, /noiseSuppression/);
  assert.match(capture, /NotAllowedError/);
  assert.match(capture, /preRollMs/);
  assert.match(capture, /push_to_talk/);
  assert.match(capture, /continuous/);
});

test("Playback queue supports generation cancel for barge-in", async () => {
  const queue = await read("lib/hades-voice/playback-queue.ts");
  assert.match(queue, /alignGeneration|bumpGeneration|generation/);
  assert.match(queue, /stop\(/);
  assert.match(queue, /isPlaying/);
});

test("Settings Spraak panel includes install and device tests", async () => {
  const settings = await read("components/hades/pages/settings-page.tsx");
  const panel = await read("components/hades/voice/voice-settings-panel.tsx");
  assert.match(settings, /Spraak/);
  assert.match(panel, /Test microfoon/);
  assert.match(panel, /Test stem/);
  assert.match(panel, /Installatie/);
  assert.match(panel, /voice_wake_word_enabled/);
  assert.match(panel, /voice_barge_in/);
  assert.match(panel, /voice_session_idle_seconds/);
  assert.match(panel, /voiceRecordingsDelete|Opnamen bewaren/);
});
