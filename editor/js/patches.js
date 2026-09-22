/**
 * LEVIATHAN STUDIO — scoped document patches for history / save / AI / recipes.
 *
 * Entries are keyed by stable identity (`node:<id>` / `shell:<selector>`).
 * Nodes and components use identity-addressed structural ops so undo of page A
 * never replaces unrelated records introduced on page B.
 *
 * CSS: whole-file ownership when a file string changes. Fine-grained CSS block
 * isolation is not claimed — user-authored CSS outside editor-owned markers is
 * preserved only when the file string itself is unchanged.
 */

import { FILES } from "./constants.js";

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

export function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function nodeKey(node) {
  if (!node || typeof node !== "object") return null;
  if (node.id) return `id:${node.id}`;
  if (node.nodeId) return `id:${node.nodeId}`;
  if (node.key) return `key:${node.key}`;
  return null;
}

function componentKey(comp) {
  if (!comp || typeof comp !== "object") return null;
  if (comp.id) return `id:${comp.id}`;
  if (comp.key) return `key:${comp.key}`;
  return null;
}

function indexByKey(list, keyFn) {
  const map = new Map();
  const order = [];
  const anonymous = [];
  for (const item of list || []) {
    const k = keyFn(item);
    if (!k) {
      anonymous.push(clone(item));
      continue;
    }
    map.set(k, clone(item));
    order.push(k);
  }
  return { map, order, anonymous };
}

/**
 * Diff two arrays of identity-bearing records into structural ops.
 * Ops: insert | delete | update | reorder
 */
export function diffIdentityList(beforeList, afterList, keyFn, { pageHint } = {}) {
  const before = indexByKey(beforeList, keyFn);
  const after = indexByKey(afterList, keyFn);
  /** @type {Array<object>} */
  const ops = [];

  // Deletes
  for (const key of before.order) {
    if (!after.map.has(key)) {
      ops.push({ op: "delete", key, before: before.map.get(key) });
    }
  }

  // Inserts + updates
  for (const key of after.order) {
    const next = after.map.get(key);
    if (!before.map.has(key)) {
      ops.push({
        op: "insert",
        key,
        after: next,
        index: after.order.indexOf(key),
        page: pageHint || next?.page || null,
      });
    } else if (!deepEqual(before.map.get(key), next)) {
      ops.push({
        op: "update",
        key,
        before: before.map.get(key),
        after: next,
      });
    }
  }

  // Reorder — full identity order (not only shared keys) so undo of
  // delete+reorder restores absolute positions.
  if (!deepEqual(before.order, after.order)) {
    ops.push({
      op: "reorder",
      before: before.order.slice(),
      after: after.order.slice(),
    });
  }

  // Anonymous (no identity) — whole-list fallback for that subset only
  if (!deepEqual(before.anonymous, after.anonymous)) {
    ops.push({
      op: "anonymous",
      before: before.anonymous,
      after: after.anonymous,
    });
  }

  return ops;
}

function applyIdentityOps(list, ops, direction, keyFn) {
  const forward = direction === "forward";
  let { map, order, anonymous } = indexByKey(list, keyFn);

  for (const op of ops || []) {
    if (op.op === "delete") {
      if (forward) {
        map.delete(op.key);
        order = order.filter((k) => k !== op.key);
      } else {
        map.set(op.key, clone(op.before));
        if (!order.includes(op.key)) order.push(op.key);
      }
    } else if (op.op === "insert") {
      if (forward) {
        map.set(op.key, clone(op.after));
        const idx = Math.min(op.index ?? order.length, order.length);
        if (!order.includes(op.key)) order.splice(idx, 0, op.key);
      } else {
        map.delete(op.key);
        order = order.filter((k) => k !== op.key);
      }
    } else if (op.op === "update") {
      const value = forward ? op.after : op.before;
      // Precondition: do not silently apply stale update over divergent value
      const current = map.get(op.key);
      const expected = forward ? op.before : op.after;
      if (current != null && expected != null && !deepEqual(current, expected)) {
        // Conflicting — skip this op rather than clobber
        continue;
      }
      if (value === undefined) map.delete(op.key);
      else map.set(op.key, clone(value));
    } else if (op.op === "reorder") {
      const target = (forward ? op.after : op.before).filter((k) => map.has(k));
      const rest = order.filter((k) => !target.includes(k));
      order = [...target, ...rest];
    } else if (op.op === "anonymous") {
      anonymous = clone(forward ? op.after : op.before) || [];
    }
  }

  return [...order.map((k) => map.get(k)).filter(Boolean), ...anonymous];
}

/**
 * Diff meta object by top-level keys (scoped), not whole-object replace.
 */
export function diffMeta(beforeMeta, afterMeta) {
  const be = beforeMeta || {};
  const ae = afterMeta || {};
  const keys = new Set([...Object.keys(be), ...Object.keys(ae)]);
  const out = {};
  for (const key of keys) {
    if (!deepEqual(be[key], ae[key])) {
      out[key] = {
        before: key in be ? clone(be[key]) : undefined,
        after: key in ae ? clone(ae[key]) : undefined,
      };
    }
  }
  return out;
}

