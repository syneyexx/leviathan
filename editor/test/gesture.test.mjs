/**
 * Gesture draft restore tests (P0-D) — pure style/attribute capture.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { captureElementChrome, createGestureDraft, restoreElementChrome } from "../js/gesture-draft.js";

function fakeEl(initial = {}) {
  const styles = { ...initial.styles };
  const attrs = { ...(initial.attrs || {}) };
  const el = {
    style: new Proxy(styles, {
      get(t, k) {
        return t[k] || "";
      },
      set(t, k, v) {
        t[k] = v;
        return true;
      },
    }),
    dataset: { ...(initial.dataset || {}) },
    isConnected: true,
    parentElement: initial.parent || null,
    nextSibling: null,
    hasAttribute(k) {
      return k in attrs && attrs[k] != null;
    },
    getAttribute(k) {
      return attrs[k];
    },
    setAttribute(k, v) {
      attrs[k] = v;
    },
    removeAttribute(k) {
      delete attrs[k];
    },
    _attrs: attrs,
    _styles: styles,
  };
  return el;
}

test("P0-D: failed promotion path restores exact prior styles", () => {
  const el = fakeEl({
    styles: { position: "relative", left: "", top: "", width: "100%", height: "auto", margin: "8px" },
    attrs: { style: "position:relative;width:100%;height:auto;margin:8px" },
    dataset: { lvbNode: "n1" },
  });
  const snap = captureElementChrome(el);
  el.style.position = "absolute";
  el.style.left = "10px";
  el.style.top = "20px";
  el.style.width = "200px";
  el.style.height = "100px";
  el.style.margin = "0";
  restoreElementChrome(snap);
  assert.equal(el.style.position, "relative");
  assert.equal(el.style.left, "");
  assert.equal(el.style.width, "100%");
  assert.equal(el.style.height, "auto");
  assert.equal(el.style.margin, "8px");
});

test("P0-D: gesture draft cancel restores all touched nodes; no history side effects", () => {
  const draft = createGestureDraft();
  const a = fakeEl({ styles: { left: "1px" }, dataset: { lvbId: "a" } });
  const b = fakeEl({ styles: { left: "2px" }, dataset: { lvbId: "b" } });
  draft.begin("resize", { content: { entries: {} } });
  draft.note(a);
  draft.note(b);
  a.style.left = "99px";
  b.style.left = "88px";
  const result = draft.cancel();
  assert.equal(result.restored, true);
  assert.equal(a.style.left, "1px");
  assert.equal(b.style.left, "2px");
  assert.equal(draft.isActive(), false);
  assert.equal(draft.exportUncommitted(), null);
});

test("P0-D: commit clears draft without restoring", () => {
  const draft = createGestureDraft();
  const a = fakeEl({ styles: { left: "1px" } });
  draft.begin("move", {});
  draft.note(a);
  a.style.left = "50px";
  draft.commit();
  assert.equal(a.style.left, "50px");
  assert.equal(draft.isActive(), false);
});
