/**
 * Controlled-audio (fake MediaStream) tests for AudioCapture permission/teardown.
 * No physical microphone required.
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
  server: { middlewareMode: true },
});

after(async () => vite.close());

function installBrowserStubs({ secure = true } = {}) {
  const mediaDevices = {
    getUserMedia: async () => {
      throw new Error("unmocked getUserMedia");
    },
    enumerateDevices: async () => [],
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  };
  const win = globalThis.window || globalThis;
  Object.defineProperty(win, "isSecureContext", {
    configurable: true,
    get: () => secure,
  });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: win,
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices },
  });
  if (!globalThis.DOMException) {
    globalThis.DOMException = class DOMException extends Error {
      constructor(message, name) {
        super(message);
        this.name = name || "Error";
      }
    };
  }
  return mediaDevices;
}

test("voiceMediaSupported rejects insecure context", async () => {
  installBrowserStubs({ secure: false });
  const mod = await vite.ssrLoadModule("/lib/hades-voice/audio-capture.ts");
  const support = mod.voiceMediaSupported();
  assert.equal(support.ok, false);
  assert.match(support.reason || "", /beveiligde|HTTPS|localhost/i);
});

test("AudioCapture maps NotAllowedError to denied mic state", async () => {
  installBrowserStubs({ secure: true });
  const mod = await vite.ssrLoadModule("/lib/hades-voice/audio-capture.ts");
  const states = [];
  const errors = [];
  const capture = new mod.AudioCapture({
    onStateChange: (state) => states.push(state),
    onError: (message) => errors.push(message),
    getUserMedia: async () => {
      throw new DOMException("Permission denied", "NotAllowedError");
    },
  });
  await assert.rejects(() => capture.requestPermissionAndStart(), /geweigerd|Permission|Microfoon/i);
  assert.equal(capture.getMicState(), "denied");
  assert.ok(states.includes("denied"));
  assert.ok(errors.some((msg) => /geweigerd/i.test(msg)));
});

test("AudioCapture stop ends MediaStream tracks (HOST_TEST session close)", async () => {
  installBrowserStubs({ secure: true });
  const mod = await vite.ssrLoadModule("/lib/hades-voice/audio-capture.ts");
  let stopped = 0;
  const track = {
    kind: "audio",
    enabled: true,
    stop: () => {
      stopped += 1;
    },
  };
  const stream = {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  };
  const capture = new mod.AudioCapture({
    getUserMedia: async () => stream,
  });
  await capture.requestPermissionAndStart();
  assert.equal(capture.isCapturing(), true);
  await capture.stop();
  assert.equal(stopped, 1);
  assert.equal(capture.isCapturing(), false);
  assert.equal(capture.getMicState(), "idle");
});
