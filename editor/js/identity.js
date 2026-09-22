/**
 * LEVIATHAN STUDIO — stable document identity & v2→v3 migration.
 * Keys prefer node:<id>; shell uses shell:<selector>; legacy selectors migrate.
 */

import { SHELL_LOCK } from "./constants.js";
import { uid } from "./util.js";

export const DOC_VERSION = 3;

export const SCOPE = {
  PAGE: "page",
  GLOBAL_SHELL: "global-shell",
  COMPONENT_MASTER: "component-master",
  GLOBAL_TOKEN: "global-token",
};

export function isShellSelector(selector) {
  if (!selector) return false;
  if (selector.startsWith("shell:")) return true;
  const bare = selector.startsWith(".") ? selector : `.${selector.replace(/^\./, "")}`;
  return SHELL_LOCK.has(selector) || SHELL_LOCK.has(bare);
}

export function entryKeyFromNodeId(nodeId) {
  return `node:${nodeId}`;
}

export function entryKeyFromShell(selector) {
  const sel = selector.startsWith(".") ? selector : selector.startsWith("shell:") ? selector.slice(6) : `.${selector}`;
  return `shell:${sel}`;
}

export function parseEntryKey(key) {
  if (!key) return { kind: "legacy", key };
  if (key.startsWith("node:")) return { kind: "node", nodeId: key.slice(5), key };
  if (key.startsWith("shell:")) return { kind: "shell", selector: key.slice(6), key };
  return { kind: "legacy", key };
}

export function ensureNodeId(el) {
  if (!(el instanceof Element)) return null;
  if (el.dataset.lvbNode) return el.dataset.lvbNode;
  if (el.dataset.lvbId) {
    el.dataset.lvbNode = el.dataset.lvbId;
    return el.dataset.lvbId;
  }
  const id = uid("n");
  el.dataset.lvbNode = id;
  return id;
}

export function pageKey(pathname = typeof location !== "undefined" ? location.pathname : "/") {
  return String(pathname || "/").replace(/\/$/, "") || "/";
}

/**
 * Resolve identity for an editable element.
 * Never treats class / img[src] / nth-child as unique identity for persistence.
 */
export function identityFor(el, { page = pageKey(), forceShell = false } = {}) {
  if (!(el instanceof Element)) {
    return { key: "unknown", scope: SCOPE.PAGE, page, ambiguous: true, reason: "not-element" };
  }
  const classes = [...(el.classList || [])];
  const isShell = forceShell || classes.some((c) => SHELL_LOCK.has(`.${c}`));
  if (isShell) {
    const shellClass = classes.find((c) => SHELL_LOCK.has(`.${c}`));
    const selector = shellClass ? `.${shellClass}` : null;
    return {
      key: selector ? entryKeyFromShell(selector) : `shell:unknown`,
      scope: SCOPE.GLOBAL_SHELL,
      page: "*",
      selector,
      nodeId: null,
      ambiguous: !selector,
      reason: selector ? null : "shell-without-class",
    };
  }
  if (el.dataset.lvbComponentId && el.dataset.lvbMaster === "1") {
    const nodeId = ensureNodeId(el);
    return {
      key: entryKeyFromNodeId(nodeId),
      scope: SCOPE.COMPONENT_MASTER,
      page: "*",
      nodeId,
      componentId: el.dataset.lvbComponentId,
      ambiguous: false,
    };
  }
  const nodeId = ensureNodeId(el);
  return {
    key: entryKeyFromNodeId(nodeId),
    scope: SCOPE.PAGE,
    page,
    nodeId,
    ambiguous: false,
  };
}

/**
 * CSS override selector for a node — always attribute-based for non-shell.
 */
export function cssSelectorForIdentity(ident) {
  if (!ident) return null;
  if (ident.scope === SCOPE.GLOBAL_SHELL && ident.selector) return ident.selector;
  if (ident.nodeId) return `[data-lvb-node="${ident.nodeId}"]`;
  return null;
}

/**
 * Migrate v2 content (selector-keyed entries) → v3 with node keys where possible.
 * Ambiguous legacy entries are kept under their selector key and listed in meta.ambiguous.
 */
