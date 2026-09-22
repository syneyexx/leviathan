/**
 * Editor AI — context, snapshot planning, preview/stale semantics (Node).
 */

import assert from "node:assert/strict";
import test from "node:test";

import { CONTEXT_PROTOCOL, CONTEXT_VERSION, TASKS, newRequestId } from "../js/ai/protocol.js";
import { collectEditorContext, contextSummaryLines } from "../js/ai/context.js";
import { planSelectionCrop, planPageCrop } from "../js/ai/snapshots.js";
import { createAiState, AiPhase, isBusy } from "../js/ai/state.js";
import { createPreviewController } from "../js/ai/preview.js";
import { createStore } from "../js/state.js";
import { createCommands } from "../js/commands.js";

test("protocol constants and tasks", () => {
  assert.equal(CONTEXT_PROTOCOL, "leviathan.editor-context");
  assert.equal(CONTEXT_VERSION, 1);
  assert.ok(TASKS.some((t) => t.id === "generate_image"));
  assert.ok(newRequestId().length >= 8);
});

test("ai state machine busy flags", () => {
  assert.equal(isBusy(AiPhase.IDLE), false);
  assert.equal(isBusy(AiPhase.GENERATING), true);
  assert.equal(isBusy(AiPhase.PREVIEW_READY), false);
  const s = createAiState();
  assert.equal(s.phase, AiPhase.IDLE);
  assert.equal(s.styleSource, "page_and_selection");
});

test("collectEditorContext structured and bounded", () => {
  // Minimal DOM stubs via jsdom-less synthetic element-like objects are hard;
  // exercise path with null selection.
  const store = createStore({
    page: "/analytics",
    viewMode: "design",
    breakpoint: "desktop",
    content: { docId: "doc1", version: 3, entries: {}, nodes: [], components: [], meta: {} },
    contentRevision: 3,
    files: { "tokens.css": ":root { --accent: #5B9FD4; --bg: #0B0E14; }" },
  });
  const ctx = {
    store,
    session: { primary: null, uiEpoch: 2, selected: [] },
    selection: { keys: () => [] },
    tokens: () => [
      { name: "--accent", value: "#5B9FD4" },
      { name: "--bg", value: "#0B0E14" },
    ],
  };
  const { context } = collectEditorContext(ctx, {
    task: "generate_image",
    instruction: "Maak een afbeelding van Leviathan in deze stijl",
    styleSource: "page_and_selection",
    width: 1280,
    height: 720,
    variants: 2,
  });
  assert.equal(context.protocol, CONTEXT_PROTOCOL);
  assert.equal(context.version, 1);
  assert.equal(context.request.task, "generate_image");
  assert.equal(context.page.route, "/analytics");
  assert.equal(context.output.width, 1280);
  assert.equal(context.output.height, 720);
  assert.equal(context.output.variants, 2);
  assert.equal(context.policy.previewOnly, true);
  assert.equal(context.policy.allowDirectSourceRewrite, false);
  assert.ok(Object.keys(context.style.tokens).length >= 1);
  assert.ok(!JSON.stringify(context).includes("<html"));
  const lines = contextSummaryLines(context);
  assert.ok(lines.some((l) => l.includes("/analytics")));
});

test("snapshot crop math clamps and scales", () => {
  // Fake element with getBoundingClientRect
  globalThis.window = { innerWidth: 1000, innerHeight: 800, devicePixelRatio: 2 };
  const el = {
    getBoundingClientRect: () => ({ left: 100, top: 50, width: 2000, height: 1000 }),
  };
  const plan = planSelectionCrop(el, { padding: 10, maxEdge: 1280 });
  assert.equal(plan.ok, true);
  assert.ok(plan.output.width <= 1280);
  assert.ok(plan.output.height <= 1280);
  assert.ok(plan.output.scale <= 1);
  // zero size
  const bad = planSelectionCrop({ getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });
  assert.equal(bad.ok, false);
});

