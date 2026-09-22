/**
 * Editor Context Protocol collector — structured, size-aware, no giant DOM dumps.
 */

import { CONTEXT_PROTOCOL, CONTEXT_VERSION, emptyPolicy, newRequestId } from "./protocol.js";

const MAX_NEARBY = 8;
const MAX_TOKENS = 40;
const MAX_SIBLINGS = 8;

function inferred(value, confidence, source = "heuristic") {
  if (value == null) return null;
  return { value, confidence, source };
}

function hasTag(el) {
  return !!el && typeof el === "object" && typeof el.tagName === "string";
}

function readBounds(el) {
  if (!hasTag(el) || typeof el.getBoundingClientRect !== "function") return null;
  const r = el.getBoundingClientRect();
  return {
    x: Math.round(r.left),
    y: Math.round(r.top),
    width: Math.round(r.width),
    height: Math.round(r.height),
  };
}

function classifyRole(el) {
  if (!hasTag(el)) return null;
  const tag = el.tagName.toLowerCase();
  const cls = String(el.className || "").toLowerCase();
  const id = String(el.id || "").toLowerCase();
  const text = (el.textContent || "").trim();
  if (tag === "img") return inferred("image", 0.95, "tag");
  if (tag === "h1" || tag === "h2") return inferred("heading", 0.9, "tag");
  if (tag === "button" || el.getAttribute?.("role") === "button") return inferred("cta", 0.85, "tag");
  if (tag === "p" || tag === "span" || tag === "a") return inferred("text", 0.7, "tag");
  if (/hero|banner/.test(cls) || /hero|banner/.test(id)) return inferred("hero-background", 0.72, "heuristic");
  if (/card/.test(cls)) return inferred("card", 0.65, "heuristic");
  if (/icon/.test(cls) || /icon/.test(id)) return inferred("icon", 0.7, "heuristic");
  try {
    if (typeof getComputedStyle === "function") {
      const bg = getComputedStyle(el).backgroundImage;
      if (bg && bg !== "none") return inferred("background-image", 0.8, "computed");
    }
  } catch {
    /* ignore */
  }
  if (text.length > 0 && text.length < 80 && (el.children?.length || 0) === 0) return inferred("text", 0.55, "heuristic");
  return inferred("container", 0.5, "heuristic");
}

function selectionKind(el, role) {
  if (!el) return "any";
  const tag = el.tagName;
  if (tag === "IMG") return "image";
  const roleVal = role?.value;
  if (roleVal === "text" || roleVal === "heading" || roleVal === "cta") return "text";
  if (roleVal === "image" || roleVal === "background-image" || roleVal === "hero-background") return "visual";
  if (roleVal === "container" || roleVal === "card") return "container";
  try {
    const bg = getComputedStyle(el).backgroundImage;
    if (bg && bg !== "none") return "visual";
  } catch {
    /* ignore */
  }
  return "any";
}

function summaryFor(el) {
  if (!hasTag(el)) return {};
  let cs;
  try {
    if (typeof getComputedStyle !== "function") return {};
    cs = getComputedStyle(el);
  } catch {
    return {};
  }
  const out = {
    display: cs.display,
    position: cs.position,
    fontFamily: cs.fontFamily,
    fontSize: cs.fontSize,
    fontWeight: cs.fontWeight,
    color: cs.color,
    backgroundColor: cs.backgroundColor,
    borderRadius: cs.borderRadius,
    boxShadow: cs.boxShadow === "none" ? null : cs.boxShadow,
    opacity: cs.opacity,
    objectFit: cs.objectFit,
  };
  if (el.tagName === "IMG") {
    out.src = el.getAttribute("src") || null;
    out.alt = el.getAttribute("alt") || null;
    out.naturalWidth = el.naturalWidth || null;
    out.naturalHeight = el.naturalHeight || null;
  }
  const text = (el.childNodes.length && [...el.childNodes].every((n) => n.nodeType === 3)
    ? el.textContent
    : el.tagName.match(/^(H[1-6]|P|BUTTON|A|LABEL|SPAN)$/)
      ? el.textContent
      : "")
    ?.trim()
    .slice(0, 400);
  if (text) out.text = text;
  return out;
}