export function applyMetaDiff(meta, diff, direction) {
  const next = { ...(meta || {}) };
  const pick = (pair) => (direction === "forward" ? pair?.after : pair?.before);
  for (const [key, pair] of Object.entries(diff || {})) {
    const value = pick(pair);
    if (value === undefined) delete next[key];
    else next[key] = clone(value);
  }
  return next;
}

/**
 * Diff two content+files snapshots into a scoped patch.
 */
export function diffSnapshots(before, after) {
  const patch = {
    entries: {},
    nodeOps: [],
    componentOps: [],
    /** @deprecated legacy whole-array — only set when migrating old patches */
    nodes: null,
    components: null,
    metaDiff: {},
    meta: null,
    files: {},
    selected: after?.selected ?? null,
    labelScope: after?.scope || before?.scope || null,
    page: after?.page || before?.page || null,
    cssOwnership: "whole-file",
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

  patch.nodeOps = diffIdentityList(before?.content?.nodes, after?.content?.nodes, nodeKey, {
    pageHint: after?.page || before?.page,
  });
  patch.componentOps = diffIdentityList(
    before?.content?.components,
    after?.content?.components,
    componentKey,
  );

  patch.metaDiff = diffMeta(before?.content?.meta, after?.content?.meta);

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
    !(patch.nodeOps && patch.nodeOps.length) &&
    !(patch.componentOps && patch.componentOps.length) &&
    !Object.keys(patch.metaDiff || {}).length &&
    !patch.nodes &&
    !patch.components &&
    !patch.meta &&
    !Object.keys(patch.files || {}).length
  );
}

/**
 * Apply patch direction ("forward" = after, "back" = before) onto live store state.
 * Only touches identities present in the patch — other pages/nodes stay intact.
 */
export function applyPatch(state, patch, direction = "back") {
  if (!patch || !state) return state;
  const pick = (pair) => (direction === "forward" ? pair?.after : pair?.before);
  const content = {
    ...state.content,
    entries: { ...(state.content?.entries || {}) },
    nodes: Array.isArray(state.content?.nodes) ? state.content.nodes.map((n) => clone(n)) : [],
    components: Array.isArray(state.content?.components)
      ? state.content.components.map((c) => clone(c))
      : [],
    meta: { ...(state.content?.meta || {}) },
  };

  for (const [key, pair] of Object.entries(patch.entries || {})) {
    const value = pick(pair);
    if (value === undefined) delete content.entries[key];
    else content.entries[key] = clone(value);
  }

  if (patch.nodeOps?.length) {
    content.nodes = applyIdentityOps(content.nodes, patch.nodeOps, direction, nodeKey);
  } else if (patch.nodes) {
    // Legacy whole-array patches
    content.nodes = clone(pick(patch.nodes) || []);
  }

  if (patch.componentOps?.length) {
    content.components = applyIdentityOps(content.components, patch.componentOps, direction, componentKey);
  } else if (patch.components) {
    content.components = clone(pick(patch.components) || []);
  }

  if (patch.metaDiff && Object.keys(patch.metaDiff).length) {
    content.meta = applyMetaDiff(content.meta, patch.metaDiff, direction);
  } else if (patch.meta) {
    content.meta = clone(pick(patch.meta) || {});
  }

  const files = { ...state.files };
  for (const [name, pair] of Object.entries(patch.files || {})) {
    files[name] = pick(pair) ?? "";
  }

  return { content, files };
}

export function invertPatch(patch) {
  if (!patch) return patch;
  const invertPair = (pair) => ({ before: pair?.after, after: pair?.before });
  const invertOp = (op) => {
    if (op.op === "insert") return { ...op, op: "delete", before: op.after, after: undefined };
    if (op.op === "delete") return { ...op, op: "insert", after: op.before, before: undefined };
    if (op.op === "update" || op.op === "anonymous" || op.op === "reorder") {
      return { ...op, before: op.after, after: op.before };
    }
    return op;
  };
  return {
    ...patch,
    entries: Object.fromEntries(Object.entries(patch.entries || {}).map(([k, v]) => [k, invertPair(v)])),
    nodeOps: (patch.nodeOps || []).map(invertOp),
    componentOps: (patch.componentOps || []).map(invertOp),
    nodes: patch.nodes ? invertPair(patch.nodes) : null,
    components: patch.components ? invertPair(patch.components) : null,
    metaDiff: Object.fromEntries(Object.entries(patch.metaDiff || {}).map(([k, v]) => [k, invertPair(v)])),
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
  for (const op of patch.nodeOps || []) {
    const n = op.after || op.before;
    if (n?.page && n.page !== "*") pages.add(n.page);
  }
  return {
    entries: Object.keys(patch.entries || {}).length,
    nodes: !!(patch.nodeOps?.length || patch.nodes),
    components: !!(patch.componentOps?.length || patch.components),
    files: Object.keys(patch.files || {}),
    pages: [...pages],
    cssOwnership: patch.cssOwnership || "whole-file",
  };
}

/**
 * Local fingerprint helper for UI/diagnostics — NOT the server concurrency token.
 * Server uses SHA-256 over the complete persisted state; never substitute this.
 */
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
