import assert from "node:assert/strict";
import test from "node:test";

import { createCommands } from "../js/commands.js";
import { alignItems, distributeItems, snapRect, snapToGuides, zoomToCursor } from "../js/geometry.js";
import { createStore } from "../js/state.js";
import {
  classifyToken,
  declsToText,
  fuzzyScore,
  parseDecls,
  parseShadowList,
  parseShorthand,
  parseTokens,
  serializeShadows,
  shorthandFromSides,
  upsertOverride,
} from "../js/util.js";

test("store notifies on change and skips identical patches", () => {
  const store = createStore({ n: 1 });
  let hits = 0;
  store.subscribe(() => {
    hits += 1;
  });
  store.setState({ n: 2 });
  store.setState({ n: 2 });
  assert.equal(store.getState().n, 2);
  assert.equal(hits, 1);
});

test("commands undo redo and cap history", () => {
  const store = createStore({ canUndo: false, canRedo: false, historyLabel: "" });
  const values = [];
  let current = 0;
  const ctx = {
    store,
    session: {},
    content: {
      snapshot: () => current,
      sameSnap: (a, b) => a === b,
      restore: (v) => {
        current = v;
      },
      setStatus: () => {},
    },
  };
  const commands = createCommands(ctx);
  commands.execute({
    label: "inc",
    do: () => {
      current += 1;
    },
    undo: () => {
      current -= 1;
    },
  });
  assert.equal(current, 1);
  commands.undo();
  assert.equal(current, 0);
  commands.redo();
  assert.equal(current, 1);
  for (let i = 0; i < 120; i += 1) {
    commands.execute({
      label: "n",
      do: () => {
        values.push(i);
      },
      undo: () => {
        values.pop();
      },
    });
  }
  assert.equal(commands._debug().length, 100);
});

test("gesture snapshots once", () => {
  let current = "a";
  const store = createStore({});
  const ctx = {
    store,
    session: {},
    content: {
      snapshot: () => current,
      sameSnap: (a, b) => a === b,
      restore: (v) => {
        current = v;
      },
      setStatus: () => {},
    },
  };
  const commands = createCommands(ctx);
  commands.beginGesture("drag");
  current = "b";
  commands.endGesture();
  assert.equal(commands._debug().length, 1);
  commands.undo();
  assert.equal(current, "a");
});

test("align and distribute", () => {
  const aligned = alignItems(
    [
      { id: 1, left: 0, top: 10, width: 10, height: 10 },
      { id: 2, left: 40, top: 30, width: 20, height: 10 },
    ],
    "left",
  );
  assert.equal(aligned[0].left, 0);
  assert.equal(aligned[1].left, 0);
  const spread = distributeItems(
    [
      { i: 0, left: 0, top: 0, width: 10, height: 10 },
      { i: 1, left: 12, top: 0, width: 10, height: 10 },
      { i: 2, left: 100, top: 0, width: 10, height: 10 },
    ],
    "x",
  );
  assert.equal(spread[0].left, 0);
  assert.equal(spread[2].left, 100);
  assert.ok(spread[1].left > 10);
});

test("snap and zoom", () => {
  const hit = snapToGuides(11, [
    { at: 0, kind: "edge" },
    { at: 10, kind: "center" },
  ]);
  assert.equal(hit.at, 10);
  assert.equal(hit.kind, "center");
  const snapped = snapRect({ left: 9, top: 3, width: 10, height: 10 }, [{ at: 10, kind: "edge" }], [{ at: 0, kind: "edge" }]);
  assert.equal(snapped.dx, 1);
  const zoom = zoomToCursor({ zoom: 1, panX: 0, panY: 0, clientX: 100, clientY: 40, nextZoom: 2, originX: 0, originY: 0 });
  assert.equal(zoom.zoom, 2);
  assert.equal(zoom.panX, -100);
  assert.equal(zoom.panY, -40);
});

test("css decls shadows shorthand tokens fuzzy", () => {
  const css = upsertOverride("body{}", ".lv-main", declsToText({ color: "red" }));
  assert.match(css, /LV-EDITOR:BEGIN \.lv-main/);
  assert.deepEqual(parseDecls("color: red; padding: 1px 2px;"), { color: "red", padding: "1px 2px" });
  const shadows = parseShadowList("0 8px 24px rgba(0, 0, 0, 0.4), inset 0 0 0 1px #fff");
  assert.equal(shadows.length, 2);
  assert.equal(shadows[1].inset, true);
  assert.match(serializeShadows(shadows), /inset/);
  assert.deepEqual(parseShorthand("8px 12px"), { top: "8px", right: "12px", bottom: "8px", left: "12px" });
  assert.equal(shorthandFromSides({ top: "1px", right: "1px", bottom: "1px", left: "1px" }, true), "1px");
  const tokens = parseTokens(":root {\n  --lv-gold: #D6A957;\n  --lv-font-ui: \"Manrope\", sans-serif;\n  --lv-text-md: clamp(12px, 1vw, 14px);\n}");
  assert.equal(classifyToken(tokens[0].name, tokens[0].value), "Kleuren");
  assert.equal(tokens[1].group, "Lettertypen");
  assert.equal(tokens[2].group, "Maten");
  assert.ok(fuzzyScore("gold", "--lv-gold") > 0);
  assert.equal(fuzzyScore("zzz", "gold"), 0);
});
