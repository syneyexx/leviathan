(() => {
  /**
   * Leviathan Visual Builder — Dreamweaver-style canvas editor
   * Move · resize · copy/paste · context menu · insert · undo · layers · snap
   */
  const API =
    document.querySelector("script[data-lv-editor-api]")?.getAttribute("data-lv-editor-api") ||
    "http://127.0.0.1:5199";

  const FILES = ["tokens.css", "leviathan.css", "pages.css", "chat.css"];
  const SHELL_LOCK = new Set([".lv-app", ".lv-body", ".lv-header", ".lv-sidebar", ".lv-footer", ".lv-right", ".lv-main"]);

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
      ],
    },
    {
      title: "Box",
      props: [
        { key: "padding", label: "Padding", type: "text", ph: "12px" },
        { key: "margin", label: "Margin", type: "text", ph: "0" },
        { key: "gap", label: "Gap", type: "text", ph: "10px" },
        { key: "width", label: "Width", type: "text", ph: "auto" },
        { key: "height", label: "Height", type: "text", ph: "auto" },
        { key: "min-height", label: "Min height", type: "text", ph: "120px" },
        { key: "max-width", label: "Max width", type: "text", ph: "100%" },
      ],
    },
    {
      title: "Achtergrond & rand",
      props: [
        { key: "background", label: "Background", type: "text", ph: "#0a0c0b" },
        { key: "background-color", label: "BG color", type: "color" },
        { key: "background-image", label: "BG image", type: "text", ph: "url(...)" },
        { key: "border", label: "Border", type: "text", ph: "1px solid #74572B" },
        { key: "border-color", label: "Border color", type: "color" },
        { key: "border-radius", label: "Radius", type: "text", ph: "12px" },
        { key: "box-shadow", label: "Shadow", type: "text", ph: "0 8px 24px rgba(0,0,0,.4)" },
        { key: "opacity", label: "Opacity", type: "text", ph: "1" },
      ],
    },
    {
      title: "Layout",
      props: [
        { key: "display", label: "Display", type: "text", ph: "flex" },
        { key: "flex-direction", label: "Direction", type: "text", ph: "column" },
        { key: "align-items", label: "Align", type: "text", ph: "center" },
        { key: "justify-content", label: "Justify", type: "text", ph: "center" },
        { key: "overflow", label: "Overflow", type: "text", ph: "hidden" },
      ],
    },
  ];

  const state = {
    enabled: true,
    showCode: false,
    showDock: true,
    showLayers: false,
    snap: true,
    autoSave: true,
    files: Object.fromEntries(FILES.map((n) => [n, ""])),
    saved: Object.fromEntries(FILES.map((n) => [n, ""])),
    dirty: Object.fromEntries(FILES.map((n) => [n, false])),
    content: { version: 2, entries: {}, nodes: [] },
    contentDirty: false,
    activeFile: "leviathan.css",
    selectedEl: null,
    selectedRegion: null,
    selectedSelector: null,
    hoverEl: null,
    saveTimer: null,
    mode: null, // move | resize | null
    inlineEditing: false,
    applyingContent: false,
    clipboard: null,
    history: [],
    historyIndex: -1,
    suppressHistory: false,
  };

  const ui = {};

  /* ------------------------------------------------------------------ */
  /* Utils                                                              */
  /* ------------------------------------------------------------------ */

  function $(sel, root = document) {
    return root.querySelector(sel);
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
    if (!ui.status) return;
    ui.status.textContent = text;
    ui.status.className = `lvb-status${kind ? ` is-${kind}` : ""}`;
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

  function pickEditable(target) {
    if (!(target instanceof Element) || isBuilderNode(target)) return null;
    let el = target;
    if (el.closest("img")) {
      const img = el.closest("img");
      if (img && !isBuilderNode(img)) {
        return { el: img, region: regionFor(img), selector: selectorFor(img), kind: "img" };
      }
    }
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
    if (!re.test(css)) return css;
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

  /* ------------------------------------------------------------------ */
  /* History / dirty / save                                             */
  /* ------------------------------------------------------------------ */

  function pushHistory(label = "edit") {
    if (state.suppressHistory) return;
    const snap = {
      label,
      files: structuredClone(state.files),
      content: structuredClone(state.content),
    };
    state.history = state.history.slice(0, state.historyIndex + 1);
    state.history.push(snap);
    if (state.history.length > 60) state.history.shift();
    state.historyIndex = state.history.length - 1;
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
    renderDock();
    renderLayers();
    refreshSelectionChrome();
    state.suppressHistory = false;
    state.historyIndex = index;
    setStatus(`History: ${snap.label}`, "ok");
    scheduleSave();
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
    setStatus("Opgeslagen", "ok");
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
    renderLayers();
    setStatus("Dreamweaver-modus klaar", "ok");
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
    if (entry.html != null && el.tagName !== "IMG" && !el.dataset.lvbId) {
      // only for simple text nodes; widgets use mountNodes
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
          const parent = document.querySelector(node.parent || ".lv-main") || document.getElementById("root") || document.body;
          parent.appendChild(el);
        }
        if (node.styles) {
          for (const [k, v] of Object.entries(node.styles)) el.style.setProperty(k, v);
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
      // keep data attrs
      return {
        ...node,
        html: clone.outerHTML,
        parent: node.parent || selectorFor(el.parentElement) || ".lv-main",
        styles: {
          ...(node.styles || {}),
          position: el.style.position || undefined,
          left: el.style.left || undefined,
          top: el.style.top || undefined,
          width: el.style.width || undefined,
          height: el.style.height || undefined,
          zIndex: el.style.zIndex || undefined,
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
      ui.codeFile.textContent = "lv-editor-content.json";
      if (document.activeElement !== ui.codeArea) ui.codeArea.value = JSON.stringify(state.content, null, 2);
    } else {
      ui.codeFile.textContent = state.activeFile;
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
      node.querySelectorAll(".lvb-handle").forEach((h) => h.remove());
      const dirs = state.selectedRegion?.edge
        ? [state.selectedRegion.edge]
        : ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
      for (const dir of dirs) {
        const handle = document.createElement("div");
        handle.className = "lvb-handle";
        handle.dataset.dir = dir;
        node.appendChild(handle);
      }
      // move grip in center
      if (!state.selectedRegion?.edge && !isShellLocked(state.selectedEl) && !isLocked(state.selectedEl)) {
        const move = document.createElement("div");
        move.className = "lvb-move-grip";
        move.title = "Slepen om te verplaatsen";
        move.textContent = "✥";
        node.appendChild(move);
      }
    }
  }

  function refreshSelectionChrome() {
    if (!state.enabled || state.inlineEditing) {
      ui.hover.hidden = true;
      if (!state.selectedEl || state.inlineEditing) ui.select.hidden = true;
      return;
    }
    if (state.hoverEl && state.hoverEl !== state.selectedEl) {
      placeBox(ui.hover, boxFromEl(state.hoverEl), false);
      ui.hoverLabel.textContent = labelFor(state.hoverEl);
    } else ui.hover.hidden = true;

    if (state.selectedEl) {
      placeBox(ui.select, boxFromEl(state.selectedEl), true);
      const lock = isLocked(state.selectedEl) ? " 🔒" : "";
      ui.selectLabel.textContent = (state.selectedSelector || labelFor(state.selectedEl)) + lock;
    } else ui.select.hidden = true;
  }

  function selectTarget(picked) {
    endInlineEdit(true);
    hideContextMenu();
    state.selectedEl = picked.el;
    state.selectedRegion = picked.region;
    state.selectedSelector = picked.selector;
    if (picked.region?.varKey) state.activeFile = "tokens.css";
    else state.activeFile = styleFileForSelector();
    syncCodePane();
    renderDock();
    renderLayers();
    refreshSelectionChrome();
  }

  function clearSelection() {
    endInlineEdit(true);
    state.selectedEl = null;
    state.selectedRegion = null;
    state.selectedSelector = null;
    refreshSelectionChrome();
    renderDock();
    renderLayers();
  }

  /* ------------------------------------------------------------------ */
  /* Dock / layers                                                      */
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

  function renderDock() {
    const el = state.selectedEl;
    if (!el) {
      ui.dockBody.innerHTML = `
        <p class="lvb-muted"><b>Dreamweaver-builder</b></p>
        <p class="lvb-muted">Sleep · resize · rechtermuisklik · Ctrl+C/V/D · pijltjes om te nudgen · Insert om toe te voegen.</p>
        <div class="lvb-section">Snel toevoegen</div>
        <div class="lvb-chip-row">
          <button type="button" class="lvb-chip" data-insert="text">+ Tekst</button>
          <button type="button" class="lvb-chip" data-insert="heading">+ Titel</button>
          <button type="button" class="lvb-chip" data-insert="image">+ Image</button>
          <button type="button" class="lvb-chip" data-insert="box">+ Box</button>
          <button type="button" class="lvb-chip" data-insert="button">+ Knop</button>
          <button type="button" class="lvb-chip" data-insert="divider">+ Lijn</button>
        </div>`;
      return;
    }

    const region = state.selectedRegion;
    const selector = state.selectedSelector;
    const decls = currentDecls();
    let html = `<h3>${escapeHtml(selector)}</h3>`;

    if (el.tagName === "IMG") {
      const src = el.getAttribute("src") || "";
      html += `
        <div class="lvb-section">Image</div>
        <div class="lvb-field"><label>Bron (URL)</label>
          <input type="text" data-role="img-src" value="${escapeHtml(src)}" /></div>
        <div class="lvb-field"><label>Upload</label>
          <input type="file" accept="image/*" data-role="img-file" /></div>
        <div class="lvb-field"><label>Alt</label>
          <input type="text" data-role="img-alt" value="${escapeHtml(el.getAttribute("alt") || "")}" /></div>`;
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

    html += `<div class="lvb-section">Styles</div>`;
    for (const group of STYLE_GROUPS) {
      html += `<div class="lvb-section lvb-section-sub">${group.title}</div><div class="lvb-row">`;
      for (const prop of group.props) {
        const val = decls[prop.key] || el.style.getPropertyValue(prop.key) || "";
        const hint = computedHint(el, prop.key).trim();
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
        <button type="button" class="lvb-chip" data-act2="hide">Verberg</button>
        <button type="button" class="lvb-chip" data-act2="show">Toon</button>
        <button type="button" class="lvb-chip" data-act2="front">Naar voren</button>
        <button type="button" class="lvb-chip" data-act2="back">Naar achter</button>
        <button type="button" class="lvb-chip" data-act2="align-left">⬅</button>
        <button type="button" class="lvb-chip" data-act2="align-center">⬌</button>
        <button type="button" class="lvb-chip" data-act2="align-right">➡</button>
        <button type="button" class="lvb-chip" data-act2="clear-styles">Reset styles</button>
      </div>`;

    ui.dockBody.innerHTML = html;
  }

  function renderLayers() {
    if (!ui.layersList) return;
    const root = document.getElementById("root") || document.body;
    const items = [...root.querySelectorAll("[class*='lv-'], [data-lvb-id], img")].slice(0, 80);
    ui.layersList.innerHTML = items
      .map((el) => {
        const sel = selectorFor(el);
        const active = state.selectedEl === el ? " is-on" : "";
        const lock = isLocked(el) ? "🔒" : "";
        return `<button type="button" class="lvb-layer${active}" data-layer-sel="${escapeHtml(sel)}">${lock} ${escapeHtml(labelFor(el))}</button>`;
      })
      .join("");
  }

  /* ------------------------------------------------------------------ */
  /* Style / region updates                                             */
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
  }

  function updateDecl(prop, value, { history = true } = {}) {
    const selector = state.selectedSelector;
    if (!selector || !state.selectedEl) return;
    if (history) pushHistory(`style:${prop}`);
    const file = state.activeFile === "tokens.css" ? styleFileForSelector() : state.activeFile;
    const decls = readOverrideDecls(state.files[file], selector);
    if (!String(value).trim()) {
      delete decls[prop];
      state.selectedEl.style.removeProperty(prop);
    } else {
      decls[prop] = String(value).trim();
      state.selectedEl.style.setProperty(prop, String(value).trim());
    }
    state.files[file] = upsertOverride(state.files[file], selector, declsToText(decls));
    state.activeFile = file;
    // also store in content entry for robust reopen
    const entry = getEntry(selector) || {};
    const styles = { ...(entry.styles || {}) };
    if (!String(value).trim()) delete styles[prop];
    else styles[prop] = String(value).trim();
    upsertContentEntry(selector, { styles });
    markDirty(file);
    applyTokensLive();
    syncCodePane();
    refreshSelectionChrome();
  }

  function bakePosition(el, selector) {
    const cs = getComputedStyle(el);
    if (cs.position === "static") {
      el.style.position = "relative";
    }
    const left = el.style.left || "0px";
    const top = el.style.top || "0px";
    updateDecl("position", el.style.position || "relative", { history: false });
    updateDecl("left", left, { history: false });
    updateDecl("top", top, { history: false });
    upsertContentEntry(selector, {
      position: el.style.position || "relative",
      left,
      top,
      width: el.style.width || undefined,
      height: el.style.height || undefined,
    });
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
    renderDock();
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
        renderDock();
        refreshSelectionChrome();
      });
    } else refreshSelectionChrome();
  }

  /* ------------------------------------------------------------------ */
  /* Move / resize / snap                                               */
  /* ------------------------------------------------------------------ */

  function snapValue(v, guides) {
    if (!state.snap) return v;
    const threshold = 6;
    for (const g of guides) {
      if (Math.abs(v - g) <= threshold) return g;
    }
    return v;
  }

  function collectSnapGuides(el) {
    const parent = el.parentElement || document.body;
    const pr = parent.getBoundingClientRect();
    const guidesX = [pr.left, pr.left + pr.width / 2, pr.right];
    const guidesY = [pr.top, pr.top + pr.height / 2, pr.bottom];
    [...parent.children].forEach((sib) => {
      if (sib === el) return;
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

  function startMove(event) {
    const el = state.selectedEl;
    if (!el || isShellLocked(el) || isLocked(el)) return;
    event.preventDefault();
    event.stopPropagation();
    pushHistory("move");
    state.mode = "move";

    const startX = event.clientX;
    const startY = event.clientY;
    const cs = getComputedStyle(el);
    if (cs.position === "static") el.style.position = "relative";
    const baseLeft = parseFloat(el.style.left) || 0;
    const baseTop = parseFloat(el.style.top) || 0;
    const { guidesX, guidesY } = collectSnapGuides(el);

    const onMove = (ev) => {
      let nextLeft = baseLeft + (ev.clientX - startX);
      let nextTop = baseTop + (ev.clientY - startY);
      const rect = el.getBoundingClientRect();
      const absLeft = rect.left - (parseFloat(el.style.left) || 0) + nextLeft;
      const absTop = rect.top - (parseFloat(el.style.top) || 0) + nextTop;
      const snappedL = snapValue(absLeft, guidesX);
      const snappedT = snapValue(absTop, guidesY);
      nextLeft += snappedL - absLeft;
      nextTop += snappedT - absTop;
      showSnapLines(
        Math.abs(snappedL - absLeft) < 0.1 ? snappedL : null,
        Math.abs(snappedT - absTop) < 0.1 ? snappedT : null,
      );
      el.style.left = `${Math.round(nextLeft)}px`;
      el.style.top = `${Math.round(nextTop)}px`;
      refreshSelectionChrome();
    };

    const onUp = () => {
      state.mode = null;
      hideSnapLines();
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      bakePosition(el, state.selectedSelector || selectorFor(el));
      renderDock();
      setStatus("Verplaatst", "ok");
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
      w = Math.max(16, Math.round(w));
      h = Math.max(16, Math.round(h));
      if (getComputedStyle(el).position === "static") el.style.position = "relative";
      if (dir.includes("w") || dir.includes("n")) {
        el.style.left = `${Math.round(left)}px`;
        el.style.top = `${Math.round(top)}px`;
      }
      el.style.width = `${w}px`;
      el.style.height = `${h}px`;
      refreshSelectionChrome();
    };

    const onUp = () => {
      state.mode = null;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (!region?.varKey) {
        updateDecl("width", el.style.width, { history: false });
        updateDecl("height", el.style.height, { history: false });
        if (el.style.left) updateDecl("left", el.style.left, { history: false });
        if (el.style.top) updateDecl("top", el.style.top, { history: false });
        if (el.style.position) updateDecl("position", el.style.position || "relative", { history: false });
      }
      renderDock();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function nudge(dx, dy) {
    const el = state.selectedEl;
    if (!el || isShellLocked(el) || isLocked(el)) return;
    pushHistory("nudge");
    if (getComputedStyle(el).position === "static") el.style.position = "relative";
    const left = (parseFloat(el.style.left) || 0) + dx;
    const top = (parseFloat(el.style.top) || 0) + dy;
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    bakePosition(el, state.selectedSelector || selectorFor(el));
    refreshSelectionChrome();
  }

  /* ------------------------------------------------------------------ */
  /* Clipboard / CRUD                                                   */
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
    const parent =
      document.querySelector(parentSel) ||
      state.selectedEl ||
      document.querySelector(".lv-main") ||
      document.getElementById("root") ||
      document.body;
    // if selected is not a good container, use its parent or main
    let mount = parent;
    if (state.selectedEl && !parentSel) {
      mount = isShellLocked(state.selectedEl) ? state.selectedEl : state.selectedEl.parentElement || state.selectedEl;
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
    const el = state.selectedEl;
    if (!el || isShellLocked(el)) return setStatus("Shell-elementen kun je niet verwijderen", "dirty");
    if (isLocked(el)) return setStatus("Element is gelocked", "dirty");
    pushHistory("delete");
    const selector = state.selectedSelector || selectorFor(el);
    if (el.dataset.lvbId) {
      state.content.nodes = state.content.nodes.filter((n) => n.id !== el.dataset.lvbId);
      el.remove();
    } else {
      updateDecl("display", "none", { history: false });
      upsertContentEntry(selector, { hide: true });
      el.style.display = "none";
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
    renderDock();
    refreshSelectionChrome();
    setStatus(next ? "Gelocked" : "Unlocked", "ok");
  }

  function bringForward() {
    const el = state.selectedEl;
    if (!el) return;
    pushHistory("z");
    const z = (parseInt(el.style.zIndex || getComputedStyle(el).zIndex, 10) || 1) + 1;
    el.style.zIndex = String(z);
    updateDecl("z-index", String(z), { history: false });
  }

  function sendBack() {
    const el = state.selectedEl;
    if (!el) return;
    pushHistory("z");
    const z = (parseInt(el.style.zIndex || getComputedStyle(el).zIndex, 10) || 1) - 1;
    el.style.zIndex = String(z);
    updateDecl("z-index", String(z), { history: false });
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

  function insertPreset(type) {
    const presets = {
      text: {
        label: "tekst",
        html: `<p class="lvb-widget lvb-text" style="margin:0;color:#E8E4DC;font-size:14px;">Nieuwe tekst — dubbelklik om te bewerken</p>`,
      },
      heading: {
        label: "titel",
        html: `<h2 class="lvb-widget lvb-heading" style="margin:0;color:#F5DFA9;font-family:Cinzel,serif;letter-spacing:0.2em;text-transform:uppercase;">Nieuwe titel</h2>`,
      },
      image: {
        label: "image",
        html: `<img class="lvb-widget lvb-image" src="/assets/hero.jpg" alt="Nieuwe image" width="240" height="140" style="display:block;max-width:100%;border-radius:8px;object-fit:cover;" />`,
      },
      box: {
        label: "box",
        html: `<div class="lvb-widget lvb-box" style="min-width:160px;min-height:100px;padding:14px;border:1px solid #74572B;border-radius:12px;background:rgba(8,10,9,0.88);color:#E8E4DC;">Nieuwe box</div>`,
      },
      button: {
        label: "knop",
        html: `<button type="button" class="lvb-widget lvb-button lv-button-primary" style="padding:10px 16px;">Nieuwe knop</button>`,
      },
      divider: {
        label: "lijn",
        html: `<hr class="lvb-widget lvb-divider" style="width:180px;border:0;border-top:1px solid rgba(214,169,87,0.35);margin:8px 0;" />`,
      },
    };
    const preset = presets[type];
    if (!preset) return;
    insertWidget(preset);
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
    const items = [
      { label: "Kopiëren", k: "⌘C", act: "copy" },
      { label: "Plakken", k: "⌘V", act: "paste" },
      { label: "Dupliceren", k: "⌘D", act: "duplicate" },
      { sep: true },
      { label: "Verwijderen", k: "Del", act: "delete" },
      { label: isLocked(el) ? "Unlock" : "Lock", act: "lock" },
      { sep: true },
      { label: "Tekst bewerken", act: "edit-text", disabled: !el || el.tagName === "IMG" },
      { label: "Image vervangen…", act: "replace-image", disabled: !el || el.tagName !== "IMG" },
      { sep: true },
      { label: "Naar voren", act: "front" },
      { label: "Naar achter", act: "back" },
      { label: "Links uitlijnen", act: "align-left" },
      { label: "Centreren", act: "align-center" },
      { label: "Rechts uitlijnen", act: "align-right" },
      { sep: true },
      { label: "Insert → Tekst", act: "insert-text" },
      { label: "Insert → Image", act: "insert-image" },
      { label: "Insert → Box", act: "insert-box" },
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
      case "edit-text":
        return state.selectedEl && startInlineEdit(state.selectedEl);
      case "replace-image":
        return ui.hiddenFile?.click();
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
        return insertPreset("image");
      case "insert-box":
        return insertPreset("box");
      default:
        break;
    }
  }

  /* ------------------------------------------------------------------ */
  /* UI build                                                           */
  /* ------------------------------------------------------------------ */

  function buildUI() {
    const root = document.createElement("div");
    root.id = "lvb-root";
    root.innerHTML = `
      <div class="lvb-bar">
        <div class="lvb-brand">DW Builder</div>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn" data-nav="/">Command</button>
        <button type="button" class="lvb-btn" data-nav="/chat">Chat</button>
        <button type="button" class="lvb-btn" data-nav="/research">Research</button>
        <button type="button" class="lvb-btn" data-nav="/settings">Settings</button>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn" data-insert="text" title="Tekst">+T</button>
        <button type="button" class="lvb-btn" data-insert="image" title="Image">+Img</button>
        <button type="button" class="lvb-btn" data-insert="box" title="Box">+Box</button>
        <button type="button" class="lvb-btn" data-insert="button" title="Knop">+Btn</button>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn is-on" data-act="toggle-edit">Edit aan</button>
        <button type="button" class="lvb-btn is-on" data-act="toggle-dock">Panel</button>
        <button type="button" class="lvb-btn" data-act="toggle-layers">Layers</button>
        <button type="button" class="lvb-btn" data-act="toggle-code">Code</button>
        <button type="button" class="lvb-btn is-on" data-act="toggle-snap">Snap</button>
        <button type="button" class="lvb-btn" data-act="undo" title="Ctrl+Z">Undo</button>
        <button type="button" class="lvb-btn" data-act="redo" title="Ctrl+Shift+Z">Redo</button>
        <button type="button" class="lvb-btn" data-act="reload">Herladen</button>
        <button type="button" class="lvb-btn lvb-btn-primary" data-act="save">Opslaan</button>
        <div class="lvb-sep"></div>
        <span class="lvb-status" data-role="status">Start…</span>
      </div>
      <div class="lvb-dock is-open" data-role="dock">
        <div data-role="dock-body"></div>
        <div class="lvb-chip-row" data-role="files"></div>
      </div>
      <div class="lvb-layers" data-role="layers" hidden>
        <div class="lvb-layers-head">Layers</div>
        <div class="lvb-layers-list" data-role="layers-list"></div>
      </div>
      <div class="lvb-code" data-role="code">
        <div class="lvb-code-head">
          <span data-role="code-file">leviathan.css</span>
          <span>Live ↔ echte bestanden</span>
        </div>
        <textarea data-role="code-area" spellcheck="false" wrap="off"></textarea>
      </div>
      <div class="lvb-menu" data-role="menu" hidden></div>
      <div class="lvb-snap-x" data-role="snap-x"></div>
      <div class="lvb-snap-y" data-role="snap-y"></div>
      <input type="file" accept="image/*" data-role="hidden-file" hidden />
      <div class="lvb-hover" hidden><div class="lvb-label" data-role="hover-label"></div></div>
      <div class="lvb-select" hidden><div class="lvb-label" data-role="select-label"></div></div>
    `;
    document.documentElement.appendChild(root);

    ui.root = root;
    ui.status = $('[data-role="status"]', root);
    ui.dock = $('[data-role="dock"]', root);
    ui.dockBody = $('[data-role="dock-body"]', root);
    ui.files = $('[data-role="files"]', root);
    ui.code = $('[data-role="code"]', root);
    ui.codeFile = $('[data-role="code-file"]', root);
    ui.codeArea = $('[data-role="code-area"]', root);
    ui.layers = $('[data-role="layers"]', root);
    ui.layersList = $('[data-role="layers-list"]', root);
    ui.menu = $('[data-role="menu"]', root);
    ui.snapX = $('[data-role="snap-x"]', root);
    ui.snapY = $('[data-role="snap-y"]', root);
    ui.hiddenFile = $('[data-role="hidden-file"]', root);
    ui.hover = $(".lvb-hover", root);
    ui.select = $(".lvb-select", root);
    ui.hoverLabel = $('[data-role="hover-label"]', root);
    ui.selectLabel = $('[data-role="select-label"]', root);

    ui.files.innerHTML = [...FILES, "__content__"]
      .map((f) => {
        const label = f === "__content__" ? "content.json" : f;
        return `<button type="button" class="lvb-chip${f === state.activeFile ? " is-on" : ""}" data-file="${f}">${label}</button>`;
      })
      .join("");

    document.body.classList.add("lvb-editing");
    renderDock();
  }

  function bind() {
    ui.root.addEventListener("click", (event) => {
      const nav = event.target.closest("[data-nav]");
      if (nav) return void window.location.assign(nav.dataset.nav);

      const insert = event.target.closest("[data-insert]");
      if (insert) return insertPreset(insert.dataset.insert);

      const menuBtn = event.target.closest("[data-menu]");
      if (menuBtn) return runMenuAction(menuBtn.dataset.menu);

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
      if (act === "toggle-dock") {
        state.showDock = !state.showDock;
        ui.dock.classList.toggle("is-open", state.showDock);
        btn.classList.toggle("is-on", state.showDock);
      }
      if (act === "toggle-layers") {
        state.showLayers = !state.showLayers;
        ui.layers.hidden = !state.showLayers;
        btn.classList.toggle("is-on", state.showLayers);
        renderLayers();
      }
      if (act === "toggle-code") {
        state.showCode = !state.showCode;
        ui.code.classList.toggle("is-open", state.showCode);
        btn.classList.toggle("is-on", state.showCode);
      }
      if (act === "toggle-snap") {
        state.snap = !state.snap;
        btn.classList.toggle("is-on", state.snap);
        setStatus(state.snap ? "Snap aan" : "Snap uit", "ok");
      }
      if (act === "undo") undo();
      if (act === "redo") redo();
      if (act === "save") saveAll().catch((e) => setStatus(String(e), "dirty"));
      if (act === "reload") loadAll().catch((e) => setStatus(String(e), "dirty"));
    });

    ui.files.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-file]");
      if (!chip) return;
      state.activeFile = chip.dataset.file;
      syncCodePane();
    });

    ui.layers.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-layer-sel]");
      if (!btn) return;
      try {
        const el = document.querySelector(btn.dataset.layerSel);
        if (el) selectTarget({ el, region: regionFor(el), selector: selectorFor(el), kind: "element" });
      } catch {
        /* ignore */
      }
    });

    ui.dock.addEventListener("input", (event) => {
      const t = event.target;
      if (!(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement)) return;
      if (t.dataset.role === "region-var" && state.selectedRegion?.varKey) {
        updateRegionVar(state.selectedRegion, Number(t.value));
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
    });

    ui.dock.addEventListener("change", (event) => {
      const t = event.target;
      if (!(t instanceof HTMLInputElement)) return;
      if (t.dataset.role === "img-file" && t.files?.[0] && state.selectedEl?.tagName === "IMG") {
        const file = t.files[0];
        const reader = new FileReader();
        reader.onload = async () => {
          try {
            setStatus("Uploaden…");
            const uploaded = await apiUpload(file.name, String(reader.result));
            const oldSrc = state.selectedEl.getAttribute("src") || "";
            await commitImageSrc(state.selectedEl, state.selectedSelector, uploaded.url, oldSrc);
          } catch (err) {
            setStatus(String(err), "dirty");
          }
        };
        reader.readAsDataURL(file);
      }
    });

    ui.hiddenFile.addEventListener("change", () => {
      const file = ui.hiddenFile.files?.[0];
      if (!file || state.selectedEl?.tagName !== "IMG") return;
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const uploaded = await apiUpload(file.name, String(reader.result));
          const oldSrc = state.selectedEl.getAttribute("src") || "";
          await commitImageSrc(state.selectedEl, state.selectedSelector, uploaded.url, oldSrc);
        } catch (err) {
          setStatus(String(err), "dirty");
        }
      };
      reader.readAsDataURL(file);
      ui.hiddenFile.value = "";
    });

    ui.dock.addEventListener("click", (event) => {
      const insert = event.target.closest("[data-insert]");
      if (insert) return insertPreset(insert.dataset.insert);
      const act2 = event.target.closest("[data-act2]");
      if (act2) {
        const a = act2.dataset.act2;
        if (a === "copy") copySelection();
        if (a === "paste") pasteClipboard();
        if (a === "duplicate") duplicateSelection();
        if (a === "delete") deleteSelection();
        if (a === "lock") toggleLock();
        if (a === "hide") {
          updateDecl("display", "none");
          upsertContentEntry(state.selectedSelector, { hide: true });
        }
        if (a === "show") {
          updateDecl("display", "");
          upsertContentEntry(state.selectedSelector, { hide: false });
          if (state.selectedEl) state.selectedEl.style.display = "";
        }
        if (a === "front") bringForward();
        if (a === "back") sendBack();
        if (a === "align-left") alignInParent("left");
        if (a === "align-center") alignInParent("center");
        if (a === "align-right") alignInParent("right");
        if (a === "clear-styles") {
          const file = state.activeFile === "tokens.css" ? styleFileForSelector() : state.activeFile;
          const re = new RegExp(
            `${escapeReg(BEGIN(state.selectedSelector))}[\\s\\S]*?${escapeReg(END(state.selectedSelector))}\\n?`,
          );
          pushHistory("clear-styles");
          state.files[file] = state.files[file].replace(re, "");
          markDirty(file);
          applyTokensLive();
          renderDock();
        }
      }
      if (event.target.closest('[data-role="inline-edit"]') && state.selectedEl) {
        startInlineEdit(state.selectedEl);
      }
    });

    ui.dock.addEventListener("focusout", (event) => {
      const t = event.target;
      if (!(t instanceof HTMLTextAreaElement) || t.dataset.role !== "text") return;
      if (!state.selectedEl) return;
      commitText(state.selectedEl, state.selectedSelector, t.value);
    });

    ui.codeArea.addEventListener("input", () => {
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
    });

    ui.select.addEventListener("pointerdown", (event) => {
      const handle = event.target.closest(".lvb-handle");
      if (handle) return startResize(event, handle.dataset.dir);
      if (event.target.closest(".lvb-move-grip")) return startMove(event);
      // drag anywhere on selection chrome to move
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
        const picked = pickEditable(event.target);
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
        const picked = pickEditable(event.target);
        if (!picked) return;
        event.preventDefault();
        event.stopPropagation();
        selectTarget(picked);
      },
      true,
    );

    document.addEventListener(
      "dblclick",
      (event) => {
        if (!state.enabled) return;
        if (isBuilderNode(event.target)) return;
        const picked = pickEditable(event.target);
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
        const picked = isBuilderNode(event.target) ? (state.selectedEl ? { el: state.selectedEl, region: state.selectedRegion, selector: state.selectedSelector, kind: "element" } : null) : pickEditable(event.target);
        if (!picked && !state.selectedEl) return;
        event.preventDefault();
        event.stopPropagation();
        showContextMenu(event.clientX, event.clientY, picked);
      },
      true,
    );

    // Drag existing images with Alt+drag directly on page
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (!state.enabled || state.inlineEditing) return;
        if (isBuilderNode(event.target)) return;
        if (!(event.altKey || event.button === 1)) return;
        const picked = pickEditable(event.target);
        if (!picked || isShellLocked(picked.el) || isLocked(picked.el)) return;
        selectTarget(picked);
        startMove(event);
      },
      true,
    );

    // Drop image files onto canvas
    window.addEventListener("dragover", (e) => {
      if (!state.enabled) return;
      e.preventDefault();
    });
    window.addEventListener("drop", async (e) => {
      if (!state.enabled) return;
      e.preventDefault();
      const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith("image/"));
      if (!file) return;
      try {
        setStatus("Uploaden…");
        const dataUrl = await new Promise((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => resolve(String(r.result));
          r.onerror = reject;
          r.readAsDataURL(file);
        });
        const uploaded = await apiUpload(file.name, dataUrl);
        const el = insertWidget({
          label: "image",
          html: `<img class="lvb-widget lvb-image" src="${uploaded.url}" alt="${escapeHtml(file.name)}" style="display:block;max-width:280px;border-radius:8px;" />`,
        });
        if (el) {
          el.style.left = `${Math.round(e.clientX - 80)}px`;
          el.style.top = `${Math.round(e.clientY - 40)}px`;
          el.style.position = "fixed";
          // convert fixed to relative-ish by baking
          bakePosition(el, selectorFor(el));
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
        renderLayers();
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
