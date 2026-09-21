(() => {
  const API =
    document.querySelector("script[data-lv-editor-api]")?.getAttribute("data-lv-editor-api") ||
    "http://127.0.0.1:5199";

  const FILES = ["tokens.css", "leviathan.css", "pages.css", "chat.css"];

  /** Layout regions on the real Leviathan shell */
  const REGIONS = [
    {
      id: "header",
      selector: ".lv-header",
      label: "Header",
      varKey: "--lv-header-height",
      axis: "y",
      edge: "s",
      min: 48,
      max: 180,
    },
    {
      id: "sidebar",
      selector: ".lv-sidebar",
      label: "Sidebar",
      varKey: "--lv-sidebar-width",
      axis: "x",
      edge: "e",
      min: 110,
      max: 340,
    },
    {
      id: "right",
      selector: ".lv-right",
      label: "Right panel",
      varKey: "--lv-right-panel-width",
      axis: "x",
      edge: "w",
      min: 120,
      max: 420,
    },
    {
      id: "footer",
      selector: ".lv-footer",
      label: "Footer",
      varKey: "--lv-footer-height",
      axis: "y",
      edge: "n",
      min: 44,
      max: 140,
    },
    {
      id: "main",
      selector: ".lv-main",
      label: "Main",
      varKey: null,
      axis: "pad",
      edge: null,
      min: 0,
      max: 64,
    },
  ];

  const EDITABLE_PROPS = [
    { key: "padding", label: "Padding" },
    { key: "gap", label: "Gap" },
    { key: "font-size", label: "Font size" },
    { key: "min-height", label: "Min height" },
    { key: "width", label: "Width" },
    { key: "max-width", label: "Max width" },
    { key: "border-radius", label: "Radius" },
  ];

  const state = {
    enabled: true,
    showCode: true,
    showDock: true,
    autoSave: true,
    files: Object.fromEntries(FILES.map((n) => [n, ""])),
    saved: Object.fromEntries(FILES.map((n) => [n, ""])),
    dirty: Object.fromEntries(FILES.map((n) => [n, false])),
    activeFile: "tokens.css",
    selectedEl: null,
    selectedRegion: null,
    selectedSelector: null,
    hoverEl: null,
    saveTimer: null,
    dragging: false,
  };

  const ui = {};

  function $(sel, root = document) {
    return root.querySelector(sel);
  }

  function escapeReg(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function setStatus(text, kind = "") {
    ui.status.textContent = text;
    ui.status.className = `lvb-status${kind ? ` is-${kind}` : ""}`;
  }

  function isBuilderNode(node) {
    return !!(node && (node === ui.root || ui.root.contains(node)));
  }

  function pickEditable(target) {
    if (!(target instanceof Element) || isBuilderNode(target)) return null;
    const region = REGIONS.find((r) => target.closest(r.selector));
    if (region) {
      const el = target.closest(region.selector);
      return { el, region, selector: region.selector };
    }
    const withClass = target.closest("[class]");
    if (!withClass || isBuilderNode(withClass)) return null;
    const lv = [...withClass.classList].find((c) => c.startsWith("lv-"));
    if (!lv) return null;
    return { el: withClass, region: null, selector: `.${lv}` };
  }

  function parseClamp(value) {
    const m = String(value || "")
      .trim()
      .match(
        /^clamp\(\s*([\d.]+)(px|vh|vw|%)\s*,\s*([\d.]+)(px|vh|vw|%)\s*,\s*([\d.]+)(px|vh|vw|%)\s*\)$/i,
      );
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
      if (next.minUnit === "px" && next.min > px) {
        next.min = Math.max(def.min, Math.round(px * 0.75));
      }
      return formatClamp(next);
    }
    return `${Math.round(px)}px`;
  }

  const BEGIN = (sel) => `/* === LV-EDITOR:BEGIN ${sel} === */`;
  const END = (sel) => `/* === LV-EDITOR:END ${sel} === */`;

  function upsertOverride(css, selector, declarations) {
    const block = `${BEGIN(selector)}\n${selector} {\n${declarations}\n}\n${END(selector)}`;
    const re = new RegExp(
      `${escapeReg(BEGIN(selector))}[\\s\\S]*?${escapeReg(END(selector))}`,
    );
    if (re.test(css)) return css.replace(re, block);
    const trimmed = css.replace(/\s*$/, "");
    return `${trimmed}\n\n${block}\n`;
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

  async function loadFiles() {
    for (const name of FILES) {
      const data = await apiGet(name);
      state.files[name] = data.content;
      state.saved[name] = data.content;
      state.dirty[name] = false;
    }
    syncCodePane();
    setStatus("Gesynchroniseerd met schijf", "ok");
  }

  function markDirty(name) {
    state.dirty[name] = state.files[name] !== state.saved[name];
    const any = FILES.some((f) => state.dirty[f]);
    setStatus(any ? "Niet opgeslagen · auto-save aan" : "Gesynchroniseerd", any ? "dirty" : "ok");
    if (state.autoSave) scheduleSave();
  }

  function scheduleSave() {
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(() => {
      saveAll().catch((err) => setStatus(String(err), "dirty"));
    }, 450);
  }

  async function saveAll() {
    const dirty = FILES.filter((f) => state.dirty[f]);
    if (!dirty.length) {
      setStatus("Niets te opslaan", "ok");
      return;
    }
    setStatus("Opslaan…");
    for (const name of dirty) {
      await apiPut(name, state.files[name]);
      state.saved[name] = state.files[name];
      state.dirty[name] = false;
    }
    setStatus(`Opgeslagen · ${dirty.join(", ")}`, "ok");
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

  function syncCodePane() {
    if (!ui.codeArea) return;
    ui.codeFile.textContent = state.activeFile;
    if (document.activeElement !== ui.codeArea) {
      ui.codeArea.value = state.files[state.activeFile] || "";
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
    node.style.width = `${rect.width}px`;
    node.style.height = `${rect.height}px`;
    node.hidden = false;
    if (withHandles) {
      node.querySelectorAll(".lvb-handle").forEach((h) => h.remove());
      const dirs = state.selectedRegion
        ? state.selectedRegion.edge
          ? [state.selectedRegion.edge]
          : []
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
    if (!state.enabled) {
      ui.hover.hidden = true;
      ui.select.hidden = true;
      return;
    }
    if (state.hoverEl && state.hoverEl !== state.selectedEl) {
      placeBox(ui.hover, boxFromEl(state.hoverEl), false);
      ui.hoverLabel.textContent = labelFor(state.hoverEl);
    } else {
      ui.hover.hidden = true;
    }
    if (state.selectedEl) {
      placeBox(ui.select, boxFromEl(state.selectedEl), true);
      ui.selectLabel.textContent = state.selectedSelector || labelFor(state.selectedEl);
      renderDock();
    } else {
      ui.select.hidden = true;
    }
  }

  function labelFor(el) {
    const lv = [...el.classList].find((c) => c.startsWith("lv-"));
    return lv ? `.${lv}` : el.tagName.toLowerCase();
  }

  function selectTarget(picked) {
    state.selectedEl = picked.el;
    state.selectedRegion = picked.region;
    state.selectedSelector = picked.selector;
    if (picked.region?.varKey) state.activeFile = "tokens.css";
    else if (picked.selector?.includes("chat")) state.activeFile = "chat.css";
    else if (document.body.innerHTML.includes("lv-chat") && location.pathname.includes("chat")) {
      state.activeFile = "chat.css";
    } else {
      state.activeFile = "leviathan.css";
    }
    syncCodePane();
    refreshSelectionChrome();
  }

  function renderDock() {
    const el = state.selectedEl;
    if (!el) {
      ui.dockBody.innerHTML = `<p class="lvb-muted">Klik op de echte layout om te selecteren. Sleep de gele handles om te resizen — code schrijft automatisch mee.</p>`;
      return;
    }

    const region = state.selectedRegion;
    let html = `<h3>${state.selectedSelector || labelFor(el)}</h3>`;

    if (region?.varKey) {
      const cur = getVar(state.files["tokens.css"], region.varKey) || "80px";
      const px = Math.round(pxFromCssValue(cur, 80));
      html += `
        <div class="lvb-field">
          <label>${region.label} · <code>${region.varKey}</code> (${px}px)</label>
          <input type="range" min="${region.min}" max="${region.max}" value="${px}" data-role="region-var" />
        </div>`;
    }

    if (region?.id === "main") {
      const padX = pxFromCssValue(getVar(state.files["tokens.css"], "--lv-page-pad-x"), 10);
      const padY = pxFromCssValue(getVar(state.files["tokens.css"], "--lv-page-pad-y"), 10);
      const gap = pxFromCssValue(getVar(state.files["tokens.css"], "--lv-content-gap"), 10);
      html += `
        <div class="lvb-field"><label>Page pad X (${padX}px)</label>
          <input type="range" min="0" max="48" value="${padX}" data-role="token" data-key="--lv-page-pad-x" /></div>
        <div class="lvb-field"><label>Page pad Y (${padY}px)</label>
          <input type="range" min="0" max="48" value="${padY}" data-role="token" data-key="--lv-page-pad-y" /></div>
        <div class="lvb-field"><label>Content gap (${gap}px)</label>
          <input type="range" min="0" max="40" value="${gap}" data-role="token" data-key="--lv-content-gap" /></div>`;
    }

    const file = state.activeFile === "tokens.css" ? "leviathan.css" : state.activeFile;
    const decls = readOverrideDecls(state.files[file] || "", state.selectedSelector);
    html += `<p class="lvb-muted">Element styles → ${file}</p><div class="lvb-row">`;
    for (const prop of EDITABLE_PROPS) {
      const val = decls[prop.key] || "";
      html += `<div class="lvb-field"><label>${prop.label}</label>
        <input type="text" data-role="decl" data-prop="${prop.key}" value="${val.replace(/"/g, "&quot;")}" placeholder="bijv. 16px" /></div>`;
    }
    html += `</div>`;
    ui.dockBody.innerHTML = html;
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
    renderDock();
  }

  function updateTokenKey(key, px, min = 0, max = 200) {
    const cur = getVar(state.files["tokens.css"], key) || `${px}px`;
    const next = cssFromPx(cur, Math.round(px), { min, max });
    state.files["tokens.css"] = setVar(state.files["tokens.css"], key, next);
    state.activeFile = "tokens.css";
    markDirty("tokens.css");
    applyTokensLive();
    syncCodePane();
  }

  function updateDecl(prop, value) {
    const selector = state.selectedSelector;
    if (!selector) return;
    const file =
      state.activeFile === "tokens.css"
        ? "leviathan.css"
        : state.activeFile;
    const decls = readOverrideDecls(state.files[file], selector);
    if (!value.trim()) delete decls[prop];
    else decls[prop] = value.trim();
    state.files[file] = upsertOverride(state.files[file], selector, declsToText(decls));
    state.activeFile = file;
    markDirty(file);
    applyTokensLive();
    syncCodePane();
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

      // Generic element: write width/height/min-height override
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
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function buildUI() {
    const root = document.createElement("div");
    root.id = "lvb-root";
    root.innerHTML = `
      <div class="lvb-bar">
        <div class="lvb-brand">Layout Builder</div>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn" data-nav="/">Command</button>
        <button type="button" class="lvb-btn" data-nav="/chat">Chat</button>
        <button type="button" class="lvb-btn" data-nav="/status">Status</button>
        <button type="button" class="lvb-btn" data-nav="/settings">Settings</button>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn is-on" data-act="toggle-edit">Edit aan</button>
        <button type="button" class="lvb-btn is-on" data-act="toggle-dock">Panel</button>
        <button type="button" class="lvb-btn is-on" data-act="toggle-code">Code</button>
        <button type="button" class="lvb-btn" data-act="reload">Herladen</button>
        <button type="button" class="lvb-btn lvb-btn-primary" data-act="save">Opslaan</button>
        <div class="lvb-sep"></div>
        <span class="lvb-status" data-role="status">Start…</span>
      </div>
      <div class="lvb-dock is-open" data-role="dock">
        <div data-role="dock-body"></div>
        <div class="lvb-chip-row" data-role="files"></div>
      </div>
      <div class="lvb-code is-open" data-role="code">
        <div class="lvb-code-head">
          <span data-role="code-file">tokens.css</span>
          <span>Live ↔ echte bestanden in Data/frontend/src/styles</span>
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

    ui.files.innerHTML = FILES.map(
      (f) => `<button type="button" class="lvb-chip${f === state.activeFile ? " is-on" : ""}" data-file="${f}">${f}</button>`,
    ).join("");

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
      if (act === "reload") loadFiles().then(applyTokensLive).catch((e) => setStatus(String(e), "dirty"));
    });

    ui.files.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-file]");
      if (!chip) return;
      state.activeFile = chip.dataset.file;
      ui.files.querySelectorAll(".lvb-chip").forEach((c) => c.classList.toggle("is-on", c === chip));
      syncCodePane();
    });

    ui.dock.addEventListener("input", (event) => {
      const t = event.target;
      if (!(t instanceof HTMLInputElement)) return;
      if (t.dataset.role === "region-var" && state.selectedRegion?.varKey) {
        updateRegionVar(state.selectedRegion, Number(t.value));
      }
      if (t.dataset.role === "token") {
        updateTokenKey(t.dataset.key, Number(t.value));
      }
      if (t.dataset.role === "decl") {
        updateDecl(t.dataset.prop, t.value);
      }
    });

    ui.codeArea.addEventListener("input", () => {
      const name = state.activeFile;
      state.files[name] = ui.codeArea.value;
      markDirty(name);
      applyTokensLive();
    });

    ui.select.addEventListener("pointerdown", onPointerDownHandle);

    document.addEventListener(
      "mousemove",
      (event) => {
        if (!state.enabled || state.dragging) return;
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
        if (!state.enabled) return;
        if (isBuilderNode(event.target)) return;
        const picked = pickEditable(event.target);
        if (!picked) return;
        event.preventDefault();
        event.stopPropagation();
        selectTarget(picked);
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
      if (event.key === "Escape") {
        state.selectedEl = null;
        state.selectedRegion = null;
        state.selectedSelector = null;
        refreshSelectionChrome();
        renderDock();
      }
    });
  }

  async function boot() {
    buildUI();
    bind();
    try {
      await loadFiles();
      applyTokensLive();
      setStatus("Klik op de layout om te bewerken", "ok");
    } catch (err) {
      setStatus(`API offline? Start EDIT_LAYOUT.bat — ${err}`, "dirty");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
