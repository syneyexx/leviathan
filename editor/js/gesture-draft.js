/**
 * Gesture draft — captures exact style/attribute state before the first mutation.
 * Cancel / failed promotion restores touched nodes; never leaves a half-promoted box.
 */

const STYLE_KEYS = [
  "position",
  "left",
  "top",
  "right",
  "bottom",
  "width",
  "height",
  "minWidth",
  "minHeight",
  "maxWidth",
  "maxHeight",
  "margin",
  "marginTop",
  "marginRight",
  "marginBottom",
  "marginLeft",
  "transform",
  "rotate",
  "zIndex",
  "objectFit",
  "objectPosition",
];

const ATTR_KEYS = ["style", "src", "width", "height", "data-lvb-free"];

/**
 * @param {Element} el
 */
export function captureElementChrome(el) {
  if (!el || typeof el !== "object" || !el.style) return null;
  const styles = {};
  for (const key of STYLE_KEYS) {
    styles[key] = el.style[key] || "";
  }
  const attrs = {};
  for (const key of ATTR_KEYS) {
    attrs[key] = typeof el.hasAttribute === "function" && el.hasAttribute(key) ? el.getAttribute(key) : null;
  }
  const parent = el.parentElement;
  const nextSibling = el.nextSibling;
  return {
    el,
    styles,
    attrs,
    parent,
    nextSibling,
    // Stable identity for selection restore
    nodeKey: el.dataset?.lvbNode || el.dataset?.lvbId || null,
  };
}

/**
 * @param {ReturnType<typeof captureElementChrome>} snap
 */
export function restoreElementChrome(snap) {
  if (!snap?.el) return false;
  const { el, styles, attrs, parent, nextSibling } = snap;
  if (!el.isConnected && parent) {
    try {
      parent.insertBefore(el, nextSibling || null);
    } catch {
      /* parent may be gone */
    }
  }
  if (!el.isConnected) return false;
  for (const key of STYLE_KEYS) {
    const value = styles[key] || "";
    if (value) el.style[key] = value;
    else el.style[key] = "";
  }
  for (const key of ATTR_KEYS) {
    const value = attrs[key];
    if (value == null) el.removeAttribute(key);
    else el.setAttribute(key, value);
  }
  return true;
}

export function createGestureDraft() {
  /** @type {Map<Element, ReturnType<typeof captureElementChrome>>} */
  const touched = new Map();
  let modelBefore = null;
  let label = "";
  let active = false;
  let committed = false;

  function begin(nextLabel, modelSnapshot) {
    if (active) return false;
    active = true;
    committed = false;
    label = nextLabel || "bewerken";
    modelBefore = modelSnapshot;
    touched.clear();
    return true;
  }

  function note(el) {
    if (!active || !el || typeof el !== "object") return null;
    if (touched.has(el)) return touched.get(el);
    const snap = captureElementChrome(el);
    if (snap) touched.set(el, snap);
    return snap;
  }

  function restoreAll() {
    for (const snap of touched.values()) restoreElementChrome(snap);
  }

  function cancel() {
    if (!active) return { restored: false, modelBefore: null };
    restoreAll();
    const out = { restored: true, modelBefore, label, count: touched.size };
    active = false;
    committed = false;
    modelBefore = null;
    touched.clear();
    return out;
  }

  function commit() {
    if (!active) return false;
    committed = true;
    active = false;
    modelBefore = null;
    touched.clear();
    return true;
  }

  function discardWithoutRestore() {
    active = false;
    committed = false;
    modelBefore = null;
    touched.clear();
  }

  return {
    begin,
    note,
    restoreAll,
    cancel,
    commit,
    discardWithoutRestore,
    isActive: () => active,
    wasCommitted: () => committed,
    getModelBefore: () => modelBefore,
    getLabel: () => label,
    touchedCount: () => touched.size,
    /** Uncommitted draft marker for recovery — never treated as durable save content. */
    exportUncommitted() {
      if (!active) return null;
      return {
        kind: "uncommitted-gesture",
        label,
        nodeKeys: [...touched.values()].map((s) => s.nodeKey).filter(Boolean),
        at: Date.now(),
      };
    },
  };
}
