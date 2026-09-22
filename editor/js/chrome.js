/**
 * Leviathan Visual Builder — docks, tabs, floats, selection chrome.
 * Paint is delegated to ctx.renderer (WebGPU scene-graph or DOM fallback).
 */

import { BREAKPOINTS, LAYOUT_STORAGE_KEY } from "./constants.js";
import { EDITOR_PAGES } from "./pages.js";

const LAYOUT_KEY = LAYOUT_STORAGE_KEY;

export function createChrome(ctx, panels) {
  const panelMap = new Map(panels.map((panel) => [panel.id, panel]));
  const ui = {};
  let paintRaf = 0;
  let root;

  function $(sel, scope = root) {
    return scope.querySelector(sel);
  }

  function build() {
    root = document.createElement("div");
    root.id = "lvb-root";
    root.innerHTML = shellHtml();
    document.documentElement.appendChild(root);
    ui.root = root;
    ui.status = $("[data-role='status']");
    ui.zoom = $("[data-role='zoom']");
    ui.toolLabel = $("[data-role='tool-label']");
    ui.left = $("[data-role='dock-left']");
    ui.right = $("[data-role='dock-right']");
    ui.leftBody = $("[data-role='left-body']");
    ui.rightBody = $("[data-role='right-body']");
    ui.code = $("[data-role='code']");
    ui.codeBody = $("[data-role='code-body']");
    ui.tabs = $("[data-role='tabs']");
    ui.hover = $(".lvb-hover");
    ui.hoverLabel = $("[data-role='hover-label']");
    ui.select = $(".lvb-select");
    ui.selectLabel = $("[data-role='select-label']");
    ui.multis = $("[data-role='multis']");
    ui.guides = $("[data-role='guides']");
    ui.marquee = $("[data-role='marquee']");
    ui.drop = $("[data-role='drop']");
    ui.measure = $("[data-role='measure']");
    ui.menu = $("[data-role='menu']");
    ui.media = $("[data-role='media']");
    ui.grid = $("[data-role='grid']");
    ui.pixel = $("[data-role='pixel-grid']");
    ui.columns = $("[data-role='column-grid']");
    ui.file = $("[data-role='file']");
    ui.palette = $("[data-role='palette']");
    ui.pageSwitch = $("[data-role='page-switch']");

    for (const panel of panels) {
      if (panel.zone === "modal") {
        panel.host = ui.media;
        panel.bind?.(ui.media);
        safeRender(panel);
        continue;
      }
      const host = document.createElement("div");
      host.className = "lvb-panel-host";
      host.dataset.host = panel.id;
      const zone = panel.zone === "left" ? ui.leftBody : panel.zone === "bottom" ? ui.codeBody : ui.rightBody;
      zone.appendChild(host);
      panel.host = host;
      panel.place = "dock";
      panel.bind?.(host);
    }
    ui.columns.innerHTML = Array.from({ length: 12 }, () => "<i></i>").join("");
    document.body.classList.add("lvb-editing", "lvb-tool-select");
    restoreLayout();
    wire();
    syncChrome();
    invalidateAll();
    ctx.renderer?.init?.(root)?.then?.(() => schedulePaint());
  }

  function shellHtml() {
    return `<div class="lvb-bar">
        <div class="lvb-brand">Leviathan</div>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn" data-nav="/">Command</button>
        <button type="button" class="lvb-btn" data-nav="/chat">Chat</button>
        <button type="button" class="lvb-btn" data-nav="/research">Research</button>
        <button type="button" class="lvb-btn" data-nav="/settings">Settings</button>
        <div class="lvb-sep"></div>
        <label class="lvb-page-switch" title="Leviathan pagina">
          <span>Pagina</span>
          <select data-role="page-switch">
            ${EDITOR_PAGES.map((p) => `<option value="${p.path}">${p.label}</option>`).join("")}
          </select>
        </label>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn" data-insert="text" title="Tekst">+T</button>
        <button type="button" class="lvb-btn" data-act="add-image" title="Image">+Img</button>
        <button type="button" class="lvb-btn" data-insert="box" title="Box">+Box</button>
        <button type="button" class="lvb-btn" data-insert="button" title="Knop">+Btn</button>
        <div class="lvb-sep"></div>
        <div class="lvb-seg" data-role="breakpoints">
          ${Object.values(BREAKPOINTS)
            .map((bp) => `<button type="button" class="lvb-mini" data-bp="${bp.id}">${bp.label}</button>`)
            .join("")}
        </div>
        <div class="lvb-sep"></div>
        <button type="button" class="lvb-btn is-on" data-act="toggle-edit">Edit aan</button>
        <button type="button" class="lvb-btn" data-act="undo">Undo</button>
        <button type="button" class="lvb-btn" data-act="redo">Redo</button>
        <button type="button" class="lvb-btn" data-act="reload">Herladen</button>
        <button type="button" class="lvb-btn" data-act="palette">⌘K</button>
        <button type="button" class="lvb-btn lvb-btn-primary" data-act="save">Opslaan</button>
      </div>
      <div class="lvb-rail">
        <button type="button" class="lvb-tool is-on" data-tool="select" title="Selecteren (V)">V</button>
        <button type="button" class="lvb-tool" data-tool="hand" title="Hand (H)">H</button>
        <button type="button" class="lvb-tool" data-tool="rotate" title="Roteren (R)">R</button>
        <button type="button" class="lvb-tool" data-tool="measure" title="Meten (M)">M</button>
      </div>
      <aside class="lvb-dock lvb-dock-left is-open" data-role="dock-left">
        <div class="lvb-dock-resizer" data-resize="left"></div>
        <div class="lvb-dock-body" data-role="left-body"></div>
      </aside>
      <aside class="lvb-dock lvb-dock-right is-open" data-role="dock-right">
        <div class="lvb-dock-resizer" data-resize="right"></div>
        <div class="lvb-dock-head">
          <div class="lvb-tabs" data-role="tabs"></div>
          <button type="button" class="lvb-mini" data-act="float-tab" title="Zweven">↗</button>
        </div>
        <div class="lvb-dock-body" data-role="right-body"></div>
      </aside>
      <section class="lvb-code" data-role="code" hidden>
        <div data-role="code-body"></div>
      </section>
      <div class="lvb-statusbar">
        <button type="button" class="lvb-mini" data-act="zoom-out">−</button>
        <button type="button" class="lvb-zoom" data-role="zoom" data-act="zoom-reset">100%</button>
        <button type="button" class="lvb-mini" data-act="zoom-in">+</button>
        <span data-role="tool-label">Selecteren</span>
        <button type="button" class="lvb-mini" data-act="toggle-snap">Snap</button>
        <button type="button" class="lvb-mini" data-act="toggle-grid">Grid</button>
        <button type="button" class="lvb-mini" data-act="toggle-columns">Kolommen</button>
        <button type="button" class="lvb-mini" data-act="toggle-layers">Lagen</button>
        <button type="button" class="lvb-mini" data-act="toggle-dock">Inspector</button>
        <button type="button" class="lvb-mini" data-act="toggle-code">Code</button>
        <span class="lvb-status" data-role="status">Start…</span>
      </div>
      <div class="lvb-canvas-grid" data-role="grid" hidden>
        <div class="lvb-pixel-grid" data-role="pixel-grid" hidden></div>
        <div class="lvb-columns" data-role="column-grid" hidden></div>
      </div>
      <div class="lvb-guides" data-role="guides"></div>
      <div class="lvb-marquee" data-role="marquee" hidden></div>
      <div class="lvb-drop" data-role="drop" hidden></div>
      <svg class="lvb-measure" data-role="measure" hidden></svg>
      <div class="lvb-multis" data-role="multis"></div>
      <div class="lvb-hover" hidden><div class="lvb-label" data-role="hover-label"></div></div>
      <div class="lvb-select" hidden><div class="lvb-label" data-role="select-label"></div></div>
      <div class="lvb-menu" data-role="menu" hidden></div>
      <div class="lvb-media" data-role="media" hidden></div>
      <div class="lvb-palette" data-role="palette" hidden></div>
      <input type="file" accept="image/*" data-role="file" hidden />`;
  }

  function rightTabs() {
    return panels.filter((panel) => panel.zone === "right");
  }

  function syncChrome() {
    const s = ctx.store.getState();
    ui.left.hidden = !s.showLeft;
    ui.right.hidden = !s.showRight;
    ui.code.hidden = !s.showCode;
    ui.left.style.width = `${s.leftW || 260}px`;
    ui.right.style.width = `${s.rightW || 320}px`;
    ui.zoom.textContent = `${Math.round((s.zoom || 1) * 100)}%`;
    const tools = { select: "Selecteren", hand: "Hand", rotate: "Roteren", measure: "Meten" };
    ui.toolLabel.textContent = tools[s.tool] || "Selecteren";
    const primary = ctx.session.primary;
    const count = ctx.session.selected.length;
    let selInfo = "";
    if (primary?.isConnected) {
      const r = primary.getBoundingClientRect();
      const z = s.zoom || 1;
      const w = Math.round(r.width / z);
      const h = Math.round(r.height / z);
      selInfo = count > 1 ? `${count} geselecteerd · ${w}×${h}` : `${w}×${h}`;
    }
    const dirty = s.contentDirty || Object.values(s.dirtyFiles || {}).some(Boolean);
    const base = s.status || "";
    ui.status.textContent = [selInfo, dirty ? "● niet opgeslagen" : "", base].filter(Boolean).join(" · ");
    ui.status.className = `lvb-status${s.statusKind ? ` is-${s.statusKind}` : ""}${dirty ? " is-dirty" : ""}`;
    root.querySelectorAll("[data-tool]").forEach((btn) => btn.classList.toggle("is-on", btn.dataset.tool === s.tool));
    root.querySelectorAll("[data-bp]").forEach((btn) => btn.classList.toggle("is-on", btn.dataset.bp === s.breakpoint));
    root.querySelector("[data-act='toggle-snap']")?.classList.toggle("is-on", s.snap);
    root.querySelector("[data-act='toggle-grid']")?.classList.toggle("is-on", s.showGrid);
    root.querySelector("[data-act='toggle-columns']")?.classList.toggle("is-on", s.showColumns);
    root.querySelector("[data-act='toggle-layers']")?.classList.toggle("is-on", s.showLeft);
    root.querySelector("[data-act='toggle-dock']")?.classList.toggle("is-on", s.showRight);
    root.querySelector("[data-act='toggle-code']")?.classList.toggle("is-on", s.showCode);
    document.body.classList.toggle("lvb-editing", s.enabled !== false);
    document.body.classList.remove("lvb-tool-select", "lvb-tool-hand", "lvb-tool-rotate", "lvb-tool-measure");
    document.body.classList.add(`lvb-tool-${s.tool || "select"}`);
    if (ui.pageSwitch) {
      const path = ctx.pages?.currentPage?.() || s.page || location.pathname || "/";
      const key = String(path).replace(/\/$/, "") || "/";
      if (ui.pageSwitch.value !== key && [...ui.pageSwitch.options].some((o) => o.value === key || o.value === path)) {
        ui.pageSwitch.value = [...ui.pageSwitch.options].find((o) => o.value === key || o.value === path)?.value || key;
      }
    }
    placeFrame();
    ui.tabs.innerHTML = rightTabs()
      .map((panel) => `<button type="button" class="lvb-tab${s.rightTab === panel.id ? " is-on" : ""}" data-tab="${panel.id}">${panel.title}</button>`)
      .join("");
    for (const panel of panels) {
      if (!panel.host || panel.zone === "modal") continue;
      if (panel.place === "float") continue;
      if (panel.zone === "right") panel.host.hidden = s.rightTab !== panel.id;
      else panel.host.hidden = false;
    }
  }

  function visible(panel) {
    const s = ctx.store.getState();
    if (panel.place === "float") return true;
    if (panel.zone === "left") return !!s.showLeft;
    if (panel.zone === "bottom") return !!s.showCode;
    if (panel.zone === "modal") return false;
    return !!s.showRight && s.rightTab === panel.id;
  }

  function safeRender(panel) {
    try {
      panel.render?.();
    } catch (err) {
      const message = err?.message || String(err);
      ctx.content.setStatus(`${panel.title || panel.id}: ${message}`, "dirty");
    }
  }

  function invalidate(id) {
    const panel = panelMap.get(id);
    if (!panel || !visible(panel)) return;
    const sig = panel.signature?.() ?? "";
    if (sig === panel._sig) return;
    panel._sig = sig;
    safeRender(panel);
  }

  function invalidateAll() {
    for (const id of panelMap.keys()) invalidate(id);
  }

  function schedulePaint() {
    if (paintRaf) return;
    paintRaf = requestAnimationFrame(() => {
      paintRaf = 0;
      ctx.renderer?.paint?.(ui);
    });
  }

  /** Session mirrors consumed by renderer (GPU or DOM). */
  function setGuides(snap) {
    ctx.session._snapGuides = snap || null;
    schedulePaint();
  }

  function clearGuides() {
    ctx.session._snapGuides = null;
    ctx.session.dropEl = null;
    if (ui.guides) ui.guides.innerHTML = "";
    if (ui.drop) ui.drop.hidden = true;
    schedulePaint();
  }

  function showMarquee(rect) {
    ctx.session._marquee = rect || null;
    schedulePaint();
  }

  function showDrop(el) {
    ctx.session.dropEl = el || null;
    schedulePaint();
  }

  function syncCamera() {
    const page = document.getElementById("root");
    const s = ctx.store.getState();
    if (!page) return;
    const rect = page.getBoundingClientRect();
    ui.grid.style.left = `${rect.left - s.panX}px`;
    ui.grid.style.top = `${rect.top - s.panY}px`;
    ui.grid.style.width = `${page.offsetWidth}px`;
    ui.grid.style.height = `${Math.max(page.offsetHeight, 400)}px`;
    ui.grid.style.transform = `translate(${s.panX}px, ${s.panY}px) scale(${s.zoom || 1})`;
    ui.grid.hidden = !s.showGrid && !s.showColumns;
    ui.pixel.hidden = !s.showGrid;
    ui.columns.hidden = !s.showColumns;
  }

  function showMenu(x, y, items) {
    ui.menu.innerHTML = items
      .map((item) => {
        if (item.sep) return `<div class="lvb-menu-sep"></div>`;
        return `<button type="button" class="lvb-menu-item${item.disabled ? " is-disabled" : ""}" data-menu-id="${item.id || ""}" ${item.disabled ? "disabled" : ""}>
          <span>${item.label}</span>${item.kbd ? `<kbd>${item.kbd}</kbd>` : ""}
        </button>`;
      })
      .join("");
    ui.menu.hidden = false;
    ui.menu._items = items.filter((item) => !item.sep);
    const mw = ui.menu.offsetWidth;
    const mh = ui.menu.offsetHeight;
    ui.menu.style.left = `${Math.min(x, window.innerWidth - mw - 8)}px`;
    ui.menu.style.top = `${Math.min(y, window.innerHeight - mh - 8)}px`;
  }

  function hideMenu() {
    if (ui.menu) ui.menu.hidden = true;
  }

  function openMedia(mode) {
    panelMap.get("media")?.open?.(mode);
  }

  function pickUpload(mode) {
    ctx.session.imageMode = mode;
    ui.file.value = "";
    ui.file.click();
  }

  function floatTab() {
    const id = ctx.store.getState().rightTab;
    const panel = panelMap.get(id);
    if (!panel || panel.place === "float") return;
    const win = document.createElement("div");
    win.className = "lvb-float";
    win.dataset.panel = id;
    win.style.left = "96px";
    win.style.top = "96px";
    win.innerHTML = `<div class="lvb-float-head"><span>${panel.title}</span><button type="button" data-redock>Dock</button></div><div class="lvb-float-body"></div>`;
    root.appendChild(win);
    const body = win.querySelector(".lvb-float-body");
    body.appendChild(panel.host);
    panel.host.hidden = false;
    panel.place = "float";
    panel._sig = null;
    safeRender(panel);
    const head = win.querySelector(".lvb-float-head");
    head.addEventListener("pointerdown", (event) => {
      if (event.target.closest("[data-redock]")) return;
      const startX = event.clientX;
      const startY = event.clientY;
      const left = parseFloat(win.style.left) || 0;
      const top = parseFloat(win.style.top) || 0;
      const move = (ev) => {
        win.style.left = `${left + ev.clientX - startX}px`;
        win.style.top = `${top + ev.clientY - startY}px`;
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        saveLayout();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
    win.querySelector("[data-redock]").addEventListener("click", () => {
      panel.place = "dock";
      ui.rightBody.appendChild(panel.host);
      win.remove();
      ctx.store.setState({ rightTab: id, showRight: true });
      panel._sig = null;
      saveLayout();
    });
    saveLayout();
  }

  function applyPreset(name) {
    if (name === "focus") ctx.store.setState({ showLeft: false, showRight: false, showCode: false });
    if (name === "studio") ctx.store.setState({ showLeft: true, showRight: true, showCode: false, rightTab: "inspector" });
    if (name === "code") ctx.store.setState({ showLeft: true, showRight: true, showCode: true, rightTab: "code" });
    if (name === "full") ctx.store.setState({ showLeft: true, showRight: true, showCode: true, rightTab: "inspector", leftW: 280, rightW: 360 });
    saveLayout();
    const labels = { focus: "Focus", code: "Code-layout", full: "Volledig", studio: "Studio-layout" };
    ctx.content.setStatus(labels[name] || "Studio-layout", "ok");
  }

  function saveLayout() {
    const s = ctx.store.getState();
    const floats = [...root.querySelectorAll(".lvb-float")].map((el) => ({
      id: el.dataset.panel,
      x: parseFloat(el.style.left) || 80,
      y: parseFloat(el.style.top) || 80,
      w: parseFloat(el.style.width) || 0,
    }));
    try {
      localStorage.setItem(
        LAYOUT_KEY,
        JSON.stringify({
          showLeft: s.showLeft,
          showRight: s.showRight,
          showCode: s.showCode,
          rightTab: s.rightTab,
          leftW: s.leftW,
          rightW: s.rightW,
          floats,
        }),
      );
    } catch {
      /* ignore quota */
    }
  }

  function restoreLayout() {
    try {
      const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "null");
      if (!saved) return;
      ctx.store.setState({
        showLeft: saved.showLeft !== false,
        showRight: saved.showRight !== false,
        showCode: !!saved.showCode,
        rightTab: saved.rightTab || "inspector",
        leftW: saved.leftW || 260,
        rightW: saved.rightW || 320,
      });
      // Rehydrate floats after panels are mounted
      queueMicrotask(() => {
        for (const f of saved.floats || []) {
          if (!f?.id || !panelMap.get(f.id)) continue;
          const was = ctx.store.getState().rightTab;
          ctx.store.setState({ rightTab: f.id });
          floatTab();
          const win = root.querySelector(`.lvb-float[data-panel="${f.id}"]`);
          if (win) {
            win.style.left = `${f.x || 96}px`;
            win.style.top = `${f.y || 96}px`;
            if (f.w) win.style.width = `${f.w}px`;
          }
          ctx.store.setState({ rightTab: was });
        }
      });
    } catch {
      /* ignore broken layout */
    }
  }

  function placeFrame() {
    const bar = root.querySelector(".lvb-bar");
    const rail = root.querySelector(".lvb-rail");
    if (!bar) return;
    const top = bar.offsetHeight + 8;
    const maxH = `calc(100vh - ${top + 56}px)`;
    ui.left.style.top = `${top}px`;
    ui.right.style.top = `${top}px`;
    ui.left.style.maxHeight = maxH;
    ui.right.style.maxHeight = maxH;
    if (rail) rail.style.top = `${top}px`;
  }

  function wire() {
    window.addEventListener("resize", placeFrame);
    ui.pageSwitch?.addEventListener("change", () => {
      const path = ui.pageSwitch.value;
      if (path) ctx.pages?.go?.(path);
    });
    root.addEventListener("click", (event) => {
      const nav = event.target.closest("[data-nav]");
      if (nav) {
        event.preventDefault();
        ctx.pages?.go?.(nav.dataset.nav) || window.location.assign(nav.dataset.nav);
        return;
      }
      const tab = event.target.closest("[data-tab]");
      if (tab) {
        ctx.store.setState({ rightTab: tab.dataset.tab, showRight: true });
        const panel = panelMap.get(tab.dataset.tab);
        if (panel) panel._sig = null;
        saveLayout();
        return;
      }
      const tool = event.target.closest("[data-tool]");
      if (tool) {
        ctx.store.setState({ tool: tool.dataset.tool });
        return;
      }
      const bp = event.target.closest("[data-bp]");
      if (bp) {
        ctx.camera.setBreakpoint(bp.dataset.bp);
        saveLayout();
        return;
      }
      const insert = event.target.closest("[data-insert]");
      if (insert && !event.target.closest(".lvb-panel-host")) ctx.widgets.insertPreset(insert.dataset.insert);
      const menuBtn = event.target.closest("[data-menu-id]");
      if (menuBtn) {
        const item = (ui.menu._items || []).find((entry) => entry.id === menuBtn.dataset.menuId);
        hideMenu();
        item?.run?.();
        return;
      }
      const act = event.target.closest("[data-act]")?.dataset.act;
      if (!act || event.target.closest(".lvb-panel-host") || event.target.closest(".lvb-media")) return;
      if (act === "toggle-edit") {
        const next = ctx.store.getState().enabled === false;
        ctx.store.setState({ enabled: next });
        const btn = event.target.closest("[data-act='toggle-edit']");
        if (btn) btn.textContent = next ? "Edit aan" : "Edit uit";
        document.body.classList.toggle("lvb-editing", next);
      }
      if (act === "undo") ctx.commands.undo();
      if (act === "reload") ctx.content.loadAll().catch((err) => ctx.content.setStatus(String(err.message || err), "dirty"));
      if (act === "redo") ctx.commands.redo();
      if (act === "save") ctx.content.saveAll().catch((err) => ctx.content.setStatus(String(err.message || err), "dirty"));
      if (act === "palette") ctx.palette.toggle();
      if (act === "add-image") openMedia("insert");
      if (act === "float-tab") floatTab();
      if (act === "zoom-in") ctx.camera.zoomAt(window.innerWidth / 2, window.innerHeight / 2, ctx.store.getState().zoom * 1.1);
      if (act === "zoom-out") ctx.camera.zoomAt(window.innerWidth / 2, window.innerHeight / 2, ctx.store.getState().zoom / 1.1);
      if (act === "zoom-reset") ctx.camera.reset();
      if (act === "toggle-snap") {
        ctx.store.setState({ snap: !ctx.store.getState().snap });
        ctx.content.setStatus(ctx.store.getState().snap ? "Snap aan" : "Snap uit", "ok");
      }
      if (act === "toggle-grid") ctx.store.setState({ showGrid: !ctx.store.getState().showGrid });
      if (act === "toggle-columns") ctx.store.setState({ showColumns: !ctx.store.getState().showColumns });
      if (act === "toggle-layers") {
        ctx.store.setState({ showLeft: !ctx.store.getState().showLeft });
        saveLayout();
      }
      if (act === "toggle-dock") {
        ctx.store.setState({ showRight: !ctx.store.getState().showRight });
        saveLayout();
      }
      if (act === "toggle-code") {
        ctx.store.setState({ showCode: !ctx.store.getState().showCode });
        saveLayout();
      }
    });

    ui.file.addEventListener("change", () => {
      const file = ui.file.files?.[0];
      if (!file) return;
      ctx.widgets.uploadFile(file, ctx.session.imageMode || "insert").catch((err) => ctx.content.setStatus(String(err.message || err), "dirty"));
      ui.file.value = "";
    });

    root.addEventListener("pointerdown", (event) => {
      const handle = event.target.closest("[data-resize]");
      if (!handle) return;
      event.preventDefault();
      const side = handle.dataset.resize;
      const start = event.clientX;
      const initial = side === "left" ? ctx.store.getState().leftW || 260 : ctx.store.getState().rightW || 320;
      const move = (ev) => {
        const delta = side === "left" ? ev.clientX - start : start - ev.clientX;
        const width = Math.min(520, Math.max(220, initial + delta));
        ctx.store.setState(side === "left" ? { leftW: width } : { rightW: width });
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        saveLayout();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });

    ctx.store.subscribe(() => {
      syncChrome();
      syncCamera();
      invalidateAll();
    });
    window.addEventListener("resize", () => {
      ctx.renderer?.resize?.();
      syncCamera();
      schedulePaint();
    });
    window.addEventListener("scroll", () => schedulePaint(), true);
  }

  return {
    build,
    ui: () => ui,
    invalidate,
    invalidateAll,
    schedulePaint,
    setGuides,
    clearGuides,
    showMarquee,
    showDrop,
    showMenu,
    hideMenu,
    openMedia,
    pickUpload,
    applyPreset,
    syncCamera,
    saveLayout,
    selectBox: () => ui.select,
  };
}
