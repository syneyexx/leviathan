/**
 * Structural identity-addressed patch tests (P0-C).
 */

import test from "node:test";
import assert from "node:assert/strict";
import { FILES } from "../js/constants.js";
import { applyPatch, diffSnapshots, patchIsEmpty, summarizePatch } from "../js/patches.js";

const emptyFiles = () => Object.fromEntries(FILES.map((f) => [f, ""]));

test("P0-C: undo node A does not remove node B added on another page", () => {
  const beforeA = {
    content: {
      version: 3,
      entries: {},
      nodes: [
        { id: "a", page: "/a", tag: "div" },
        { id: "shell", page: "*", tag: "header" },
      ],
      components: [],
      meta: { note: "keep" },
    },
    files: emptyFiles(),
    page: "/a",
  };
  const afterA = {
    content: {
      ...beforeA.content,
      nodes: [
        { id: "a", page: "/a", tag: "div", x: 10 },
        { id: "shell", page: "*", tag: "header" },
      ],
    },
    files: emptyFiles(),
    page: "/a",
  };
  const patchA = diffSnapshots(beforeA, afterA);
  assert.ok(patchA.nodeOps.some((op) => op.op === "update" && op.key === "id:a"));
  assert.ok(!patchIsEmpty(patchA));

  // Meanwhile page B inserts node b into the live document
  let state = {
    content: {
      version: 3,
      entries: {},
      nodes: [
        { id: "a", page: "/a", tag: "div", x: 10 },
        { id: "shell", page: "*", tag: "header" },
        { id: "b", page: "/b", tag: "section" },
      ],
      components: [{ id: "c1", name: "Card" }],
      meta: { note: "keep", extra: true },
    },
    files: emptyFiles(),
  };

  state = applyPatch(state, patchA, "back");
  assert.equal(state.content.nodes.find((n) => n.id === "a")?.x, undefined);
  assert.ok(state.content.nodes.find((n) => n.id === "b"), "unrelated insert must survive");
  assert.ok(state.content.nodes.find((n) => n.id === "shell"));
  assert.ok(state.content.components.find((c) => c.id === "c1"));
  assert.equal(state.content.meta.extra, true);
  assert.equal(state.content.meta.note, "keep");
});

test("P0-C: insert/delete/reorder across three pages", () => {
  const before = {
    content: {
      version: 3,
      entries: {},
      nodes: [
        { id: "p1", page: "/1" },
        { id: "p2", page: "/2" },
        { id: "p3", page: "/3" },
      ],
      components: [],
      meta: {},
    },
    files: emptyFiles(),
  };
  const after = {
    content: {
      version: 3,
      entries: {},
      nodes: [
        { id: "p3", page: "/3" },
        { id: "p1", page: "/1" },
        { id: "p4", page: "/1" },
      ],
      components: [],
      meta: {},
    },
    files: emptyFiles(),
  };
  // deleted p2, inserted p4, reordered p3 before p1
  const patch = diffSnapshots(before, after);
  assert.ok(patch.nodeOps.some((o) => o.op === "delete" && o.key === "id:p2"));
  assert.ok(patch.nodeOps.some((o) => o.op === "insert" && o.key === "id:p4"));
  assert.ok(patch.nodeOps.some((o) => o.op === "reorder"));

  let state = { content: clone(after.content), files: emptyFiles() };
  state = applyPatch(state, patch, "back");
  assert.deepEqual(
    state.content.nodes.map((n) => n.id),
    ["p1", "p2", "p3"],
  );
  state = applyPatch(state, patch, "forward");
  assert.deepEqual(
    state.content.nodes.map((n) => n.id),
    ["p3", "p1", "p4"],
  );
});

test("P0-C: component update is identity-scoped", () => {
  const before = {
    content: {
      version: 3,
      entries: {},
      nodes: [],
      components: [
        { id: "c1", name: "A" },
        { id: "c2", name: "B" },
      ],
      meta: {},
    },
    files: emptyFiles(),
  };
  const after = {
    content: {
      ...before.content,
      components: [
        { id: "c1", name: "A2" },
        { id: "c2", name: "B" },
      ],
    },
    files: emptyFiles(),
  };
  const patch = diffSnapshots(before, after);
  // Live doc gained c3
  let state = {
    content: {
      ...after.content,
      components: [
        { id: "c1", name: "A2" },
        { id: "c2", name: "B" },
        { id: "c3", name: "C" },
      ],
    },
    files: emptyFiles(),
  };
  state = applyPatch(state, patch, "back");
  assert.equal(state.content.components.find((c) => c.id === "c1").name, "A");
  assert.ok(state.content.components.find((c) => c.id === "c3"));
});

test("P0-C: metaDiff preserves unrelated keys; CSS is whole-file ownership", () => {
  const before = {
    content: { version: 3, entries: {}, nodes: [], components: [], meta: { a: 1, b: 2 } },
    files: { ...emptyFiles(), "tokens.css": ":root{--x:1}" },
  };
  const after = {
    content: { version: 3, entries: {}, nodes: [], components: [], meta: { a: 9, b: 2 } },
    files: { ...emptyFiles(), "tokens.css": ":root{--x:2}" },
  };
  const patch = diffSnapshots(before, after);
  assert.equal(patch.cssOwnership, "whole-file");
  assert.ok(patch.files["tokens.css"]);
  assert.deepEqual(Object.keys(patch.metaDiff), ["a"]);

  let state = {
    content: { version: 3, entries: {}, nodes: [], components: [], meta: { a: 9, b: 2, c: 3 } },
    files: after.files,
  };
  state = applyPatch(state, patch, "back");
  assert.equal(state.content.meta.a, 1);
  assert.equal(state.content.meta.c, 3);
  assert.equal(state.files["tokens.css"], ":root{--x:1}");
  assert.equal(summarizePatch(patch).cssOwnership, "whole-file");
});

test("P0-C: stale update precondition skips divergent current value", () => {
  const patch = {
    entries: {},
    nodeOps: [
      {
        op: "update",
        key: "id:a",
        before: { id: "a", x: 1 },
        after: { id: "a", x: 2 },
      },
    ],
    componentOps: [],
    metaDiff: {},
    files: {},
  };
  let state = {
    content: { nodes: [{ id: "a", x: 99 }], components: [], entries: {}, meta: {} },
    files: emptyFiles(),
  };
  state = applyPatch(state, patch, "forward");
  assert.equal(state.content.nodes[0].x, 99, "divergent value must not be clobbered");
});

function clone(v) {
  return JSON.parse(JSON.stringify(v));
}
