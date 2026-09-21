/**
 * Behavioral unit tests for PlaybackQueue generation cancel / interrupt latency.
 * Uses a stubbed document + HTMLAudioElement (no physical speakers required).
 */

import assert from "node:assert/strict";
import test, { after, before } from "node:test";
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

before(() => {
  class FakeAudio {
    volume = 1;
    src = "";
    onended = null;
    onerror = null;
    preload = "";
    play() {
      return Promise.resolve();
    }
    pause() {}
    load() {}
    removeAttribute() {
      this.src = "";
    }
  }
  globalThis.performance = globalThis.performance || { now: () => Date.now() };
  globalThis.URL = globalThis.URL || {
    createObjectURL: () => "blob:fake",
    revokeObjectURL: () => undefined,
  };
  globalThis.document = {
    createElement: (tag) => {
      assert.equal(tag, "audio");
      return new FakeAudio();
    },
  };
});

test("PlaybackQueue rejects stale generation and measures interrupt stop", async () => {
  const mod = await vite.ssrLoadModule("/lib/hades-voice/playback-queue.ts");
  /** @type {import("../lib/hades-voice/playback-queue").PlaybackQueue} */
  const queue = new mod.PlaybackQueue();
  const gen = queue.getGeneration();
  assert.equal(
    queue.enqueue({
      sessionId: "s",
      turnId: "t",
      responseId: "r",
      order: 0,
      generation: gen,
      mimeType: "audio/wav",
      blob: new Blob([new Uint8Array([1, 2, 3])], { type: "audio/wav" }),
    }),
    true,
  );
  assert.equal(
    queue.enqueue({
      sessionId: "s",
      turnId: "t",
      responseId: "r",
      order: 1,
      generation: gen - 1,
      mimeType: "audio/wav",
      blob: new Blob([new Uint8Array([4])], { type: "audio/wav" }),
    }),
    false,
  );
  const latency = queue.stop("barge-in");
  assert.equal(typeof latency, "number");
  assert.ok(latency >= 0);
  assert.ok(latency < 250, `interrupt bookkeeping should be well under 250ms locally, got ${latency}`);
  assert.equal(queue.isPlaying(), false);
  assert.ok(queue.getGeneration() > gen);
});

test("alignGeneration cancels queued segments from older generation", async () => {
  const mod = await vite.ssrLoadModule("/lib/hades-voice/playback-queue.ts");
  const queue = new mod.PlaybackQueue();
  const gen = queue.getGeneration();
  queue.enqueue({
    sessionId: "s",
    turnId: "t",
    responseId: "r",
    order: 0,
    generation: gen,
    mimeType: "audio/wav",
    blob: new Blob([new Uint8Array([9])], { type: "audio/wav" }),
  });
  queue.alignGeneration(gen + 2);
  assert.equal(queue.getGeneration(), gen + 2);
  assert.equal(
    queue.enqueue({
      sessionId: "s",
      turnId: "t",
      responseId: "r",
      order: 0,
      generation: gen,
      mimeType: "audio/wav",
      blob: new Blob([new Uint8Array([9])], { type: "audio/wav" }),
    }),
    false,
  );
});
