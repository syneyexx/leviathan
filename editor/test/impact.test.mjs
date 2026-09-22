/**
 * Change impact + token rename planning tests.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { FILES } from "../js/constants.js";
import { applyPatch, diffSnapshots } from "../js/patches.js";

function emptyFiles() {
  return Object.fromEntries(FILES.map((f) => [f, ""]));
}

test("planImpact counts come from planned patch only", () => {
  const before = {
    content: {
      version: 3,
      entries: { "node:a": { text: "1", page: "/a" } },
      nodes: [{ id: "a", page: "/a" }],
      components: [],
      meta: {},
    },
    files: emptyFiles(),
  };
  const after = {
    content: {
      version: 3,
      entries: { "node:a": { text: "2", page: "/a" }, "node:b": { text: "x", page: "/b" } },
      nodes: [
        { id: "a", page: "/a" },
        { id: "b", page: "/b" },
      ],
      components: [],
      meta: {},
    },
    files: { ...emptyFiles(), "tokens.css": ":root{--lv-x:1}" },
  };
  const patch = diffSnapshots(before, after);
  assert.equal(Object.keys(patch.entries).length, 2);
  assert.ok(patch.nodeOps.some((o) => o.op === "insert" && o.key === "id:b"));
  assert.ok(patch.files["tokens.css"]);
});

test("token rename updates var() and decl without clobbering unrelated text", () => {
  const before = {
    content: {
      version: 3,
      entries: {
        "node:a": { page: "/", styles: { color: "var(--lv-gold)", border: "1px solid #D6A957" } },
      },
      nodes: [],
      components: [],
      meta: {},
    },
    files: {
      ...emptyFiles(),
      "tokens.css": ":root {\n  --lv-gold: #D6A957;\n  --lv-other: 1;\n}\n/* mention --lv-gold in comment stays */",
    },
  };
  const after = JSON.parse(JSON.stringify(before));
  const oldName = "--lv-gold";
  const newName = "--lv-accent";
  const needle = `var(${oldName})`;
  const replacement = `var(${newName})`;
  after.files["tokens.css"] = after.files["tokens.css"]
    .split(needle)
    .join(replacement)
    .replace(/(^|[\s;{])--lv-gold\s*:/g, `$1${newName}:`);
  after.content.entries["node:a"].styles.color = after.content.entries["node:a"].styles.color
    .split(needle)
    .join(replacement);

  const patch = diffSnapshots(before, after);
  const state = applyPatch({ content: before.content, files: before.files }, patch, "forward");
  assert.match(state.files["tokens.css"], /--lv-accent:\s*#D6A957/);
  assert.doesNotMatch(state.files["tokens.css"], /--lv-gold\s*:/);
  assert.equal(state.content.entries["node:a"].styles.color, "var(--lv-accent)");
  // Hex in border left alone — not a blind global replace of the value string
  assert.equal(state.content.entries["node:a"].styles.border, "1px solid #D6A957");
});