function nodeBrief(el, identity) {
  if (!hasTag(el)) return null;
  const bounds = readBounds(el);
  const key = identity?.keyFor?.(el) || el.dataset?.lvbNode || el.dataset?.lvbId || null;
  return {
    key,
    tag: el.tagName.toLowerCase(),
    bounds,
    role: classifyRole(el),
  };
}

function collectTokens(tokenList, limit = MAX_TOKENS) {
  const tokens = {};
  const palette = [];
  for (const t of tokenList || []) {
    if (Object.keys(tokens).length >= limit) break;
    const name = t.name || t.id || t.key;
    const value = t.value;
    if (!name || value == null) continue;
    tokens[String(name)] = String(value).slice(0, 120);
    if (/color|bg|accent|surface|border/i.test(String(name)) && palette.length < 12) {
      palette.push({ name: String(name), value: String(value) });
    }
  }
  return { tokens, palette };
}

function styleSummaryFrom(tokens, selectionSummary, styleSource) {
  const parts = [];
  parts.push(`styleSource=${styleSource}`);
  if (selectionSummary?.backgroundColor) parts.push(`bg=${selectionSummary.backgroundColor}`);
  if (selectionSummary?.color) parts.push(`fg=${selectionSummary.color}`);
  if (selectionSummary?.borderRadius) parts.push(`radius=${selectionSummary.borderRadius}`);
  if (selectionSummary?.fontFamily) parts.push(`font=${selectionSummary.fontFamily}`);
  const accent = tokens["--studio-accent"] || tokens["--lv-accent"] || tokens["--accent"];
  if (accent) parts.push(`accent=${accent}`);
  return parts.join("; ");
}

/**
 * @param {object} ctx studio context
 * @param {object} options collector options from AI panel state
 */
