/**
 * Visual snapshot subsystem — Design canvas / selection / padded region.
 *
 * No giant dependency: SVG foreignObject rasterization with bounded resolution.
 * Does not mutate document history or trigger saves.
 * Excludes Studio chrome (#lvb-root) by capturing #root (or selection subtree).
 */

const MAX_EDGE = 1280;
const JPEG_QUALITY = 0.72;
const DEFAULT_PAD = 24;

function isStudioChrome(node) {
  if (!(node instanceof Element)) return false;
  return !!(node.closest?.("#lvb-root") || node.id === "lvb-root" || node.classList?.contains("lvb-root"));
}

/**
 * Compute crop rectangle in viewport coordinates for an element, with padding,
 * accounting for camera zoom by using getBoundingClientRect (already transformed).
 */
export function planSelectionCrop(el, { padding = DEFAULT_PAD, maxEdge = MAX_EDGE } = {}) {
  if (!el || typeof el.getBoundingClientRect !== "function") {
    return { ok: false, reason: "no-element" };
  }
  const rect = el.getBoundingClientRect();
  if (rect.width < 1 || rect.height < 1) {
    return { ok: false, reason: "zero-size" };
  }
  const pad = Math.max(0, Number(padding) || 0);
  let x = rect.left - pad;
  let y = rect.top - pad;
  let w = rect.width + pad * 2;
  let h = rect.height + pad * 2;
  // Clamp to viewport
  const vw = typeof window !== "undefined" ? window.innerWidth : w;
  const vh = typeof window !== "undefined" ? window.innerHeight : h;
  if (x < 0) {
    w += x;
    x = 0;
  }
  if (y < 0) {
    h += y;
    y = 0;
  }
  w = Math.min(w, vw - x);
  h = Math.min(h, vh - y);
  const scale = Math.min(1, maxEdge / Math.max(w, h, 1));
  return {
    ok: true,
    viewport: { x, y, width: w, height: h },
    output: {
      width: Math.max(1, Math.round(w * scale)),
      height: Math.max(1, Math.round(h * scale)),
      scale,
    },
    padding: pad,
    dpr: typeof window !== "undefined" ? Math.min(window.devicePixelRatio || 1, 2) : 1,
  };
}

export function planPageCrop({ maxEdge = MAX_EDGE } = {}) {
  const root = document.getElementById("root");
  if (!root) return { ok: false, reason: "no-root" };
  return planSelectionCrop(root, { padding: 0, maxEdge });
}

/**
 * Attempt to rasterize an element subtree via SVG foreignObject.
 * Falls back with honest failure — never silently returns chrome screenshot.
 */
