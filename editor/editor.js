(() => {
  const FILES = ["tokens.css", "leviathan.css", "pages.css", "chat.css"];

  const LAYOUT_VARS = [
    {
      key: "--lv-header-height",
      label: "Header hoogte",
      region: "header",
      axis: "y",
      min: 40,
      max: 160,
    },
    {
      key: "--lv-sidebar-width",
      label: "Sidebar breedte",
      region: "sidebar",
      axis: "x",
      min: 100,
      max: 320,
    },
    {
      key: "--lv-right-panel-width",
      label: "Rechter paneel",
      region: "right",
      axis: "x",
      min: 120,
      max: 400,
    },
    {
      key: "--lv-footer-height",
      label: "Footer hoogte",
      region: "footer",
      axis: "y",
      min: 40,
      max: 120,
    },
    {
      key: "--lv-content-gap",
      label: "Content gap",
      region: "content",
      axis: "n",
      min: 0,
      max: 40,
    },
    {
      key: "--lv-card-gap",
      label: "Card gap",
      region: "content",
      axis: "n",
      min: 0,
      max: 40,
    },
    {
      key: "--lv-page-pad-x",
      label: "Page pad X",
      region: "content",
      axis: "n",
      min: 0,
      max: 48,
    },
    {
      key: "--lv-page-pad-y",
      label: "Page pad Y",
      region: "content",
      axis: "n",
      min: 0,
      max: 48,
    },
  ];

  const state = {
    activeFile: "tokens.css",
    files: Object.fromEntries(FILES.map((name) => [name, ""])),
    saved: Object.fromEntries(FILES.map((name) => [name, ""])),
    dirty: Object.fromEntries(FILES.map((name) => [name, false])),
    previewReady: false,
    selectedRegion: null,
    regions: {},
    autoSaveTimer: null,
  };

  const els = {
    tabs: document.getElementById("fileTabs"),
    code: document.getElementById("code"),
    codeFileLabel: document.getElementById("codeFileLabel"),
    dirtyBadge: document.getElementById("dirtyBadge"),
    status: document.getElementById("statusText"),
    controls: document.getElementById("layoutControls"),
    preview: document.getElementById("preview"),
    previewFrame: document.getElementById("previewFrame"),
    guides: document.getElementById("guides"),
    btnSave: document.getElementById("btnSave"),
    btnReload: document.getElementById("btnReload"),
    autoSave: document.getElementById("autoSave"),
    showGuides: document.getElementById("showGuides"),
  };

  function setStatus(text, kind = "") {
    els.status.textContent = text;
    els.status.className = `ed-status${kind ? ` is-${kind}` : ""}`;
  }

  function updateDirtyUI() {
    const dirty = state.dirty[state.activeFile];
    els.dirtyBadge.hidden = !dirty;
    setStatus(
      dirty ? `${state.activeFile} · niet opgeslagen` : `${state.activeFile} · synchroon`,
      dirty ? "dirty" : "ok",
    );
  }

  function postPreview(payload) {
    if (!els.preview.contentWindow) return;
    els.preview.contentWindow.postMessage(payload, "*");
  }

  function pushAllFilesToPreview() {
    for (const name of FILES) {
      if (!state.files[name]) continue;
      postPreview({ type: "apply-file", name, content: state.files[name] });
    }
    postPreview({ type: "request-regions" });
  }

  function parseClamp(value) {
    const m = String(value)
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

  function parsePx(value) {
    const m = String(value).trim().match(/^([\d.]+)px$/i);
    return m ? Number(m[1]) : null;
  }

  function getVarValue(cssText, key) {
    const re = new RegExp(`(${escapeReg(key)}\\s*:\\s*)([^;]+);`);
    const m = cssText.match(re);
    return m ? m[2].trim() : null;
  }

  function setVarValue(cssText, key, value) {
    const re = new RegExp(`(${escapeReg(key)}\\s*:\\s*)([^;]+)(;)`);
    if (!re.test(cssText)) return cssText;
    return cssText.replace(re, `$1${value}$3`);
  }

  function escapeReg(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function formatClamp(parts) {
    return `clamp(${parts.min}${parts.minUnit}, ${parts.preferred}${parts.preferredUnit}, ${parts.max}${parts.maxUnit})`;
  }

  function sliderValueFromCss(cssValue, fallback = 80) {
    const clamp = parseClamp(cssValue);
    if (clamp) {
      if (clamp.preferredUnit === "px") return clamp.preferred;
      if (clamp.maxUnit === "px") return clamp.max;
      return fallback;
    }
    const px = parsePx(cssValue);
    return px ?? fallback;
  }

  function cssFromSlider(def, px, currentCss) {
    const clamp = parseClamp(currentCss || "");
    if (clamp) {
      const next = { ...clamp };
      if (next.preferredUnit === "px") next.preferred = px;
      else if (next.maxUnit === "px") next.max = px;
      else {
        next.preferred = px;
        next.preferredUnit = "px";
      }
      if (next.maxUnit === "px" && next.max < px) next.max = px;
      if (next.minUnit === "px" && next.min > px) next.min = Math.max(def.min, Math.round(px * 0.75));
      return formatClamp(next);
    }
    return `${px}px`;
  }

  function renderControls() {
    const tokens = state.files["tokens.css"] || "";
    els.controls.innerHTML = "";

    for (const def of LAYOUT_VARS) {
      const current = getVarValue(tokens, def.key) || `${Math.round((def.min + def.max) / 2)}px`;
      const clamp = parseClamp(current);
      const px = sliderValueFromCss(current, Math.round((def.min + def.max) / 2));

      const card = document.createElement("div");
      card.className = `ed-control${state.selectedRegion === def.region ? " is-active" : ""}`;
      card.dataset.region = def.region;

      card.innerHTML = `
        <div class="ed-control-label">
          <span>${def.label}</span>
          <code>${def.key}</code>
        </div>
        <input type="range" min="${def.min}" max="${def.max}" value="${Math.round(px)}" data-key="${def.key}" />
        <div class="ed-control-meta">
          <label>Min<input data-part="min" data-key="${def.key}" value="${clamp ? clamp.min : Math.round(px * 0.75)}" /></label>
          <label>Pref<input data-part="preferred" data-key="${def.key}" value="${clamp ? clamp.preferred : Math.round(px)}" /></label>
          <label>Max<input data-part="max" data-key="${def.key}" value="${clamp ? clamp.max : Math.round(px)}" /></label>
        </div>
      `;
      els.controls.appendChild(card);
    }
  }

  function syncControlCard(key, cssValue) {
    const def = LAYOUT_VARS.find((v) => v.key === key);
    if (!def) return;
    const card = els.controls.querySelector(`.ed-control input[data-key="${key}"][type="range"]`)?.closest(".ed-control");
    if (!card) return;
    const clamp = parseClamp(cssValue);
    const px = sliderValueFromCss(cssValue, Math.round((def.min + def.max) / 2));
    const range = card.querySelector('input[type="range"]');
    if (range) range.value = String(Math.round(px));
    const minInput = card.querySelector('input[data-part="min"]');
    const prefInput = card.querySelector('input[data-part="preferred"]');
    const maxInput = card.querySelector('input[data-part="max"]');
    if (minInput) minInput.value = String(clamp ? clamp.min : Math.round(px * 0.75));
    if (prefInput) prefInput.value = String(clamp ? clamp.preferred : Math.round(px));
    if (maxInput) maxInput.value = String(clamp ? clamp.max : Math.round(px));
  }

  function applyTokenVar(key, cssValue, { fromCode = false, rebuildControls = false } = {}) {
    let tokens = state.files["tokens.css"];
    tokens = setVarValue(tokens, key, cssValue);
    state.files["tokens.css"] = tokens;
    markDirty("tokens.css", tokens);

    if (state.activeFile === "tokens.css" && !fromCode) {
      const start = els.code.selectionStart;
      const wasFocused = document.activeElement === els.code;
      els.code.value = tokens;
      if (wasFocused) els.code.selectionStart = els.code.selectionEnd = start;
    }

    postPreview({ type: "apply-file", name: "tokens.css", content: tokens });
    postPreview({ type: "request-regions" });
    if (rebuildControls) renderControls();
    else syncControlCard(key, cssValue);
    scheduleAutoSave();
  }

  function markDirty(name, content) {
    state.dirty[name] = content !== state.saved[name];
    updateDirtyUI();
  }

  function scheduleAutoSave() {
    if (!els.autoSave.checked) return;
    clearTimeout(state.autoSaveTimer);
    state.autoSaveTimer = setTimeout(() => {
      saveActive().catch((err) => setStatus(String(err), "dirty"));
    }, 700);
  }

  async function loadFile(name) {
    const res = await fetch(`/api/file?name=${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error(`Kon ${name} niet laden`);
    const data = await res.json();
    state.files[name] = data.content;
    state.saved[name] = data.content;
    state.dirty[name] = false;
  }

  async function loadAll() {
    setStatus("Bestanden laden…");
    for (const name of FILES) {
      await loadFile(name);
    }
    renderTabs();
    selectFile(state.activeFile, { force: true });
    renderControls();
    if (state.previewReady) pushAllFilesToPreview();
    setStatus("Klaar", "ok");
  }

  async function saveFile(name) {
    const content = state.files[name];
    const res = await fetch(`/api/file?name=${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Opslaan mislukt: ${name}`);
    }
    state.saved[name] = content;
    state.dirty[name] = false;
  }

  async function saveActive() {
    const dirtyFiles = FILES.filter((name) => state.dirty[name]);
    if (!dirtyFiles.length) {
      setStatus("Niets te opslaan", "ok");
      return;
    }
    setStatus("Opslaan…");
    for (const name of dirtyFiles) {
      await saveFile(name);
    }
    updateDirtyUI();
    setStatus(`Opgeslagen · ${dirtyFiles.join(", ")}`, "ok");
  }

  function renderTabs() {
    els.tabs.innerHTML = "";
    for (const name of FILES) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `ed-tab${name === state.activeFile ? " is-active" : ""}`;
      btn.textContent = state.dirty[name] ? `${name} •` : name;
      btn.addEventListener("click", () => selectFile(name));
      els.tabs.appendChild(btn);
    }
  }

  function selectFile(name, { force = false } = {}) {
    if (!force && name === state.activeFile) return;
    state.activeFile = name;
    els.code.value = state.files[name] || "";
    els.codeFileLabel.textContent = name;
    renderTabs();
    updateDirtyUI();
  }

  function onCodeInput() {
    const name = state.activeFile;
    const content = els.code.value;
    state.files[name] = content;
    markDirty(name, content);
    renderTabs();
    postPreview({ type: "apply-file", name, content });
    if (name === "tokens.css") renderControls();
    postPreview({ type: "request-regions" });
    scheduleAutoSave();
  }

  function renderGuides() {
    const show = els.showGuides.checked;
    els.guides.hidden = !show;
    if (!show) {
      els.guides.innerHTML = "";
      return;
    }

    const regions = state.regions || {};
    els.guides.innerHTML = "";

    const order = [
      { name: "header", handle: "bottom" },
      { name: "sidebar", handle: "right" },
      { name: "right", handle: "left" },
      { name: "footer", handle: "top" },
    ];

    for (const item of order) {
      const rect = regions[item.name];
      if (!rect) continue;
      const guide = document.createElement("div");
      guide.className = `ed-guide${state.selectedRegion === item.name ? " is-active" : ""}`;
      guide.style.left = `${rect.left}px`;
      guide.style.top = `${rect.top}px`;
      guide.style.width = `${rect.width}px`;
      guide.style.height = `${rect.height}px`;
      guide.textContent = item.name;
      guide.dataset.region = item.name;

      const handle = document.createElement("div");
      handle.className = `ed-handle ${item.handle === "left" || item.handle === "right" ? "ed-handle-h" : "ed-handle-v"}`;
      if (item.handle === "right") handle.style.left = "100%";
      if (item.handle === "left") handle.style.left = "0%";
      if (item.handle === "bottom") handle.style.top = "100%";
      if (item.handle === "top") handle.style.top = "0%";
      handle.dataset.region = item.name;
      handle.dataset.handle = item.handle;
      guide.appendChild(handle);
      els.guides.appendChild(guide);
    }
  }

  function regionToVar(region) {
    return LAYOUT_VARS.find((v) => v.region === region && (v.axis === "x" || v.axis === "y"));
  }

  function startDrag(event) {
    const handle = event.target.closest(".ed-handle");
    if (!handle) return;
    event.preventDefault();
    event.stopPropagation();

    const region = handle.dataset.region;
    const edge = handle.dataset.handle;
    const def = regionToVar(region);
    if (!def) return;

    state.selectedRegion = region;
    postPreview({ type: "select-region", region });
    renderControls();

    const tokens = state.files["tokens.css"];
    const current = getVarValue(tokens, def.key) || "80px";
    let value = sliderValueFromCss(current, 80);

    const onMove = (ev) => {
      const frame = els.previewFrame.getBoundingClientRect();
      if (edge === "right") {
        const sidebar = state.regions.sidebar;
        if (!sidebar) return;
        value = Math.round(clamp(ev.clientX - frame.left - sidebar.left, def.min, def.max));
      } else if (edge === "left") {
        const right = state.regions.right;
        if (!right) return;
        value = Math.round(clamp(frame.left + right.left + right.width - ev.clientX, def.min, def.max));
      } else if (edge === "bottom") {
        value = Math.round(clamp(ev.clientY - frame.top, def.min, def.max));
      } else if (edge === "top") {
        const footer = state.regions.footer;
        if (!footer) return;
        value = Math.round(clamp(frame.top + footer.top + footer.height - ev.clientY, def.min, def.max));
      }

      const nextCss = cssFromSlider(def, value, getVarValue(state.files["tokens.css"], def.key));
      applyTokenVar(def.key, nextCss);
    };

    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function clamp(n, min, max) {
    return Math.min(max, Math.max(min, n));
  }

  function bindControls() {
    els.controls.addEventListener("input", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      const key = target.dataset.key;
      if (!key) return;

      const def = LAYOUT_VARS.find((v) => v.key === key);
      if (!def) return;

      const current = getVarValue(state.files["tokens.css"], key) || "80px";
      const clampParts = parseClamp(current) || {
        min: Math.round(def.min),
        minUnit: "px",
        preferred: Math.round((def.min + def.max) / 2),
        preferredUnit: "px",
        max: Math.round(def.max),
        maxUnit: "px",
      };

      if (target.type === "range") {
        const px = Number(target.value);
        applyTokenVar(key, cssFromSlider(def, px, current));
        return;
      }

      const part = target.dataset.part;
      const num = Number(target.value);
      if (!part || Number.isNaN(num)) return;
      clampParts[part] = num;
      applyTokenVar(key, formatClamp(clampParts), { rebuildControls: false });
    });

    els.controls.addEventListener("click", (event) => {
      const card = event.target.closest(".ed-control");
      if (!card) return;
      state.selectedRegion = card.dataset.region;
      postPreview({ type: "select-region", region: state.selectedRegion });
      renderControls();
      renderGuides();
    });
  }

  function bindChrome() {
    els.btnSave.addEventListener("click", () => {
      saveActive().catch((err) => setStatus(String(err), "dirty"));
    });
    els.btnReload.addEventListener("click", () => {
      loadAll().catch((err) => setStatus(String(err), "dirty"));
    });
    els.code.addEventListener("input", onCodeInput);
    els.showGuides.addEventListener("change", renderGuides);
    els.guides.addEventListener("pointerdown", startDrag);

    document.querySelectorAll(".ed-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".ed-chip").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        els.previewFrame.style.maxWidth = btn.dataset.w === "100%" ? "100%" : btn.dataset.w;
        setTimeout(() => postPreview({ type: "request-regions" }), 200);
      });
    });

    window.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveActive().catch((err) => setStatus(String(err), "dirty"));
      }
    });

    window.addEventListener("message", (event) => {
      const data = event.data || {};
      if (data.type === "preview-ready") {
        state.previewReady = true;
        pushAllFilesToPreview();
      }
      if (data.type === "regions") {
        state.regions = data.regions || {};
        renderGuides();
      }
      if (data.type === "region-click") {
        state.selectedRegion = data.region;
        postPreview({ type: "select-region", region: data.region });
        renderControls();
        renderGuides();
        if (state.activeFile !== "tokens.css") selectFile("tokens.css");
      }
    });

    els.preview.addEventListener("load", () => {
      state.previewReady = true;
      pushAllFilesToPreview();
    });
  }

  bindControls();
  bindChrome();
  loadAll().catch((err) => setStatus(String(err), "dirty"));
})();
