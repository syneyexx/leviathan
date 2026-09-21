/**
 * Leviathan Visual Builder — docks, tabs, floats, selection chrome.
 */

import { BREAKPOINTS } from "./constants.js";

const LAYOUT_KEY = "lvb.dock.v1";

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
    ui.status.textContent = s.status || "";
    ui.status.className = `lvb-status${s.statusKind ? ` is-${s.statusKind}` : ""}`;
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
      paintSelection();
      paintMeasure();
    });
  }

  function placeBox(node, rect) {
    node.style.left = `${rect.left}px`;
    node.style.top = `${rect.top}px`;
    node.style.width = `${Math.max(rect.width, 8)}px`;
    node.style.height = `${Math.max(rect.height, 8)}px`;
    node.hidden = false;
  }

  function paintSelection() {
    const s = ctx.store.getState();
    if (!s.enabled || ctx.session.inlineEl) {
      ui.hover.hidden = true;
      ui.select.hidden = true;
      ui.multis.innerHTML = "";
      return;
    }
    const hover = ctx.session.hoverEl;
    if (hover && hover !== ctx.session.primary && !ctx.session.selected.includes(hover)) {
      placeBox(ui.hover, hover.getBoundingClientRect());
      ui.hoverLabel.textContent = ctx.selection.labelFor(hover);
    } else ui.hover.hidden = true;

    ui.multis.innerHTML = ctx.session.selected
      .filter((el) => el !== ctx.session.primary && el.isConnected)
      .map((el) => {
        const r = el.getBoundingClientRect();
        return `<div class="lvb-multi" style="left:${r.left}px;top:${r.top}px;width:${Math.max(r.width, 4)}px;height:${Math.max(r.height, 4)}px"></div>`;
      })
      .join("");

    const el = ctx.session.primary;
    if (!el || !el.isConnected) {
      ui.select.hidden = true;
      return;
    }
    const rect = el.getBoundingClientRect();
    placeBox(ui.select, rect);
    ui.select.querySelectorAll(".lvb-handle, .lvb-rotate").forEach((n) => n.remove());
    const region = ctx.selection.regionFor(el);
    const dirs = region?.edge ? [region.edge] : ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
    if (!ctx.selection.isLocked(el)) {
      for (const dir of dirs) {
        const handle = document.createElement("div");
        handle.className = "lvb-handle";
        handle.dataset.dir = dir;
        ui.select.appendChild(handle);
      }
    }
    const count = ctx.session.selected.length;
    const lock = ctx.selection.isLocked(el) ? " 🔒" : "";
    ui.selectLabel.textContent = `${ctx.selection.selectorFor(el)}${lock}${count > 1 ? ` +${count - 1}` : ""}`;
    if (rect.top < 28) ui.selectLabel.style.top = "2px";
    else ui.selectLabel.style.top = "-22px";
  }

  function paintMeasure() {
    const m = ctx.session.measure;
    if (!m?.a) {
      ui.measure.hidden = true;
      return;
    }
    const a = ctx.camera.localToScreen(m.a.x, m.a.y);
    const b = m.b ? ctx.camera.localToScreen(m.b.x, m.b.y) : null;
    ui.measure.hidden = false;
    ui.measure.setAttribute("width", String(window.innerWidth));
    ui.measure.setAttribute("height", String(window.innerHeight));
    if (!b) {
      ui.measure.innerHTML = `<circle cx="${a.x}" cy="${a.y}" r="4" />`;
      return;
    }
    const dx = Math.round((m.b.x - m.a.x));
    const dy = Math.round((m.b.y - m.a.y));
    const dist = Math.round(Math.hypot(dx, dy));
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    ui.measure.innerHTML = `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />
      <circle cx="${a.x}" cy="${a.y}" r="3.5" /><circle cx="${b.x}" cy="${b.y}" r="3.5" />
      <text x="${mx + 8}" y="${my - 8}">${dist}px  Δ${dx},${dy}</text>`;
  }

  function setGuides(snap) {
    const lines = [];
    if (snap?.lineX != null) lines.push(`<div class="lvb-guide is-x is-${snap.kindX || "edge"}" style="left:${snap.lineX}px"></div>`);
    if (snap?.lineY != null) lines.push(`<div class="lvb-guide is-y is-${snap.kindY || "edge"}" style="top:${snap.lineY}px"></div>`);
    ui.guides.innerHTML = lines.join("");
  }

  function clearGuides() {
    ui.guides.innerHTML = "";
    ui.drop.hidden = true;
  }

  function showMarquee(rect) {
    if (!rect) {
      ui.marquee.hidden = true;
      return;
    }
    ui.marquee.hidden = false;
    ui.marquee.style.left = `${rect.left}px`;
    ui.marquee.style.top = `${rect.top}px`;
    ui.marquee.style.width = `${rect.width}px`;
    ui.marquee.style.height = `${rect.height}px`;
  }

  function showDrop(el) {
    if (!el) {
      ui.drop.hidden = true;
      ctx.session.dropEl = null;
      return;
    }
    ctx.session.dropEl = el;
    const r = el.getBoundingClientRect();
    ui.drop.hidden = false;
    ui.drop.style.left = `${r.left}px`;
    ui.drop.style.top = `${r.top}px`;
    ui.drop.style.width = `${r.width}px`;
    ui.drop.style.height = `${r.height}px`;
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
    if (name === "code") ctx.store.setState({ showLeft: true, showRight: true, showCode: true, rightTab: "inspector" });
    saveLayout();
    ctx.content.setStatus(name === "focus" ? "Focus" : name === "code" ? "Code-layout" : "Studio-layout", "ok");
  }

  function saveLayout() {
    const s = ctx.store.getState();
    const floats = [...root.querySelectorAll(".lvb-float")].map((el) => ({
      id: el.dataset.panel,
      x: parseFloat(el.style.left) || 80,
      y: parseFloat(el.style.top) || 80,
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
    root.addEventListener("click", (event) => {
      const nav = event.target.closest("[data-nav]");
      if (nav) {
        window.location.assign(nav.dataset.nav);
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