export async function captureElementSnapshot(el, { maxEdge = MAX_EDGE, padding = 0, type = "selection" } = {}) {
  if (!el || typeof el.cloneNode !== "function") {
    return { ok: false, reason: "no-element", type };
  }
  if (isStudioChrome(el) && el.id !== "root") {
    return { ok: false, reason: "studio-chrome-refused", type };
  }

  const plan = planSelectionCrop(el, { padding, maxEdge });
  if (!plan.ok) return { ...plan, type };

  try {
    const clone = el.cloneNode(true);
    // Strip editor chrome artifacts if any leaked into clone
    clone.querySelectorAll?.("#lvb-root, [data-lvb-handle], .lvb-handle, .lvb-selection").forEach((n) => n.remove());
    clone.querySelectorAll?.("[contenteditable]").forEach((n) => n.removeAttribute("contenteditable"));

    const width = Math.round(el.getBoundingClientRect().width) || plan.output.width;
    const height = Math.round(el.getBoundingClientRect().height) || plan.output.height;
    const outW = plan.output.width;
    const outH = plan.output.height;

    const wrapper = document.createElement("div");
    wrapper.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
    wrapper.style.cssText = `width:${width}px;height:${height}px;overflow:hidden;background:transparent;`;
    wrapper.appendChild(clone);

    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${outW}" height="${outH}">
      <foreignObject width="100%" height="100%" x="0" y="0">
        ${new XMLSerializer().serializeToString(wrapper)}
      </foreignObject>
    </svg>`;

    const svgUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    const img = await loadImage(svgUrl);
    const canvas = document.createElement("canvas");
    canvas.width = outW;
    canvas.height = outH;
    const g = canvas.getContext("2d");
    if (!g) return { ok: false, reason: "no-2d-context", type };
    g.fillStyle = "#0B0E14";
    g.fillRect(0, 0, outW, outH);
    g.drawImage(img, 0, 0, outW, outH);
    const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
    // Bound payload
    if (dataUrl.length > 1_100_000) {
      const tighter = canvas.toDataURL("image/jpeg", 0.55);
      if (tighter.length > 1_100_000) {
        return { ok: false, reason: "snapshot-too-large", type };
      }
      return finishSnapshot(tighter, outW, outH, type, plan, el);
    }
    return finishSnapshot(dataUrl, outW, outH, type, plan, el);
  } catch (err) {
    return {
      ok: false,
      reason: "capture-failed",
      message: String(err?.message || err),
      type,
    };
  }
}

function finishSnapshot(dataUrl, width, height, type, plan, el) {
  const nodeKey = el?.dataset?.lvbNode || el?.dataset?.lvbId || null;
  return {
    ok: true,
    type,
    dataUrl,
    width,
    height,
    bytesEstimate: Math.round((dataUrl.length * 3) / 4),
    meta: {
      captureType: type,
      sourceNode: nodeKey,
      viewport: plan.viewport,
      timestamp: Date.now(),
    },
  };
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image-load-failed"));
    img.src = url;
  });
}

/**
 * Capture page (design root) without studio chrome.
 */
export async function capturePageSnapshot(ctx, opts = {}) {
  const mode = ctx?.store?.getState?.()?.viewMode || "design";
  if (mode === "preview") {
    const iframe = document.querySelector("[data-role='viewport-iframe']");
    try {
      const doc = iframe?.contentDocument;
      const root = doc?.getElementById("root") || doc?.body;
      if (root) {
        const snap = await captureElementSnapshot(root, { ...opts, type: "page", padding: 0 });
        if (snap.ok) snap.meta = { ...snap.meta, sourcePage: "preview", mode: "preview" };
        return snap;
      }
    } catch {
      return { ok: false, reason: "preview-iframe-inaccessible", type: "page", mode: "preview" };
    }
  }
  const root = document.getElementById("root");
  const snap = await captureElementSnapshot(root, { ...opts, type: "page", padding: 0 });
  if (snap.ok) snap.meta = { ...snap.meta, sourcePage: "design", mode: "design" };
  return snap;
}

export async function captureSelectionSnapshot(el, opts = {}) {
  return captureElementSnapshot(el, { ...opts, type: "selection", padding: 0 });
}

export async function captureRegionSnapshot(el, opts = {}) {
  return captureElementSnapshot(el, { ...opts, type: "region", padding: opts.padding ?? DEFAULT_PAD });
}

/**
 * Attach snapshots to a context object based on toggles. Mutates visualContext.
 * Ephemeral — caller should not persist into document model.
 */
export async function attachVisualContext(ctx, context, options = {}) {
  const included = [];
  const primary = options.primary || ctx.session.primary;
  let degraded = false;
  let degradeReason = null;

  if (options.pageVisual) {
    const pageSnap = await capturePageSnapshot(ctx, { maxEdge: options.maxEdge || MAX_EDGE });
    if (pageSnap.ok) {
      context.visualContext.pageSnapshot = {
        dataUrl: pageSnap.dataUrl,
        width: pageSnap.width,
        height: pageSnap.height,
        meta: pageSnap.meta,
      };
      included.push("Page snapshot");
    } else {
      degraded = true;
      degradeReason = `page-snapshot:${pageSnap.reason}`;
    }
  }

  if (options.selectionVisual && primary) {
    const selSnap = await captureSelectionSnapshot(primary, { maxEdge: options.maxEdge || MAX_EDGE });
    if (selSnap.ok) {
      context.visualContext.selectionSnapshot = {
        dataUrl: selSnap.dataUrl,
        width: selSnap.width,
        height: selSnap.height,
        meta: selSnap.meta,
      };
      included.push("Selection snapshot");
    } else {
      degraded = true;
      degradeReason = degradeReason || `selection-snapshot:${selSnap.reason}`;
    }
  }

  if (options.regionVisual && primary) {
    const region = await captureRegionSnapshot(primary, {
      maxEdge: options.maxEdge || MAX_EDGE,
      padding: options.padding ?? DEFAULT_PAD,
    });
    if (region.ok) {
      context.visualContext.regionSnapshot = {
        dataUrl: region.dataUrl,
        width: region.width,
        height: region.height,
        meta: region.meta,
      };
      included.push("Region snapshot");
    }
  }

  context.visualContext.included = included;
  context.visualContext.degraded = degraded;
  context.visualContext.degradeReason = degradeReason;
  return context;
}

/** Revoke blob URLs if any were created (data URLs need no revoke). */
export function disposeSnapshotUrls(_snaps) {
  // data: URLs — nothing to revoke; reserved for future blob: refs
}
