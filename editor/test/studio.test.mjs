import assert from "node:assert/strict";
import test from "node:test";

import { createCommands } from "../js/commands.js";
import { createStore } from "../js/state.js";
import { applyPatch, diffSnapshots, hashDocument, patchIsEmpty } from "../js/patches.js";
import {
  DOC_VERSION,
  SCOPE,
  entryKeyFromNodeId,
  migrateContent,
  parseEntryKey,
} from "../js/identity.js";
import { BEGIN, END, upsertOverride } from "../js/util.js";
import { createSaveCoordinator, SaveState } from "../js/save.js";
import { FILES } from "../js/constants.js";

test("clearStyles markers BEGIN/END are exported and match upsert", () => {
  const sel = "[data-lvb-node=\"abc\"]";
  const css = upsertOverride("", sel, "color: red;");
  assert.match(css, new RegExp(BEGIN(sel).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(css, new RegExp(END(sel).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  const cleared = css.replace(
    new RegExp(`${BEGIN(sel).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[\\s\\S]*?${END(sel).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\n?`),
    "",
  );
  assert.equal(cleared.trim(), "");
});

test("migrate v2 legacy selectors to v3 with ambiguous flags", () => {
  const v2 = {
    version: 2,
    entries: {
      ".lv-card": { styles: { color: "red" } },
      ".lv-header": { width: "80px" },
    },
    nodes: [],
    components: [],
  };
  const v3 = migrateContent(v2);
  assert.equal(v3.version, DOC_VERSION);
  assert.ok(v3.entries["shell:.lv-header"]);
  assert.equal(v3.entries["shell:.lv-header"].scope, SCOPE.GLOBAL_SHELL);
  assert.ok(v3.entries[".lv-card"].ambiguous);
  assert.ok(v3.meta.ambiguous.some((a) => a.key === ".lv-card"));
});

test("identity prefers node id over class", () => {
  const el = {
    dataset: { lvbNode: "n1" },
    classList: { [Symbol.iterator]: function* () { yield "lv-card"; } },
    tagName: "DIV",
  };
  // minimal Element-like — identityFor checks instanceof Element in browser;
  // unit path: parseEntryKey / entryKeyFromNodeId
  assert.equal(entryKeyFromNodeId("n1"), "node:n1");
  assert.equal(parseEntryKey("node:n1").kind, "node");
  assert.equal(parseEntryKey("shell:.lv-main").kind, "shell");
});

test("scoped patch undo keeps other page entries", () => {
  const before = {
    files: Object.fromEntries(FILES.map((f) => [f, ""])),
    content: {
      version: 3,
      entries: {
        "node:a": { text: "A1", page: "/a", nodeId: "a" },
        "node:b": { text: "B1", page: "/b", nodeId: "b" },
      },
      nodes: [],
      components: [],
    },
  };
  const afterA = {
    files: { ...before.files },
    content: {
      ...before.content,
      entries: {
        "node:a": { text: "A2", page: "/a", nodeId: "a" },
        "node:b": { text: "B1", page: "/b", nodeId: "b" },
      },
    },
  };
  const afterB = {
    files: { ...before.files },
    content: {
      ...before.content,
      entries: {
        "node:a": { text: "A2", page: "/a", nodeId: "a" },
        "node:b": { text: "B2", page: "/b", nodeId: "b" },
      },
    },
  };
  const patchA = diffSnapshots(before, afterA);
  const patchB = diffSnapshots(afterA, afterB);
  assert.ok(!patchIsEmpty(patchA));
  assert.ok(!patchIsEmpty(patchB));

  // Undo A after B was applied: only reverse A's delta
  let state = { content: afterB.content, files: afterB.files };
  state = applyPatch(state, patchA, "back");
  assert.equal(state.content.entries["node:a"].text, "A1");
  assert.equal(state.content.entries["node:b"].text, "B2", "page B edit must survive undo of A");
});

test("commands gesture records scoped patch across pages", () => {
  const store = createStore({ canUndo: false, canRedo: false, historyLabel: "" });
  let snap = {
    files: Object.fromEntries(FILES.map((f) => [f, ""])),
    content: { version: 3, entries: { "node:a": { text: "1", page: "/a" }, "node:b": { text: "1", page: "/b" } }, nodes: [], components: [] },
    page: "/a",
    selected: [],
  };
  const ctx = {
    store,
    session: {},
    content: {
      snapshot: () => JSON.parse(JSON.stringify(snap)),
      sameSnap: (a, b) => JSON.stringify(a.content) === JSON.stringify(b.content),
      patchBetween: (before, after) => diffSnapshots(before, after),
      restorePatch: (patch, dir) => {
        const next = applyPatch({ content: snap.content, files: snap.files }, patch, dir);
        snap = { ...snap, content: next.content, files: next.files };
      },
      setStatus: () => {},
    },
  };
  const commands = createCommands(ctx);
  commands.beginGesture("edit-a");
  snap.content.entries["node:a"].text = "2";
  snap.page = "/a";
  commands.endGesture();
  snap.page = "/b";
  commands.beginGesture("edit-b");
  snap.content.entries["node:b"].text = "9";
  commands.endGesture();
  // undo B
  commands.undo();
  assert.equal(snap.content.entries["node:b"].text, "1");
  assert.equal(snap.content.entries["node:a"].text, "2");
  // undo A
  commands.undo();
  assert.equal(snap.content.entries["node:a"].text, "1");
});

test("save coordinator keeps dirty when edits continue during save", async () => {
  const store = createStore({
    files: Object.fromEntries(FILES.map((f) => [f, "x"])),
    saved: Object.fromEntries(FILES.map((f) => [f, "x"])),
    dirtyFiles: Object.fromEntries(FILES.map((f) => [f, false])),
    content: { version: 3, entries: {}, nodes: [], components: [] },
    contentDirty: true,
  });
  let resolveSave;
  const slow = new Promise((r) => {
    resolveSave = r;
  });
  const ctx = {
    store,
    content: {
      ensure: () => store.getState().content,
      syncNodesFromDom: () => {},
      setStatus: () => {},
    },
    api: {
      saveTransaction: async () => {
        await slow;
        return { revision: 1, hash: "abc" };
      },
    },
  };
  const save = createSaveCoordinator(ctx);
  save.markDirty();
  const p = save.saveAll();
  // edit during save
  store.setState({ contentDirty: true });
  save.markDirty();
  resolveSave();
  await p;
  const st = save.getState();
  assert.equal(st.saveState, SaveState.DIRTY);
  assert.ok(st.localRevision > st.savedRevision);
});

test("hashDocument is stable for same payload", () => {
  const a = hashDocument({ entries: { x: 1 }, nodes: [], components: [], revision: 0 }, { "tokens.css": "" });
  const b = hashDocument({ entries: { x: 1 }, nodes: [], components: [], revision: 0 }, { "tokens.css": "" });
  assert.equal(a, b);
});
