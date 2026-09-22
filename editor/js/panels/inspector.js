/**
 * Leviathan Visual Builder — visual inspector.
 */

import {
  alphaFromColor,
  colorWithAlpha,
  escapeHtml,
  isTokenValue,
  numFrom,
  parseShadowList,
  parseShorthand,
  serializeShadows,
  shorthandFromSides,
  swatchStore,
  toHexColor,
} from "../util.js";

const swatches = swatchStore();

function fieldValue(read) {
  return read.value || "";
}

export function createInspector(ctx) {
  const panel = {
    id: "inspector",
    title: "Inspector",
    zone: "right",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      const s = ctx.store.getState();
      return `${s.sel}|${s.breakpoint}|${s.uiEpoch || 0}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("focusin", (event) => {
        const live = event.target.closest?.("[data-live]");
        if (!live || live.dataset.nohistory) return;
        ctx.commands.beginGesture(live.dataset.prop || live.dataset.side || "bewerken");
      });
      host.addEventListener("pointerdown", (event) => {
        if (event.target.closest("button")) ctx.commands.endGesture();
      });
      host.addEventListener("focusout", (event) => {
        const t = event.target;
        const node = el();
        if (t?.dataset?.role === "text" && node) {
          const baseline = ctx.content.stageText(node, t.value);
          ctx.commands.endGesture();
          if (baseline && baseline !== t.value && !node.dataset.lvbId) ctx.content.replaceSource(baseline, t.value);
          return;
        }
        if (t?.dataset?.role === "img-src" && node?.tagName === "IMG") {
          const src = t.value.trim();
          const prev = ctx.content.getEntry(ctx.selection.selectorFor(node))?.src || node.getAttribute("src");
          node.setAttribute("src", src);
          ctx.content.patchEntry(ctx.selection.selectorFor(node), { src });
          ctx.commands.endGesture();
          if (prev && prev !== src && !node.dataset.lvbId) ctx.content.replaceSource(prev, src);
          return;
        }
        if (t?.dataset?.role === "raw" && node) {
          ctx.content.applyRaw(node, t.value);
        }
        ctx.commands.endGesture();
      });
      host.addEventListener("input", (event) => onInput(event));
      host.addEventListener("click", (event) => onClick(event));
    },
    render() {
      if (!this.host) return;
      const top = this.host.scrollTop;
      this.host.innerHTML = renderInspector(ctx);
      this.host.scrollTop = top;
    },
  };

  function el() {
    return ctx.session.primary;
  }

  /** All mutable targets for batch property writes (multi-select aware). */
  function targets() {
    const list = ctx.selection.mutable("edit");
    return list.length ? list : el() ? [el()] : [];
  }

  function readMixed(prop) {
    const nodes = targets();
    if (!nodes.length) return { value: "", mixed: false, hint: "" };
    const first = ctx.content.readProp(nodes[0], prop);
    let mixed = false;
    for (let i = 1; i < nodes.length; i += 1) {
      const next = ctx.content.readProp(nodes[i], prop);
      if ((next.value || "") !== (first.value || "")) {
        mixed = true;
        break;
      }
    }
    return { value: mixed ? "" : first.value, mixed, hint: first.hint || "", placeholder: mixed ? "Gemengd" : first.hint || "" };
  }

  function applyAll(prop, value) {
    for (const node of targets()) ctx.content.applyProp(node, prop, value);
  }

  function onInput(event) {
    const t = event.target;
    const node = el();
    if (!node || !(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement)) return;
    if (t.dataset.role === "text") {
      if (node.childElementCount === 0 || [...node.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) {
        node.textContent = t.value;
      }
      ctx.chrome.schedulePaint();
      return;
    }
    if (t.dataset.role === "img-src") {
      node.setAttribute("src", t.value.trim());
      return;
    }
    if (t.dataset.role === "img-alt") {
      node.setAttribute("alt", t.value);
      ctx.content.patchEntry(ctx.selection.selectorFor(node), { alt: t.value });
      return;
    }
    if (t.dataset.role === "raw") return;
    if (t.dataset.role === "region" && ctx.selection.regionFor(node)?.varKey) {
      ctx.content.setRegionPx(ctx.selection.regionFor(node), Number(t.value));
      return;
    }
    if (t.dataset.side) {
      applySides(node, t.dataset.box, t.dataset.side, t.value);
      return;
    }
    if (t.dataset.shadow != null) {
      applyShadow(node);
      return;
    }
    if (t.dataset.prop) {
      let value = t.value;
      if (t.dataset.unit === "px" && value && numFrom(value) != null && !isTokenValue(value)) value = `${value}px`;
      if (t.dataset.unit === "deg" && value && numFrom(value) != null && !String(value).includes("deg")) value = `${value}deg`;
      if (t.dataset.role === "color-hex") value = syncColorAlpha(t);
      if (t.dataset.role === "color-alpha") value = syncColorAlpha(t);
      if (t.dataset.role === "position-mode" || t.dataset.prop === "position") {
        for (const n of targets()) ctx.layout.setPositionMode(n, value);
        ctx.chrome.schedulePaint();
        return;
      }
      if (t.dataset.prop === "width" && ctx.session.aspectLock && ctx.session.aspect) {
        applyAll("width", value);
        const w = numFrom(value);
        if (w != null) applyAll("height", `${Math.round(w / ctx.session.aspect)}px`);
        ctx.chrome.schedulePaint();
        return;
      }
      if (t.dataset.prop === "left" || t.dataset.prop === "top" || t.dataset.prop === "width" || t.dataset.prop === "height") {
        for (const n of targets()) ctx.layout.ensureFreeTransform(n);
      }
      applyAll(t.dataset.prop, value);
      ctx.chrome.schedulePaint();
    }
  }

  function syncColorAlpha(input) {
    const wrap = input.closest("[data-color-wrap]");
    if (!wrap) return input.value;
    const hex = wrap.querySelector("[data-role='color-hex']")?.value || "#ffffff";
    const alpha = wrap.querySelector("[data-role='color-alpha']")?.value || "1";
    const prop = wrap.dataset.prop;
    const value = colorWithAlpha(hex, alpha);
    const text = wrap.querySelector("[data-role='color-text']");
    if (text && document.activeElement !== text) text.value = value;
    if (input.dataset.role !== "color-text") return value;
    return input.value;
  }

  function applySides(node, box, side, value) {
    const host = panel.host;
    const inputs = [...host.querySelectorAll(`[data-box="${box}"]`)];
    const linked = ctx.session.link[box] !== false;
    if (linked) {
      for (const input of inputs) input.value = value;
    }
    const sides = { top: "", right: "", bottom: "", left: "" };
    for (const input of inputs) sides[input.dataset.side] = input.value || "0";
    const next = linked ? (value || "0") : shorthandFromSides(sides, false);
    ctx.content.applyProp(node, box, next);
    for (const name of ["top", "right", "bottom", "left"]) ctx.content.applyProp(node, `${box}-${name}`, "");
    ctx.chrome.schedulePaint();
  }

  function applyShadow(node) {
    const rows = [...panel.host.querySelectorAll("[data-shadow-row]")];
    const layers = rows.map((row) => ({
      inset: row.querySelector("[data-shadow='inset']")?.checked || false,
      x: withPx(row.querySelector("[data-shadow='x']")?.value),
      y: withPx(row.querySelector("[data-shadow='y']")?.value),
      blur: withPx(row.querySelector("[data-shadow='blur']")?.value),
      spread: withPx(row.querySelector("[data-shadow='spread']")?.value),
      color: row.querySelector("[data-shadow='color']")?.value || "rgba(0,0,0,.4)",
    }));
    ctx.content.applyProp(node, "box-shadow", serializeShadows(layers));
  }

  function onClick(event) {
    const node = el();
    const insert = event.target.closest("[data-insert]");
    if (insert) {
      ctx.widgets.insertPreset(insert.dataset.insert);
      return;
    }
    const setProp = event.target.closest("[data-set-prop]");
    if (setProp && node) {
      const nodes = ctx.selection.mutable("edit");
      ctx.commands.capture(setProp.dataset.setProp, () => {
        for (const n of nodes.length ? nodes : [node]) {
          ctx.content.applyProp(n, setProp.dataset.setProp, setProp.dataset.setValue);
        }
      });
      bumpRender(ctx);
      return;
    }
    const crumb = event.target.closest("[data-crumb]");
    if (crumb) {
      try {
        const found = document.querySelector(crumb.dataset.crumb);
        if (found) ctx.selection.set([found], found);
      } catch {
        /* ignore */
      }
      return;
    }
    const link = event.target.closest("[data-link]");
    if (link) {
      const key = link.dataset.link;
      ctx.session.link[key] = !ctx.session.link[key];
      ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
      ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
      return;
    }
    const align = event.target.closest("[data-align]");
    if (align) {
      ctx.layout.align(align.dataset.align);
      return;
    }
    const dist = event.target.closest("[data-distribute]");
    if (dist) {
      ctx.layout.distribute(dist.dataset.distribute);
      return;
    }
    const act = event.target.closest("[data-act]")?.dataset.act;
    if (act === "inline" && node) beginInline(ctx, node);
    if (act === "add-image" || act === "pick-image") ctx.chrome.openMedia(act === "add-image" ? "insert" : "replace");
    if (act === "upload-replace") ctx.chrome.pickUpload("replace");
    if (act === "lock") ctx.widgets.toggleLock(node);
    if (act === "hide") ctx.widgets.setHidden(node, true);
    if (act === "show") ctx.widgets.setHidden(node, false);
    if (act === "front") ctx.widgets.bumpZ(1);
    if (act === "back") ctx.widgets.bumpZ(-1);
    if (act === "flip-h") ctx.widgets.flip("x");
    if (act === "flip-v") ctx.widgets.flip("y");
    if (act === "group") ctx.widgets.groupSelection();
    if (act === "ungroup") ctx.widgets.ungroupSelection();
    if (act === "copy-style") ctx.widgets.copyStyle();
    if (act === "paste-style") ctx.widgets.pasteStyle();
    if (act === "duplicate") ctx.widgets.duplicateSelection();
    if (act === "delete") ctx.widgets.deleteSelection();
    if (act === "component") ctx.widgets.createComponent();
    if (act === "detach") ctx.widgets.detachComponent(node);
    if (act === "clear") {
      ctx.commands.capture("reset-styles", () => ctx.content.clearStyles(node));
      ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
      ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    }
    if (act === "aspect" && node) {
      ctx.session.aspectLock = !ctx.session.aspectLock;
      const w = node.getBoundingClientRect().width / (ctx.store.getState().zoom || 1);
      const h = node.getBoundingClientRect().height / (ctx.store.getState().zoom || 1);
      ctx.session.aspect = h ? w / h : 1;
      ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
      ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    }
    if (act === "shadow-add") {
      ctx.commands.capture("schaduw", () => {
        const current = parseShadowList(ctx.content.readProp(node, "box-shadow").value);
        current.push({ x: "0px", y: "8px", blur: "24px", spread: "0px", color: "rgba(0,0,0,0.35)", inset: false });
        ctx.content.applyProp(node, "box-shadow", serializeShadows(current));
      });
      bumpRender(ctx);
    }
    const del = event.target.closest("[data-shadow-del]");
    if (del && node) {
      const index = Number(del.dataset.shadowDel);
      ctx.commands.capture("schaduw", () => {
        const current = parseShadowList(ctx.content.readProp(node, "box-shadow").value);
        current.splice(index, 1);
        ctx.content.applyProp(node, "box-shadow", serializeShadows(current));
      });
      bumpRender(ctx);
    }
    const tokenBtn = event.target.closest("[data-token-for]");
    if (tokenBtn) {
      openTokens(tokenBtn.dataset.tokenFor);
      return;
    }
    const pick = event.target.closest("[data-pick-token]");
    if (pick && node) {
      ctx.commands.capture("token", () => ctx.content.applyProp(node, pick.dataset.pickProp, `var(${pick.dataset.pickToken})`));
      closeTokens();
      bumpRender(ctx);
      return;
    }
    const detach = event.target.closest("[data-detach]");
    if (detach && node) {
      const prop = detach.dataset.detach;
      let computed = "";
      try {
        computed = getComputedStyle(node).getPropertyValue(prop).trim();
      } catch {
        computed = "";
      }
      ctx.commands.capture("ontkoppel", () => ctx.content.applyProp(node, prop, computed));
      bumpRender(ctx);
      return;
    }
    const sw = event.target.closest("[data-swatch]");
    if (sw && node) {
      const prop = sw.dataset.swatchProp || "background-color";
      ctx.commands.capture("kleur", () => ctx.content.applyProp(node, prop, sw.dataset.swatch));
      swatches.push(sw.dataset.swatch);
      bumpRender(ctx);
    }
    if (event.target.closest("[data-close-tokens]")) closeTokens();
  }

  function openTokens(prop) {
    const pop = panel.host.querySelector("[data-token-pop]");
    if (!pop) return;
    pop.hidden = false;
    pop.dataset.prop = prop;
    paintTokenChoices(prop, "");
    const search = pop.querySelector("[data-token-search]");
    search?.focus();
    search.oninput = () => paintTokenChoices(prop, search.value);
  }

  function closeTokens() {
    const pop = panel.host.querySelector("[data-token-pop]");
    if (pop) pop.hidden = true;
  }

  function paintTokenChoices(prop, query) {
    const pop = panel.host.querySelector("[data-token-list]");
    if (!pop) return;
    const q = query.trim().toLowerCase();
    const tokens = ctx.tokens()
      .filter((token) => !q || token.name.includes(q) || token.value.toLowerCase().includes(q))
      .slice(0, 40);
    pop.innerHTML = tokens
      .map(
        (token) => `<button type="button" class="lvb-token-item" data-pick-token="${token.name}" data-pick-prop="${escapeHtml(prop)}">
          <i style="background:${escapeHtml(token.group === "Kleuren" ? token.value : "transparent")}"></i>
          <span>${escapeHtml(token.name)}</span>
        </button>`,
      )
      .join("") || `<p class="lvb-muted">Geen tokens</p>`;
  }

  return panel;
}

function beginInline(ctx, node) {
  ctx.session.inlineEl = node;
  node.contentEditable = "true";
  node.classList.add("lvb-inline-editing");
  node.focus();
  const onBlur = () => {
    node.removeEventListener("blur", onBlur);
    node.contentEditable = "false";
    node.classList.remove("lvb-inline-editing");
    const text = node.textContent || "";
    ctx.session.inlineEl = null;
    const baseline = ctx.content.stageText(node, text);
    ctx.commands.endGesture();
    if (!ctx.commands.isGesturing()) {
      /* stageText already mutated; record if gesture was not open */
    }
    if (baseline && baseline !== text && !node.dataset.lvbId) ctx.content.replaceSource(baseline, text);
    ctx.chrome.schedulePaint();
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
  };
  ctx.commands.beginGesture("tekst");
  node.addEventListener("blur", onBlur);
}

function withPx(value) {
  if (value == null || value === "") return "0px";
  if (isTokenValue(value) || /px|%|em|rem/.test(value)) return value;
  return `${value}px`;
}

function renderInspector(ctx) {
  const node = ctx.session.primary;
  if (!node) {
    return `<p class="lvb-muted"><b>Leviathan Studio</b></p>
      <p class="lvb-muted">Selecteer een element. V selecteert, H pan, R roteert, M meet. ⌘K opent het commandopalet.</p>
      <div class="lvb-section">Snel toevoegen</div>
      <div class="lvb-chip-row">
        <button type="button" class="lvb-chip" data-insert="text">+ Tekst</button>
        <button type="button" class="lvb-chip" data-insert="heading">+ Titel</button>
        <button type="button" class="lvb-chip" data-insert="box">+ Box</button>
        <button type="button" class="lvb-chip" data-insert="button">+ Knop</button>
        <button type="button" class="lvb-chip" data-act="add-image">+ Image</button>
      </div>`;
  }
  const selector = ctx.selection.selectorFor(node);
  const crumbs = ctx.selection.path(node);
  const bp = ctx.store.getState().breakpoint;
  const multi = ctx.session.selected.length;
  let html = `<div class="lvb-crumbs">${crumbs
    .map((part) => `<button type="button" data-crumb="${escapeHtml(ctx.selection.selectorFor(part))}">${escapeHtml(ctx.selection.labelFor(part))}</button>`)
    .join("<span>/</span>")}</div>`;
  if (multi > 1) {
    html += `<h3>${multi} elementen</h3><p class="lvb-muted">Gemengde waarden tonen “Gemengd”. Wijzigingen gelden voor alle geselecteerde elementen.</p>`;
  } else {
    html += `<h3>${escapeHtml(selector)}</h3>`;
  }
  if (bp !== "desktop") html += `<p class="lvb-flag">Overrides voor ${escapeHtml(bp)} → content JSON</p>`;
  if (node.tagName === "IMG") {
    const fit = ctx.content.readProp(node, "object-fit").value || "cover";
    const objPos = ctx.content.readProp(node, "object-position");
    html += `<div class="lvb-section">Image</div>
      <label class="lvb-field"><span>Bron</span><input data-live="1" data-role="img-src" value="${escapeHtml(node.getAttribute("src") || "")}" /></label>
      <label class="lvb-field"><span>Alt</span><input data-live="1" data-role="img-alt" value="${escapeHtml(node.getAttribute("alt") || "")}" /></label>
      <label class="lvb-field"><span>Object-fit</span>
        <select data-live="1" data-prop="object-fit">
          ${["cover", "contain", "fill", "none", "scale-down"].map((v) => `<option ${fit === v ? "selected" : ""}>${v}</option>`).join("")}
        </select>
      </label>
      <label class="lvb-field"><span>Object-position</span><input data-live="1" data-prop="object-position" value="${escapeHtml(objPos.value)}" placeholder="50% 50%" /></label>
      <div class="lvb-chip-row">
        <button type="button" class="lvb-chip" data-act="pick-image">Kies image…</button>
        <button type="button" class="lvb-chip" data-act="upload-replace">Upload…</button>
        <button type="button" class="lvb-chip" data-act="flip-h">Flip H</button>
        <button type="button" class="lvb-chip" data-act="flip-v">Flip V</button>
      </div>`;
  } else {
    const text = node.childElementCount === 0 || [...node.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) ? node.textContent || "" : "";
    html += `<div class="lvb-section">Tekst</div>
      <label class="lvb-field"><span>Inhoud</span><textarea data-live="1" data-role="text" rows="3">${escapeHtml(text)}</textarea></label>
      <button type="button" class="lvb-btn" data-act="inline">Inline bewerken</button>`;
  }
  const region = ctx.selection.regionFor(node);
  if (region?.varKey) {
    const px = ctx.content.regionPx(region);
    html += `<div class="lvb-section">Shell maat</div>
      <label class="lvb-field"><span>${escapeHtml(region.label)} (${px}px)</span>
        <input data-live="1" data-role="region" type="range" min="${region.min}" max="${region.max}" value="${px}" />
      </label>`;
  }
  html += sectionSpacing(ctx, node);
  html += sectionSize(ctx, node);
  html += sectionType(ctx, node);
  html += sectionColor(ctx, node, "color", "Tekstkleur");
  html += sectionColor(ctx, node, "background-color", "Achtergrond");
  html += sectionBorder(ctx, node);
  html += sectionShadow(ctx, node);
  html += sectionLayout(ctx, node);
  html += sectionPosition(ctx, node);
  html += sectionAlign(ctx);
  html += `<details class="lvb-fold"><summary>Geavanceerd CSS</summary>
      <textarea data-live="1" data-prop="__raw" data-role="raw" rows="8">${escapeHtml(ctx.content.rawDecls(node))}</textarea>
    </details>`;
  html += `<div class="lvb-token-pop" data-token-pop hidden>
      <div class="lvb-pop-head"><span>Token</span><button type="button" data-close-tokens>×</button></div>
      <input data-token-search data-nohistory="1" placeholder="Filter --lv-" />
      <div data-token-list></div>
    </div>`;
  html += `<div class="lvb-section">Acties</div><div class="lvb-chip-row">
      <button type="button" class="lvb-chip" data-act="duplicate">Dupliceer</button>
      <button type="button" class="lvb-chip" data-act="delete">Verwijder</button>
      <button type="button" class="lvb-chip" data-act="lock">${ctx.selection.isLocked(node) ? "Unlock" : "Lock"}</button>
      <button type="button" class="lvb-chip" data-act="hide">Verberg</button>
      <button type="button" class="lvb-chip" data-act="show">Toon</button>
      <button type="button" class="lvb-chip" data-act="front">Naar voren</button>
      <button type="button" class="lvb-chip" data-act="back">Naar achter</button>
      <button type="button" class="lvb-chip" data-act="group">Groepeer</button>
      <button type="button" class="lvb-chip" data-act="ungroup">Degroepeer</button>
      <button type="button" class="lvb-chip" data-act="copy-style">Kopieer stijl</button>
      <button type="button" class="lvb-chip" data-act="paste-style">Plak stijl</button>
      <button type="button" class="lvb-chip" data-act="component">Maak component</button>
      <button type="button" class="lvb-chip" data-act="detach">Detach</button>
      <button type="button" class="lvb-chip" data-act="clear">Reset styles</button>
    </div>`;
  return html;
}

function bumpRender(ctx) {
  ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
  ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
}

function sectionSpacing(ctx, node) {
  return `<div class="lvb-section">Spacing</div>
    ${boxModel(ctx, node, "margin", "Margin")}
    ${boxModel(ctx, node, "padding", "Padding")}`;
}

function boxModel(ctx, node, prop, label) {
  const linked = ctx.session.link[prop] !== false;
  const read = ctx.content.readProp(node, prop);
  const sides = parseShorthand(read.value || read.hint || "0");
  for (const side of ["top", "right", "bottom", "left"]) {
    const long = ctx.content.readProp(node, `${prop}-${side}`);
    if (long.value) sides[side] = long.value;
  }
  const bound = isTokenValue(read.value);
  return `<div class="lvb-boxmodel ${bound ? "is-bound" : ""}">
      <div class="lvb-boxmodel-label"><span>${label}</span>
        <button type="button" class="lvb-mini ${linked ? "is-on" : ""}" data-link="${prop}">${linked ? "Gekoppeld" : "Per zijde"}</button>
        <button type="button" class="lvb-mini" data-token-for="${prop}">var</button>
        ${bound ? `<button type="button" class="lvb-mini" data-detach="${prop}">Ontkoppel</button>` : ""}
      </div>
      <div class="lvb-boxgrid">
        ${sideInput(prop, "top", sides.top)}
        <div class="lvb-boxmid">
          ${sideInput(prop, "left", sides.left)}
          <i>${label === "Margin" ? "buiten" : "binnen"}</i>
          ${sideInput(prop, "right", sides.right)}
        </div>
        ${sideInput(prop, "bottom", sides.bottom)}
      </div>
    </div>`;
}

function sideInput(box, side, value) {
  return `<input data-live="1" data-box="${box}" data-side="${side}" value="${escapeHtml(value || "")}" title="${side}" />`;
}

function sectionSize(ctx, node) {
  const nodes = ctx.session.selected.filter((el) => ctx.selection.canMutate(el));
  const mix = (prop) => {
    if (nodes.length < 2) return ctx.content.readProp(node, prop);
    const first = ctx.content.readProp(nodes[0], prop);
    for (let i = 1; i < nodes.length; i += 1) {
      if ((ctx.content.readProp(nodes[i], prop).value || "") !== (first.value || "")) {
        return { value: "", mixed: true, hint: first.hint, placeholder: "Gemengd" };
      }
    }
    return first;
  };
  const lockLabel = ctx.session.aspectLock ? "Ratio vast" : "Ratio vrij (ontgrendeld)";
  return `<div class="lvb-section">Formaat</div>
    <div class="lvb-row">
      ${numField("W", "width", mix("width"), true)}
      ${numField("H", "height", mix("height"), true)}
    </div>
    <button type="button" class="lvb-btn ${ctx.session.aspectLock ? "is-on" : ""}" data-act="aspect">${lockLabel}</button>
    <p class="lvb-muted">Shift tijdens resize = tijdelijk ratio. Inspectorknop = vast.</p>
    <div class="lvb-row">
      ${numField("Min W", "min-width", mix("min-width"), true)}
      ${numField("Max W", "max-width", mix("max-width"), true)}
      ${numField("Min H", "min-height", mix("min-height"), true)}
      ${numField("Max H", "max-height", mix("max-height"), true)}
    </div>`;
}

function numField(label, prop, read, px) {
  const raw = fieldValue(read);
  const shown = px && raw.endsWith("px") ? raw.slice(0, -2) : raw;
  const bound = isTokenValue(raw);
  const mixed = read.mixed ? " is-mixed" : "";
  return `<label class="lvb-field ${bound ? "is-bound" : ""}${mixed}"><span>${label}</span>
      <span class="lvb-inline">
        <input data-live="1" data-prop="${prop}" ${px ? 'data-unit="px"' : ""} value="${escapeHtml(bound ? raw : shown)}" placeholder="${escapeHtml(read.placeholder || read.hint || (read.mixed ? "Gemengd" : ""))}" />
        <button type="button" class="lvb-mini" data-token-for="${prop}">var</button>
        ${bound ? `<button type="button" class="lvb-mini" data-detach="${prop}">×</button>` : ""}
      </span>
    </label>`;
}

function sectionType(ctx, node) {
  const size = ctx.content.readProp(node, "font-size");
  const weight = ctx.content.readProp(node, "font-weight");
  const lh = ctx.content.readProp(node, "line-height");
  const ls = ctx.content.readProp(node, "letter-spacing");
  const family = ctx.content.readProp(node, "font-family");
  const align = ctx.content.readProp(node, "text-align").value || "left";
  const transform = ctx.content.readProp(node, "text-transform").value || "none";
  const decoration = ctx.content.readProp(node, "text-decoration").value || "none";
  return `<div class="lvb-section">Typografie</div>
    <div class="lvb-row">
      ${numField("Grootte", "font-size", size, true)}
      <label class="lvb-field"><span>Gewicht</span>
        <select data-live="1" data-prop="font-weight">
          ${[400, 500, 600, 700, 800].map((w) => `<option ${String(weight.value || weight.hint) === String(w) ? "selected" : ""}>${w}</option>`).join("")}
        </select>
      </label>
    </div>
    <div class="lvb-row">
      <label class="lvb-field"><span>Regelhoogte</span><input data-live="1" data-prop="line-height" value="${escapeHtml(lh.value)}" placeholder="${escapeHtml(lh.hint || "1.4")}" /></label>
      <label class="lvb-field"><span>Tracking</span><input data-live="1" data-prop="letter-spacing" value="${escapeHtml(ls.value)}" placeholder="${escapeHtml(ls.hint || "0")}" /></label>
    </div>
    <label class="lvb-field ${isTokenValue(family.value) ? "is-bound" : ""}"><span>Font</span>
      <span class="lvb-inline">
        <input data-live="1" data-prop="font-family" value="${escapeHtml(family.value)}" placeholder="${escapeHtml(family.hint || "Cinzel, serif")}" />
        <button type="button" class="lvb-mini" data-token-for="font-family">var</button>
      </span>
    </label>
    <div class="lvb-seg" data-seg="text-align">
      ${["left", "center", "right", "justify"].map((v) => `<button type="button" class="lvb-mini ${align === v ? "is-on" : ""}" data-set-prop="text-align" data-set-value="${v}">${v === "left" ? "Links" : v === "center" ? "Midden" : v === "right" ? "Rechts" : "Uitvul"}</button>`).join("")}
    </div>
    <div class="lvb-seg">
      ${["none", "uppercase", "lowercase", "capitalize"].map((v) => `<button type="button" class="lvb-mini ${transform === v ? "is-on" : ""}" data-set-prop="text-transform" data-set-value="${v}">${v === "none" ? "Aa" : v}</button>`).join("")}
    </div>
    <div class="lvb-seg">
      ${["none", "underline", "line-through"].map((v) => `<button type="button" class="lvb-mini ${decoration === v ? "is-on" : ""}" data-set-prop="text-decoration" data-set-value="${v}">${v === "none" ? "Geen" : v}</button>`).join("")}
    </div>`;
}

function sectionColor(ctx, node, prop, label) {
  const read = ctx.content.readProp(node, prop);
  const raw = read.value || read.hint || "";
  const bound = isTokenValue(read.value);
  const hex = toHexColor(raw || "#ffffff");
  const alpha = alphaFromColor(raw);
  const colors = ctx.tokens().filter((token) => token.group === "Kleuren").slice(0, 10);
  const recent = swatches.read();
  return `<div class="lvb-section">${label}</div>
    <div class="lvb-color ${bound ? "is-bound" : ""}" data-color-wrap data-prop="${prop}">
      <input data-live="1" data-prop="${prop}" data-role="color-hex" type="color" value="${hex}" />
      <input data-live="1" data-prop="${prop}" data-role="color-text" value="${escapeHtml(read.value)}" placeholder="${escapeHtml(read.hint || "")}" />
      <button type="button" class="lvb-mini" data-token-for="${prop}">var</button>
      ${bound ? `<button type="button" class="lvb-mini" data-detach="${prop}">Ontkoppel</button>` : ""}
      <label class="lvb-alpha"><span>Alpha</span><input data-live="1" data-prop="${prop}" data-role="color-alpha" type="range" min="0" max="1" step="0.01" value="${alpha}" /></label>
      <div class="lvb-swatches">
        ${[...recent, ...colors.map((token) => token.value)].slice(0, 12).map((color) => `<button type="button" class="lvb-swatch" style="background:${escapeHtml(color)}" data-swatch="${escapeHtml(color)}" data-swatch-prop="${prop}" title="${escapeHtml(color)}"></button>`).join("")}
      </div>
    </div>`;
}

function sectionBorder(ctx, node) {
  const width = ctx.content.readProp(node, "border-width");
  const style = ctx.content.readProp(node, "border-style").value || "solid";
  const color = ctx.content.readProp(node, "border-color");
  const radius = ctx.content.readProp(node, "border-radius");
  return `<div class="lvb-section">Rand</div>
    <div class="lvb-row">
      ${numField("Dikte", "border-width", width, true)}
      <label class="lvb-field"><span>Stijl</span>
        <select data-live="1" data-prop="border-style">
          ${["none", "solid", "dashed", "dotted"].map((v) => `<option ${style === v ? "selected" : ""}>${v}</option>`).join("")}
        </select>
      </label>
    </div>
    ${sectionColor(ctx, node, "border-color", "Randkleur")}
    <label class="lvb-field ${isTokenValue(radius.value) ? "is-bound" : ""}"><span>Radius</span>
      <span class="lvb-inline">
        <input data-live="1" data-prop="border-radius" value="${escapeHtml(radius.value)}" placeholder="${escapeHtml(radius.hint || "12px")}" />
        <button type="button" class="lvb-mini" data-token-for="border-radius">var</button>
        ${isTokenValue(radius.value) ? `<button type="button" class="lvb-mini" data-detach="border-radius">×</button>` : ""}
      </span>
    </label>
    <div class="lvb-row">
      ${corner(ctx, node, "border-top-left-radius", "TL")}
      ${corner(ctx, node, "border-top-right-radius", "TR")}
      ${corner(ctx, node, "border-bottom-right-radius", "BR")}
      ${corner(ctx, node, "border-bottom-left-radius", "BL")}
    </div>
    <p class="lvb-muted">Leeg = ${escapeHtml(color.hint || "geen")}</p>`;
}

function corner(ctx, node, prop, label) {
  const read = ctx.content.readProp(node, prop);
  return `<label class="lvb-field"><span>${label}</span><input data-live="1" data-prop="${prop}" value="${escapeHtml(read.value)}" placeholder="${escapeHtml(read.hint || "")}" /></label>`;
}

function sectionShadow(ctx, node) {
  const read = ctx.content.readProp(node, "box-shadow");
  const layers = parseShadowList(read.value);
  const rows = layers
    .map(
      (layer, i) => `<div class="lvb-shadow" data-shadow-row>
        <input data-live="1" data-shadow="x" value="${escapeHtml(numFrom(layer.x) ?? 0)}" title="x" />
        <input data-live="1" data-shadow="y" value="${escapeHtml(numFrom(layer.y) ?? 0)}" title="y" />
        <input data-live="1" data-shadow="blur" value="${escapeHtml(numFrom(layer.blur) ?? 0)}" title="blur" />
        <input data-live="1" data-shadow="spread" value="${escapeHtml(numFrom(layer.spread) ?? 0)}" title="spread" />
        <input data-live="1" data-shadow="color" type="text" value="${escapeHtml(layer.color)}" />
        <label><input data-live="1" data-shadow="inset" type="checkbox" ${layer.inset ? "checked" : ""}/> in</label>
        <button type="button" data-shadow-del="${i}">×</button>
      </div>`,
    )
    .join("");
  return `<div class="lvb-section">Schaduw</div>${rows || `<p class="lvb-muted">Geen lagen</p>`}
    <button type="button" class="lvb-btn" data-act="shadow-add">+ Laag</button>`;
}

function sectionLayout(ctx, node) {
  const display = ctx.content.readProp(node, "display").value || ctx.content.readProp(node, "display").hint || "block";
  const dir = ctx.content.readProp(node, "flex-direction").value || "row";
  const gap = ctx.content.readProp(node, "gap");
  const justify = ctx.content.readProp(node, "justify-content").value || "flex-start";
  const align = ctx.content.readProp(node, "align-items").value || "stretch";
  const cols = ctx.content.readProp(node, "grid-template-columns");
  return `<div class="lvb-section">Layout</div>
    <label class="lvb-field"><span>Display</span>
      <select data-live="1" data-prop="display">
        ${["block", "flex", "grid", "inline-flex", "inline-block", "none"].map((v) => `<option ${display === v ? "selected" : ""}>${v}</option>`).join("")}
      </select>
    </label>
    <div class="lvb-seg">
      ${["row", "column"].map((v) => `<button type="button" class="lvb-mini ${dir === v ? "is-on" : ""}" data-set-prop="flex-direction" data-set-value="${v}">${v === "row" ? "Rij" : "Kolom"}</button>`).join("")}
    </div>
    ${numField("Gap", "gap", gap, false)}
    <div class="lvb-section lvb-section-sub">Justify</div>
    <div class="lvb-seg">
      ${["flex-start", "center", "flex-end", "space-between"].map((v) => `<button type="button" class="lvb-mini ${justify === v ? "is-on" : ""}" data-set-prop="justify-content" data-set-value="${v}">${v.replace("flex-", "")}</button>`).join("")}
    </div>
    <div class="lvb-section lvb-section-sub">Align</div>
    <div class="lvb-seg">
      ${["flex-start", "center", "flex-end", "stretch"].map((v) => `<button type="button" class="lvb-mini ${align === v ? "is-on" : ""}" data-set-prop="align-items" data-set-value="${v}">${v.replace("flex-", "")}</button>`).join("")}
    </div>
    <label class="lvb-field"><span>Grid kolommen</span><input data-live="1" data-prop="grid-template-columns" value="${escapeHtml(cols.value)}" placeholder="1fr 1fr" /></label>`;
}

function sectionPosition(ctx, node) {
  const pos = ctx.content.readProp(node, "position").value || getComputedStyle(node).position || "static";
  const rot = ctx.content.readProp(node, "rotate");
  const rotVal = rot.value || (node.style.rotate || "").replace("deg", "") || "";
  return `<div class="lvb-section">Positie</div>
    <label class="lvb-field"><span>Position</span>
      <select data-live="1" data-prop="position" data-role="position-mode">
        ${["static", "relative", "absolute", "fixed", "sticky"].map((v) => `<option ${pos === v ? "selected" : ""}>${v}</option>`).join("")}
      </select>
    </label>
    <div class="lvb-row">
      ${numField("X", "left", ctx.content.readProp(node, "left"), true)}
      ${numField("Y", "top", ctx.content.readProp(node, "top"), true)}
    </div>
    <div class="lvb-row">
      ${numField("W", "width", ctx.content.readProp(node, "width"), true)}
      ${numField("H", "height", ctx.content.readProp(node, "height"), true)}
    </div>
    <div class="lvb-row">
      <label class="lvb-field"><span>Rotate</span><input data-live="1" data-prop="rotate" data-unit="deg" value="${escapeHtml(rotVal)}" placeholder="0" /></label>
      ${numField("Z-index", "z-index", ctx.content.readProp(node, "z-index"), false)}
    </div>
    <div class="lvb-row">
      ${numField("Right", "right", ctx.content.readProp(node, "right"), false)}
      ${numField("Bottom", "bottom", ctx.content.readProp(node, "bottom"), false)}
    </div>
    <label class="lvb-field"><span>Opacity</span><input data-live="1" data-prop="opacity" type="range" min="0" max="1" step="0.01" value="${escapeHtml(ctx.content.readProp(node, "opacity").value || ctx.content.readProp(node, "opacity").hint || "1")}" /></label>`;
}

function sectionAlign(ctx) {
  const count = ctx.session.selected.length;
  return `<div class="lvb-section">Uitlijnen ${count >= 2 ? `(${count})` : ""}</div>
    <div class="lvb-aligngrid">
      ${[
        ["left", "Links"],
        ["center", "Midden"],
        ["right", "Rechts"],
        ["top", "Boven"],
        ["middle", "Midden↕"],
        ["bottom", "Onder"],
      ]
        .map(([id, label]) => `<button type="button" class="lvb-mini" data-align="${id}">${label}</button>`)
        .join("")}
      <button type="button" class="lvb-mini" data-distribute="x">Verdeel H</button>
      <button type="button" class="lvb-mini" data-distribute="y">Verdeel V</button>
    </div>`;
}
