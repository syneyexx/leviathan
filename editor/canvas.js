(() => {
  /**
   * Leviathan Visual Builder — Full Freedom Layout Editor
   * Free layout · multi-select · reparent · dockable panels · tokens · widgets
   * Overlay only when LEVIATHAN_EDITOR=1 (serve). Never in production builds.
   */
  const API =
    document.querySelector("script[data-lv-editor-api]")?.getAttribute("data-lv-editor-api") ||
    "http://127.0.0.1:5199";

  const FILES = ["tokens.css", "leviathan.css", "pages.css", "chat.css"];
  const SHELL_LOCK = new Set([
    ".lv-app",
    ".lv-body",
    ".lv-header",
    ".lv-sidebar",
    ".lv-footer",
    ".lv-right",
    ".lv-main",
  ]);
  const CHROME_KEY = "lvb-chrome-layout-v1";
  const GRID_SIZE = 8;

  const REGIONS = [
    { id: "header", selector: ".lv-header", label: "Header", varKey: "--lv-header-height", edge: "s", min: 48, max: 180 },
    { id: "sidebar", selector: ".lv-sidebar", label: "Sidebar", varKey: "--lv-sidebar-width", edge: "e", min: 110, max: 340 },
    { id: "right", selector: ".lv-right", label: "Right panel", varKey: "--lv-right-panel-width", edge: "w", min: 120, max: 420 },
    { id: "footer", selector: ".lv-footer", label: "Footer", varKey: "--lv-footer-height", edge: "n", min: 44, max: 140 },
    { id: "main", selector: ".lv-main", label: "Main", varKey: null, edge: null, min: 0, max: 64 },
  ];

  const STYLE_GROUPS = [
    {
      title: "Positie",
      props: [
        { key: "position", label: "Position", type: "text", ph: "relative" },
        { key: "left", label: "Left", type: "text", ph: "0px" },
        { key: "top", label: "Top", type: "text", ph: "0px" },
        { key: "right", label: "Right", type: "text", ph: "auto" },
        { key: "bottom", label: "Bottom", type: "text", ph: "auto" },
        { key: "z-index", label: "Z-index", type: "text", ph: "1" },
        { key: "transform", label: "Transform", type: "text", ph: "none" },
        { key: "rotate", label: "Rotate (°)", type: "text", ph: "0" },
      ],
    },
    {
      title: "Afmetingen",
      props: [
        { key: "width", label: "Width", type: "text", ph: "auto" },
        { key: "height", label: "Height", type: "text", ph: "auto" },
        { key: "min-width", label: "Min W", type: "text", ph: "0" },
        { key: "max-width", label: "Max W", type: "text", ph: "none" },
        { key: "min-height", label: "Min H", type: "text", ph: "0" },
        { key: "max-height", label: "Max H", type: "text", ph: "none" },
      ],
    },
    {
      title: "Flex / Grid",
      props: [
        { key: "display", label: "Display", type: "text", ph: "flex" },
        { key: "flex-direction", label: "Direction", type: "text", ph: "column" },
        { key: "flex-wrap", label: "Wrap", type: "text", ph: "nowrap" },
        { key: "align-items", label: "Align", type: "text", ph: "center" },
        { key: "justify-content", label: "Justify", type: "text", ph: "center" },
        { key: "align-self", label: "Align self", type: "text", ph: "auto" },
        { key: "flex", label: "Flex", type: "text", ph: "0 1 auto" },
        { key: "grid-template-columns", label: "Grid cols", type: "text", ph: "1fr 1fr" },
        { key: "grid-template-rows", label: "Grid rows", type: "text", ph: "auto" },
        { key: "grid-gap", label: "Grid gap", type: "text", ph: "12px" },
        { key: "place-items", label: "Place", type: "text", ph: "center" },
      ],
    },
    {
      title: "Spacing",
      props: [
        { key: "padding", label: "Padding", type: "text", ph: "12px" },
        { key: "padding-top", label: "Pad T", type: "text", ph: "" },
        { key: "padding-right", label: "Pad R", type: "text", ph: "" },
        { key: "padding-bottom", label: "Pad B", type: "text", ph: "" },
        { key: "padding-left", label: "Pad L", type: "text", ph: "" },
        { key: "margin", label: "Margin", type: "text", ph: "0" },
        { key: "margin-top", label: "Mar T", type: "text", ph: "" },
        { key: "margin-right", label: "Mar R", type: "text", ph: "" },
        { key: "margin-bottom", label: "Mar B", type: "text", ph: "" },
        { key: "margin-left", label: "Mar L", type: "text", ph: "" },
        { key: "gap", label: "Gap", type: "text", ph: "10px" },
      ],
    },
    {
      title: "Typografie",
      props: [
        { key: "color", label: "Tekstkleur", type: "color" },
        { key: "font-size", label: "Font size", type: "text", ph: "16px" },
        { key: "font-weight", label: "Weight", type: "text", ph: "600" },
        { key: "font-family", label: "Font", type: "text", ph: "Cinzel, serif" },
        { key: "letter-spacing", label: "Tracking", type: "text", ph: "0.12em" },
        { key: "line-height", label: "Line height", type: "text", ph: "1.4" },
        { key: "text-align", label: "Align", type: "text", ph: "left" },
        { key: "text-transform", label: "Transform", type: "text", ph: "uppercase" },
        { key: "white-space", label: "Whitespace", type: "text", ph: "normal" },
        { key: "text-overflow", label: "Overflow", type: "text", ph: "ellipsis" },
      ],
    },
    {
      title: "Achtergrond & rand",
      props: [
        { key: "background", label: "Background", type: "text", ph: "#0a0c0b" },
        { key: "background-color", label: "BG color", type: "color" },
        { key: "background-image", label: "BG image", type: "text", ph: "url(...)" },
        { key: "background-size", label: "BG size", type: "text", ph: "cover" },
        { key: "background-position", label: "BG pos", type: "text", ph: "center" },
        { key: "border", label: "Border", type: "text", ph: "1px solid #74572B" },
        { key: "border-color", label: "Border color", type: "color" },
        { key: "border-width", label: "Border W", type: "text", ph: "1px" },
        { key: "border-radius", label: "Radius", type: "text", ph: "12px" },
        { key: "outline", label: "Outline", type: "text", ph: "none" },
      ],
    },
    {
      title: "Effecten",
      props: [
        { key: "box-shadow", label: "Shadow", type: "text", ph: "0 8px 24px rgba(0,0,0,.4)" },
        { key: "opacity", label: "Opacity", type: "text", ph: "1" },
        { key: "overflow", label: "Overflow", type: "text", ph: "hidden" },
        { key: "overflow-x", label: "Overflow X", type: "text", ph: "auto" },
        { key: "overflow-y", label: "Overflow Y", type: "text", ph: "auto" },
        { key: "filter", label: "Filter", type: "text", ph: "none" },
        { key: "backdrop-filter", label: "Backdrop", type: "text", ph: "blur(8px)" },
        { key: "object-fit", label: "Object-fit", type: "text", ph: "cover" },
        { key: "object-position", label: "Focal", type: "text", ph: "50% 50%" },
        { key: "pointer-events", label: "Pointer", type: "text", ph: "auto" },
        { key: "cursor", label: "Cursor", type: "text", ph: "default" },
      ],
    },
  ];

  const INSERT_PRESETS = {
    text: {
      label: "tekst",
      html: `<p class="lvb-widget lvb-text" style="margin:0;color:#E8E4DC;font-size:14px;">Nieuwe tekst — dubbelklik om te bewerken</p>`,
    },
    heading: {
      label: "titel",
      html: `<h2 class="lvb-widget lvb-heading" style="margin:0;color:#F5DFA9;font-family:Cinzel,serif;letter-spacing:0.2em;text-transform:uppercase;">Nieuwe titel</h2>`,
    },
    image: { label: "image", html: null },
    button: {
      label: "knop",
      html: `<button type="button" class="lvb-widget lvb-button lv-button-primary" style="padding:10px 16px;">Nieuwe knop</button>`,
    },
    divider: {
      label: "lijn",
      html: `<hr class="lvb-widget lvb-divider" style="width:180px;border:0;border-top:1px solid rgba(214,169,87,0.35);margin:8px 0;" />`,
    },
    spacer: {
      label: "spacer",
      html: `<div class="lvb-widget lvb-spacer" style="width:100%;height:24px;min-height:8px;" aria-hidden="true"></div>`,
    },
    container: {
      label: "frame",
      html: `<div class="lvb-widget lvb-frame" style="min-width:200px;min-height:120px;padding:16px;border:1px dashed rgba(214,169,87,0.45);border-radius:12px;background:rgba(8,10,9,0.55);position:relative;"></div>`,
    },
    html: {
      label: "html",
      html: `<div class="lvb-widget lvb-html" style="padding:10px;color:#E8E4DC;border:1px solid rgba(214,169,87,0.25);border-radius:8px;">Custom HTML</div>`,
    },
  };

  const TOKEN_KEYS = [
    { key: "--lv-bg", label: "Achtergrond", type: "color" },
    { key: "--lv-fg", label: "Voorgrond", type: "color" },
    { key: "--lv-gold", label: "Goud", type: "color" },
    { key: "--lv-gold-soft", label: "Goud soft", type: "color" },
    { key: "--lv-border", label: "Rand", type: "color" },
    { key: "--lv-header-height", label: "Header H", type: "size" },
    { key: "--lv-sidebar-width", label: "Sidebar W", type: "size" },
    { key: "--lv-right-panel-width", label: "Right W", type: "size" },
    { key: "--lv-footer-height", label: "Footer H", type: "size" },
    { key: "--lv-radius", label: "Radius", type: "size" },
    { key: "--lv-font-body", label: "Font body", type: "text" },
    { key: "--lv-font-display", label: "Font display", type: "text" },
    { key: "--lv-space-1", label: "Space 1", type: "size" },
    { key: "--lv-space-2", label: "Space 2", type: "size" },
    { key: "--lv-space-3", label: "Space 3", type: "size" },
    { key: "--lv-space-4", label: "Space 4", type: "size" },
  ];

  const DEFAULT_CHROME = {
    leftW: 260,
    rightW: 320,
    bottomH: 0,
    leftCollapsed: false,
    rightCollapsed: false,
    bottomOpen: false,
    docks: {
      left: ["layers", "insert", "assets"],
      right: ["inspector", "tokens"],
      bottom: ["code", "history"],
    },
    floating: {},
    activeTabs: { left: "layers", right: "inspector", bottom: "code" },
  };

  const PANEL_META = {
    inspector: { title: "Inspector", icon: "◈" },
    layers: { title: "Layers", icon: "☰" },
    assets: { title: "Assets", icon: "▣" },
    insert: { title: "Invoegen", icon: "+" },
    tokens: { title: "Tokens", icon: "◐" },
    code: { title: "Code", icon: "{}" },
    history: { title: "History", icon: "↺" },
  };

  const state = {
    enabled: true,
    snap: true,
    grid: false,
    aspectLock: false,
    autoSave: true,
    rotateEnabled: true,
    files: Object.fromEntries(FILES.map((n) => [n, ""])),
    saved: Object.fromEntries(FILES.map((n) => [n, ""])),
    dirty: Object.fromEntries(FILES.map((n) => [n, false])),
    content: { version: 2, entries: {}, nodes: [] },
    contentDirty: false,
    activeFile: "leviathan.css",
    selectedEls: [],
    selectedEl: null,
    selectedRegion: null,
    selectedSelector: null,
    hoverEl: null,
    saveTimer: null,
    mode: null,
    inlineEditing: false,
    applyingContent: false,
    clipboard: null,
    history: [],
    historyIndex: -1,
    suppressHistory: false,
    imagePickerMode: "insert",
    dropTarget: null,
    chrome: structuredClone(DEFAULT_CHROME),
    zoom: 1,
  };

  const ui = {};

  /* ------------------------------------------------------------------ */
  /* Utils                                                              */
  /* ------------------------------------------------------------------ */

  function $(sel, root = document) {
    return root.querySelector(sel);
  }

  function $$(sel, root = document) {
    return [...root.querySelectorAll(sel)];
  }

  function escapeReg(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function uid(prefix = "lvb") {
    return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
  }

  function setStatus(text, kind = "") {
    if (ui.status) {
      ui.status.textContent = text;
      ui.status.className = `lvb-status-pill${kind ? ` is-${kind}` : ""}`;
    }
    if (ui.barSave) {
      const any = state.contentDirty || FILES.some((f) => state.dirty[f]);
      ui.barSave.textContent = any ? "Dirty" : "Synced";
      ui.barSave.style.color = any ? "#db8a34" : "#20dc8c";
    }
  }

  function isBuilderNode(node) {
    return !!(node && (node === ui.root || (ui.root && ui.root.contains(node))));
  }

  function isShellLocked(el) {
    if (!(el instanceof Element)) return true;
    return [...el.classList].some((c) => SHELL_LOCK.has(`.${c}`));
  }

  function isLocked(el) {
    return el?.dataset?.lvbLocked === "1" || getEntry(selectorFor(el))?.locked;
  }

  function canMutate(el) {
    return el && !isShellLocked(el) && !isLocked(el);
  }

  function selectorFor(el) {
    if (!(el instanceof Element)) return "unknown";
    if (el.dataset.lvbId) return `[data-lvb-id="${el.dataset.lvbId}"]`;
    if (el.tagName === "IMG") {
      const src = el.getAttribute("src");
      if (src) return `img[src="${src}"]`;
      return "img";
    }
    const lv = [...el.classList].filter((c) => c.startsWith("lv-") && !c.startsWith("lvb-"));
    if (lv.length === 1) return `.${lv[0]}`;
    if (lv.length > 1) return `.${lv.join(".")}`;
    if (el.id && el.id !== "root") return `#${el.id}`;
    const tag = el.tagName.toLowerCase();
    const parent = el.parentElement;
    if (parent && parent !== document.body) {
      const idx = [...parent.children].indexOf(el) + 1;
      return `${selectorFor(parent)} > ${tag}:nth-child(${idx})`;
    }
    return tag;
  }

  function regionFor(el) {
    return REGIONS.find((r) => el.matches?.(r.selector)) || null;
  }

  function hasDirectText(el) {
    return [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  }

  function labelFor(el) {
    if (el.dataset?.lvbId) return el.dataset.lvbLabel || el.dataset.lvbId;
    if (el.tagName === "IMG") return "image";
    const lv = [...el.classList].find((c) => c.startsWith("lv-"));
    return lv ? `.${lv}` : el.tagName.toLowerCase();
  }

  function findDescendantImage(el) {
    if (!(el instanceof Element)) return null;
    if (el.tagName === "IMG") return el;
    const preferred = el.querySelector(
      "img.lv-sidebar-footer-mark, img.lv-thumb, img.lv-avatar, img.lv-ornament-img, img.lv-msg-avatar, .lv-earth-mini img, .lv-hero-media img, .lv-world-view img, .lv-brand-mark img, img.lvb-image",
    );
    if (preferred && !isBuilderNode(preferred)) return preferred;
    const directImgs = [...el.children].filter((c) => c.tagName === "IMG" && !isBuilderNode(c));
    if (directImgs.length === 1) return directImgs[0];
    const all = [...el.querySelectorAll("img")].filter((img) => !isBuilderNode(img));
    if (all.length === 1) return all[0];
    return null;
  }

  function resolveImageEl(el) {
    if (!el) return null;
    if (el.tagName === "IMG") return el;
    return findDescendantImage(el);
  }

  function hasReplaceableBackground(el) {
    if (!(el instanceof Element)) return false;
    try {
      const bg = getComputedStyle(el).backgroundImage || "";
      return /url\(/i.test(bg) && bg !== "none";
    } catch {
      return false;
    }
  }

  function pickEditable(target, clientX, clientY) {
    if (!(target instanceof Element) || isBuilderNode(target)) return null;

    let imgHit = target.tagName === "IMG" ? target : target.closest?.("img");
    if (!imgHit) imgHit = findDescendantImage(target);
    if (!imgHit && clientX != null && clientY != null) {
      const prev = ui.select?.style.pointerEvents;
      const prevHover = ui.hover?.style.pointerEvents;
      if (ui.select) ui.select.style.pointerEvents = "none";
      if (ui.hover) ui.hover.style.pointerEvents = "none";
      $$(".lvb-multi", ui.root).forEach((n) => (n.style.pointerEvents = "none"));
      try {
        const stack = document.elementsFromPoint(clientX, clientY);
        for (const node of stack) {
          if (!(node instanceof Element) || isBuilderNode(node)) continue;
          if (node.tagName === "IMG") {
            imgHit = node;
            break;
          }
          const nested = findDescendantImage(node);
          if (nested) {
            imgHit = nested;
            break;
          }
        }
      } finally {
        if (ui.select) ui.select.style.pointerEvents = prev || "";
        if (ui.hover) ui.hover.style.pointerEvents = prevHover || "";
      }
    }
    if (imgHit && !isBuilderNode(imgHit)) {
      return { el: imgHit, region: regionFor(imgHit), selector: selectorFor(imgHit), kind: "img" };
    }

    let el = target;
    while (el && el !== document.body && el.id !== "root") {
      if (isBuilderNode(el)) return null;
      if (el.dataset?.lvbId) return { el, region: regionFor(el), selector: selectorFor(el), kind: "widget" };
      if (el.classList && [...el.classList].some((c) => c.startsWith("lv-"))) {
        const kind = el.childElementCount === 0 || hasDirectText(el) ? "texty" : "element";
        return { el, region: regionFor(el), selector: selectorFor(el), kind };
      }
      if (["H1", "H2", "H3", "H4", "P", "SPAN", "LABEL", "BUTTON", "A", "DIV", "SECTION", "ARTICLE"].includes(el.tagName)) {
        return { el, region: regionFor(el), selector: selectorFor(el), kind: "texty" };
      }
      el = el.parentElement;
    }
    return null;
  }

  function getEntry(selector) {
    return state.content.entries?.[selector] || null;
  }

  function ensureContentShape() {
    state.content.version = 2;
    state.content.entries = state.content.entries || {};
    state.content.nodes = state.content.nodes || [];
  }

  function primarySelection() {
    return state.selectedEls[0] || state.selectedEl || null;
  }

  function setPrimaryFromList() {
    state.selectedEl = primarySelection();
    if (state.selectedEl) {
      state.selectedRegion = regionFor(state.selectedEl);
      state.selectedSelector = selectorFor(state.selectedEl);
    } else {
      state.selectedRegion = null;
      state.selectedSelector = null;
    }
  }

  /* ------------------------------------------------------------------ */
  /* CSS helpers                                                        */
  /* ------------------------------------------------------------------ */

  function parseClamp(value) {
    const m = String(value || "")
      .trim()
      .match(/^clamp\(\s*([\d.]+)(px|vh|vw|%)\s*,\s*([\d.]+)(px|vh|vw|%)\s*,\s*([\d.]+)(px|vh|vw|%)\s*\)$/i);
    if (!m) return null;
    return {
      min: Number(m[1]),
      minUnit: m[2],
      preferred: Number(m[3]),
      preferredUnit: m[4],
      max: Number(m[5]),
      maxUnit: m[6],
    };
  }

  function formatClamp(p) {
    return `clamp(${p.min}${p.minUnit}, ${p.preferred}${p.preferredUnit}, ${p.max}${p.maxUnit})`;
  }

  function getVar(css, key) {
    const m = css.match(new RegExp(`(${escapeReg(key)}\\s*:\\s*)([^;]+);`));
    return m ? m[2].trim() : null;
  }

  function setVar(css, key, value) {
    const re = new RegExp(`(${escapeReg(key)}\\s*:\\s*)([^;]+)(;)`);
    if (!re.test(css)) {
      // append into :root if possible
      if (/:root\s*\{/.test(css)) {
        return css.replace(/:root\s*\{/, `:root {\n  ${key}: ${value};`);
      }
      return `${css}\n:root { ${key}: ${value}; }\n`;
    }
    return css.replace(re, `$1${value}$3`);
  }

  function pxFromCssValue(value, fallback = 80) {
    const clamp = parseClamp(value);
    if (clamp) {
      if (clamp.preferredUnit === "px") return clamp.preferred;
      if (clamp.maxUnit === "px") return clamp.max;
      return fallback;
    }
    const m = String(value || "").match(/^([\d.]+)px$/i);
    return m ? Number(m[1]) : fallback;
  }

  function cssFromPx(current, px, def) {
    const clamp = parseClamp(current || "");
    if (clamp) {
      const next = { ...clamp };
      if (next.preferredUnit === "px") next.preferred = px;
      else {
        next.preferred = px;
        next.preferredUnit = "px";
      }
      if (next.maxUnit === "px" && next.max < px) next.max = px;
      if (next.minUnit === "px" && next.min > px) next.min = Math.max(def.min, Math.round(px * 0.75));
      return formatClamp(next);
    }
    return `${Math.round(px)}px`;
  }

  const BEGIN = (sel) => `/* === LV-EDITOR:BEGIN ${sel} === */`;
  const END = (sel) => `/* === LV-EDITOR:END ${sel} === */`;

  function upsertOverride(css, selector, declarations) {
    const block = `${BEGIN(selector)}\n${selector} {\n${declarations}\n}\n${END(selector)}`;
    const re = new RegExp(`${escapeReg(BEGIN(selector))}[\\s\\S]*?${escapeReg(END(selector))}`);
    if (re.test(css)) return css.replace(re, block);
    return `${css.replace(/\s*$/, "")}\n\n${block}\n`;
  }

  function readOverrideDecls(css, selector) {
    const re = new RegExp(
      `${escapeReg(BEGIN(selector))}[\\s\\S]*?${escapeReg(selector)}\\s*\\{([\\s\\S]*?)\\}[\\s\\S]*?${escapeReg(END(selector))}`,
    );
    const m = css.match(re);
    if (!m) return {};
    const out = {};
    for (const line of m[1].split(";")) {
      const [k, ...rest] = line.split(":");
      if (!k || !rest.length) continue;
      out[k.trim()] = rest.join(":").trim();
    }
    return out;
  }

  function declsToText(decls) {
    return Object.entries(decls)
      .filter(([, v]) => v != null && String(v).trim() !== "")
      .map(([k, v]) => `  ${k}: ${v};`)
      .join("\n");
  }

  function styleFileForSelector() {
    if (location.pathname.includes("chat")) return "chat.css";
    if (["/brain", "/models", "/training", "/settings", "/status", "/research", "/datasets", "/tools"].some((p) =>
      location.pathname.includes(p),
    )) {
      return "pages.css";
    }
    return "leviathan.css";
  }

  function parseRotateDeg(el) {
    const t = el.style.transform || getComputedStyle(el).transform || "";
    const m = t.match(/rotate\(\s*(-?[\d.]+)deg\s*\)/i);
    if (m) return Number(m[1]);
    const mm = t.match(/matrix\(([^)]+)\)/);
    if (mm) {
      const parts = mm[1].split(",").map((x) => Number(x.trim()));
      if (parts.length >= 2) return (Math.atan2(parts[1], parts[0]) * 180) / Math.PI;
    }
    return 0;
  }

  function setRotateDeg(el, deg) {
    const t = (el.style.transform || "").replace(/rotate\([^)]*\)/gi, "").trim();
    const next = `${t} rotate(${Math.round(deg)}deg)`.trim();
    el.style.transform = next;
  }

  /* ------------------------------------------------------------------ */
  /* API                                                                */
  /* ------------------------------------------------------------------ */

  async function apiGet(name) {
    const res = await fetch(`${API}/api/file?name=${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error(`Laden mislukt: ${name}`);
    return res.json();
  }

  async function apiPut(name, content) {
    const res = await fetch(`${API}/api/file?name=${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!res.ok) throw new Error(`Opslaan mislukt: ${name}`);
    return res.json();
  }

  async function apiGetContent() {
    const res = await fetch(`${API}/api/content`);
    if (!res.ok) throw new Error("Content laden mislukt");
    return res.json();
  }

  async function apiPutContent(content) {
    const res = await fetch(`${API}/api/content`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!res.ok) throw new Error("Content opslaan mislukt");
    return res.json();
  }

  async function apiReplaceText(oldText, newText) {
    if (!oldText || oldText === newText || oldText.length < 2) return { changed: [] };
    const res = await fetch(`${API}/api/replace-text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old: oldText, new: newText }),
    });
    if (!res.ok) throw new Error("Brontekst vervangen mislukt");
    return res.json();
  }

  async function apiUpload(filename, dataUrl) {
    const res = await fetch(`${API}/api/upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, data: dataUrl }),
    });
    if (!res.ok) throw new Error("Upload mislukt");
    return res.json();
  }

  async function apiListAssets() {
    const res = await fetch(`${API}/api/assets`);
    if (!res.ok) throw new Error("Assets laden mislukt");
    return res.json();
  }

  /* ------------------------------------------------------------------ */
  /* History / dirty / save                                             */
  /* ------------------------------------------------------------------ */

  function pushHistory(label = "edit") {
    if (state.suppressHistory) return;
    const snap = {
      label,
      files: structuredClone(state.files),
      content: structuredClone(state.content),
      at: Date.now(),
    };
    state.history = state.history.slice(0, state.historyIndex + 1);
    state.history.push(snap);
    if (state.history.length > 80) state.history.shift();
    state.historyIndex = state.history.length - 1;
    renderHistoryPanel();
  }

  function restoreHistory(index) {
    const snap = state.history[index];
    if (!snap) return;
    state.suppressHistory = true;
    state.files = structuredClone(snap.files);
    state.content = structuredClone(snap.content);
    ensureContentShape();
    FILES.forEach((f) => {
      state.dirty[f] = state.files[f] !== state.saved[f];
    });
    state.contentDirty = true;
    applyTokensLive();
    applyContentOverrides();
    mountNodes();
    syncCodePane();
    renderAllPanels();
    refreshSelectionChrome();
    state.suppressHistory = false;
    state.historyIndex = index;
    setStatus(`History: ${snap.label}`, "ok");
    scheduleSave();
    renderHistoryPanel();
  }

  function undo() {
    if (state.historyIndex <= 0) return setStatus("Niets om terug te zetten", "dirty");
    restoreHistory(state.historyIndex - 1);
  }

  function redo() {
    if (state.historyIndex >= state.history.length - 1) return setStatus("Niets om opnieuw te doen", "dirty");
    restoreHistory(state.historyIndex + 1);
  }

  function markDirty(name) {
    state.dirty[name] = state.files[name] !== state.saved[name];
    updateDirtyStatus();
    if (state.autoSave) scheduleSave();
  }

  function markContentDirty() {
    state.contentDirty = true;
    updateDirtyStatus();
    if (state.autoSave) scheduleSave();
  }

  function updateDirtyStatus() {
    const any = state.contentDirty || FILES.some((f) => state.dirty[f]);
    setStatus(any ? "Niet opgeslagen · auto-save" : "Gesynchroniseerd", any ? "dirty" : "ok");
  }

  function scheduleSave() {
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(() => {
      saveAll().catch((err) => setStatus(String(err), "dirty"));
    }, 550);
  }

  async function saveAll() {
    const dirty = FILES.filter((f) => state.dirty[f]);
    if (!dirty.length && !state.contentDirty) {
      setStatus("Niets te opslaan", "ok");
      return;
    }
    setStatus("Opslaan…");
    for (const name of dirty) {
      await apiPut(name, state.files[name]);
      state.saved[name] = state.files[name];
      state.dirty[name] = false;
    }
    if (state.contentDirty) {
      syncNodesFromDom();
      await apiPutContent(state.content);
      state.contentDirty = false;
    }
    setStatus("Opgeslagen in Leviathan-bestanden", "ok");
  }

  async function loadAll() {
    for (const name of FILES) {
      const data = await apiGet(name);
      state.files[name] = data.content;
      state.saved[name] = data.content;
      state.dirty[name] = false;
    }
    const contentRes = await apiGetContent();
    state.content = contentRes.content || { version: 2, entries: {}, nodes: [] };
    ensureContentShape();
    state.contentDirty = false;
    state.history = [];
    state.historyIndex = -1;
    pushHistory("load");
    syncCodePane();
    applyTokensLive();
    applyContentOverrides();
    mountNodes();
    renderAllPanels();
    setStatus("Visual builder klaar", "ok");
  }

  /* ------------------------------------------------------------------ */
  /* Apply live CSS / content / widgets                                 */
  /* ------------------------------------------------------------------ */

  function applyTokensLive() {
    const tokens = state.files["tokens.css"] || "";
    const re = /(--lv-[\w-]+)\s*:\s*([^;]+);/g;
    let match;
    while ((match = re.exec(tokens))) {
      document.documentElement.style.setProperty(match[1], match[2].trim());
    }
    let ov = document.getElementById("lvb-live-overrides");
    if (!ov) {
      ov = document.createElement("style");
      ov.id = "lvb-live-overrides";
      document.head.appendChild(ov);
    }
    const blocks = [];
    const blockRe = /\/\* === LV-EDITOR:BEGIN [\s\S]*?=== LV-EDITOR:END .*? === \*\//g;
    for (const file of ["leviathan.css", "pages.css", "chat.css"]) {
      const found = (state.files[file] || "").match(blockRe);
      if (found) blocks.push(...found);
    }
    ov.textContent = blocks.join("\n");
  }

  function applyEntryToEl(el, entry) {
    if (!entry || !(el instanceof Element)) return;
    if (entry.text != null && el.tagName !== "IMG") {
      if (el.childElementCount === 0 || hasDirectText(el)) el.textContent = entry.text;
    }
    if (entry.src && el.tagName === "IMG") el.setAttribute("src", entry.src);
    if (entry.alt != null && el.tagName === "IMG") el.setAttribute("alt", entry.alt);
    if (entry.styles) {
      for (const [k, v] of Object.entries(entry.styles)) {
        el.style.setProperty(k, v);
      }
    }
    if (entry.left != null) el.style.left = entry.left;
    if (entry.top != null) el.style.top = entry.top;
    if (entry.width != null) el.style.width = entry.width;
    if (entry.height != null) el.style.height = entry.height;
    if (entry.position) el.style.position = entry.position;
    if (entry.zIndex != null) el.style.zIndex = String(entry.zIndex);
    if (entry.hide) el.style.display = "none";
    if (entry.locked) el.dataset.lvbLocked = "1";
  }

  function applyContentOverrides() {
    state.applyingContent = true;
    try {
      ensureContentShape();
      for (const [selector, entry] of Object.entries(state.content.entries)) {
        let nodes;
        try {
          nodes = document.querySelectorAll(selector);
        } catch {
          continue;
        }
        nodes.forEach((el) => {
          if (!(el instanceof Element) || isBuilderNode(el)) return;
          applyEntryToEl(el, entry);
        });
      }
    } finally {
      state.applyingContent = false;
    }
  }

  function mountNodes() {
    state.applyingContent = true;
    try {
      document.querySelectorAll("[data-lvb-id]").forEach((el) => {
        if (!state.content.nodes.some((n) => n.id === el.dataset.lvbId)) el.remove();
      });
      for (const node of state.content.nodes) {
        let el = document.querySelector(`[data-lvb-id="${node.id}"]`);
        if (!el) {
          const wrap = document.createElement("div");
          wrap.innerHTML = node.html;
          el = wrap.firstElementChild;
          if (!el) continue;
          el.dataset.lvbId = node.id;
          if (node.label) el.dataset.lvbLabel = node.label;
          const parent =
            document.querySelector(node.parent || ".lv-main") || document.getElementById("root") || document.body;
          parent.appendChild(el);
        }
        if (node.styles) {
          for (const [k, v] of Object.entries(node.styles)) {
            if (v != null && v !== "") el.style.setProperty(k, v);
          }
        }
      }
    } finally {
      state.applyingContent = false;
    }
  }

  function syncNodesFromDom() {
    ensureContentShape();
    state.content.nodes = state.content.nodes.map((node) => {
      const el = document.querySelector(`[data-lvb-id="${node.id}"]`);
      if (!el) return node;
      const clone = el.cloneNode(true);
      return {
        ...node,
        html: clone.outerHTML,
        parent: selectorFor(el.parentElement) || node.parent || ".lv-main",
        styles: {
          ...(node.styles || {}),
          position: el.style.position || undefined,
          left: el.style.left || undefined,
          top: el.style.top || undefined,
          width: el.style.width || undefined,
          height: el.style.height || undefined,
          zIndex: el.style.zIndex || undefined,
          transform: el.style.transform || undefined,
          minWidth: el.style.minWidth || undefined,
          maxWidth: el.style.maxWidth || undefined,
          minHeight: el.style.minHeight || undefined,
          maxHeight: el.style.maxHeight || undefined,
        },
      };
    });
  }

  function upsertContentEntry(selector, patch) {
    ensureContentShape();
    const prev = state.content.entries[selector] || {};
    state.content.entries[selector] = { ...prev, ...patch };
    markContentDirty();
  }

  /* ------------------------------------------------------------------ */
  /* Selection chrome                                                   */
  /* ------------------------------------------------------------------ */

  function syncCodePane() {
    if (!ui.codeArea) return;
    if (state.activeFile === "__content__") {
      if (ui.codeFile) ui.codeFile.textContent = "lv-editor-content.json";
      if (document.activeElement !== ui.codeArea) ui.codeArea.value = JSON.stringify(state.content, null, 2);
    } else {
      if (ui.codeFile) ui.codeFile.textContent = state.activeFile;
      if (document.activeElement !== ui.codeArea) ui.codeArea.value = state.files[state.activeFile] || "";
    }
    if (ui.files) {
      ui.files.querySelectorAll(".lvb-chip").forEach((c) => {
        c.classList.toggle("is-on", c.dataset.file === state.activeFile);
      });
    }
  }

  function boxFromEl(el) {
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, width: r.width, height: r.height };
  }

  function placeBox(node, rect, withHandles) {
    node.style.left = `${rect.left}px`;
    node.style.top = `${rect.top}px`;
    node.style.width = `${Math.max(rect.width, 8)}px`;
    node.style.height = `${Math.max(rect.height, 8)}px`;
    node.hidden = false;
    if (withHandles) {
      node.querySelectorAll(".lvb-handle, .lvb-move-grip").forEach((h) => h.remove());
      const region = state.selectedRegion;
      const dirs = region?.edge ? [region.edge] : ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
      for (const dir of dirs) {
        const handle = document.createElement("div");
        handle.className = "lvb-handle";
        handle.dataset.dir = dir;
        node.appendChild(handle);
      }
      if (state.rotateEnabled && !region?.edge && canMutate(state.selectedEl)) {
        const rot = document.createElement("div");
        rot.className = "lvb-handle";
        rot.dataset.dir = "rot";
        rot.title = "Roteer";
        node.appendChild(rot);
      }
      if (!region?.edge && canMutate(state.selectedEl)) {
        const move = document.createElement("div");
        move.className = "lvb-move-grip";
        move.title = "Slepen om te verplaatsen (Shift = multi)";
        move.textContent = "✥";
        node.appendChild(move);
      }
    }
  }

  function refreshSelectionChrome() {
    if (!state.enabled || state.inlineEditing) {
      if (ui.hover) ui.hover.hidden = true;
      if (!state.selectedEl || state.inlineEditing) {
        if (ui.select) ui.select.hidden = true;
      }
      clearMultiBoxes();
      return;
    }

    if (state.hoverEl && !state.selectedEls.includes(state.hoverEl)) {
      placeBox(ui.hover, boxFromEl(state.hoverEl), false);
      ui.hoverLabel.textContent = labelFor(state.hoverEl);
    } else if (ui.hover) ui.hover.hidden = true;

    clearMultiBoxes();
    if (state.selectedEls.length > 1) {
      for (const el of state.selectedEls.slice(1)) {
        const box = document.createElement("div");
        box.className = "lvb-multi";
        const r = boxFromEl(el);
        box.style.left = `${r.left}px`;
        box.style.top = `${r.top}px`;
        box.style.width = `${r.width}px`;
        box.style.height = `${r.height}px`;
        ui.root.appendChild(box);
      }
    }

    if (state.selectedEl) {
      placeBox(ui.select, boxFromEl(state.selectedEl), true);
      const lock = isLocked(state.selectedEl) ? " 🔒" : "";
      const multi = state.selectedEls.length > 1 ? ` (+${state.selectedEls.length - 1})` : "";
      ui.selectLabel.textContent = (state.selectedSelector || labelFor(state.selectedEl)) + lock + multi;
    } else if (ui.select) ui.select.hidden = true;

    updateStatusBar();
  }

  function clearMultiBoxes() {
    $$(".lvb-multi", ui.root).forEach((n) => n.remove());
  }

  function updateStatusBar() {
    if (!ui.barSel) return;
    const n = state.selectedEls.length;
    ui.barSel.textContent = n ? `${n} geselecteerd · ${labelFor(state.selectedEl)}` : "Geen selectie";
    if (ui.barZoom) ui.barZoom.textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function selectTarget(picked, { additive = false } = {}) {
    endInlineEdit(true);
    hideContextMenu();
    if (!picked?.el) return;
    if (additive) {
      const idx = state.selectedEls.indexOf(picked.el);
      if (idx >= 0) state.selectedEls.splice(idx, 1);
      else state.selectedEls.push(picked.el);
    } else {
      state.selectedEls = [picked.el];
    }
    setPrimaryFromList();
    if (state.selectedRegion?.varKey) state.activeFile = "tokens.css";
    else state.activeFile = styleFileForSelector();
    syncCodePane();
    renderInspector();
    renderLayersPanel();
    refreshSelectionChrome();
  }

  function clearSelection() {
    endInlineEdit(true);
    state.selectedEls = [];
    setPrimaryFromList();
    refreshSelectionChrome();
    renderInspector();
    renderLayersPanel();
  }

  /* ------------------------------------------------------------------ */
  /* Chrome panel system                                                */
  /* ------------------------------------------------------------------ */

  function loadChromeLayout() {
    try {
      const raw = localStorage.getItem(CHROME_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      state.chrome = { ...structuredClone(DEFAULT_CHROME), ...parsed, docks: { ...DEFAULT_CHROME.docks, ...(parsed.docks || {}) } };
    } catch {
      /* ignore */
    }
  }

  function saveChromeLayout() {
    try {
      localStorage.setItem(CHROME_KEY, JSON.stringify(state.chrome));
    } catch {
      /* ignore */
    }
  }

  function resetChromeLayout() {
    state.chrome = structuredClone(DEFAULT_CHROME);
    saveChromeLayout();
    applyChromeLayout();
    renderChromePanels();
    setStatus("Editor-layout gereset", "ok");
  }

  function applyChromeLayout() {
    const c = state.chrome;
    ui.root.style.setProperty("--lvb-left-w", `${c.leftCollapsed ? 0 : c.leftW}px`);
    ui.root.style.setProperty("--lvb-right-w", `${c.rightCollapsed ? 0 : c.rightW}px`);
    ui.root.style.setProperty("--lvb-bottom-h", `${c.bottomOpen ? c.bottomH || 220 : 0}px`);
    ui.dockLeft.classList.toggle("is-collapsed", !!c.leftCollapsed);
    ui.dockRight.classList.toggle("is-collapsed", !!c.rightCollapsed);
    ui.dockBottom.classList.toggle("is-open", !!c.bottomOpen);
    if (c.bottomOpen && !c.bottomH) {
      c.bottomH = 220;
      ui.root.style.setProperty("--lvb-bottom-h", "220px");
    }
  }

  function panelHost(side) {
    if (side === "left") return ui.dockLeft;
    if (side === "right") return ui.dockRight;
    if (side === "bottom") return ui.dockBottom;
    return ui.floatLayer;
  }

  function findPanelSide(id) {
    for (const side of ["left", "right", "bottom"]) {
      if (state.chrome.docks[side]?.includes(id)) return side;
    }
    if (state.chrome.floating[id]) return "float";
    return null;
  }

  function undockPanel(id) {
    for (const side of ["left", "right", "bottom"]) {
      state.chrome.docks[side] = (state.chrome.docks[side] || []).filter((x) => x !== id);
    }
    const rect = { x: 120, y: 80, w: 300, h: 360 };
    state.chrome.floating[id] = rect;
    saveChromeLayout();
    renderChromePanels();
  }

  function dockPanel(id, side) {
    delete state.chrome.floating[id];
    for (const s of ["left", "right", "bottom"]) {
      state.chrome.docks[s] = (state.chrome.docks[s] || []).filter((x) => x !== id);
    }
    state.chrome.docks[side] = state.chrome.docks[side] || [];
    if (!state.chrome.docks[side].includes(id)) state.chrome.docks[side].push(id);
    state.chrome.activeTabs[side] = id;
    if (side === "bottom") {
      state.chrome.bottomOpen = true;
      if (!state.chrome.bottomH) state.chrome.bottomH = 220;
    }
    if (side === "left") state.chrome.leftCollapsed = false;
    if (side === "right") state.chrome.rightCollapsed = false;
    saveChromeLayout();
    applyChromeLayout();
    renderChromePanels();
  }

  function maximizePanel(id) {
    const side = findPanelSide(id);
    if (side === "float") {
      state.chrome.floating[id] = { x: 40, y: 56, w: window.innerWidth - 80, h: window.innerHeight - 100 };
    } else if (side === "bottom") {
      state.chrome.bottomH = Math.min(480, Math.round(window.innerHeight * 0.45));
      state.chrome.bottomOpen = true;
      applyChromeLayout();
    } else if (side === "left") {
      state.chrome.leftW = Math.min(480, Math.round(window.innerWidth * 0.35));
      applyChromeLayout();
    } else if (side === "right") {
      state.chrome.rightW = Math.min(520, Math.round(window.innerWidth * 0.38));
      applyChromeLayout();
    }
    saveChromeLayout();
    renderChromePanels();
  }

  function renderChromePanels() {
    ui.dockLeft.innerHTML = "";
    ui.dockRight.innerHTML = "";
    ui.dockBottom.innerHTML = "";
    ui.floatLayer.innerHTML = "";

    for (const side of ["left", "right", "bottom"]) {
      const ids = state.chrome.docks[side] || [];
      if (!ids.length) continue;
      const active = state.chrome.activeTabs[side] || ids[0];
      if (ids.length > 1) {
        const tabs = document.createElement("div");
        tabs.className = "lvb-chip-row";
        tabs.style.padding = "6px 8px";
        tabs.innerHTML = ids
          .map(
            (id) =>
              `<button type="button" class="lvb-chip${id === active ? " is-on" : ""}" data-tab-side="${side}" data-tab-id="${id}">${PANEL_META[id]?.title || id}</button>`,
          )
          .join("");
        panelHost(side).appendChild(tabs);
      }
      const showId = ids.includes(active) ? active : ids[0];
      state.chrome.activeTabs[side] = showId;
      panelHost(side).appendChild(buildPanelEl(showId, side));
    }

    for (const [id, rect] of Object.entries(state.chrome.floating || {})) {
      const el = buildPanelEl(id, "float");
      el.classList.add("is-floating");
      el.style.left = `${rect.x}px`;
      el.style.top = `${rect.y}px`;
      el.style.width = `${rect.w}px`;
      el.style.height = `${rect.h}px`;
      const resize = document.createElement("div");
      resize.className = "lvb-panel-resize";
      el.appendChild(resize);
      ui.floatLayer.appendChild(el);
      bindFloatDrag(el, id, resize);
    }

    renderAllPanels();
  }

  function buildPanelEl(id, side) {
    const meta = PANEL_META[id] || { title: id, icon: "•" };
    const panel = document.createElement("div");
    panel.className = "lvb-panel";
    panel.dataset.panel = id;
    panel.dataset.side = side;
    panel.innerHTML = `
      <div class="lvb-panel-head" data-role="panel-head">
        <span class="lvb-panel-title">${meta.icon} ${meta.title}</span>
        <div class="lvb-panel-actions">
          <button type="button" class="lvb-ico" data-panel-act="dock-left" title="Dock links">◀</button>
          <button type="button" class="lvb-ico" data-panel-act="dock-right" title="Dock rechts">▶</button>
          <button type="button" class="lvb-ico" data-panel-act="dock-bottom" title="Dock onder">▼</button>
          <button type="button" class="lvb-ico" data-panel-act="float" title="Float">⧉</button>
          <button type="button" class="lvb-ico" data-panel-act="max" title="Maximaliseer">▣</button>
          <button type="button" class="lvb-ico" data-panel-act="collapse" title="Inklappen">–</button>
        </div>
      </div>
      <div class="lvb-panel-body" data-role="panel-body"></div>
    `;
    return panel;
  }

  function bindFloatDrag(panel, id, resizeHandle) {
    const head = $('[data-role="panel-head"]', panel);
    head.addEventListener("pointerdown", (e) => {
      if (e.target.closest("[data-panel-act]")) return;
      e.preventDefault();
      const startX = e.clientX;
      const startY = e.clientY;
      const rect = state.chrome.floating[id];
      const ox = rect.x;
      const oy = rect.y;
      const onMove = (ev) => {
        rect.x = Math.max(0, ox + (ev.clientX - startX));
        rect.y = Math.max(40, oy + (ev.clientY - startY));
        panel.style.left = `${rect.x}px`;
        panel.style.top = `${rect.y}px`;
        highlightDockHot(ev.clientX, ev.clientY);
      };
      const onUp = (ev) => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        clearDockHot();
        const drop = dockSideAt(ev.clientX, ev.clientY);
        if (drop) dockPanel(id, drop);
        else {
          saveChromeLayout();
        }
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });

    resizeHandle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const startX = e.clientX;
      const startY = e.clientY;
      const rect = state.chrome.floating[id];
      const ow = rect.w;
      const oh = rect.h;
      const onMove = (ev) => {
        rect.w = Math.max(220, ow + (ev.clientX - startX));
        rect.h = Math.max(160, oh + (ev.clientY - startY));
        panel.style.width = `${rect.w}px`;
        panel.style.height = `${rect.h}px`;
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        saveChromeLayout();
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
  }

  function highlightDockHot(x, y) {
    clearDockHot();
    const side = dockSideAt(x, y);
    if (side === "left") ui.dockLeft.classList.add("lvb-dock-hot");
    if (side === "right") ui.dockRight.classList.add("lvb-dock-hot");
    if (side === "bottom") ui.dockBottom.classList.add("lvb-dock-hot");
  }

  function clearDockHot() {
    [ui.dockLeft, ui.dockRight, ui.dockBottom].forEach((d) => d.classList.remove("lvb-dock-hot"));
  }

  function dockSideAt(x, y) {
    const leftW = state.chrome.leftCollapsed ? 40 : state.chrome.leftW;
    const rightW = state.chrome.rightCollapsed ? 40 : state.chrome.rightW;
    if (x < leftW + 20) return "left";
    if (x > window.innerWidth - rightW - 20) return "right";
    if (y > window.innerHeight - 80) return "bottom";
    return null;
  }

  function panelBody(id) {
    const panel = ui.root.querySelector(`.lvb-panel[data-panel="${id}"]`);
    return panel ? $('[data-role="panel-body"]', panel) : null;
  }

  function renderAllPanels() {
    renderInspector();
    renderLayersPanel();
    renderInsertPanel();
    renderTokensPanel();
    renderAssetsPanel();
    renderCodePanel();
    renderHistoryPanel();
  }

  /* ------------------------------------------------------------------ */
  /* Panel content renderers                                            */
  /* ------------------------------------------------------------------ */

  function currentDecls() {
    const file = state.activeFile === "tokens.css" ? styleFileForSelector() : state.activeFile;
    return readOverrideDecls(state.files[file] || "", state.selectedSelector || "");
  }

  function computedHint(el, prop) {
    try {
      return getComputedStyle(el).getPropertyValue(prop) || "";
    } catch {
      return "";
    }
  }

  function toHexColor(value) {
    const v = String(value || "").trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) return v;
    if (/^#[0-9a-fA-F]{3}$/.test(v)) return `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`;
    const m = v.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
    if (m) {
      const h = (n) => Number(n).toString(16).padStart(2, "0");
      return `#${h(m[1])}${h(m[2])}${h(m[3])}`;
    }
    return "#ffffff";
  }

  function renderInspector() {
    const body = panelBody("inspector");
    if (!body) return;
    const el = state.selectedEl;
    if (!el) {
      body.innerHTML = `
        <p class="lvb-muted"><b>Full Freedom Builder</b></p>
        <p class="lvb-muted">Sleep · resize · reparent · multi-select (Shift) · rechtermuisklik · panelen docken.</p>
        <div class="lvb-section">Snel invoegen</div>
        <div class="lvb-chip-row">
          <button type="button" class="lvb-chip" data-insert="text">+ Tekst</button>
          <button type="button" class="lvb-chip" data-insert="heading">+ Titel</button>
          <button type="button" class="lvb-chip" data-act="add-image">+ Image</button>
          <button type="button" class="lvb-chip" data-insert="container">+ Frame</button>
          <button type="button" class="lvb-chip" data-insert="button">+ Knop</button>
          <button type="button" class="lvb-chip" data-insert="spacer">+ Spacer</button>
        </div>`;
      return;
    }

    const region = state.selectedRegion;
    const selector = state.selectedSelector;
    const decls = currentDecls();
    let html = `<h3 style="margin:0;font-size:13px;color:#f5dfa9;">${escapeHtml(selector)}</h3>`;

    if (el.tagName === "IMG" || resolveImageEl(el)) {
      const img = resolveImageEl(el) || el;
      if (img !== el) {
        selectTarget({ el: img, region: regionFor(img), selector: selectorFor(img), kind: "img" });
        return;
      }
      const src = img.getAttribute("src") || "";
      html += `
        <div class="lvb-section">Image</div>
        <div class="lvb-field"><label>Bron (URL)</label>
          <input type="text" data-role="img-src" value="${escapeHtml(src)}" /></div>
        <div class="lvb-field"><label>Upload / bibliotheek</label>
          <div class="lvb-chip-row">
            <button type="button" class="lvb-chip" data-act2="pick-image">Kies image…</button>
            <button type="button" class="lvb-chip" data-act2="upload-replace">Upload…</button>
          </div>
        </div>
        <div class="lvb-field"><label>Alt</label>
          <input type="text" data-role="img-alt" value="${escapeHtml(img.getAttribute("alt") || "")}" /></div>
        <div class="lvb-row">
          <div class="lvb-field"><label>Object-fit</label>
            <input type="text" data-role="decl" data-prop="object-fit" value="${escapeHtml(decls["object-fit"] || img.style.objectFit || "")}" placeholder="cover" /></div>
          <div class="lvb-field"><label>Focal point</label>
            <input type="text" data-role="decl" data-prop="object-position" value="${escapeHtml(decls["object-position"] || img.style.objectPosition || "")}" placeholder="50% 50%" /></div>
        </div>`;
    } else {
      const text = hasDirectText(el) || el.childElementCount === 0 ? el.textContent || "" : "";
      html += `
        <div class="lvb-section">Tekst</div>
        <div class="lvb-field"><label>Inhoud (of dubbelklik)</label>
          <textarea data-role="text" rows="3">${escapeHtml(text)}</textarea></div>
        <button type="button" class="lvb-btn" data-role="inline-edit" style="width:100%">Inline bewerken</button>`;
    }

    if (region?.varKey) {
      const cur = getVar(state.files["tokens.css"], region.varKey) || "80px";
      const px = Math.round(pxFromCssValue(cur, 80));
      html += `
        <div class="lvb-section">Shell maat</div>
        <div class="lvb-field"><label>${region.label} (${px}px)</label>
          <input type="range" min="${region.min}" max="${region.max}" value="${px}" data-role="region-var" /></div>`;
    }

    html += `
      <div class="lvb-section">Constraints</div>
      <div class="lvb-chip-row">
        <button type="button" class="lvb-chip${state.aspectLock ? " is-on" : ""}" data-act2="aspect">Aspect lock</button>
        <button type="button" class="lvb-chip${state.grid ? " is-on" : ""}" data-act2="grid">Grid ${GRID_SIZE}px</button>
      </div>`;

    html += `<div class="lvb-section">Styles</div>`;
    for (const group of STYLE_GROUPS) {
      html += `<div class="lvb-section lvb-section-sub">${group.title}</div><div class="lvb-row">`;
      for (const prop of group.props) {
        let val = decls[prop.key] || el.style.getPropertyValue(prop.key) || "";
        if (prop.key === "rotate") val = String(Math.round(parseRotateDeg(el)));
        const hint = prop.key === "rotate" ? "0" : computedHint(el, prop.key).trim();
        if (prop.type === "color") {
          html += `<div class="lvb-field"><label>${prop.label}</label>
            <div class="lvb-color-row">
              <input type="color" data-role="decl-color" data-prop="${prop.key}" value="${toHexColor(val || hint)}" />
              <input type="text" data-role="decl" data-prop="${prop.key}" value="${escapeHtml(val)}" placeholder="${escapeHtml(hint || prop.ph || "")}" />
            </div></div>`;
        } else {
          html += `<div class="lvb-field"><label>${prop.label}</label>
            <input type="text" data-role="decl" data-prop="${prop.key}" value="${escapeHtml(val)}" placeholder="${escapeHtml(hint || prop.ph || "")}" /></div>`;
        }
      }
      html += `</div>`;
    }

    html += `
      <div class="lvb-section">Acties</div>
      <div class="lvb-chip-row">
        <button type="button" class="lvb-chip" data-act2="copy">Kopieer</button>
        <button type="button" class="lvb-chip" data-act2="duplicate">Dupliceer</button>
        <button type="button" class="lvb-chip" data-act2="paste">Plak</button>
        <button type="button" class="lvb-chip" data-act2="delete">Verwijder</button>
        <button type="button" class="lvb-chip" data-act2="lock">${isLocked(el) ? "Unlock" : "Lock"}</button>
        <button type="button" class="lvb-chip" data-act2="group">Group</button>
        <button type="button" class="lvb-chip" data-act2="ungroup">Ungroup</button>
        <button type="button" class="lvb-chip" data-act2="front">Naar voren</button>
        <button type="button" class="lvb-chip" data-act2="back">Naar achter</button>
        <button type="button" class="lvb-chip" data-act2="align-left">⬅</button>
        <button type="button" class="lvb-chip" data-act2="align-center">⬌</button>
        <button type="button" class="lvb-chip" data-act2="align-right">➡</button>
        <button type="button" class="lvb-chip" data-act2="convert-widget">→ Widget</button>
        <button type="button" class="lvb-chip" data-act2="clear-styles">Reset styles</button>
      </div>`;

    body.innerHTML = html;
  }

  function renderLayersPanel() {
    const body = panelBody("layers");
    if (!body) return;
    const root = document.getElementById("root") || document.body;
    const items = [...root.querySelectorAll("[class*='lv-'], [data-lvb-id], img")].filter((el) => !isBuilderNode(el)).slice(0, 120);
    body.innerHTML = `
      <div class="lvb-chip-row" style="margin-bottom:6px">
        <button type="button" class="lvb-chip" data-act2="front">▲ Voor</button>
        <button type="button" class="lvb-chip" data-act2="back">▼ Achter</button>
      </div>
      <div data-role="layers-list" style="display:flex;flex-direction:column;gap:4px;">
        ${items
          .map((el, i) => {
            const sel = selectorFor(el);
            const active = state.selectedEls.includes(el) ? " is-on" : "";
            const lock = isLocked(el) || isShellLocked(el) ? " is-locked" : "";
            const depth = Math.min(4, (sel.match(/>/g) || []).length);
            const indent = `<span class="lvb-layer-indent" style="width:${depth * 10}px"></span>`;
            return `<button type="button" class="lvb-layer${active}${lock}" draggable="true" data-layer-sel="${escapeHtml(sel)}" data-layer-idx="${i}">${indent}${isLocked(el) ? "🔒 " : ""}${escapeHtml(labelFor(el))}</button>`;
          })
          .join("")}
      </div>`;
  }

  function renderInsertPanel() {
    const body = panelBody("insert");
    if (!body) return;
    const cards = [
      ["text", "T", "Tekst"],
      ["heading", "H", "Titel"],
      ["image", "▣", "Image"],
      ["button", "Btn", "Knop"],
      ["divider", "—", "Divider"],
      ["spacer", "↕", "Spacer"],
      ["container", "□", "Frame"],
      ["html", "</>", "HTML"],
    ];
    body.innerHTML = `
      <p class="lvb-muted">Sleep naar canvas of klik om in te voegen bij selectie.</p>
      <div class="lvb-insert-grid">
        ${cards
          .map(
            ([id, ico, label]) =>
              `<button type="button" class="lvb-insert-card" draggable="true" data-insert="${id}"><span class="lvb-insert-ico">${ico}</span>${label}</button>`,
          )
          .join("")}
      </div>`;
  }

  function renderTokensPanel() {
    const body = panelBody("tokens");
    if (!body) return;
    const css = state.files["tokens.css"] || "";
    let html = `<p class="lvb-muted">Live token-editor (tokens.css). Wijzigingen gaan naar Leviathan.</p>`;
    html += `<div class="lvb-section">Shell regio's</div>`;
    for (const region of REGIONS.filter((r) => r.varKey)) {
      const cur = getVar(css, region.varKey) || "80px";
      const px = Math.round(pxFromCssValue(cur, 80));
      html += `<div class="lvb-field"><label>${region.label} (${px}px)</label>
        <input type="range" min="${region.min}" max="${region.max}" value="${px}" data-role="token-region" data-region="${region.id}" /></div>`;
    }
    html += `<div class="lvb-section">Design tokens</div>`;
    for (const tok of TOKEN_KEYS) {
      const val = getVar(css, tok.key) || "";
      if (tok.type === "color") {
        html += `<div class="lvb-field"><label>${tok.label} <code style="opacity:.5">${tok.key}</code></label>
          <div class="lvb-color-row">
            <input type="color" data-role="token-color" data-key="${tok.key}" value="${toHexColor(val)}" />
            <input type="text" data-role="token-val" data-key="${tok.key}" value="${escapeHtml(val)}" />
          </div></div>`;
      } else {
        html += `<div class="lvb-field"><label>${tok.label} <code style="opacity:.5">${tok.key}</code></label>
          <input type="text" data-role="token-val" data-key="${tok.key}" value="${escapeHtml(val)}" /></div>`;
      }
    }
    body.innerHTML = html;
  }

  async function renderAssetsPanel() {
    const body = panelBody("assets");
    if (!body) return;
    body.innerHTML = `<p class="lvb-muted">Assets laden…</p>
      <div class="lvb-chip-row">
        <button type="button" class="lvb-chip" data-act="upload-image">Upload</button>
        <button type="button" class="lvb-chip" data-act="refresh-assets">Ververs</button>
      </div>
      <div data-role="assets-grid" class="lvb-media-grid" style="margin-top:8px"></div>`;
    try {
      const data = await apiListAssets();
      const grid = $('[data-role="assets-grid"]', body);
      const assets = data.assets || [];
      if (!grid) return;
      if (!assets.length) {
        grid.innerHTML = `<p class="lvb-muted">Nog geen images.</p>`;
        return;
      }
      grid.innerHTML = assets
        .map(
          (a) => `<button type="button" class="lvb-media-item" data-asset-url="${escapeHtml(a.url)}" title="${escapeHtml(a.name)}">
            <img src="${escapeHtml(a.url)}" alt="" loading="lazy" />
            <span>${escapeHtml(a.name)}</span>
          </button>`,
        )
        .join("");
    } catch (err) {
      body.insertAdjacentHTML("beforeend", `<p class="lvb-muted">${escapeHtml(String(err))}</p>`);
    }
  }

  function renderCodePanel() {
    const body = panelBody("code");
    if (!body) return;
    if (!body.dataset.ready) {
      body.innerHTML = `
        <div class="lvb-chip-row" data-role="files"></div>
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
          <strong data-role="code-file" style="color:#f5dfa9;font-size:11px;">leviathan.css</strong>
          <span class="lvb-muted">Live ↔ echte bestanden</span>
        </div>
        <textarea class="lvb-code-area" data-role="code-area" spellcheck="false" wrap="off"></textarea>`;
      body.dataset.ready = "1";
      ui.files = $('[data-role="files"]', body);
      ui.codeFile = $('[data-role="code-file"]', body);
      ui.codeArea = $('[data-role="code-area"]', body);
      ui.files.innerHTML = [...FILES, "__content__"]
        .map((f) => {
          const label = f === "__content__" ? "content.json" : f;
          return `<button type="button" class="lvb-chip${f === state.activeFile ? " is-on" : ""}" data-file="${f}">${label}</button>`;
        })
        .join("");
      ui.codeArea.addEventListener("input", onCodeInput);
      ui.files.addEventListener("click", (event) => {
        const chip = event.target.closest("[data-file]");
        if (!chip) return;
        state.activeFile = chip.dataset.file;
        syncCodePane();
      });
    }
    syncCodePane();
  }

  function onCodeInput() {
    if (state.activeFile === "__content__") {
      try {
        state.content = JSON.parse(ui.codeArea.value);
        ensureContentShape();
        markContentDirty();
        applyContentOverrides();
        mountNodes();
      } catch {
        setStatus("Ongeldige JSON", "dirty");
      }
      return;
    }
    const name = state.activeFile;
    state.files[name] = ui.codeArea.value;
    markDirty(name);
    applyTokensLive();
  }

  function renderHistoryPanel() {
    const body = panelBody("history");
    if (!body) return;
    body.innerHTML = state.history
      .map((h, i) => {
        const on = i === state.historyIndex ? " is-on" : "";
        const t = new Date(h.at || Date.now()).toLocaleTimeString();
        return `<button type="button" class="lvb-layer${on}" data-hist="${i}">${escapeHtml(h.label)} <span style="opacity:.5">${t}</span></button>`;
      })
      .reverse()
      .join("") || `<p class="lvb-muted">Nog geen history.</p>`;
  }


  /* ------------------------------------------------------------------ */
  /* Style / region / token updates                                     */
  /* ------------------------------------------------------------------ */

  function updateRegionVar(region, px) {
    pushHistory("region");
    const cur = getVar(state.files["tokens.css"], region.varKey) || `${px}px`;
    const next = cssFromPx(cur, Math.round(px), region);
    state.files["tokens.css"] = setVar(state.files["tokens.css"], region.varKey, next);
    state.activeFile = "tokens.css";
    markDirty("tokens.css");
    applyTokensLive();
    syncCodePane();
    refreshSelectionChrome();
    renderTokensPanel();
  }

  function updateToken(key, value) {
    pushHistory(`token:${key}`);
    state.files["tokens.css"] = setVar(state.files["tokens.css"], key, value);
    state.activeFile = "tokens.css";
    markDirty("tokens.css");
    applyTokensLive();
    syncCodePane();
  }

  function updateDecl(prop, value, { history = true, el = null, selector = null } = {}) {
    const target = el || state.selectedEl;
    const sel = selector || state.selectedSelector;
    if (!sel || !target) return;
    if (prop === "rotate") {
      if (history) pushHistory("rotate");
      setRotateDeg(target, Number(value) || 0);
      updateDecl("transform", target.style.transform, { history: false, el: target, selector: sel });
      return;
    }
    if (history) pushHistory(`style:${prop}`);
    const file = state.activeFile === "tokens.css" ? styleFileForSelector() : state.activeFile;
    const decls = readOverrideDecls(state.files[file], sel);
    if (!String(value).trim()) {
      delete decls[prop];
      target.style.removeProperty(prop);
    } else {
      decls[prop] = String(value).trim();
      target.style.setProperty(prop, String(value).trim());
    }
    state.files[file] = upsertOverride(state.files[file], sel, declsToText(decls));
    state.activeFile = file;
    const entry = getEntry(sel) || {};
    const styles = { ...(entry.styles || {}) };
    if (!String(value).trim()) delete styles[prop];
    else styles[prop] = String(value).trim();
    upsertContentEntry(sel, { styles });
    markDirty(file);
    applyTokensLive();
    syncCodePane();
    refreshSelectionChrome();
  }

  function bakePosition(el, selector) {
    const cs = getComputedStyle(el);
    if (cs.position === "static") el.style.position = "relative";
    const left = el.style.left || "0px";
    const top = el.style.top || "0px";
    updateDecl("position", el.style.position || "relative", { history: false, el, selector });
    updateDecl("left", left, { history: false, el, selector });
    updateDecl("top", top, { history: false, el, selector });
    if (el.style.width) updateDecl("width", el.style.width, { history: false, el, selector });
    if (el.style.height) updateDecl("height", el.style.height, { history: false, el, selector });
    if (el.style.transform) updateDecl("transform", el.style.transform, { history: false, el, selector });
    upsertContentEntry(selector, {
      position: el.style.position || "relative",
      left,
      top,
      width: el.style.width || undefined,
      height: el.style.height || undefined,
    });
  }

  function clampSize(el, w, h) {
    const cs = getComputedStyle(el);
    const minW = parseFloat(cs.minWidth) || 16;
    const minH = parseFloat(cs.minHeight) || 16;
    const maxW = parseFloat(cs.maxWidth);
    const maxH = parseFloat(cs.maxHeight);
    let nw = Math.max(minW, w);
    let nh = Math.max(minH, h);
    if (!Number.isNaN(maxW) && maxW > 0) nw = Math.min(nw, maxW);
    if (!Number.isNaN(maxH) && maxH > 0) nh = Math.min(nh, maxH);
    if (state.aspectLock) {
      const ratio = (parseFloat(el.dataset.lvbAspect) || w / Math.max(1, h));
      el.dataset.lvbAspect = String(ratio);
      nh = Math.round(nw / ratio);
    }
    if (state.grid) {
      nw = Math.round(nw / GRID_SIZE) * GRID_SIZE;
      nh = Math.round(nh / GRID_SIZE) * GRID_SIZE;
    }
    return { w: nw, h: nh };
  }

  /* ------------------------------------------------------------------ */
  /* Text / image commit                                                */
  /* ------------------------------------------------------------------ */

  async function commitText(el, selector, newText) {
    pushHistory("text");
    const entry = getEntry(selector) || {};
    const baseline = entry.text != null ? entry.text : el.dataset.lvbOriginalText || el.textContent || "";
    if (!el.dataset.lvbOriginalText) el.dataset.lvbOriginalText = baseline;
    el.textContent = newText;
    upsertContentEntry(selector, { text: newText, prevText: baseline });
    applyContentOverrides();
    try {
      if (baseline && baseline !== newText && baseline.length >= 2 && !el.dataset.lvbId) {
        const result = await apiReplaceText(baseline, newText);
        setStatus(result.changed?.length ? `Tekst in ${result.changed.length} bron(nen)` : "Tekst opgeslagen", "ok");
      } else setStatus("Tekst opgeslagen", "ok");
    } catch (err) {
      setStatus(String(err), "dirty");
    }
    syncCodePane();
  }

  async function commitImageSrc(el, selector, newSrc, oldSrc) {
    pushHistory("image");
    el.setAttribute("src", newSrc);
    upsertContentEntry(selector, { src: newSrc });
    if (newSrc !== oldSrc) upsertContentEntry(`img[src="${newSrc}"]`, { src: newSrc });
    try {
      if (oldSrc && oldSrc !== newSrc && !el.dataset.lvbId) {
        const result = await apiReplaceText(oldSrc, newSrc);
        setStatus(result.changed?.length ? `Image in ${result.changed.length} bron(nen)` : "Image opgeslagen", "ok");
      }
    } catch (err) {
      setStatus(String(err), "dirty");
    }
    state.selectedSelector = el.dataset.lvbId ? selectorFor(el) : `img[src="${newSrc}"]`;
    syncCodePane();
    refreshSelectionChrome();
    renderInspector();
  }

  function startInlineEdit(el) {
    if (!el || el.tagName === "IMG" || isLocked(el)) return;
    endInlineEdit(true);
    state.inlineEditing = true;
    ui.select.hidden = true;
    ui.hover.hidden = true;
    el.contentEditable = "true";
    el.classList.add("lvb-inline-editing");
    el.focus();
    const onBlur = () => {
      el.removeEventListener("blur", onBlur);
      endInlineEdit(false);
    };
    el.addEventListener("blur", onBlur);
  }

  function endInlineEdit(cancel) {
    const el = state.selectedEl;
    if (!state.inlineEditing || !el) {
      state.inlineEditing = false;
      return;
    }
    el.contentEditable = "false";
    el.classList.remove("lvb-inline-editing");
    state.inlineEditing = false;
    if (!cancel) {
      commitText(el, state.selectedSelector || selectorFor(el), el.textContent || "").then(() => {
        renderInspector();
        refreshSelectionChrome();
      });
    } else refreshSelectionChrome();
  }

  /* ------------------------------------------------------------------ */
  /* Move / resize / rotate / reparent / snap                           */
  /* ------------------------------------------------------------------ */

  function snapValue(v, guides) {
    if (!state.snap) return v;
    const threshold = 6;
    for (const g of guides) {
      if (Math.abs(v - g) <= threshold) return g;
    }
    if (state.grid) return Math.round(v / GRID_SIZE) * GRID_SIZE;
    return v;
  }

  function collectSnapGuides(el) {
    const parent = el.parentElement || document.body;
    const pr = parent.getBoundingClientRect();
    const guidesX = [pr.left, pr.left + pr.width / 2, pr.right];
    const guidesY = [pr.top, pr.top + pr.height / 2, pr.bottom];
    [...parent.children].forEach((sib) => {
      if (sib === el || state.selectedEls.includes(sib)) return;
      const r = sib.getBoundingClientRect();
      guidesX.push(r.left, r.left + r.width / 2, r.right);
      guidesY.push(r.top, r.top + r.height / 2, r.bottom);
    });
    return { guidesX, guidesY, parentRect: pr };
  }

  function showSnapLines(x, y) {
    ui.snapX.style.display = x == null ? "none" : "block";
    ui.snapY.style.display = y == null ? "none" : "block";
    if (x != null) ui.snapX.style.left = `${x}px`;
    if (y != null) ui.snapY.style.top = `${y}px`;
  }

  function hideSnapLines() {
    ui.snapX.style.display = "none";
    ui.snapY.style.display = "none";
  }

  function clearDropHint() {
    if (state.dropTarget) {
      state.dropTarget.classList.remove("lvb-drop-hint");
      state.dropTarget = null;
    }
  }

  function findDropContainer(clientX, clientY, movingEls) {
    const prev = ui.select?.style.pointerEvents;
    if (ui.select) ui.select.style.pointerEvents = "none";
    $$(".lvb-multi, .lvb-hover", ui.root).forEach((n) => (n.style.pointerEvents = "none"));
    let hit = null;
    try {
      const stack = document.elementsFromPoint(clientX, clientY);
      for (const node of stack) {
        if (!(node instanceof Element) || isBuilderNode(node)) continue;
        if (movingEls.includes(node) || movingEls.some((m) => m.contains(node))) continue;
        if (node.matches(".lv-main, .lv-sidebar, .lv-header, .lv-footer, .lv-right, .lvb-frame, [data-lvb-id]")) {
          if (node.tagName === "IMG") continue;
          hit = node;
          break;
        }
        const display = getComputedStyle(node).display || "";
        if (
          node.children &&
          (display.includes("flex") || display.includes("grid") || getComputedStyle(node).position !== "static")
        ) {
          if (["DIV", "SECTION", "ARTICLE", "MAIN", "ASIDE", "HEADER", "FOOTER"].includes(node.tagName)) {
            hit = node;
            break;
          }
        }
      }
    } finally {
      if (ui.select) ui.select.style.pointerEvents = prev || "";
    }
    return hit;
  }

  function reparentElement(el, newParent, clientX, clientY) {
    if (!newParent || newParent === el || el.contains(newParent)) return false;
    if (newParent === el.parentElement) return false;
    const pr = newParent.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    const left = Math.round(er.left - pr.left + (newParent.scrollLeft || 0));
    const top = Math.round(er.top - pr.top + (newParent.scrollTop || 0));
    const cs = getComputedStyle(newParent);
    if (cs.position === "static") {
      // keep absolute relative to parent by ensuring positioned parent or use relative on child
    }
    newParent.appendChild(el);
    if (getComputedStyle(el).position === "static") el.style.position = "absolute";
    else if (el.style.position === "relative" || !el.style.position) el.style.position = "absolute";
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    if (el.dataset.lvbId) {
      const node = state.content.nodes.find((n) => n.id === el.dataset.lvbId);
      if (node) node.parent = selectorFor(newParent);
    }
    bakePosition(el, selectorFor(el));
    markContentDirty();
    return true;
  }

  function startMove(event) {
    const els = state.selectedEls.length ? [...state.selectedEls] : state.selectedEl ? [state.selectedEl] : [];
    const movable = els.filter((el) => canMutate(el));
    if (!movable.length) return;
    event.preventDefault();
    event.stopPropagation();
    pushHistory("move");
    state.mode = "move";

    const startX = event.clientX;
    const startY = event.clientY;
    const bases = movable.map((el) => {
      const cs = getComputedStyle(el);
      if (cs.position === "static") el.style.position = "relative";
      return {
        el,
        left: parseFloat(el.style.left) || 0,
        top: parseFloat(el.style.top) || 0,
        guides: collectSnapGuides(el),
      };
    });

    const onMove = (ev) => {
      let guideX = null;
      let guideY = null;
      for (const b of bases) {
        let nextLeft = b.left + (ev.clientX - startX);
        let nextTop = b.top + (ev.clientY - startY);
        if (state.grid) {
          nextLeft = Math.round(nextLeft / GRID_SIZE) * GRID_SIZE;
          nextTop = Math.round(nextTop / GRID_SIZE) * GRID_SIZE;
        }
        const rect = b.el.getBoundingClientRect();
        const absLeft = rect.left - (parseFloat(b.el.style.left) || 0) + nextLeft;
        const absTop = rect.top - (parseFloat(b.el.style.top) || 0) + nextTop;
        const snappedL = snapValue(absLeft, b.guides.guidesX);
        const snappedT = snapValue(absTop, b.guides.guidesY);
        nextLeft += snappedL - absLeft;
        nextTop += snappedT - absTop;
        if (Math.abs(snappedL - absLeft) < 0.1) guideX = snappedL;
        if (Math.abs(snappedT - absTop) < 0.1) guideY = snappedT;
        b.el.style.left = `${Math.round(nextLeft)}px`;
        b.el.style.top = `${Math.round(nextTop)}px`;
      }
      showSnapLines(guideX, guideY);

      const drop = findDropContainer(ev.clientX, ev.clientY, movable);
      clearDropHint();
      if (drop && !movable.includes(drop)) {
        state.dropTarget = drop;
        drop.classList.add("lvb-drop-hint");
      }
      refreshSelectionChrome();
    };

    const onUp = (ev) => {
      state.mode = null;
      hideSnapLines();
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      const drop = state.dropTarget;
      clearDropHint();
      if (drop) {
        for (const el of movable) reparentElement(el, drop, ev.clientX, ev.clientY);
        setStatus("Herparented", "ok");
      } else {
        for (const el of movable) bakePosition(el, selectorFor(el));
        setStatus("Verplaatst", "ok");
      }
      setPrimaryFromList();
      renderInspector();
      renderLayersPanel();
      refreshSelectionChrome();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function startResize(event, dir) {
    const el = state.selectedEl;
    if (!el || isLocked(el)) return;
    event.preventDefault();
    event.stopPropagation();
    pushHistory("resize");
    state.mode = "resize";

    const region = state.selectedRegion;
    const startX = event.clientX;
    const startY = event.clientY;
    const startRect = el.getBoundingClientRect();
    if (!el.dataset.lvbAspect) el.dataset.lvbAspect = String(startRect.width / Math.max(1, startRect.height));

    const onMove = (ev) => {
      if (region?.varKey) {
        let px;
        if (region.edge === "e") px = startRect.width + (ev.clientX - startX);
        else if (region.edge === "w") px = startRect.width - (ev.clientX - startX);
        else if (region.edge === "s") px = startRect.height + (ev.clientY - startY);
        else if (region.edge === "n") px = startRect.height - (ev.clientY - startY);
        else return;
        px = Math.min(region.max, Math.max(region.min, px));
        updateRegionVar(region, px);
        return;
      }
      if (isShellLocked(el)) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      let w = startRect.width;
      let h = startRect.height;
      let left = parseFloat(el.style.left) || 0;
      let top = parseFloat(el.style.top) || 0;
      if (dir.includes("e")) w = startRect.width + dx;
      if (dir.includes("w")) {
        w = startRect.width - dx;
        left = (parseFloat(el.style.left) || 0) + dx;
      }
      if (dir.includes("s")) h = startRect.height + dy;
      if (dir.includes("n")) {
        h = startRect.height - dy;
        top = (parseFloat(el.style.top) || 0) + dy;
      }
      const clamped = clampSize(el, w, h);
      w = clamped.w;
      h = clamped.h;
      if (getComputedStyle(el).position === "static") el.style.position = "relative";
      if (dir.includes("w") || dir.includes("n")) {
        el.style.left = `${Math.round(left)}px`;
        el.style.top = `${Math.round(top)}px`;
      }
      el.style.width = `${Math.round(w)}px`;
      el.style.height = `${Math.round(h)}px`;
      refreshSelectionChrome();
    };

    const onUp = () => {
      state.mode = null;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (!region?.varKey && !isShellLocked(el)) {
        updateDecl("width", el.style.width, { history: false });
        updateDecl("height", el.style.height, { history: false });
        if (el.style.left) updateDecl("left", el.style.left, { history: false });
        if (el.style.top) updateDecl("top", el.style.top, { history: false });
        if (el.style.position) updateDecl("position", el.style.position || "relative", { history: false });
      }
      renderInspector();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function startRotate(event) {
    const el = state.selectedEl;
    if (!canMutate(el)) return;
    event.preventDefault();
    event.stopPropagation();
    pushHistory("rotate");
    state.mode = "rotate";
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const startDeg = parseRotateDeg(el);
    const startAng = (Math.atan2(event.clientY - cy, event.clientX - cx) * 180) / Math.PI;

    const onMove = (ev) => {
      const ang = (Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180) / Math.PI;
      let deg = startDeg + (ang - startAng);
      if (ev.shiftKey) deg = Math.round(deg / 15) * 15;
      setRotateDeg(el, deg);
      refreshSelectionChrome();
    };
    const onUp = () => {
      state.mode = null;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      updateDecl("transform", el.style.transform, { history: false });
      renderInspector();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function nudge(dx, dy) {
    const els = state.selectedEls.filter((el) => canMutate(el));
    if (!els.length) return;
    pushHistory("nudge");
    for (const el of els) {
      if (getComputedStyle(el).position === "static") el.style.position = "relative";
      const left = (parseFloat(el.style.left) || 0) + dx;
      const top = (parseFloat(el.style.top) || 0) + dy;
      el.style.left = `${left}px`;
      el.style.top = `${top}px`;
      bakePosition(el, selectorFor(el));
    }
    refreshSelectionChrome();
  }

  /* ------------------------------------------------------------------ */
  /* Clipboard / CRUD / group                                           */
  /* ------------------------------------------------------------------ */

  function serializeSelection() {
    const el = state.selectedEl;
    if (!el) return null;
    const clone = el.cloneNode(true);
    return {
      html: clone.outerHTML,
      selector: state.selectedSelector,
      tag: el.tagName,
      styles: {
        position: el.style.position,
        left: el.style.left,
        top: el.style.top,
        width: el.style.width,
        height: el.style.height,
        zIndex: el.style.zIndex,
        transform: el.style.transform,
      },
      text: el.tagName !== "IMG" ? el.textContent : null,
      src: el.tagName === "IMG" ? el.getAttribute("src") : null,
    };
  }

  function copySelection() {
    state.clipboard = serializeSelection();
    if (!state.clipboard) return setStatus("Niets geselecteerd", "dirty");
    try {
      navigator.clipboard?.writeText(state.clipboard.html);
    } catch {
      /* ignore */
    }
    setStatus("Gekopieerd", "ok");
  }

  function insertWidget({ html, label, parentSel, styles }) {
    pushHistory(`insert:${label}`);
    ensureContentShape();
    const id = uid();
    const wrap = document.createElement("div");
    wrap.innerHTML = html.trim();
    const el = wrap.firstElementChild;
    if (!el) return null;
    el.dataset.lvbId = id;
    el.dataset.lvbLabel = label || "widget";
    Object.assign(el.style, {
      position: "relative",
      left: "0px",
      top: "0px",
      ...(styles || {}),
    });
    let mount =
      document.querySelector(parentSel) ||
      document.querySelector(".lv-main") ||
      document.getElementById("root") ||
      document.body;
    if (state.selectedEl && !parentSel) {
      mount = isShellLocked(state.selectedEl)
        ? state.selectedEl
        : state.selectedEl.classList.contains("lvb-frame")
          ? state.selectedEl
          : state.selectedEl.parentElement || state.selectedEl;
    }
    if (parentSel) mount = document.querySelector(parentSel) || mount;
    mount.appendChild(el);
    state.content.nodes.push({
      id,
      label: label || "widget",
      parent: selectorFor(mount),
      html: el.outerHTML,
      styles: {
        position: el.style.position,
        left: el.style.left,
        top: el.style.top,
        width: el.style.width,
        height: el.style.height,
      },
    });
    markContentDirty();
    selectTarget({ el, region: null, selector: selectorFor(el), kind: "widget" });
    setStatus(`${label || "Element"} toegevoegd`, "ok");
    return el;
  }

  function pasteClipboard() {
    if (!state.clipboard) return setStatus("Klembord leeg", "dirty");
    const data = state.clipboard;
    const el = insertWidget({
      html: data.html,
      label: "paste",
      styles: {
        ...data.styles,
        left: `${(parseFloat(data.styles?.left) || 0) + 16}px`,
        top: `${(parseFloat(data.styles?.top) || 0) + 16}px`,
        position: data.styles?.position || "relative",
      },
    });
    if (el && data.src && el.tagName === "IMG") el.setAttribute("src", data.src);
    if (el && data.text && el.tagName !== "IMG" && (el.childElementCount === 0 || hasDirectText(el))) {
      el.textContent = data.text;
    }
  }

  function duplicateSelection() {
    copySelection();
    pasteClipboard();
  }

  function deleteSelection() {
    const els = [...state.selectedEls];
    if (!els.length) return;
    pushHistory("delete");
    for (const el of els) {
      if (isShellLocked(el)) {
        setStatus("Shell-elementen kun je niet verwijderen", "dirty");
        continue;
      }
      if (isLocked(el)) {
        setStatus("Element is gelocked", "dirty");
        continue;
      }
      const selector = selectorFor(el);
      if (el.dataset.lvbId) {
        state.content.nodes = state.content.nodes.filter((n) => n.id !== el.dataset.lvbId);
        el.remove();
      } else {
        el.style.display = "none";
        upsertContentEntry(selector, { hide: true });
        const file = styleFileForSelector();
        const decls = readOverrideDecls(state.files[file], selector);
        decls.display = "none";
        state.files[file] = upsertOverride(state.files[file], selector, declsToText(decls));
        markDirty(file);
      }
    }
    markContentDirty();
    clearSelection();
    setStatus("Verwijderd / verborgen", "ok");
  }

  function toggleLock() {
    const el = state.selectedEl;
    if (!el) return;
    pushHistory("lock");
    const next = !isLocked(el);
    el.dataset.lvbLocked = next ? "1" : "0";
    upsertContentEntry(state.selectedSelector || selectorFor(el), { locked: next });
    renderInspector();
    refreshSelectionChrome();
    setStatus(next ? "Gelocked" : "Unlocked", "ok");
  }

  function bringForward() {
    for (const el of state.selectedEls) {
      pushHistory("z");
      const z = (parseInt(el.style.zIndex || getComputedStyle(el).zIndex, 10) || 1) + 1;
      el.style.zIndex = String(z);
      updateDecl("z-index", String(z), { history: false, el, selector: selectorFor(el) });
      if (el.nextElementSibling) el.parentElement?.insertBefore(el.nextElementSibling, el);
    }
    renderLayersPanel();
  }

  function sendBack() {
    for (const el of state.selectedEls) {
      pushHistory("z");
      const z = (parseInt(el.style.zIndex || getComputedStyle(el).zIndex, 10) || 1) - 1;
      el.style.zIndex = String(z);
      updateDecl("z-index", String(z), { history: false, el, selector: selectorFor(el) });
      if (el.previousElementSibling) el.parentElement?.insertBefore(el, el.previousElementSibling);
    }
    renderLayersPanel();
  }

  function alignInParent(mode) {
    const el = state.selectedEl;
    if (!el || isShellLocked(el)) return;
    pushHistory(`align-${mode}`);
    const parent = el.parentElement;
    if (!parent) return;
    if (getComputedStyle(el).position === "static") el.style.position = "relative";
    const pr = parent.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    const curLeft = parseFloat(el.style.left) || 0;
    let next = curLeft;
    if (mode === "left") next = curLeft + (pr.left - er.left);
    if (mode === "center") next = curLeft + (pr.left + pr.width / 2 - (er.left + er.width / 2));
    if (mode === "right") next = curLeft + (pr.right - er.right);
    el.style.left = `${Math.round(next)}px`;
    bakePosition(el, state.selectedSelector || selectorFor(el));
    refreshSelectionChrome();
  }

  function groupSelection() {
    const els = state.selectedEls.filter((el) => canMutate(el));
    if (els.length < 2) return setStatus("Selecteer 2+ elementen om te groeperen", "dirty");
    pushHistory("group");
    const parent = els[0].parentElement || document.querySelector(".lv-main");
    const rects = els.map((el) => el.getBoundingClientRect());
    const left = Math.min(...rects.map((r) => r.left));
    const top = Math.min(...rects.map((r) => r.top));
    const right = Math.max(...rects.map((r) => r.right));
    const bottom = Math.max(...rects.map((r) => r.bottom));
    const pr = parent.getBoundingClientRect();
    const frame = insertWidget({
      label: "group",
      parentSel: selectorFor(parent),
      html: `<div class="lvb-widget lvb-frame lvb-group" style="position:absolute;left:${Math.round(left - pr.left)}px;top:${Math.round(top - pr.top)}px;width:${Math.round(right - left)}px;height:${Math.round(bottom - top)}px;padding:0;border:1px dashed rgba(214,169,87,0.5);background:transparent;"></div>`,
      styles: { position: "absolute" },
    });
    if (!frame) return;
    for (const el of els) {
      const er = el.getBoundingClientRect();
      frame.appendChild(el);
      el.style.position = "absolute";
      el.style.left = `${Math.round(er.left - left)}px`;
      el.style.top = `${Math.round(er.top - top)}px`;
      bakePosition(el, selectorFor(el));
    }
    syncNodesFromDom();
    markContentDirty();
    selectTarget({ el: frame, region: null, selector: selectorFor(frame), kind: "widget" });
    setStatus("Gegroepeerd", "ok");
  }

  function ungroupSelection() {
    const el = state.selectedEl;
    if (!el || !el.classList.contains("lvb-group") && !el.classList.contains("lvb-frame")) {
      return setStatus("Selecteer een groep/frame", "dirty");
    }
    if (isShellLocked(el)) return;
    pushHistory("ungroup");
    const parent = el.parentElement;
    const kids = [...el.children];
    const fr = el.getBoundingClientRect();
    const pr = parent.getBoundingClientRect();
    for (const kid of kids) {
      const kr = kid.getBoundingClientRect();
      parent.appendChild(kid);
      kid.style.position = "absolute";
      kid.style.left = `${Math.round(kr.left - pr.left)}px`;
      kid.style.top = `${Math.round(kr.top - pr.top)}px`;
      bakePosition(kid, selectorFor(kid));
    }
    if (el.dataset.lvbId) {
      state.content.nodes = state.content.nodes.filter((n) => n.id !== el.dataset.lvbId);
      el.remove();
    }
    markContentDirty();
    clearSelection();
    setStatus("Ungrouped", "ok");
  }

  function convertToWidget() {
    const el = state.selectedEl;
    if (!el || el.dataset.lvbId || isShellLocked(el)) return setStatus("Al widget of shell", "dirty");
    pushHistory("convert");
    const id = uid();
    el.dataset.lvbId = id;
    el.dataset.lvbLabel = labelFor(el);
    el.classList.add("lvb-widget");
    ensureContentShape();
    state.content.nodes.push({
      id,
      label: el.dataset.lvbLabel,
      parent: selectorFor(el.parentElement),
      html: el.outerHTML,
      styles: {
        position: el.style.position,
        left: el.style.left,
        top: el.style.top,
        width: el.style.width,
        height: el.style.height,
      },
    });
    markContentDirty();
    selectTarget({ el, region: null, selector: selectorFor(el), kind: "widget" });
    setStatus("Geconverteerd naar widget", "ok");
  }

  function insertPreset(type) {
    if (type === "image") {
      openImageLibrary({ mode: "insert" });
      return;
    }
    if (type === "html") {
      const custom = window.prompt("Custom HTML:", '<div class="lvb-widget" style="padding:8px;color:#E8E4DC;">Custom</div>');
      if (!custom) return;
      insertWidget({ label: "html", html: custom });
      return;
    }
    const preset = INSERT_PRESETS[type];
    if (!preset?.html) return;
    insertWidget(preset);
  }

  function insertImageAtUrl(url, alt = "Image") {
    const safeAlt = escapeHtml(alt || "Image");
    const el = insertWidget({
      label: "image",
      html: `<img class="lvb-widget lvb-image" src="${url}" alt="${safeAlt}" style="display:block;width:240px;max-width:100%;height:auto;border-radius:8px;object-fit:cover;" />`,
      styles: { position: "relative", left: "12px", top: "12px", width: "240px" },
    });
    if (el) {
      syncNodesFromDom();
      markContentDirty();
      setStatus("Image toegevoegd — sleep om te plaatsen", "ok");
    }
    return el;
  }

  async function uploadAndInsertImage(file) {
    setStatus("Image uploaden…");
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const uploaded = await apiUpload(file.name, dataUrl);
    await applyPickedImageUrl(uploaded.url, file.name);
  }

  async function openImageLibrary({ mode = "insert" } = {}) {
    state.imagePickerMode = mode;
    if (!ui.media) return;
    ui.media.hidden = false;
    ui.mediaTitle.textContent = mode === "replace" || mode === "replace-bg" ? "Image vervangen" : "Image toevoegen";
    ui.mediaGrid.innerHTML = `<p class="lvb-muted">Assets laden…</p>`;
    try {
      const data = await apiListAssets();
      const assets = data.assets || [];
      if (!assets.length) {
        ui.mediaGrid.innerHTML = `<p class="lvb-muted">Nog geen images. Upload er een via de knop hierboven.</p>`;
        return;
      }
      ui.mediaGrid.innerHTML = assets
        .map(
          (a) => `<button type="button" class="lvb-media-item" data-asset-url="${escapeHtml(a.url)}" title="${escapeHtml(a.name)}">
            <img src="${escapeHtml(a.url)}" alt="" loading="lazy" />
            <span>${escapeHtml(a.name)}</span>
          </button>`,
        )
        .join("");
    } catch (err) {
      ui.mediaGrid.innerHTML = `<p class="lvb-muted">${escapeHtml(String(err))}</p>`;
    }
  }

  async function applyPickedImageUrl(url, name = "Image") {
    if (state.imagePickerMode === "replace-bg" && state.selectedEl) {
      pushHistory("bg-image");
      updateDecl("background-image", `url("${url}")`);
      updateDecl("background-size", "cover");
      updateDecl("background-position", "center");
      setStatus("Achtergrond-image vervangen", "ok");
      hideImageLibrary();
      return;
    }
    if (state.imagePickerMode === "replace") {
      const img = resolveImageEl(state.selectedEl);
      if (img) {
        if (state.selectedEl !== img) {
          selectTarget({ el: img, region: regionFor(img), selector: selectorFor(img), kind: "img" });
        }
        const oldSrc = img.getAttribute("src") || "";
        await commitImageSrc(img, state.selectedSelector || selectorFor(img), url, oldSrc);
        hideImageLibrary();
        return;
      }
    }
    insertImageAtUrl(url, name);
    hideImageLibrary();
  }

  function hideImageLibrary() {
    if (ui.media) ui.media.hidden = true;
  }

  /* ------------------------------------------------------------------ */
  /* Context menu                                                       */
  /* ------------------------------------------------------------------ */

  function hideContextMenu() {
    if (ui.menu) ui.menu.hidden = true;
  }

  function showContextMenu(x, y, picked) {
    if (picked) selectTarget(picked);
    const el = state.selectedEl;
    const imgEl = resolveImageEl(el);
    if (imgEl && el && imgEl !== el) {
      selectTarget({ el: imgEl, region: regionFor(imgEl), selector: selectorFor(imgEl), kind: "img" });
    }
    const active = state.selectedEl;
    const canReplaceImg = Boolean(resolveImageEl(active));
    const canReplaceBg = Boolean(active && !canReplaceImg && hasReplaceableBackground(active));
    const items = [
      { label: "Kopiëren", k: "⌘C", act: "copy" },
      { label: "Plakken", k: "⌘V", act: "paste" },
      { label: "Dupliceren", k: "⌘D", act: "duplicate" },
      { sep: true },
      { label: "Verwijderen", k: "Del", act: "delete" },
      { label: isLocked(active) ? "Unlock" : "Lock", act: "lock" },
      { label: "Group", act: "group" },
      { label: "Ungroup", act: "ungroup" },
      { sep: true },
      { label: "Tekst bewerken", act: "edit-text", disabled: !active || active.tagName === "IMG" },
      { label: "Image vervangen…", act: "replace-image", disabled: !canReplaceImg && !canReplaceBg },
      { label: "Image toevoegen…", act: "insert-image" },
      { label: "Convert to widget", act: "convert-widget", disabled: !active || !!active.dataset?.lvbId || isShellLocked(active) },
      { sep: true },
      { label: "Naar voren", act: "front" },
      { label: "Naar achter", act: "back" },
      { label: "Links uitlijnen", act: "align-left" },
      { label: "Centreren", act: "align-center" },
      { label: "Rechts uitlijnen", act: "align-right" },
      { sep: true },
      { label: "Invoegen → Tekst", act: "insert-text" },
      { label: "Invoegen → Frame", act: "insert-box" },
      { label: "Invoegen → Knop", act: "insert-button" },
      { label: "Invoegen → Spacer", act: "insert-spacer" },
    ];
    ui.menu.innerHTML = items
      .map((it) => {
        if (it.sep) return `<div class="lvb-menu-sep"></div>`;
        return `<button type="button" class="lvb-menu-item${it.disabled ? " is-disabled" : ""}" data-menu="${it.act}" ${it.disabled ? "disabled" : ""}>
          <span>${it.label}</span>${it.k ? `<kbd>${it.k}</kbd>` : ""}
        </button>`;
      })
      .join("");
    ui.menu.hidden = false;
    const mw = ui.menu.offsetWidth;
    const mh = ui.menu.offsetHeight;
    ui.menu.style.left = `${Math.min(x, window.innerWidth - mw - 8)}px`;
    ui.menu.style.top = `${Math.min(y, window.innerHeight - mh - 8)}px`;
  }

  function runMenuAction(act) {
    hideContextMenu();
    switch (act) {
      case "copy":
        return copySelection();
      case "paste":
        return pasteClipboard();
      case "duplicate":
        return duplicateSelection();
      case "delete":
        return deleteSelection();
      case "lock":
        return toggleLock();
      case "group":
        return groupSelection();
      case "ungroup":
        return ungroupSelection();
      case "convert-widget":
        return convertToWidget();
      case "edit-text":
        return state.selectedEl && startInlineEdit(state.selectedEl);
      case "replace-image": {
        const img = resolveImageEl(state.selectedEl);
        if (img) {
          selectTarget({ el: img, region: regionFor(img), selector: selectorFor(img), kind: "img" });
          return openImageLibrary({ mode: "replace" });
        }
        if (state.selectedEl && hasReplaceableBackground(state.selectedEl)) {
          return openImageLibrary({ mode: "replace-bg" });
        }
        return setStatus("Geen image geselecteerd", "dirty");
      }
      case "front":
        return bringForward();
      case "back":
        return sendBack();
      case "align-left":
        return alignInParent("left");
      case "align-center":
        return alignInParent("center");
      case "align-right":
        return alignInParent("right");
      case "insert-text":
        return insertPreset("text");
      case "insert-image":
        return openImageLibrary({ mode: "insert" });
      case "insert-box":
        return insertPreset("container");
      case "insert-button":
        return insertPreset("button");
      case "insert-spacer":
        return insertPreset("spacer");
      default:
        break;
    }
  }


  /* ------------------------------------------------------------------ */
  /* UI build                                                           */
  /* ------------------------------------------------------------------ */

  function buildUI() {
    loadChromeLayout();
    const root = document.createElement("div");
    root.id = "lvb-root";
    root.innerHTML = `
      <div class="lvb-chrome">
        <div class="lvb-topbar">
          <div class="lvb-brand">Leviathan Builder</div>
          <div class="lvb-sep"></div>
          <button type="button" class="lvb-btn" data-nav="/">Command</button>
          <button type="button" class="lvb-btn" data-nav="/chat">Chat</button>
          <button type="button" class="lvb-btn" data-nav="/research">Research</button>
          <button type="button" class="lvb-btn" data-nav="/settings">Settings</button>
          <div class="lvb-sep"></div>
          <button type="button" class="lvb-btn" data-insert="text" title="Tekst">+T</button>
          <button type="button" class="lvb-btn" data-act="add-image" title="Image">+Img</button>
          <button type="button" class="lvb-btn" data-insert="container" title="Frame">+Frame</button>
          <button type="button" class="lvb-btn" data-insert="button" title="Knop">+Btn</button>
          <div class="lvb-sep"></div>
          <button type="button" class="lvb-btn is-on" data-act="toggle-edit">Edit aan</button>
          <button type="button" class="lvb-btn is-on" data-act="toggle-left">Links</button>
          <button type="button" class="lvb-btn is-on" data-act="toggle-right">Rechts</button>
          <button type="button" class="lvb-btn" data-act="toggle-bottom">Code</button>
          <button type="button" class="lvb-btn is-on" data-act="toggle-snap">Snap</button>
          <button type="button" class="lvb-btn" data-act="toggle-grid">Grid</button>
          <button type="button" class="lvb-btn" data-act="undo" title="Ctrl+Z">Undo</button>
          <button type="button" class="lvb-btn" data-act="redo" title="Ctrl+Shift+Z">Redo</button>
          <button type="button" class="lvb-btn" data-act="reload">Herladen</button>
          <button type="button" class="lvb-btn" data-act="reset-chrome" title="Reset panel-layout">Reset UI</button>
          <button type="button" class="lvb-btn" data-act="save-chrome" title="Sla editor-chrome op">UI preset</button>
          <button type="button" class="lvb-btn lvb-btn-primary" data-act="save">Opslaan</button>
          <span class="lvb-status-pill" data-role="status">Start…</span>
        </div>
        <div class="lvb-dock-left" data-role="dock-left"></div>
        <div class="lvb-center-gap" data-role="center"></div>
        <div class="lvb-dock-right" data-role="dock-right"></div>
        <div class="lvb-dock-bottom" data-role="dock-bottom"></div>
      </div>
      <div class="lvb-splitter lvb-splitter-v" data-side="left" data-role="split-left"></div>
      <div class="lvb-splitter lvb-splitter-v" data-side="right" data-role="split-right"></div>
      <div class="lvb-splitter lvb-splitter-h" data-role="split-bottom"></div>
      <div class="lvb-float-layer" data-role="float-layer"></div>
      <div class="lvb-statusbar">
        <span data-role="bar-sel">Geen selectie</span>
        <span>·</span>
        <span data-role="bar-zoom">100%</span>
        <span>·</span>
        <span data-role="bar-save">Synced</span>
        <span style="margin-left:auto;opacity:.7">Shift multi · Alt-sleep · Drop om te herparenten · ⌘S opslaan</span>
      </div>
      <div class="lvb-menu" data-role="menu" hidden></div>
      <div class="lvb-media" data-role="media" hidden>
        <div class="lvb-media-head">
          <strong data-role="media-title">Image toevoegen</strong>
          <button type="button" class="lvb-btn" data-act="close-media">Sluiten</button>
        </div>
        <div class="lvb-media-actions">
          <button type="button" class="lvb-btn lvb-btn-primary" data-act="upload-image">Upload vanaf PC</button>
          <button type="button" class="lvb-btn" data-act="refresh-media">Ververs</button>
        </div>
        <p class="lvb-muted" style="margin:0 0 8px">Kies een bestaande asset of upload een nieuwe. Blijft opgeslagen in Leviathan.</p>
        <div class="lvb-media-grid" data-role="media-grid"></div>
      </div>
      <div class="lvb-guide-x" data-role="snap-x"></div>
      <div class="lvb-guide-y" data-role="snap-y"></div>
      <input type="file" accept="image/*" data-role="hidden-file" hidden />
      <input type="file" accept="image/*" data-role="add-file" hidden />
      <div class="lvb-hover" hidden><div class="lvb-label" data-role="hover-label"></div></div>
      <div class="lvb-select" hidden><div class="lvb-label" data-role="select-label"></div></div>
    `;
    document.documentElement.appendChild(root);

    ui.root = root;
    ui.status = $('[data-role="status"]', root);
    ui.dockLeft = $('[data-role="dock-left"]', root);
    ui.dockRight = $('[data-role="dock-right"]', root);
    ui.dockBottom = $('[data-role="dock-bottom"]', root);
    ui.floatLayer = $('[data-role="float-layer"]', root);
    ui.menu = $('[data-role="menu"]', root);
    ui.media = $('[data-role="media"]', root);
    ui.mediaTitle = $('[data-role="media-title"]', root);
    ui.mediaGrid = $('[data-role="media-grid"]', root);
    ui.snapX = $('[data-role="snap-x"]', root);
    ui.snapY = $('[data-role="snap-y"]', root);
    ui.hiddenFile = $('[data-role="hidden-file"]', root);
    ui.addFile = $('[data-role="add-file"]', root);
    ui.hover = $(".lvb-hover", root);
    ui.select = $(".lvb-select", root);
    ui.hoverLabel = $('[data-role="hover-label"]', root);
    ui.selectLabel = $('[data-role="select-label"]', root);
    ui.barSel = $('[data-role="bar-sel"]', root);
    ui.barZoom = $('[data-role="bar-zoom"]', root);
    ui.barSave = $('[data-role="bar-save"]', root);
    ui.splitLeft = $('[data-role="split-left"]', root);
    ui.splitRight = $('[data-role="split-right"]', root);
    ui.splitBottom = $('[data-role="split-bottom"]', root);

    document.body.classList.add("lvb-editing");
    applyChromeLayout();
    renderChromePanels();
  }

  function bindSplitters() {
    const bindV = (el, side) => {
      el.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        const startX = e.clientX;
        const startW = side === "left" ? state.chrome.leftW : state.chrome.rightW;
        const onMove = (ev) => {
          const dx = ev.clientX - startX;
          if (side === "left") state.chrome.leftW = Math.max(180, Math.min(480, startW + dx));
          else state.chrome.rightW = Math.max(220, Math.min(560, startW - dx));
          applyChromeLayout();
        };
        const onUp = () => {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          saveChromeLayout();
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
      });
    };
    bindV(ui.splitLeft, "left");
    bindV(ui.splitRight, "right");
    ui.splitBottom.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      state.chrome.bottomOpen = true;
      const startY = e.clientY;
      const startH = state.chrome.bottomH || 220;
      const onMove = (ev) => {
        state.chrome.bottomH = Math.max(120, Math.min(480, startH - (ev.clientY - startY)));
        applyChromeLayout();
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        saveChromeLayout();
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
  }

  function handleRootClick(event) {
    const nav = event.target.closest("[data-nav]");
    if (nav) return void window.location.assign(nav.dataset.nav);

    const tab = event.target.closest("[data-tab-side]");
    if (tab) {
      state.chrome.activeTabs[tab.dataset.tabSide] = tab.dataset.tabId;
      saveChromeLayout();
      renderChromePanels();
      return;
    }

    const panelAct = event.target.closest("[data-panel-act]");
    if (panelAct) {
      const panel = panelAct.closest(".lvb-panel");
      const id = panel?.dataset.panel;
      if (!id) return;
      const act = panelAct.dataset.panelAct;
      if (act === "dock-left") dockPanel(id, "left");
      if (act === "dock-right") dockPanel(id, "right");
      if (act === "dock-bottom") dockPanel(id, "bottom");
      if (act === "float") undockPanel(id);
      if (act === "max") maximizePanel(id);
      if (act === "collapse") panel.classList.toggle("is-collapsed");
      return;
    }

    const hist = event.target.closest("[data-hist]");
    if (hist) return restoreHistory(Number(hist.dataset.hist));

    const layer = event.target.closest("[data-layer-sel]");
    if (layer) {
      try {
        const el = document.querySelector(layer.dataset.layerSel);
        if (el) selectTarget({ el, region: regionFor(el), selector: selectorFor(el), kind: "element" }, { additive: event.shiftKey || event.metaKey });
      } catch {
        /* ignore */
      }
      return;
    }

    const insert = event.target.closest("[data-insert]");
    if (insert) return insertPreset(insert.dataset.insert);

    const menuBtn = event.target.closest("[data-menu]");
    if (menuBtn) return runMenuAction(menuBtn.dataset.menu);

    const asset = event.target.closest("[data-asset-url]");
    if (asset) {
      state.imagePickerMode = state.imagePickerMode || "insert";
      applyPickedImageUrl(asset.dataset.assetUrl, asset.title || "Image").catch((err) => setStatus(String(err), "dirty"));
      return;
    }

    const act2 = event.target.closest("[data-act2]");
    if (act2) {
      const a = act2.dataset.act2;
      if (a === "copy") copySelection();
      if (a === "paste") pasteClipboard();
      if (a === "duplicate") duplicateSelection();
      if (a === "delete") deleteSelection();
      if (a === "lock") toggleLock();
      if (a === "group") groupSelection();
      if (a === "ungroup") ungroupSelection();
      if (a === "convert-widget") convertToWidget();
      if (a === "front") bringForward();
      if (a === "back") sendBack();
      if (a === "align-left") alignInParent("left");
      if (a === "align-center") alignInParent("center");
      if (a === "align-right") alignInParent("right");
      if (a === "aspect") {
        state.aspectLock = !state.aspectLock;
        renderInspector();
      }
      if (a === "grid") {
        state.grid = !state.grid;
        renderInspector();
        setStatus(state.grid ? "Grid aan" : "Grid uit", "ok");
      }
      if (a === "pick-image") openImageLibrary({ mode: "replace" });
      if (a === "upload-replace") {
        state.imagePickerMode = "replace";
        ui.hiddenFile?.click();
      }
      if (a === "clear-styles") {
        const file = state.activeFile === "tokens.css" ? styleFileForSelector() : state.activeFile;
        const re = new RegExp(
          `${escapeReg(BEGIN(state.selectedSelector))}[\\s\\S]*?${escapeReg(END(state.selectedSelector))}\\n?`,
        );
        pushHistory("clear-styles");
        state.files[file] = state.files[file].replace(re, "");
        markDirty(file);
        applyTokensLive();
        renderInspector();
      }
      return;
    }

    if (event.target.closest('[data-role="inline-edit"]') && state.selectedEl) {
      startInlineEdit(state.selectedEl);
      return;
    }

    const btn = event.target.closest("[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === "toggle-edit") {
      state.enabled = !state.enabled;
      btn.classList.toggle("is-on", state.enabled);
      btn.textContent = state.enabled ? "Edit aan" : "Edit uit";
      document.body.classList.toggle("lvb-editing", state.enabled);
      endInlineEdit(true);
      hideContextMenu();
      refreshSelectionChrome();
    }
    if (act === "toggle-left") {
      state.chrome.leftCollapsed = !state.chrome.leftCollapsed;
      btn.classList.toggle("is-on", !state.chrome.leftCollapsed);
      applyChromeLayout();
      saveChromeLayout();
    }
    if (act === "toggle-right") {
      state.chrome.rightCollapsed = !state.chrome.rightCollapsed;
      btn.classList.toggle("is-on", !state.chrome.rightCollapsed);
      applyChromeLayout();
      saveChromeLayout();
    }
    if (act === "toggle-bottom") {
      state.chrome.bottomOpen = !state.chrome.bottomOpen;
      if (state.chrome.bottomOpen && !state.chrome.bottomH) state.chrome.bottomH = 220;
      btn.classList.toggle("is-on", state.chrome.bottomOpen);
      applyChromeLayout();
      saveChromeLayout();
      renderChromePanels();
    }
    if (act === "toggle-snap") {
      state.snap = !state.snap;
      btn.classList.toggle("is-on", state.snap);
      setStatus(state.snap ? "Snap aan" : "Snap uit", "ok");
    }
    if (act === "toggle-grid") {
      state.grid = !state.grid;
      btn.classList.toggle("is-on", state.grid);
      setStatus(state.grid ? "Grid aan" : "Grid uit", "ok");
    }
    if (act === "undo") undo();
    if (act === "redo") redo();
    if (act === "save") saveAll().catch((e) => setStatus(String(e), "dirty"));
    if (act === "reload") loadAll().catch((e) => setStatus(String(e), "dirty"));
    if (act === "reset-chrome") resetChromeLayout();
    if (act === "save-chrome") {
      saveChromeLayout();
      setStatus("Editor-chrome preset opgeslagen (localStorage)", "ok");
    }
    if (act === "add-image") openImageLibrary({ mode: "insert" });
    if (act === "close-media") hideImageLibrary();
    if (act === "refresh-media") openImageLibrary({ mode: state.imagePickerMode || "insert" });
    if (act === "refresh-assets") renderAssetsPanel();
    if (act === "upload-image") ui.addFile?.click();
  }

  function handleRootInput(event) {
    const t = event.target;
    if (!(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement)) return;
    if (t.dataset.role === "region-var" && state.selectedRegion?.varKey) {
      updateRegionVar(state.selectedRegion, Number(t.value));
    }
    if (t.dataset.role === "token-region") {
      const region = REGIONS.find((r) => r.id === t.dataset.region);
      if (region) updateRegionVar(region, Number(t.value));
    }
    if (t.dataset.role === "token-val" || t.dataset.role === "token-color") {
      updateToken(t.dataset.key, t.value);
      if (t.dataset.role === "token-color") {
        const sibling = t.parentElement?.querySelector('[data-role="token-val"]');
        if (sibling) sibling.value = t.value;
      }
    }
    if (t.dataset.role === "decl") updateDecl(t.dataset.prop, t.value);
    if (t.dataset.role === "decl-color") updateDecl(t.dataset.prop, t.value);
    if (t.dataset.role === "img-src" && state.selectedEl?.tagName === "IMG") {
      const oldSrc = state.selectedEl.getAttribute("src") || "";
      commitImageSrc(state.selectedEl, state.selectedSelector, t.value.trim(), oldSrc);
    }
    if (t.dataset.role === "img-alt" && state.selectedEl?.tagName === "IMG") {
      state.selectedEl.setAttribute("alt", t.value);
      upsertContentEntry(state.selectedSelector, { alt: t.value });
    }
    if (t.dataset.role === "text" && state.selectedEl) {
      if (state.selectedEl.childElementCount === 0 || hasDirectText(state.selectedEl)) {
        state.selectedEl.textContent = t.value;
      }
      refreshSelectionChrome();
    }
  }

  function bind() {
    ui.root.addEventListener("click", handleRootClick);
    ui.root.addEventListener("input", handleRootInput);
    bindSplitters();

    ui.root.addEventListener("focusout", (event) => {
      const t = event.target;
      if (!(t instanceof HTMLTextAreaElement) || t.dataset.role !== "text") return;
      if (!state.selectedEl) return;
      commitText(state.selectedEl, state.selectedSelector, t.value);
    });

    ui.hiddenFile.addEventListener("change", () => {
      const file = ui.hiddenFile.files?.[0];
      if (!file) return;
      state.imagePickerMode = state.imagePickerMode || "replace";
      uploadAndInsertImage(file).catch((err) => setStatus(String(err), "dirty"));
      ui.hiddenFile.value = "";
    });

    ui.addFile.addEventListener("change", () => {
      const file = ui.addFile.files?.[0];
      if (!file) return;
      if (!state.imagePickerMode) state.imagePickerMode = "insert";
      uploadAndInsertImage(file).catch((err) => setStatus(String(err), "dirty"));
      ui.addFile.value = "";
    });

    ui.mediaGrid.addEventListener("click", async (event) => {
      const item = event.target.closest("[data-asset-url]");
      if (!item) return;
      try {
        await applyPickedImageUrl(item.dataset.assetUrl, item.title || "Image");
      } catch (err) {
        setStatus(String(err), "dirty");
      }
    });

    // Insert palette drag
    ui.root.addEventListener("dragstart", (e) => {
      const card = e.target.closest("[data-insert]");
      if (!card) return;
      e.dataTransfer?.setData("application/x-lvb-insert", card.dataset.insert);
      e.dataTransfer.effectAllowed = "copy";
    });

    // Layer reorder drag
    let dragLayerSel = null;
    ui.root.addEventListener("dragstart", (e) => {
      const layer = e.target.closest("[data-layer-sel]");
      if (!layer) return;
      dragLayerSel = layer.dataset.layerSel;
      e.dataTransfer?.setData("text/plain", dragLayerSel);
    });
    ui.root.addEventListener("dragover", (e) => {
      if (e.target.closest("[data-layer-sel]")) e.preventDefault();
    });
    ui.root.addEventListener("drop", (e) => {
      const target = e.target.closest("[data-layer-sel]");
      if (!target || !dragLayerSel) return;
      e.preventDefault();
      try {
        const a = document.querySelector(dragLayerSel);
        const b = document.querySelector(target.dataset.layerSel);
        if (a && b && a.parentElement === b.parentElement) {
          pushHistory("layer-reorder");
          b.parentElement.insertBefore(a, b);
          if (a.dataset.lvbId) syncNodesFromDom();
          markContentDirty();
          renderLayersPanel();
        }
      } catch {
        /* ignore */
      }
      dragLayerSel = null;
    });

    ui.select.addEventListener("pointerdown", (event) => {
      const handle = event.target.closest(".lvb-handle");
      if (handle) {
        if (handle.dataset.dir === "rot") return startRotate(event);
        return startResize(event, handle.dataset.dir);
      }
      if (event.target.closest(".lvb-move-grip")) return startMove(event);
      if (!state.selectedRegion?.edge) return startMove(event);
    });

    document.addEventListener(
      "mousemove",
      (event) => {
        if (!state.enabled || state.mode || state.inlineEditing) return;
        if (isBuilderNode(event.target)) {
          state.hoverEl = null;
          refreshSelectionChrome();
          return;
        }
        const picked = pickEditable(event.target, event.clientX, event.clientY);
        state.hoverEl = picked?.el || null;
        refreshSelectionChrome();
      },
      true,
    );

    document.addEventListener(
      "click",
      (event) => {
        if (!state.enabled || state.inlineEditing) return;
        if (isBuilderNode(event.target)) return;
        hideContextMenu();
        const picked = pickEditable(event.target, event.clientX, event.clientY);
        if (!picked) return;
        event.preventDefault();
        event.stopPropagation();
        selectTarget(picked, { additive: event.shiftKey || event.metaKey });
      },
      true,
    );

    document.addEventListener(
      "dblclick",
      (event) => {
        if (!state.enabled) return;
        if (isBuilderNode(event.target)) return;
        const picked = pickEditable(event.target, event.clientX, event.clientY);
        if (!picked || picked.el.tagName === "IMG") return;
        event.preventDefault();
        event.stopPropagation();
        selectTarget(picked);
        startInlineEdit(picked.el);
      },
      true,
    );

    document.addEventListener(
      "contextmenu",
      (event) => {
        if (!state.enabled) return;
        if (isBuilderNode(event.target) && !event.target.closest(".lvb-select")) return;
        const picked = isBuilderNode(event.target)
          ? state.selectedEl
            ? {
                el: resolveImageEl(state.selectedEl) || state.selectedEl,
                region: state.selectedRegion,
                selector: selectorFor(resolveImageEl(state.selectedEl) || state.selectedEl),
                kind: resolveImageEl(state.selectedEl) ? "img" : "element",
              }
            : null
          : pickEditable(event.target, event.clientX, event.clientY);
        if (!picked && !state.selectedEl) return;
        event.preventDefault();
        event.stopPropagation();
        showContextMenu(event.clientX, event.clientY, picked);
      },
      true,
    );

    document.addEventListener(
      "pointerdown",
      (event) => {
        if (!state.enabled || state.inlineEditing) return;
        if (isBuilderNode(event.target)) return;
        if (!(event.altKey || event.button === 1)) return;
        const picked = pickEditable(event.target, event.clientX, event.clientY);
        if (!picked || !canMutate(picked.el)) return;
        selectTarget(picked, { additive: event.shiftKey });
        startMove(event);
      },
      true,
    );

    window.addEventListener("dragover", (e) => {
      if (!state.enabled) return;
      if (e.dataTransfer?.types?.includes("application/x-lvb-insert") || [...(e.dataTransfer?.files || [])].length) {
        e.preventDefault();
      }
    });

    window.addEventListener("drop", async (e) => {
      if (!state.enabled) return;
      if (isBuilderNode(e.target) && !e.target.closest(".lvb-center-gap")) {
        const insertType = e.dataTransfer?.getData("application/x-lvb-insert");
        if (insertType) {
          e.preventDefault();
          insertPreset(insertType);
          if (state.selectedEl) {
            const parent = state.selectedEl.parentElement;
            if (parent) {
              const pr = parent.getBoundingClientRect();
              state.selectedEl.style.position = "absolute";
              state.selectedEl.style.left = `${Math.max(0, Math.round(e.clientX - pr.left - 20))}px`;
              state.selectedEl.style.top = `${Math.max(0, Math.round(e.clientY - pr.top - 20))}px`;
              bakePosition(state.selectedEl, selectorFor(state.selectedEl));
            }
          }
          return;
        }
      }
      if (isBuilderNode(e.target)) return;
      e.preventDefault();
      const insertType = e.dataTransfer?.getData("application/x-lvb-insert");
      if (insertType) {
        insertPreset(insertType);
        return;
      }
      const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith("image/"));
      if (!file) return;
      try {
        state.imagePickerMode = "insert";
        await uploadAndInsertImage(file);
        if (state.selectedEl) {
          const parent = state.selectedEl.parentElement;
          if (parent) {
            const pr = parent.getBoundingClientRect();
            state.selectedEl.style.position = "absolute";
            state.selectedEl.style.left = `${Math.max(0, Math.round(e.clientX - pr.left - 40))}px`;
            state.selectedEl.style.top = `${Math.max(0, Math.round(e.clientY - pr.top - 40))}px`;
            bakePosition(state.selectedEl, selectorFor(state.selectedEl));
          }
        }
      } catch (err) {
        setStatus(String(err), "dirty");
      }
    });

    window.addEventListener("resize", () => refreshSelectionChrome());
    window.addEventListener("scroll", () => refreshSelectionChrome(), true);

    window.addEventListener("keydown", (event) => {
      if (!state.enabled) return;
      const meta = event.ctrlKey || event.metaKey;
      const tag = document.activeElement?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA" || document.activeElement?.isContentEditable;

      if (meta && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveAll().catch((e) => setStatus(String(e), "dirty"));
        return;
      }
      if (meta && event.key.toLowerCase() === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
        return;
      }
      if (meta && (event.key.toLowerCase() === "y" || (event.key.toLowerCase() === "z" && event.shiftKey))) {
        event.preventDefault();
        redo();
        return;
      }
      if (meta && event.key.toLowerCase() === "\\") {
        event.preventDefault();
        resetChromeLayout();
        return;
      }
      if (meta && event.key.toLowerCase() === "1") {
        event.preventDefault();
        state.chrome.leftCollapsed = !state.chrome.leftCollapsed;
        applyChromeLayout();
        saveChromeLayout();
        return;
      }
      if (meta && event.key.toLowerCase() === "2") {
        event.preventDefault();
        state.chrome.rightCollapsed = !state.chrome.rightCollapsed;
        applyChromeLayout();
        saveChromeLayout();
        return;
      }
      if (meta && event.key.toLowerCase() === "3") {
        event.preventDefault();
        state.chrome.bottomOpen = !state.chrome.bottomOpen;
        applyChromeLayout();
        saveChromeLayout();
        renderChromePanels();
        return;
      }
      if (meta && event.key.toLowerCase() === "i") {
        event.preventDefault();
        dockPanel("inspector", "right");
        return;
      }
      if (typing) return;

      if (meta && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copySelection();
      }
      if (meta && event.key.toLowerCase() === "v") {
        event.preventDefault();
        pasteClipboard();
      }
      if (meta && event.key.toLowerCase() === "d") {
        event.preventDefault();
        duplicateSelection();
      }
      if (meta && event.key.toLowerCase() === "g") {
        event.preventDefault();
        if (event.shiftKey) ungroupSelection();
        else groupSelection();
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelection();
      }
      if (event.key === "Escape") {
        hideContextMenu();
        clearSelection();
      }
      const step = event.shiftKey ? 10 : 1;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        nudge(-step, 0);
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        nudge(step, 0);
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        nudge(0, -step);
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        nudge(0, step);
      }
    });

    const mo = new MutationObserver(() => {
      if (state.applyingContent || state.inlineEditing || state.mode) return;
      clearTimeout(mo._t);
      mo._t = setTimeout(() => {
        applyContentOverrides();
        mountNodes();
        refreshSelectionChrome();
        renderLayersPanel();
      }, 100);
    });
    const rootEl = document.getElementById("root");
    if (rootEl) mo.observe(rootEl, { childList: true, subtree: true, characterData: true });
  }

  async function boot() {
    buildUI();
    bind();
    try {
      await loadAll();
    } catch (err) {
      setStatus(`API offline? Start EDIT_LAYOUT.bat — ${err}`, "dirty");
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