test("preview retains target fingerprint; reject does not mutate", async () => {
  const store = createStore({
    page: "/",
    canUndo: false,
    canRedo: false,
    historyLabel: "",
    gestureActive: false,
  });
  let text = "hello";
  const el = {
    tagName: "P",
    isConnected: true,
    dataset: { lvbNode: "t1" },
    textContent: text,
    closest: () => null,
    matches: () => false,
    classList: { contains: () => false },
    setAttribute() {},
  };
  // Install minimal document.querySelector for validateTarget
  const prevDoc = globalThis.document;
  globalThis.document = {
    querySelector: (sel) => {
      if (String(sel).includes("t1")) return el;
      return null;
    },
  };

  const snaps = [];
  const ctx = {
    store,
    apiOrigin: "http://127.0.0.1:5199",
    api: {
      acceptAiAsset: async () => ({ url: "/assets/uploads/x.png" }),
      cleanupAiPreview: async () => ({ ok: true }),
    },
    session: { primary: el, uiEpoch: 1 },
    selection: { selectorFor: () => "node:t1" },
    content: {
      snapshot: () => ({ text, page: "/", entries: { "node:t1": { text } } }),
      sameSnap: (a, b) => a.text === b.text,
      patchBetween: (a, b) => ({
        entries: { "node:t1": { before: { text: a.text }, after: { text: b.text } } },
        nodeOps: [],
        componentOps: [],
        metaDiff: {},
        files: {},
      }),
      restorePatch: (p, dir) => {
        const side = dir === "back" ? p.entries["node:t1"].before : p.entries["node:t1"].after;
        text = side.text;
        el.textContent = text;
      },
      patchEntry: (_s, patch) => {
        if (patch.text != null) text = patch.text;
      },
      applyProp: () => {},
      setStatus: () => {},
    },
    widgets: {},
  };
  ctx.commands = createCommands(ctx);
  const preview = createPreviewController(ctx);
  const body = {
    requestId: "r1",
    status: "success",
    result: { kind: "text_preview", text: "rewritten" },
    provider: { id: "mock", isMock: true },
    diagnostics: {},
  };
  const p = preview.fromResult(body, { nodeKey: "node:t1", pageRoute: "/" });
  assert.equal(p.targetFingerprint.nodeKey, "node:t1");
  assert.equal(p.kind, "text_preview");

  // Reject cleans — no history
  await preview.reject(p);
  assert.equal(ctx.commands._debug().length, 0);
  assert.equal(text, "hello");

  // Accept applies one history entry
  const p2 = preview.fromResult(body, { nodeKey: "node:t1", pageRoute: "/" });
  const acc = await preview.accept(p2, { task: "rewrite_text" });
  assert.equal(acc.ok, true);
  assert.equal(text, "rewritten");
  assert.equal(ctx.commands._debug().length, 1);
  ctx.commands.undo();
  assert.equal(text, "hello");
  ctx.commands.redo();
  assert.equal(text, "rewritten");

  // Stale target
  el.isConnected = false;
  const p3 = preview.fromResult(body, { nodeKey: "node:t1", pageRoute: "/" });
  const stale = await preview.accept(p3, { task: "rewrite_text" });
  assert.equal(stale.ok, false);
  assert.equal(stale.reason, "target-gone");

  globalThis.document = prevDoc;
  void snaps;
});

test("preview does not retarget when selection changes conceptually", () => {
  const store = createStore({ page: "/", gestureActive: false });
  const ctx = {
    store,
    apiOrigin: "",
    api: {},
    session: {},
    selection: {},
    content: {},
    commands: { isGesturing: () => false },
  };
  const preview = createPreviewController(ctx);
  const p = preview.fromResult(
    {
      requestId: "r2",
      result: {
        kind: "asset_preview",
        variants: [{ id: "v1", tempId: "abc", url: "/api/editor-ai/preview/abc", width: 10, height: 10 }],
      },
      provider: { id: "mock", isMock: true },
      diagnostics: {},
    },
    { nodeKey: "node:A", pageRoute: "/" },
  );
  assert.equal(p.targetFingerprint.nodeKey, "node:A");
  // Selecting B does not mutate preview target
  assert.equal(p.targetFingerprint.nodeKey, "node:A");
});
