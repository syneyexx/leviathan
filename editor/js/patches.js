/**
 * LEVIATHAN STUDIO — scoped document patches for history / save / AI / recipes.
 * Undo applies reverse of a command's delta — never a full-document clobber.
 */

import { FILES } from "./constants.js";

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

export function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Diff two content+files snapshots into a scoped patch.
 */
export function diffSnapshots(before, after) {
  const patch = {
    entries: {},
    nodes: null,
    components: null,
    files: {},
    meta: null,
    selected: after?.selected ?? null,
    labelScope: after?.scope || before?.scope || null,
    page: after?.page || before?.page || null,
  };

  const be = before?.content?.entries || {};
  const ae = after?.content?.entries || {};
  const keys = new Set([...Object.keys(be), ...Object.keys(ae)]);
  for (const key of keys) {
    if (!deepEqual(be[key], ae[key])) {
      patch.entries[key] = {
        before: key in be ? clone(be[key]) : undefined,
        after: key in ae ? clone(ae[key]) : undefined,
      };
    }
  }

  if (!deepEqual(before?.content?.nodes, after?.content?.nodes)) {
    patch.nodes = { before: clone(before?.content?.nodes || []), after: clone(after?.content?.nodes || []) };
  }
  if (!deepEqual(before?.content?.components, after?.content?.components)) {
    patch.components = {
      before: clone(before?.content?.components || []),
      after: clone(after?.content?.components || []),
    };
  }
  if (!deepEqual(before?.content?.meta, after?.content?.meta)) {
    patch.meta = { before: clone(before?.content?.meta || {}), after: clone(after?.content?.meta || {}) };
  }

  for (const name of FILES) {
    const bf = before?.files?.[name] ?? "";
    const af = after?.files?.[name] ?? "";
    if (bf !== af) patch.files[name] = { before: bf, after: af };
  }

  return patch;
}

export function patchIsEmpty(patch) {
  if (!patch) return true;
  return (
    !Object.keys(patch.entries || {}).length &&
    !patch.nodes &&
    !patch.components &&
    !patch.meta &&
    !Object.keys(patch.files || {}).length
  );
}

/**
 * Apply patch direction ("forward" = after, "back" = before) onto live store state.
 * Only touches keys present in the patch — other pages/entries stay intact.
 */
export function applyPatch(state, patch, direction = "back") {
  if (!patch || !state) return state;
  const pick = (pair) => (direction === "forward" ? pair?.after : pair?.before);
  const content = {
    ...state.content,
    entries: { ...(state.content?.entries || {}) },
    nodes: Array.isArray(state.content?.nodes) ? [...state.content.nodes] : [],
    components: Array.isArray(state.content?.components) ? [...state.content.components] : [],
    meta: { ...(state.content?.meta || {}) },
  };

  for (const [key, pair] of Object.entries(patch.entries || {})) {
    const value = pick(pair);
    if (value === undefined) delete content.entries[key];
    else content.entries[key] = clone(value);
  }
  if (patch.nodes) content.nodes = clone(pick(patch.nodes) || []);
  if (patch.components) content.components = clone(pick(patch.components) || []);
  if (patch.meta) content.meta = clone(pick(patch.meta) || {});

  const files = { ...state.files };
  for (const [name, pair] of Object.entries(patch.files || {})) {
    files[name] = pick(pair) ?? "";
  }

  return { content, files };
}

export function invertPatch(patch) {
  if (!patch) return patch;
  const invertPair = (pair) => ({ before: pair?.after, after: pair?.before });
  return {
    ...patch,
    entries: Object.fromEntries(Object.entries(patch.entries || {}).map(([k, v]) => [k, invertPair(v)])),
    nodes: patch.nodes ? invertPair(patch.nodes) : null,
    components: patch.components ? invertPair(patch.components) : null,
    meta: patch.meta ? invertPair(patch.meta) : null,
    files: Object.fromEntries(Object.entries(patch.files || {}).map(([k, v]) => [k, invertPair(v)])),
  };
}

export function summarizePatch(patch) {
  if (!patch) return { entries: 0, nodes: false, files: [], pages: [] };
  const pages = new Set();
  for (const pair of Object.values(patch.entries || {})) {
    const e = pair.after || pair.before;
    if (e?.page && e.page !== "*") pages.add(e.page);
  }
  return {
    entries: Object.keys(patch.entries || {}).length,
    nodes: !!patch.nodes,
    components: !!patch.components,
    files: Object.keys(patch.files || {}),
    pages: [...pages],
  };
}

/** Hash a content object for concurrency checks (stable JSON). */
export function hashDocument(content, files = {}) {
  const payload = JSON.stringify({
    entries: content?.entries || {},
    nodes: content?.nodes || [],
    components: content?.components || [],
    files,
    revision: content?.revision ?? 0,
  });
  let h = 2166136261;
  for (let i = 0; i < payload.length; i += 1) {
    h ^= payload.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}