export function migrateContent(raw) {
  const content = raw && typeof raw === "object" ? { ...raw } : { version: DOC_VERSION };
  const version = Number(content.version) || 2;
  content.entries = content.entries && typeof content.entries === "object" ? { ...content.entries } : {};
  content.nodes = Array.isArray(content.nodes) ? content.nodes.map((n) => ({ ...n })) : [];
  content.components = Array.isArray(content.components) ? content.components.map((c) => ({ ...c })) : [];
  content.meta = content.meta && typeof content.meta === "object" ? { ...content.meta } : {};
  content.revision = typeof content.revision === "number" ? content.revision : 0;
  content.docId = content.docId || uid("doc");

  const ambiguous = Array.isArray(content.meta.ambiguous) ? [...content.meta.ambiguous] : [];
  const nextEntries = {};

  for (const [key, entry] of Object.entries(content.entries)) {
    const parsed = parseEntryKey(key);
    const copy = { ...(entry || {}) };

    if (parsed.kind === "node" || parsed.kind === "shell") {
      copy.scope = copy.scope || (parsed.kind === "shell" ? SCOPE.GLOBAL_SHELL : SCOPE.PAGE);
      if (parsed.kind === "node") copy.nodeId = copy.nodeId || parsed.nodeId;
      if (parsed.kind === "shell") copy.selector = copy.selector || parsed.selector;
      nextEntries[key] = copy;
      continue;
    }

    // Legacy selector key
    if (isShellSelector(key) || SHELL_LOCK.has(key)) {
      const shellKey = entryKeyFromShell(key.startsWith(".") ? key : key);
      nextEntries[shellKey] = {
        ...copy,
        scope: SCOPE.GLOBAL_SHELL,
        page: "*",
        selector: key.startsWith(".") ? key : `.${key.replace(/^\./, "")}`,
        legacyKey: key,
      };
      continue;
    }

    if (copy.nodeId) {
      const nk = entryKeyFromNodeId(copy.nodeId);
      nextEntries[nk] = {
        ...copy,
        scope: copy.scope || SCOPE.PAGE,
        page: copy.page || "*",
        legacyKey: key,
      };
      continue;
    }

    // Ambiguous: class / img[src] / nth-child — keep legacy key, flag it
    const flagged = {
      ...copy,
      scope: copy.scope || SCOPE.PAGE,
      page: copy.page || "*",
      legacyKey: key,
      ambiguous: true,
    };
    nextEntries[key] = flagged;
    if (!ambiguous.some((a) => a.key === key)) {
      ambiguous.push({
        key,
        reason: "legacy-selector-not-unique",
        hint: "Selecteer het element opnieuw om een stabiele node-ID te binden",
      });
    }
  }

  // Align widget nodes
  for (const node of content.nodes) {
    if (!node.id) node.id = uid("w");
    node.nodeId = node.nodeId || node.id;
  }

  content.entries = nextEntries;
  content.meta = { ...content.meta, ambiguous, migratedFrom: version < DOC_VERSION ? version : content.meta.migratedFrom };
  content.version = DOC_VERSION;
  return content;
}

/**
 * Resolve DOM nodes for an entry key. Prefers data-lvb-node; never expands ambiguous
 * legacy selectors to multiple nodes unless scope is explicitly global-shell.
 */
export function queryForEntry(key, entry, { document: doc = document } = {}) {
  const parsed = parseEntryKey(key);
  if (parsed.kind === "node") {
    const el = doc.querySelector(`[data-lvb-node="${CSS.escape(parsed.nodeId)}"]`);
    return el ? [el] : [];
  }
  if (parsed.kind === "shell") {
    try {
      return [...doc.querySelectorAll(parsed.selector)];
    } catch {
      return [];
    }
  }
  // Legacy / ambiguous: only apply if exactly one match, else skip (Problems panel lists it)
  if (entry?.ambiguous || entry?.nodeId == null) {
    try {
      const nodes = [...doc.querySelectorAll(key)].filter((el) => el instanceof Element);
      if (nodes.length === 1) return nodes;
      return [];
    } catch {
      return [];
    }
  }
  if (entry?.nodeId) {
    const el = doc.querySelector(`[data-lvb-node="${CSS.escape(entry.nodeId)}"]`);
    return el ? [el] : [];
  }
  return [];
}

export function bindLegacyEntry(el, key, content) {
  if (!(el instanceof Element) || !content?.entries?.[key]) return null;
  const ident = identityFor(el);
  const prev = content.entries[key];
  const next = {
    ...prev,
    nodeId: ident.nodeId,
    scope: ident.scope,
    page: ident.page,
    ambiguous: false,
    legacyKey: key,
  };
  delete content.entries[key];
  content.entries[ident.key] = next;
  if (Array.isArray(content.meta?.ambiguous)) {
    content.meta.ambiguous = content.meta.ambiguous.filter((a) => a.key !== key);
  }
  return ident;
}
