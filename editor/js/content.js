/**
 * Leviathan Visual Builder — content, CSS files, live apply, save.
 * Breakpoint overrides live in content JSON. Desktop overrides also land in styles/*.css.
 */

import { FILES } from "./constants.js";
import {
  cssFromPx,
  declsToText,
  escapeReg,
  getVar,
  parseDecls,
  pxFromCssValue,
  readOverrideDecls,
  setVar,
  upsertOverride,
} from "./util.js";

export function createContent(ctx) {
  let saveTimer = 0;
  const managed = new WeakMap();

  function state() {
    return ctx.store.getState();
  }

  function ensure(content = state().content) {
    content.version = 2;
    content.entries = content.entries && typeof content.entries === "object" ? content.entries : {};
    content.nodes = Array.isArray(content.nodes) ? content.nodes : [];
    content.components = Array.isArray(content.components) ? content.components : [];
    return content;
  }

  function setStatus(text, kind = "") {
    ctx.store.setState({ status: text, statusKind: kind });
  }

  function getEntry(selector) {
    if (!selector) return null;
    return state().content.entries?.[selector] || null;
  }

  function styleFileFor(selector = "") {
    const path = location.pathname || "";
    if (path.includes("chat") || selector.includes("chat")) return "chat.css";
    if (["/brain", "/models", "/training", "/settings", "/status", "/research", "/datasets", "/tools"].some((p) => path.includes(p))) {
      return "pages.css";
    }
    return "leviathan.css";
  }

  function markFile(name) {
    const s = state();
    const dirtyFiles = { ...s.dirtyFiles, [name]: s.files[name] !== s.saved[name] };
    ctx.store.setState({ dirtyFiles });
    refreshDirtyStatus();
    if (s.autoSave) scheduleSave();
  }

  function markContentDirty() {
    ctx.store.setState({ contentDirty: true });
    refreshDirtyStatus();
    if (state().autoSave) scheduleSave();
  }

  function refreshDirtyStatus() {
    const s = state();
    const any = s.contentDirty || FILES.some((f) => s.files[f] !== s.saved[f]);
    if (s.statusKind === "" && String(s.status || "").startsWith("Opslaan")) return;
    setStatus(any ? "Niet opgeslagen · auto-save" : "Gesynchroniseerd", any ? "dirty" : "ok");
  }

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      saveAll().catch((err) => setStatus(String(err.message || err), "dirty"));
    }, 550);
  }

  function snapshot() {
    const s = state();
    return {
      files: { ...s.files },
      content: JSON.parse(JSON.stringify(ensure())),
      selected: ctx.selection.keys(),
    };
  }

  function sameSnap(a, b) {
    if (!a || !b) return false;
    for (const name of FILES) {
      if (a.files[name] !== b.files[name]) return false;
    }
    return JSON.stringify(a.content) === JSON.stringify(b.content);
  }

  function applyTokensLive() {
    const tokens = state().files["tokens.css"] || "";
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
      const found = (state().files[file] || "").match(blockRe);
      if (found) blocks.push(...found);
    }
    ov.textContent = blocks.join("\n");
  }

  function remember(el, prop) {
    const set = managed.get(el) || new Set();
    set.add(prop);
    managed.set(el, set);
    el.dataset.lvbManaged = [...set].join(",");
  }

  function writeInline(el, prop, value) {
    if (!(el instanceof Element)) return;
    if (value == null || value === "") el.style.removeProperty(prop);
    else {
      el.style.setProperty(prop, value);
      remember(el, prop);
    }
  }

  function syncElement(el, entry, bp) {
    if (!(el instanceof Element) || !entry) return;
    const prev = new Set([...(managed.get(el) || []), ...(el.dataset.lvbManaged || "").split(",").filter(Boolean)]);
    for (const prop of prev) el.style.removeProperty(prop);
    managed.set(el, new Set());
    const write = (prop, value) => {
      if (value == null || value === "") return;
      writeInline(el, prop, String(value));
    };
    if (entry.styles) {
      for (const [k, v] of Object.entries(entry.styles)) write(k, v);
    }
    write("position", entry.position);
    write("left", entry.left);
    write("top", entry.top);
    write("width", entry.width);
    write("height", entry.height);
    if (entry.zIndex != null && entry.zIndex !== "") write("z-index", String(entry.zIndex));
    if (bp && bp !== "desktop" && entry.breakpoints?.[bp]) {
      for (const [k, v] of Object.entries(entry.breakpoints[bp])) write(k, v);
    }
    if (entry.hide) write("display", "none");
    if (entry.text != null && el.tagName !== "IMG") {
      const texty = el.childElementCount === 0 || [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (texty) el.textContent = entry.text;
    }
    if (entry.src && el.tagName === "IMG") el.setAttribute("src", entry.src);
    if (entry.alt != null && el.tagName === "IMG") el.setAttribute("alt", entry.alt);
    if (entry.locked) el.dataset.lvbLocked = "1";
    else if (el.dataset.lvbLocked === "1" && entry.locked === false) delete el.dataset.lvbLocked;
  }

  function applyContentOverrides() {
    const s = state();
    ctx.session.applying = true;
    try {
      const content = ensure();
      const bp = s.breakpoint || "desktop";
      for (const [selector, entry] of Object.entries(content.entries)) {
        let nodes;
        try {
          nodes = document.querySelectorAll(selector);
        } catch {
          continue;
        }
        nodes.forEach((el) => {
          if (!(el instanceof Element) || ctx.selection.isBuilderNode(el)) return;
          syncElement(el, entry, bp);
        });
      }
    } finally {
      ctx.session.applying = false;
    }
  }

  function mountNodes() {
    ctx.session.applying = true;
    try {
      const content = ensure();
      document.querySelectorAll("[data-lvb-id]").forEach((el) => {
        if (ctx.selection.isBuilderNode(el)) return;
        if (!content.nodes.some((n) => n.id === el.dataset.lvbId)) el.remove();
      });
      for (const node of content.nodes) {
        let el = document.querySelector(`[data-lvb-id="${node.id}"]`);
        if (el && ctx.selection.isBuilderNode(el)) el = null;
        if (!el) {
          const wrap = document.createElement("div");
          wrap.innerHTML = node.html;
          el = wrap.firstElementChild;
          if (!el) continue;
          el.dataset.lvbId = node.id;
          if (node.label) el.dataset.lvbLabel = node.label;
          if (node.componentId) el.dataset.lvbComponentId = node.componentId;
          if (node.variant) el.dataset.lvbVariant = node.variant;
          const parent =
            (node.parent && safeQuery(node.parent)) ||
            document.querySelector(".lv-main") ||
            document.getElementById("root") ||
            document.body;
          parent.appendChild(el);
        }
        if (node.styles) {
          for (const [k, v] of Object.entries(node.styles)) {
            if (v != null && v !== "") writeInline(el, k === "zIndex" ? "z-index" : k, String(v));
          }
        }
      }
    } finally {
      ctx.session.applying = false;
    }
  }

  function safeQuery(selector) {
    try {
      return document.querySelector(selector);
    } catch {
      return null;
    }
  }

  function reapply() {
    applyTokensLive();
    applyContentOverrides();
    mountNodes();
    ctx.chrome?.schedulePaint?.();
  }

  function restore(snap) {
    if (!snap) return;
    ctx.store.setState({
      files: { ...snap.files },
      content: JSON.parse(JSON.stringify(snap.content)),
      contentDirty: true,
    });
    const dirtyFiles = {};
    for (const name of FILES) dirtyFiles[name] = snap.files[name] !== state().saved[name];
    ctx.store.setState({ dirtyFiles });
    reapply();
    ctx.selection.reselect(snap.selected || []);
    scheduleSave();
  }

  function syncNodesFromDom() {
    const content = ensure();
    content.nodes = content.nodes.map((node) => {
      const el = document.querySelector(`[data-lvb-id="${node.id}"]`);
      if (!(el instanceof Element) || ctx.selection.isBuilderNode(el)) return node;
      return {
        ...node,
        html: el.outerHTML,
        parent: node.parent || ctx.selection.selectorFor(el.parentElement) || ".lv-main",
        styles: {
          ...(node.styles || {}),
          position: el.style.position || node.styles?.position,
          left: el.style.left || node.styles?.left,
          top: el.style.top || node.styles?.top,
          width: el.style.width || node.styles?.width,
          height: el.style.height || node.styles?.height,
          zIndex: el.style.zIndex || node.styles?.zIndex,
        },
      };
    });
    ctx.store.setState({ content });
  }

  function applyProp(el, prop, value) {
    if (!(el instanceof Element) || !prop) return;
    const selector = ctx.selection.selectorFor(el);
    const s = state();
    const content = ensure();
    const bp = s.breakpoint || "desktop";
    const entry = { ...(content.entries[selector] || {}) };
    const next = value == null ? "" : String(value).trim();

    if (bp !== "desktop") {
      const breakpoints = { ...(entry.breakpoints || {}) };
      const decls = { ...(breakpoints[bp] || {}) };
      if (!next) delete decls[prop];
      else decls[prop] = next;
      breakpoints[bp] = decls;
      entry.breakpoints = breakpoints;
      content.entries[selector] = entry;
      if (next) writeInline(el, prop, next);
      else if (entry.styles?.[prop]) writeInline(el, prop, entry.styles[prop]);
      else writeInline(el, prop, "");
      ctx.store.setState({ content });
      markContentDirty();
      return;
    }

    const file = s.activeFile === "tokens.css" ? styleFileFor(selector) : styleFileFor(selector);
    const decls = readOverrideDecls(s.files[file], selector);
    const styles = { ...(entry.styles || {}) };
    if (!next) {
      delete decls[prop];
      delete styles[prop];
      writeInline(el, prop, "");
    } else {
      decls[prop] = next;
      styles[prop] = next;
      writeInline(el, prop, next);
    }
    s.files[file] = upsertOverride(s.files[file] || "", selector, declsToText(decls));
    entry.styles = styles;
    if (prop === "position") {
      if (next) entry.position = next;
      else delete entry.position;
    }
    if (prop === "left" || prop === "top" || prop === "width" || prop === "height") {
      if (next) entry[prop] = next;
      else delete entry[prop];
    }
    if (prop === "z-index") {
      if (next) entry.zIndex = next;
      else delete entry.zIndex;
    }
    content.entries[selector] = entry;
    ctx.store.setState({ files: s.files, content, activeFile: file });
    markFile(file);
    markContentDirty();
    applyTokensLive();
  }

  function readProp(el, prop) {
    const selector = ctx.selection.selectorFor(el);
    const s = state();
    const entry = s.content.entries?.[selector] || {};
    const bp = s.breakpoint || "desktop";
    if (bp !== "desktop" && entry.breakpoints?.[bp] && prop in entry.breakpoints[bp]) {
      return { value: entry.breakpoints[bp][prop] ?? "", source: "breakpoint" };
    }
    if (entry.styles && prop in entry.styles) {
      return { value: entry.styles[prop] ?? "", source: "entry" };
    }
    const file = styleFileFor(selector);
    const decls = readOverrideDecls(s.files[file], selector);
    if (prop in decls) return { value: decls[prop], source: "css" };
    const inline = el.style.getPropertyValue(prop);
    if (inline) return { value: inline, source: "inline" };
    let hint = "";
    try {
      hint = getComputedStyle(el).getPropertyValue(prop).trim();
    } catch {
      hint = "";
    }
    return { value: "", source: "empty", hint };
  }

  function setRegionPx(region, px) {
    const s = state();
    const cur = getVar(s.files["tokens.css"], region.varKey) || `${px}px`;
    const next = cssFromPx(cur, Math.round(px), region);
    s.files["tokens.css"] = setVar(s.files["tokens.css"], region.varKey, next);
    ctx.store.setState({ files: s.files, activeFile: "tokens.css" });
    markFile("tokens.css");
    applyTokensLive();
    ctx.chrome?.schedulePaint?.();
  }

  function regionPx(region) {
    const cur = getVar(state().files["tokens.css"], region.varKey) || "80px";
    return Math.round(pxFromCssValue(cur, 80));
  }

  function clearStyles(el) {
    const selector = ctx.selection.selectorFor(el);
    const s = state();
    const file = styleFileFor(selector);
    const re = new RegExp(`${escapeReg(BEGIN(selector))}[\\s\\S]*?${escapeReg(END(selector))}\\n?`);
    s.files[file] = (s.files[file] || "").replace(re, "");
    const content = ensure();
    if (content.entries[selector]) {
      content.entries[selector] = { ...content.entries[selector], styles: {}, breakpoints: {} };
      delete content.entries[selector].position;
      delete content.entries[selector].left;
      delete content.entries[selector].top;
      delete content.entries[selector].width;
      delete content.entries[selector].height;
    }
    ctx.store.setState({ files: s.files, content });
    markFile(file);
    markContentDirty();
    reapply();
  }

  function stageText(el, text) {
    const selector = ctx.selection.selectorFor(el);
    const content = ensure();
    const prev = content.entries[selector] || {};
    const baseline = prev.text != null ? prev.text : el.dataset.lvbOriginalText || el.textContent || "";
    if (!el.dataset.lvbOriginalText) el.dataset.lvbOriginalText = baseline;
    el.textContent = text;
    content.entries[selector] = { ...prev, text, prevText: baseline };
    ctx.store.setState({ content });
    markContentDirty();
    return baseline;
  }

  async function replaceSource(oldText, newText) {
    if (!oldText || oldText === newText || oldText.length < 2) return;
    try {
      const result = await ctx.api.replaceText(oldText, newText);
      setStatus(result.changed?.length ? `Tekst in ${result.changed.length} bron(nen)` : "Tekst opgeslagen", "ok");
    } catch (err) {
      setStatus(String(err.message || err), "dirty");
    }
  }

  async function saveAll() {
    const s = state();
    const dirty = FILES.filter((f) => s.files[f] !== s.saved[f]);
    if (!dirty.length && !s.contentDirty) {
      setStatus("Niets te opslaan", "ok");
      return;
    }
    setStatus("Opslaan…", "");
    syncNodesFromDom();
    for (const name of dirty) {
      const body = state().files[name];
      await ctx.api.putFile(name, body);
      const saved = { ...state().saved, [name]: body };
      const dirtyFiles = { ...state().dirtyFiles, [name]: state().files[name] !== body };
      ctx.store.setState({ saved, dirtyFiles });
    }
    if (state().contentDirty) {
      await ctx.api.putContent(ensure());
      ctx.store.setState({ contentDirty: false });
    }
    setStatus("Opgeslagen in Leviathan-bestanden", "ok");
  }

  async function loadAll() {
    const files = {};
    const saved = {};
    for (const name of FILES) {
      const data = await ctx.api.getFile(name);
      files[name] = data.content || "";
      saved[name] = data.content || "";
    }
    const contentRes = await ctx.api.getContent();
    const content = ensure(contentRes.content || { version: 2, entries: {}, nodes: [], components: [] });
    ctx.store.setState({
      files,
      saved,
      dirtyFiles: Object.fromEntries(FILES.map((n) => [n, false])),
      content,
      contentDirty: false,
    });
    ctx.commands.reset();
    reapply();
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    setStatus("Studio klaar", "ok");
  }

  function setFileText(name, text) {
    const s = state();
    if (!FILES.includes(name)) return;
    s.files[name] = text;
    ctx.store.setState({ files: s.files, activeFile: name });
    markFile(name);
    applyTokensLive();
  }

  function setContentText(text) {
    const parsed = JSON.parse(text);
    const content = ensure(parsed);
    ctx.store.setState({ content, contentDirty: true });
    reapply();
    refreshDirtyStatus();
  }

  function patchEntry(selector, patch) {
    const content = ensure();
    content.entries[selector] = { ...(content.entries[selector] || {}), ...patch };
    ctx.store.setState({ content });
    markContentDirty();
  }

  function rawDecls(el) {
    const selector = ctx.selection.selectorFor(el);
    const s = state();
    const bp = s.breakpoint || "desktop";
    const entry = s.content.entries?.[selector] || {};
    if (bp !== "desktop") return declsToText(entry.breakpoints?.[bp] || {});
    const file = styleFileFor(selector);
    const fromFile = readOverrideDecls(s.files[file], selector);
    return declsToText({ ...fromFile, ...(entry.styles || {}) });
  }

  function applyRaw(el, text) {
    const decls = parseDecls(text);
    const selector = ctx.selection.selectorFor(el);
    const bp = state().breakpoint || "desktop";
    if (bp !== "desktop") {
      const content = ensure();
      const entry = { ...(content.entries[selector] || {}) };
      const breakpoints = { ...(entry.breakpoints || {}) };
      breakpoints[bp] = decls;
      entry.breakpoints = breakpoints;
      content.entries[selector] = entry;
      ctx.store.setState({ content });
      markContentDirty();
      syncElement(el, entry, bp);
      return;
    }
    const props = Object.keys({ ...(state().content.entries?.[selector]?.styles || {}), ...readOverrideDecls(state().files[styleFileFor(selector)], selector) });
    for (const prop of props) {
      if (!(prop in decls)) applyProp(el, prop, "");
    }
    for (const [k, v] of Object.entries(decls)) applyProp(el, k, v);
  }

  return {
    ensure,
    setStatus,
    getEntry,
    styleFileFor,
    snapshot,
    sameSnap,
    restore,
    reapply,
    applyTokensLive,
    applyContentOverrides,
    mountNodes,
    syncNodesFromDom,
    applyProp,
    readProp,
    setRegionPx,
    regionPx,
    clearStyles,
    stageText,
    replaceSource,
    saveAll,
    loadAll,
    scheduleSave,
    markContentDirty,
    patchEntry,
    setFileText,
    setContentText,
    rawDecls,
    applyRaw,
    syncElement,
  };
}