export function collectEditorContext(ctx, options = {}) {
  const state = ctx.store.getState();
  const primary = options.primary || ctx.session.primary;
  const keys = options.keys || (ctx.selection?.keys?.() ? [...ctx.selection.keys()] : []);
  const role = classifyRole(primary);
  const bounds = readBounds(primary);
  const aspectRatio =
    bounds && bounds.height > 0 ? Math.round((bounds.width / bounds.height) * 10000) / 10000 : null;
  const computedSummary = summaryFor(primary);
  const kind = selectionKind(primary, role);

  const tokenList = typeof ctx.tokens === "function" ? ctx.tokens() : [];
  const { tokens, palette } =
    options.includeTokens === false ? { tokens: {}, palette: [] } : collectTokens(tokenList);

  let parent = null;
  const siblings = [];
  const nearby = [];
  if (primary?.parentElement && options.includeNearby !== false) {
    parent = nodeBrief(primary.parentElement, ctx.identity);
    const kids = [...(primary.parentElement.children || [])];
    for (const sib of kids.slice(0, MAX_SIBLINGS)) {
      if (sib === primary) continue;
      const brief = nodeBrief(sib, ctx.identity);
      if (brief) siblings.push(brief);
    }
    // Nearby: previous/next + a few cousins — bounded
    const idx = kids.indexOf(primary);
    for (const el of [kids[idx - 1], kids[idx + 1], primary.parentElement?.parentElement].filter(Boolean)) {
      const brief = nodeBrief(el, ctx.identity);
      if (brief && nearby.length < MAX_NEARBY) nearby.push(brief);
    }
  }

  let currentAsset = null;
  if (primary?.tagName === "IMG") {
    currentAsset = {
      kind: "img",
      url: primary.getAttribute("src") || null,
      alt: primary.getAttribute("alt") || null,
    };
  } else if (computedSummary && primary) {
    try {
      const bg = getComputedStyle(primary).backgroundImage;
      const m = String(bg || "").match(/url\(["']?([^"')]+)/);
      if (m) currentAsset = { kind: "background", url: m[1] };
    } catch {
      /* ignore */
    }
  }

  const styleSource = options.styleSource || "page_and_selection";
  const width = options.width ?? bounds?.width ?? null;
  const height = options.height ?? bounds?.height ?? null;

  const primaryKey =
    primary?.dataset?.lvbNode ||
    primary?.dataset?.lvbId ||
    (keys[0] ? String(keys[0]).replace(/^node:/, "") : null);
  const identityKey = primaryKey
    ? primaryKey.startsWith("node:") || primaryKey.startsWith("shell:")
      ? primaryKey
      : `node:${primaryKey}`
    : null;

  const requestId = options.requestId || newRequestId();

  const context = {
    protocol: CONTEXT_PROTOCOL,
    version: CONTEXT_VERSION,
    request: {
      id: requestId,
      task: options.task || "generate_image",
      instruction: String(options.instruction || "").trim(),
      createdAt: new Date().toISOString(),
    },
    page: {
      id: state.content?.docId || null,
      route: state.page || (typeof location !== "undefined" ? location.pathname : "/"),
      kind: "studio-page",
      mode: state.viewMode || "design",
      viewport: {
        width: typeof window !== "undefined" ? window.innerWidth : null,
        height: typeof window !== "undefined" ? window.innerHeight : null,
        breakpoint: state.breakpoint || "desktop",
      },
    },
    selection: {
      keys: keys.map(String).slice(0, 32),
      primary: identityKey,
      count: keys.length || (primary ? 1 : 0),
      role,
      tag: primary?.tagName?.toLowerCase() || null,
      bounds: bounds || {},
      aspectRatio,
      computedSummary,
      kind,
    },
    style: {
      source: styleSource,
      theme: null,
      tags: [],
      tokens: styleSource === "selected_element" && options.includeTokens === false ? {} : tokens,
      typography: {
        fontFamily: computedSummary.fontFamily || null,
        fontSize: computedSummary.fontSize || null,
        fontWeight: computedSummary.fontWeight || null,
      },
      palette,
      effects: {
        boxShadow: computedSummary.boxShadow || null,
        opacity: computedSummary.opacity || null,
        borderRadius: computedSummary.borderRadius || null,
      },
      spacing: {},
      styleSummary: styleSummaryFrom(tokens, computedSummary, styleSource),
      customInstruction: options.customStyle || "",
    },
    surroundings: {
      parent,
      siblings,
      nearby,
    },
    asset: {
      current: options.includeExistingImage === false ? null : currentAsset,
      references: [],
    },
    visualContext: {
      pageSnapshot: null,
      selectionSnapshot: null,
      regionSnapshot: null,
      included: [],
      degraded: false,
      degradeReason: null,
    },
    output: {
      kind: options.outputKind || "asset",
      placement: options.placement || "cover",
      width: width ? Math.round(width) : null,
      height: height ? Math.round(height) : null,
      aspectRatio,
      variants: Math.max(1, Math.min(4, Number(options.variants) || 1)),
    },
    policy: emptyPolicy(),
    targetFingerprint: {
      pageId: state.content?.docId || null,
      pageRoute: state.page || null,
      nodeKey: identityKey,
      assetUrl: currentAsset?.url || null,
      bounds,
      generation: ctx.session?.uiEpoch ?? 0,
      contentRevision: state.contentRevision ?? 0,
    },
  };

  // Strip tokens if not requested
  if (options.includeTokens === false) {
    context.style.tokens = {};
    context.style.palette = [];
  }
  if (options.includeNearby === false) {
    context.surroundings = { parent: null, siblings: [], nearby: [] };
  }

  return { context, kind, identityKey, bounds, role };
}

export function contextSummaryLines(context) {
  if (!context) return [];
  const lines = [];
  const page = context.page?.route || "page";
  lines.push(`${page}${context.page?.mode ? ` · ${context.page.mode}` : ""}`);
  const sel = context.selection;
  if (sel?.primary) {
    const b = sel.bounds || {};
    const role = sel.role?.value || sel.tag || "element";
    lines.push(`Selected ${role} · ${b.width || "?"}×${b.height || "?"}`);
  } else {
    lines.push("No selection");
  }
  const included = context.visualContext?.included || [];
  for (const item of included) lines.push(String(item));
  const tokenCount = Object.keys(context.style?.tokens || {}).length;
  if (tokenCount) lines.push(`${tokenCount} theme tokens`);
  if (context.asset?.current?.url) lines.push("Existing image reference");
  if (context.visualContext?.degraded) lines.push(`Degraded: ${context.visualContext.degradeReason || "yes"}`);
  return lines;
}

export { classifyRole, selectionKind, readBounds };
