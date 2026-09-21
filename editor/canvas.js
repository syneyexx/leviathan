(() => {
  const API =
    document.querySelector("script[data-lv-editor-api]")?.getAttribute("data-lv-editor-api") ||
    "http://127.0.0.1:5199";

  const FILES = ["tokens.css", "leviathan.css", "pages.css", "chat.css"];

  const REGIONS = [
    { id: "header", selector: ".lv-header", label: "Header", varKey: "--lv-header-height", edge: "s", min: 48, max: 180 },
    { id: "sidebar", selector: ".lv-sidebar", label: "Sidebar", varKey: "--lv-sidebar-width", edge: "e", min: 110, max: 340 },
    { id: "right", selector: ".lv-right", label: "Right panel", varKey: "--lv-right-panel-width", edge: "w", min: 120, max: 420 },
    { id: "footer", selector: ".lv-footer", label: "Footer", varKey: "--lv-footer-height", edge: "n", min: 44, max: 140 },
    { id: "main", selector: ".lv-main", label: "Main", varKey: null, edge: null, min: 0, max: 64 },
  ];

  const STYLE_GROUPS = [
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
    autoSave: true,
    files: Object.fromEntries(FILES.map((n) => [n, ""])),
    saved: Object.fromEntries(FILES.map((n) => [n, ""])),
    dirty: Object.fromEntries(FILES.map((n) => [n, false])),
    content: { version: 1, entries: {} },
    contentDirty: false,
    activeFile: "leviathan.css",
    selectedEl: null,
    selectedRegion: null,
    selectedSelector: null,
    selectedKind: null,
    hoverEl: null,
    saveTimer: null,
    dragging: false,
    inlineEditing: false,
    applyingContent: false,
  };

  const ui = {};

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

  function setStatus(text, kind = "") {
    if (!ui.status) return;
    ui.status.textContent = text;
    ui.status.className = `lvb-status${kind ? ` is-${kind}` : ""}`;
  }

  function isBuilderNode(node) {
    return !!(node && (node === ui.root || (ui.root && ui.root.contains(node))));
  }

  function selectorFor(el) {
    if (!(el instanceof Element)) return "unknown";
    if (el.tagName === "IMG") {
      const src = el.getAttribute("src");
      if (src) return `img[src="${src}"]`;
      return "img";
    }
    const lv = [...el.classList].filter((c) => c.startsWith("lv-"));
    if (lv.length === 1) return `.${lv[0]}`;
    if (lv.length > 1) return `.${lv.join(".")}`;
    if (el.id) return `#${el.id}`;
    const tag = el.tagName.toLowerCase();
    const parent = el.parentElement;
    if (parent) {
      const idx = [...parent.children].indexOf(el) + 1;
      return `${selectorFor(parent)} > ${tag}:nth-child(${idx})`;
    }
    return tag;
  }

  function regionFor(el) {
    return REGIONS.find((r) => el.matches?.(r.selector)) || null;
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
      if (el.classList && [...el.classList].some((c) => c.startsWith("lv-"))) {
        const kind = el.childElementCount === 0 || hasDirectText(el) ? "texty" : "element";
        return { el, region: regionFor(el), selector: selectorFor(el), kind };
      }
      if (["H1", "H2", "H3", "H4", "P", "SPAN", "LABEL", "BUTTON", "A"].includes(el.tagName)) {
        return { el, region: regionFor(el), selector: selectorFor(el), kind: "texty" };
      }
      el = el.parentElement;
    }
    return null;
  }

  function hasDirectText(el) {
    return [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  }

  function labelFor(el) {
    if (el.tagName === "IMG") return "image";
    const lv = [...el.classList].find((c) => c.startsWith("lv-"));
    return lv ? `.${lv}` : el.tagName.toLowerCase();
  }

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

  async function loadAll() {
    for (const name of FILES) {
      const data = await apiGet(name);
      state.files[name] = data.content;
      state.saved[name] = data.content;
      state.dirty[name] = false;
    }
    const contentRes = await apiGetContent();
    state.content = contentRes.content || { version: 1, entries: {} };
    state.content.entries = state.content.entries || {};
    state.contentDirty = false;
    syncCodePane();
    applyTokensLive();
    applyContentOverrides();
    setStatus("Klaar — klik/dubbelklik om te bewerken", "ok");
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
    }, 500);
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
      await apiPutContent(state.content);
      state.contentDirty = false;
    }
    setStatus("Opgeslagen in echte Leviathan bestanden", "ok");
  }

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

  function applyContentOverrides() {
    state.applyingContent = true;
    try {
      const entries = state.content.entries || {};
      for (const [selector, entry] of Object.entries(entries)) {
        let nodes;
        try {
          nodes = document.querySelectorAll(selector);
        } catch {
          continue;
        }
        nodes.forEach((el) => {
          if (!(el instanceof Element) || isBuilderNode(el)) return;
          if (entry.text != null && el.tagName !== "IMG") {
            if (el.childElementCount === 0 || hasDirectText(el)) {
              el.textContent = entry.text;
            }
          }
          if (entry.html != null && el.tagName !== "IMG") {
            el.innerHTML = entry.html;
          }
          if (entry.src && el.tagName === "IMG") {
            el.setAttribute("src", entry.src);
          }
          if (entry.alt != null && el.tagName === "IMG") {
            el.setAttribute("alt", entry.alt);
          }
          if (entry.hide) el.style.display = "none";
        });
      }
    } finally {
      state.applyingContent = false;
    }
  }

  function upsertContentEntry(selector, patch) {
    const prev = state.content.entries[selector] || {};
    state.content.entries[selector] = { ...prev, ...patch };
    markContentDirty();
  }

  function syncCodePane() {
    if (!ui.codeArea) return;
    if (state.activeFile === "__content__") {
      ui.codeFile.textContent = "lv-editor-content.json";
      if (document.activeElement !== ui.codeArea) {
        ui.codeArea.value = JSON.stringify(state.content, null, 2);
      }
    } else {
      ui.codeFile.textContent = state.activeFile;
      if (document.activeElement !== ui.codeArea) {
        ui.codeArea.value = state.files[state.activeFile] || "";
      }
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
      ui.selectLabel.textContent = state.selectedSelector || labelFor(state.selectedEl);
    } else ui.select.hidden = true;
  }

  function styleFileForSelector() {
    if (location.pathname.includes("chat")) return "chat.css";
    if (["/brain", "/models", "/training", "/settings", "/status"].some((p) => location.pathname.includes(p))) {
      return "pages.css";
    }
    return "leviathan.css";
  }

  function selectTarget(picked) {
    endInlineEdit(true);
    state.selectedEl = picked.el;
    state.selectedRegion = picked.region;
    state.selectedSelector = picked.selector;
    state.selectedKind = picked.kind;
    if (picked.region?.varKey) state.activeFile = "tokens.css";
    else state.activeFile = styleFileForSelector();
    syncCodePane();
    renderDock();
    refreshSelectionChrome();
  }

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

  function renderDock() {
    const el = state.selectedEl;
    if (!el) {
      ui.dockBody.innerHTML = `
        <p class="lvb-muted"><b>Volledige visual editor</b></p>
        <p class="lvb-muted">Klik iets aan · dubbelklik tekst om te typen · images via upload/URL. Alles wordt in de echte bestanden opgeslagen.</p>`;
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
        <div class="lvb-field">
          <label>Bron (URL)</label>
          <input type="text" data-role="img-src" value="${escapeHtml(src)}" />
        </div>
        <div class="lvb-field">
          <label>Upload nieuwe image</label>
          <input type="file" accept="image/*" data-role="img-file" />
        </div>
        <div class="lvb-field">
          <label>Alt tekst</label>
          <input type="text" data-role="img-alt" value="${escapeHtml(el.getAttribute("alt") || "")}" />
        </div>`;
    } else {
      const text = hasDirectText(el) || el.childElementCount === 0 ? el.textContent || "" : "";
      html += `
        <div class="lvb-section">Tekst</div>
        <div class="lvb-field">
          <label>Inhoud (of dubbelklik op de layout)</label>
          <textarea data-role="text" rows="3">${escapeHtml(text)}</textarea>
        </div>
        <button type="button" class="lvb-btn" data-role="inline-edit" style="width:100%">Inline bewerken op layout</button>`;
    }

    if (region?.varKey) {
      const cur = getVar(state.files["tokens.css"], region.varKey) || "80px";
      const px = Math.round(pxFromCssValue(cur, 80));
      html += `
        <div class="lvb-section">Shell maat</div>
        <div class="lvb-field">
          <label>${region.label} (${px}px)</label>
          <input type="range" min="${region.min}" max="${region.max}" value="${px}" data-role="region-var" />
        </div>`;
    }

    if (region?.id === "main") {
      const padX = pxFromCssValue(getVar(state.files["tokens.css"], "--lv-page-pad-x"), 10);
      const padY = pxFromCssValue(getVar(state.files["tokens.css"], "--lv-page-pad-y"), 10);
      const gap = pxFromCssValue(getVar(state.files["tokens.css"], "--lv-content-gap"), 10);
      html += `
        <div class="lvb-field"><label>Pad X (${padX}px)</label>
          <input type="range" min="0" max="48" value="${padX}" data-role="token" data-key="--lv-page-pad-x" /></div>
        <div class="lvb-field"><label>Pad Y (${padY}px)</label>
          <input type="range" min="0" max="48" value="${padY}" data-role="token" data-key="--lv-page-pad-y" /></div>
        <div class="lvb-field"><label>Gap (${gap}px)</label>
          <input type="range" min="0" max="40" value="${gap}" data-role="token" data-key="--lv-content-gap" /></div>`;
    }

    html += `<div class="lvb-section">Styles → ${escapeHtml(state.activeFile === "tokens.css" ? styleFileForSelector() : state.activeFile)}</div>`;
    for (const group of STYLE_GROUPS) {
      html += `<div class="lvb-section lvb-section-sub">${group.title}</div><div class="lvb-row">`;
      for (const prop of group.props) {
        const val = decls[prop.key] || "";
        const hint = computedHint(el, prop.key).trim();
        if (prop.type === "color") {
          const colorVal = val || hint || "#ffffff";
          const hex = toHexColor(colorVal);
          html += `<div class="lvb-field"><label>${prop.label}</label>
            <div class="lvb-color-row">
              <input type="color" data-role="decl-color" data-prop="${prop.key}" value="${hex}" />
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
        <button type="button" class="lvb-chip" data-role="hide">Verberg</button>
        <button type="button" class="lvb-chip" data-role="show">Toon</button>
        <button type="button" class="lvb-chip" data-role="clear-styles">Reset styles</button>
      </div>`;

    ui.dockBody.innerHTML = html;
  }

  function toHexColor(value) {
    const v = String(value || "").trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) return v;
    if (/^#[0-9a-fA-F]{3}$/.test(v)) {
      return `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`;
    }
    const m = v.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
    if (m) {
      const h = (n) => Number(n).toString(16).padStart(2, "0");
      return `#${h(m[1])}${h(m[2])}${h(m[3])}`;
    }
    return "#ffffff";
  }

  function updateRegionVar(region, px) {
    const cur = getVar(state.files["tokens.css"], region.varKey) || `${px}px`;
    const next = cssFromPx(cur, Math.round(px), region);
    state.files["tokens.css"] = setVar(state.files["tokens.css"], region.varKey, next);
    state.activeFile = "tokens.css";
    markDirty("tokens.css");
    applyTokensLive();
    syncCodePane();
    refreshSelectionChrome();
  }

  function updateTokenKey(key, px) {
    const cur = getVar(state.files["tokens.css"], key) || `${px}px`;
    const next = cssFromPx(cur, Math.round(px), { min: 0, max: 200 });
    state.files["tokens.css"] = setVar(state.files["tokens.css"], key, next);
    state.activeFile = "tokens.css";
    markDirty("tokens.css");
    applyTokensLive();
    syncCodePane();
  }

  function updateDecl(prop, value) {
    const selector = state.selectedSelector;
    if (!selector) return;
    const file = state.activeFile === "tokens.css" ? styleFileForSelector() : state.activeFile;
    const decls = readOverrideDecls(state.files[file], selector);
    if (!String(value).trim()) delete decls[prop];
    else decls[prop] = String(value).trim();
    state.files[file] = upsertOverride(state.files[file], selector, declsToText(decls));
    state.activeFile = file;
    markDirty(file);
    applyTokensLive();
    syncCodePane();
    refreshSelectionChrome();
  }

  async function commitText(el, selector, newText) {
    const entry = state.content.entries[selector] || {};
    const oldText = entry.text != null ? entry.text : entry.prevText != null ? entry.prevText : null;
    const baseline = oldText != null ? oldText : (el.dataset.lvbOriginalText || el.textContent || "");
    if (!el.dataset.lvbOriginalText) el.dataset.lvbOriginalText = baseline;

    el.textContent = newText;
    upsertContentEntry(selector, { text: newText, prevText: baseline });
    applyContentOverrides();

    try {
      if (baseline && baseline !== newText && baseline.length >= 2) {
        const result = await apiReplaceText(baseline, newText);
        const n = result.changed?.length || 0;
        setStatus(n ? `Tekst opgeslagen in ${n} bronbestand(en)` : "Tekst opgeslagen (content + live)", "ok");
      } else {
        setStatus("Tekst opgeslagen", "ok");
      }
    } catch (err) {
      setStatus(String(err), "dirty");
    }
    syncCodePane();
  }

  async function commitImageSrc(el, selector, newSrc, oldSrc) {
    el.setAttribute("src", newSrc);
    upsertContentEntry(selector, { src: newSrc });
    // Keep a second key for the new src so re-apply works after DOM updates
    if (newSrc !== oldSrc) {
      upsertContentEntry(`img[src="${newSrc}"]`, { src: newSrc });
    }
    try {
      if (oldSrc && oldSrc !== newSrc) {
        const result = await apiReplaceText(oldSrc, newSrc);
        const n = result.changed?.length || 0;
        setStatus(n ? `Image bijgewerkt in ${n} bronbestand(en)` : "Image opgeslagen", "ok");
      }
    } catch (err) {
      setStatus(String(err), "dirty");
    }
    state.selectedSelector = `img[src="${newSrc}"]`;
    syncCodePane();
    refreshSelectionChrome();
    renderDock();
  }

  function startInlineEdit(el) {
    if (!el || el.tagName === "IMG") return;
    endInlineEdit(true);
    state.inlineEditing = true;
    ui.select.hidden = true;
    ui.hover.hidden = true;
    el.contentEditable = "true";
    el.classList.add("lvb-inline-editing");
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    const onBlur = () => {
      el.removeEventListener("blur", onBlur);
      endInlineEdit(false);
    };
    el.addEventListener("blur", onBlur);
    el.addEventListener(
      "keydown",
      (ev) => {
        if (ev.key === "Enter" && !ev.shiftKey) {
          ev.preventDefault();
          el.blur();
        }
        if (ev.key === "Escape") {
          ev.preventDefault();
          el.textContent = el.dataset.lvbOriginalText || el.textContent;
          el.blur();
        }
      },
      { once: false },
    );
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
      const selector = state.selectedSelector || selectorFor(el);
      commitText(el, selector, el.textContent || "").then(() => {
        renderDock();
        refreshSelectionChrome();
      });
    } else {
      refreshSelectionChrome();
    }
  }

  function onPointerDownHandle(event) {
    const handle = event.target.closest(".lvb-handle");
    if (!handle || !state.selectedEl) return;
    event.preventDefault();
    event.stopPropagation();
    state.dragging = true;
    const dir = handle.dataset.dir;
    const region = state.selectedRegion;
    const startX = event.clientX;
    const startY = event.clientY;
    const startRect = state.selectedEl.getBoundingClientRect();

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
      if (dir.includes("e")) w = startRect.width + dx;
      if (dir.includes("w")) w = startRect.width - dx;
      if (dir.includes("s")) h = startRect.height + dy;
      if (dir.includes("n")) h = startRect.height - dy;
      w = Math.max(24, Math.round(w));
      h = Math.max(24, Math.round(h));
      if (dir.includes("e") || dir.includes("w")) updateDecl("width", `${w}px`);
      if (dir.includes("n") || dir.includes("s")) updateDecl("min-height", `${h}px`);
      refreshSelectionChrome();
    };

    const onUp = () => {
      state.dragging = false;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      renderDock();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function buildUI() {
    const root = document.createElement("div");
    root.id = "lvb-root";
    root.innerHTML = `
      <div class="lvb-bar">
        <div class="lvb-brand">Visual Builder</div>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn" data-nav="/">Command</button>
        <button type="button" class="lvb-btn" data-nav="/chat">Chat</button>
        <button type="button" class="lvb-btn" data-nav="/status">Status</button>
        <button type="button" class="lvb-btn" data-nav="/models">Models</button>
        <button type="button" class="lvb-btn" data-nav="/settings">Settings</button>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn is-on" data-act="toggle-edit">Edit aan</button>
        <button type="button" class="lvb-btn is-on" data-act="toggle-dock">Panel</button>
        <button type="button" class="lvb-btn" data-act="toggle-code">Code</button>
        <button type="button" class="lvb-btn" data-act="reload">Herladen</button>
        <button type="button" class="lvb-btn lvb-btn-primary" data-act="save">Opslaan</button>
        <div class="lvb-sep"></div>
        <span class="lvb-status" data-role="status">Start…</span>
      </div>
      <div class="lvb-dock is-open" data-role="dock">
        <div data-role="dock-body"></div>
        <div class="lvb-chip-row" data-role="files"></div>
      </div>
      <div class="lvb-code" data-role="code">
        <div class="lvb-code-head">
          <span data-role="code-file">leviathan.css</span>
          <span>Live ↔ echte bestanden</span>
        </div>
        <textarea data-role="code-area" spellcheck="false" wrap="off"></textarea>
      </div>
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
    ui.hover = $(".lvb-hover", root);
    ui.select = $(".lvb-select", root);
    ui.hoverLabel = $('[data-role="hover-label"]', root);
    ui.selectLabel = $('[data-role="select-label"]', root);

    const chips = [...FILES, "__content__"];
    ui.files.innerHTML = chips
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
      if (nav) {
        window.location.assign(nav.dataset.nav);
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
        refreshSelectionChrome();
      }
      if (act === "toggle-dock") {
        state.showDock = !state.showDock;
        ui.dock.classList.toggle("is-open", state.showDock);
        btn.classList.toggle("is-on", state.showDock);
      }
      if (act === "toggle-code") {
        state.showCode = !state.showCode;
        ui.code.classList.toggle("is-open", state.showCode);
        btn.classList.toggle("is-on", state.showCode);
      }
      if (act === "save") saveAll().catch((e) => setStatus(String(e), "dirty"));
      if (act === "reload") loadAll().catch((e) => setStatus(String(e), "dirty"));
    });

    ui.files.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-file]");
      if (!chip) return;
      state.activeFile = chip.dataset.file;
      syncCodePane();
    });

    ui.dock.addEventListener("input", (event) => {
      const t = event.target;
      if (!(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement)) return;

      if (t.dataset.role === "region-var" && state.selectedRegion?.varKey) {
        updateRegionVar(state.selectedRegion, Number(t.value));
      }
      if (t.dataset.role === "token") updateTokenKey(t.dataset.key, Number(t.value));
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
        // live preview while typing in panel
        if (state.selectedEl.childElementCount === 0 || hasDirectText(state.selectedEl)) {
          state.selectedEl.textContent = t.value;
        }
        refreshSelectionChrome();
      }
    });

    ui.dock.addEventListener("change", async (event) => {
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

    ui.dock.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-role]");
      if (!btn || !state.selectedEl) return;
      if (btn.dataset.role === "inline-edit") startInlineEdit(state.selectedEl);
      if (btn.dataset.role === "hide") {
        updateDecl("display", "none");
        upsertContentEntry(state.selectedSelector, { hide: true });
      }
      if (btn.dataset.role === "show") {
        updateDecl("display", "");
        upsertContentEntry(state.selectedSelector, { hide: false });
        state.selectedEl.style.display = "";
      }
      if (btn.dataset.role === "clear-styles") {
        const file = state.activeFile === "tokens.css" ? styleFileForSelector() : state.activeFile;
        const re = new RegExp(
          `${escapeReg(BEGIN(state.selectedSelector))}[\\s\\S]*?${escapeReg(END(state.selectedSelector))}\\n?`,
        );
        state.files[file] = state.files[file].replace(re, "");
        markDirty(file);
        applyTokensLive();
        renderDock();
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
          state.content.entries = state.content.entries || {};
          markContentDirty();
          applyContentOverrides();
        } catch {
          setStatus("Ongeldige JSON in content", "dirty");
        }
        return;
      }
      const name = state.activeFile;
      state.files[name] = ui.codeArea.value;
      markDirty(name);
      applyTokensLive();
    });

    ui.select.addEventListener("pointerdown", onPointerDownHandle);

    document.addEventListener(
      "mousemove",
      (event) => {
        if (!state.enabled || state.dragging || state.inlineEditing) return;
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

    window.addEventListener("resize", () => refreshSelectionChrome());
    window.addEventListener("scroll", () => refreshSelectionChrome(), true);

    window.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveAll().catch((e) => setStatus(String(e), "dirty"));
      }
      if (event.key === "Escape" && !state.inlineEditing) {
        state.selectedEl = null;
        state.selectedRegion = null;
        state.selectedSelector = null;
        refreshSelectionChrome();
        renderDock();
      }
    });

    // Re-apply content after React re-renders
    const mo = new MutationObserver(() => {
      if (state.applyingContent || state.inlineEditing) return;
      clearTimeout(mo._t);
      mo._t = setTimeout(() => {
        applyContentOverrides();
        refreshSelectionChrome();
      }, 80);
    });
    const root = document.getElementById("root");
    if (root) mo.observe(root, { childList: true, subtree: true, characterData: true });
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
