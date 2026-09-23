/**
 * LEVIATHAN STUDIO — content, CSS files, live apply, save coordination.
 * Breakpoint overrides live in content JSON. Desktop overrides also land in styles/*.css.
 */

import { FILES } from "./constants.js";
import {
  DOC_VERSION,
  SCOPE,
  bindLegacyEntry,
  cssSelectorForIdentity,
  identityFor,
  migrateContent,
  pageKey,
  queryForEntry,
} from "./identity.js";
import { applyPatch, diffSnapshots, hashDocument, patchIsEmpty } from "./patches.js";
import { createSaveCoordinator } from "./save.js";
import {
  BEGIN,
  END,
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
  const save = createSaveCoordinator(ctx);
  ctx.save = save;

  function state() {
    return ctx.store.getState();
  }

  function ensure(content = state().content) {
    return migrateContent(content);
  }

  function setStatus(text, kind = "") {
    ctx.store.setState({ status: text, statusKind: kind });
  }

  function currentPage() {
    return ctx.pages?.currentPage?.() || pageKey();
  }

  function identityOf(el) {
    return identityFor(el, { page: currentPage() });
  }

  function keyFor(el) {
    return identityOf(el).key;
  }

  function getEntry(selectorOrKey) {
    if (!selectorOrKey) return null;
    const content = state().content;
    if (content.entries?.[selectorOrKey]) return content.entries[selectorOrKey];
    // legacy lookup by selector field
    for (const entry of Object.values(content.entries || {})) {
      if (entry?.legacyKey === selectorOrKey || entry?.selector === selectorOrKey) return entry;
    }
    return null;
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
    save.markDirty();
    if (s.autoSave) scheduleSave();
  }

  function markContentDirty() {
    ctx.store.setState({ contentDirty: true });
    save.markDirty();
    if (state().autoSave) scheduleSave();
  }

  function refreshDirtyStatus() {
    save.refreshStatus();
  }

  function scheduleSave() {
    if (!state().autoSave) return;
    // Never persist an uncommitted pointer preview
    if (ctx.commands?.isGesturing?.()) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      if (ctx.commands?.isGesturing?.()) return;
      saveAll().catch((err) => setStatus(String(err.message || err), "dirty"));
    }, 550);
  }

  /** Full snapshot for gestures — paired with scoped patch restore. */
  function snapshot() {
    const s = state();
    return {
      files: { ...s.files },
      content: JSON.parse(JSON.stringify(ensure())),
      selected: ctx.selection.keys(),
      page: currentPage(),
      scope: null,
    };
  }

  function sameSnap(a, b) {
    if (!a || !b) return false;
    for (const name of FILES) {
      if (a.files[name] !== b.files[name]) return false;
    }
    return JSON.stringify(a.content) === JSON.stringify(b.content);
  }

  function patchBetween(before, after) {
    return diffSnapshots(before, after);
  }

  /**
   * Scoped restore: only reverse the delta of a command.
   * Full snap restore kept for checkpoints / recovery.
   */
  function restorePatch(patch, direction = "back") {
    if (!patch || patchIsEmpty(patch)) return;
    const s = state();
    const next = applyPatch(s, patch, direction);
    const dirtyFiles = {};
    for (const name of FILES) dirtyFiles[name] = next.files[name] !== s.saved[name];
    ctx.store.setState({
      files: next.files,
      content: ensure(next.content),
      contentDirty: true,
      dirtyFiles,
    });
    save.markDirty();
    reapply();
    if (state().autoSave) scheduleSave();
  }

  function restore(snap) {
    if (!snap) return;
    if (snap._patch) {
      restorePatch(snap._patch, snap._direction || "back");
      if (snap.selected) ctx.selection.reselect(snap.selected);
      return;
    }
    ctx.store.setState({
      files: { ...snap.files },
      content: JSON.parse(JSON.stringify(ensure(snap.content))),
      contentDirty: true,
    });
    const dirtyFiles = {};
    for (const name of FILES) dirtyFiles[name] = snap.files[name] !== state().saved[name];
    ctx.store.setState({ dirtyFiles });
    save.markDirty();
    reapply();
    ctx.selection.reselect(snap.selected || []);
    if (state().autoSave) scheduleSave();
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
    if (entry.nodeId && !el.dataset.lvbNode) el.dataset.lvbNode = entry.nodeId;
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

  function entryAppliesToPage(entry, page) {
    if (!entry) return false;
    if (entry.scope === SCOPE.GLOBAL_SHELL || entry.scope === SCOPE.GLOBAL_TOKEN || entry.scope === SCOPE.COMPONENT_MASTER) {
      return true;
    }
    if (!entry.page || entry.page === "*" || entry.page === page) return true;
    return false;
  }

  function applyContentOverrides() {
    const s = state();
    ctx.session.applying = true;
    try {
      const content = ensure();
      const bp = s.breakpoint || "desktop";
      const page = currentPage();
      for (const [key, entry] of Object.entries(content.entries)) {
        if (!entryAppliesToPage(entry, page)) continue;
        const nodes = queryForEntry(key, entry);
        if (!nodes.length && entry.ambiguous && entry.legacyKey) {
          // leave for Problems panel
          continue;
        }
        for (const el of nodes) {
          if (!(el instanceof Element) || ctx.selection.isBuilderNode(el)) continue;
          syncElement(el, entry, bp);
        }
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
        let el = document.querySelector(`[data-lvb-id="${CSS.escape(node.id)}"]`);
        if (el && ctx.selection.isBuilderNode(el)) el = null;
        if (!el) {
          const wrap = document.createElement("div");
          wrap.innerHTML = sanitizeWidgetHtml(node.html);
          el = wrap.firstElementChild;
          if (!el) continue;
          el.dataset.lvbId = node.id;
          el.dataset.lvbNode = node.nodeId || node.id;
          if (node.label) el.dataset.lvbLabel = node.label;
          if (node.componentId) el.dataset.lvbComponentId = node.componentId;
          if (node.variant) el.dataset.lvbVariant = node.variant;
          const parent =
            (node.parent && safeQuery(node.parent)) ||
            document.querySelector(".lv-main") ||
            document.getElementById("root") ||
            document.body;
          parent.appendChild(el);
        } else if (!el.dataset.lvbNode) {
          el.dataset.lvbNode = node.nodeId || node.id;
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

  function sanitizeWidgetHtml(html) {
    const wrap = document.createElement("div");
    wrap.innerHTML = String(html || "");
    wrap.querySelectorAll("script, iframe, object, embed").forEach((n) => n.remove());
    wrap.querySelectorAll("*").forEach((el) => {
      for (const attr of [...el.attributes]) {
        const name = attr.name.toLowerCase();
        if (name.startsWith("on") || (name === "href" && /^\s*javascript:/i.test(attr.value))) {
          el.removeAttribute(attr.name);
        }
      }
    });
    return wrap.innerHTML;
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

  function syncNodesFromDom() {
    const content = ensure();
    content.nodes = content.nodes.map((node) => {
      const el = document.querySelector(`[data-lvb-id="${CSS.escape(node.id)}"]`);
      if (!(el instanceof Element) || ctx.selection.isBuilderNode(el)) return node;
      const parentIdent = el.parentElement ? identityOf(el.parentElement) : null;
      return {
        ...node,
        html: el.outerHTML,
        nodeId: el.dataset.lvbNode || node.nodeId || node.id,
        parent: parentIdent?.key || node.parent || ".lv-main",
        componentId: el.dataset.lvbComponentId || node.componentId,
        variant: el.dataset.lvbVariant || node.variant,
        styles: {
          ...(node.styles || {}),
          position: el.style.position || node.styles?.position,
          left: el.style.left || node.styles?.left,
          top: el.style.top || node.styles?.top,
          width: el.style.width || node.styles?.width,
          height: el.style.height || node.styles?.height,
          rotate: el.style.rotate || node.styles?.rotate,
          scale: el.style.scale || node.styles?.scale,
          "max-width": el.style.maxWidth || node.styles?.["max-width"],
          margin: el.style.margin || node.styles?.margin,
          zIndex: el.style.zIndex || node.styles?.zIndex,
        },
      };
    });
    ctx.store.setState({ content });
  }

  function upsertEntry(el, mutator) {
    const ident = identityOf(el);
    const content = ensure();
    // If we still have a legacy ambiguous entry matching this element uniquely, bind it
    for (const [key, entry] of Object.entries(content.entries)) {
      if (!entry?.ambiguous) continue;
      try {
        const nodes = [...document.querySelectorAll(key)];
        if (nodes.length === 1 && nodes[0] === el) {
          bindLegacyEntry(el, key, content);
          break;
        }
      } catch {
        /* ignore */
      }
    }
    const key = keyFor(el);
    const prev = { ...(content.entries[key] || {}) };
    const next = mutator({ ...prev, nodeId: ident.nodeId || prev.nodeId, scope: ident.scope, page: ident.page });
    content.entries[key] = next;
    ctx.store.setState({ content });
    return { key, entry: next, ident };
  }

  function applyProp(el, prop, value) {
    if (!(el instanceof Element) || !prop) return;
    const s = state();
    const bp = s.breakpoint || "desktop";
    const next = value == null ? "" : String(value).trim();
    const ident = identityOf(el);
    const cssSel = cssSelectorForIdentity(ident);

    if (bp !== "desktop") {
      upsertEntry(el, (entry) => {
        const breakpoints = { ...(entry.breakpoints || {}) };
        const decls = { ...(breakpoints[bp] || {}) };
        if (!next) delete decls[prop];
        else decls[prop] = next;
        breakpoints[bp] = decls;
        return { ...entry, breakpoints };
      });
      if (next) writeInline(el, prop, next);
      else {
        const entry = getEntry(keyFor(el));
        if (entry?.styles?.[prop]) writeInline(el, prop, entry.styles[prop]);
        else writeInline(el, prop, "");
      }
      markContentDirty();
      return;
    }

    const file = styleFileFor(cssSel || "");
    const selector = cssSel || keyFor(el);
    const decls = readOverrideDecls(s.files[file], selector);
    upsertEntry(el, (entry) => {
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
      const out = { ...entry, styles };
      if (prop === "position") {
        if (next) out.position = next;
        else delete out.position;
      }
      if (prop === "left" || prop === "top" || prop === "width" || prop === "height") {
        if (next) out[prop] = next;
        else delete out[prop];
      }
      if (prop === "z-index") {
        if (next) out.zIndex = next;
        else delete out.zIndex;
      }
      return out;
    });
    s.files[file] = upsertOverride(s.files[file] || "", selector, declsToText(decls));
    ctx.store.setState({ files: s.files, activeFile: file });
    markFile(file);
    markContentDirty();
    applyTokensLive();
  }

  function readProp(el, prop) {
    const key = keyFor(el);
    const s = state();
    const entry = s.content.entries?.[key] || getEntry(key) || {};
    const bp = s.breakpoint || "desktop";
    if (bp !== "desktop" && entry.breakpoints?.[bp] && prop in entry.breakpoints[bp]) {
      return { value: entry.breakpoints[bp][prop] ?? "", source: "breakpoint" };
    }
    if (entry.styles && prop in entry.styles) {
      return { value: entry.styles[prop] ?? "", source: "entry" };
    }
    const ident = identityOf(el);
    const selector = cssSelectorForIdentity(ident) || key;
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
    const ident = identityOf(el);
    const selector = cssSelectorForIdentity(ident) || keyFor(el);
    const s = state();
    const file = styleFileFor(selector);
    const re = new RegExp(`${escapeReg(BEGIN(selector))}[\\s\\S]*?${escapeReg(END(selector))}\\n?`);
    s.files[file] = (s.files[file] || "").replace(re, "");
    const content = ensure();
    const key = keyFor(el);
    if (content.entries[key]) {
      const managedProps = [...(managed.get(el) || []), ...(el.dataset.lvbManaged || "").split(",").filter(Boolean)];
      for (const prop of managedProps) el.style.removeProperty(prop);
      managed.set(el, new Set());
      delete el.dataset.lvbManaged;
      content.entries[key] = {
        ...content.entries[key],
        styles: {},
        breakpoints: {},
        nodeId: ident.nodeId,
        scope: ident.scope,
        page: ident.page,
      };
      delete content.entries[key].position;
      delete content.entries[key].left;
      delete content.entries[key].top;
      delete content.entries[key].width;
      delete content.entries[key].height;
    }
    ctx.store.setState({ files: s.files, content });
    markFile(file);
    markContentDirty();
    reapply();
  }

  function stageText(el, text) {
    const baseline =
      getEntry(keyFor(el))?.text != null
        ? getEntry(keyFor(el)).text
        : el.dataset.lvbOriginalText || el.textContent || "";
    if (!el.dataset.lvbOriginalText) el.dataset.lvbOriginalText = baseline;
    el.textContent = text;
    upsertEntry(el, (entry) => ({ ...entry, text, prevText: baseline }));
    markContentDirty();
    return baseline;
  }

  /** Visual text edits must NOT globally rewrite source trees. */
  async function replaceSource(_oldText, _newText) {
    setStatus("Bronvervanging uitgeschakeld — tekst staat in documententries", "ok");
    return { ok: false, disabled: true };
  }

  async function saveAll(opts) {
    return save.saveAll(opts);
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
    const content = ensure(contentRes.content || { version: DOC_VERSION, entries: {}, nodes: [], components: [] });
    ctx.store.setState({
      files,
      saved,
      dirtyFiles: Object.fromEntries(FILES.map((n) => [n, false])),
      content,
      contentDirty: false,
      contentRevision: contentRes.revision ?? content.revision ?? 0,
      contentHash: contentRes.hash || hashDocument(content, files),
    });
    save.adoptServer({
      revision: contentRes.revision ?? content.revision ?? 0,
      hash: contentRes.hash || hashDocument(content, files),
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

  function patchEntry(selectorOrEl, patch) {
    if (selectorOrEl instanceof Element) {
      upsertEntry(selectorOrEl, (entry) => ({ ...entry, ...patch }));
      markContentDirty();
      return;
    }
    const content = ensure();
    const key = selectorOrEl;
    content.entries[key] = { ...(content.entries[key] || {}), ...patch };
    ctx.store.setState({ content });
    markContentDirty();
  }

  function rawDecls(el) {
    const key = keyFor(el);
    const s = state();
    const bp = s.breakpoint || "desktop";
    const entry = s.content.entries?.[key] || {};
    if (bp !== "desktop") return declsToText(entry.breakpoints?.[bp] || {});
    const ident = identityOf(el);
    const selector = cssSelectorForIdentity(ident) || key;
    const file = styleFileFor(selector);
    const fromFile = readOverrideDecls(s.files[file], selector);
    return declsToText({ ...fromFile, ...(entry.styles || {}) });
  }

  function applyRaw(el, text) {
    const decls = parseDecls(text);
    const key = keyFor(el);
    const bp = state().breakpoint || "desktop";
    if (bp !== "desktop") {
      upsertEntry(el, (entry) => {
        const breakpoints = { ...(entry.breakpoints || {}) };
        breakpoints[bp] = decls;
        return { ...entry, breakpoints };
      });
      markContentDirty();
      syncElement(el, state().content.entries[key], bp);
      return;
    }
    const ident = identityOf(el);
    const selector = cssSelectorForIdentity(ident) || key;
    const props = Object.keys({
      ...(state().content.entries?.[key]?.styles || {}),
      ...readOverrideDecls(state().files[styleFileFor(selector)], selector),
    });
    for (const prop of props) {
      if (!(prop in decls)) applyProp(el, prop, "");
    }
    for (const [k, v] of Object.entries(decls)) applyProp(el, k, v);
  }

  // beforeunload warning for real dirty work
  if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", (event) => {
      if (!save.isDirty() && save.getState().localRevision <= save.getState().savedRevision) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }

  return {
    ensure,
    setStatus,
    getEntry,
    styleFileFor,
    snapshot,
    sameSnap,
    restore,
    restorePatch,
    patchBetween,
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
    keyFor,
    identityOf,
    save,
  };
}
