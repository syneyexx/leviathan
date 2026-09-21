/**
 * Leviathan Visual Builder — insert, clipboard, components, images.
 */

import { escapeHtml, uid } from "./util.js";

const PRESETS = {
  text: {
    label: "tekst",
    html: `<p class="lvb-widget lvb-text" style="margin:0;color:#E8E4DC;font-size:14px;">Nieuwe tekst — dubbelklik om te bewerken</p>`,
  },
  heading: {
    label: "titel",
    html: `<h2 class="lvb-widget lvb-heading" style="margin:0;color:#F5DFA9;font-family:Cinzel,serif;letter-spacing:0.2em;text-transform:uppercase;">Nieuwe titel</h2>`,
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

export function createWidgets(ctx) {
  function mountParent(parentSel) {
    if (parentSel) {
      try {
        const explicit = document.querySelector(parentSel);
        if (explicit) return explicit;
      } catch {
        /* ignore */
      }
    }
    const selected = ctx.session.primary;
    if (selected) {
      if (ctx.selection.isShell(selected)) return selected;
      const container = selected.tagName === "DIV" || selected.tagName === "SECTION" || selected.tagName === "ARTICLE";
      if (selected.dataset?.lvbId && container) return selected;
      return selected.parentElement || selected;
    }
    return document.querySelector(".lv-main") || document.getElementById("root") || document.body;
  }

  function insertWidget({ html, label, parentSel, styles, componentId, variant }) {
    let created = null;
    ctx.commands.capture(`invoegen:${label || "widget"}`, () => {
      const content = ctx.content.ensure();
      const id = uid();
      const wrap = document.createElement("div");
      wrap.innerHTML = String(html || "").trim();
      const el = wrap.firstElementChild;
      if (!el) return;
      el.dataset.lvbId = id;
      el.dataset.lvbLabel = label || "widget";
      if (componentId) el.dataset.lvbComponentId = componentId;
      if (variant) el.dataset.lvbVariant = variant;
      el.style.position = styles?.position || el.style.position || "relative";
      el.style.left = styles?.left || el.style.left || "0px";
      el.style.top = styles?.top || el.style.top || "0px";
      if (styles) {
        for (const [k, v] of Object.entries(styles)) {
          if (v != null && v !== "") el.style.setProperty(k === "zIndex" ? "z-index" : k, String(v));
        }
      }
      const parent = mountParent(parentSel);
      parent.appendChild(el);
      content.nodes.push({
        id,
        label: label || "widget",
        parent: ctx.selection.selectorFor(parent),
        html: el.outerHTML,
        componentId: componentId || undefined,
        variant: variant || undefined,
        styles: {
          position: el.style.position,
          left: el.style.left,
          top: el.style.top,
          width: el.style.width,
          height: el.style.height,
        },
      });
      ctx.store.setState({ content });
      ctx.content.markContentDirty();
      created = el;
    });
    if (created) {
      ctx.selection.set([created], created);
      ctx.content.setStatus(`${label || "Element"} toegevoegd`, "ok");
      ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
      ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    }
    return created;
  }

  function insertPreset(type) {
    if (type === "image") {
      ctx.chrome?.openMedia?.("insert");
      return;
    }
    const preset = PRESETS[type];
    if (!preset) return;
    insertWidget(preset);
  }

  function insertImageAtUrl(url, alt = "Image") {
    const safeAlt = escapeHtml(alt || "Image");
    const safeUrl = escapeHtml(url);
    return insertWidget({
      label: "image",
      html: `<img class="lvb-widget lvb-image" src="${safeUrl}" alt="${safeAlt}" style="display:block;width:240px;max-width:100%;height:auto;border-radius:8px;object-fit:cover;" />`,
      styles: { position: "relative", left: "12px", top: "12px", width: "240px" },
    });
  }

  function serialize(el) {
    if (!el) return null;
    return {
      html: el.cloneNode(true).outerHTML,
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
    const el = ctx.session.primary;
    ctx.session.clipboard = serialize(el);
    if (!ctx.session.clipboard) {
      ctx.content.setStatus("Niets geselecteerd", "dirty");
      return;
    }
    try {
      navigator.clipboard?.writeText(ctx.session.clipboard.html);
    } catch {
      /* clipboard optional */
    }
    ctx.content.setStatus("Gekopieerd", "ok");
  }

  function pasteClipboard() {
    const data = ctx.session.clipboard;
    if (!data) {
      ctx.content.setStatus("Klembord leeg", "dirty");
      return;
    }
    const el = insertWidget({
      html: data.html,
      label: "plakken",
      styles: {
        ...data.styles,
        left: `${(parseFloat(data.styles?.left) || 0) + 16}px`,
        top: `${(parseFloat(data.styles?.top) || 0) + 16}px`,
        position: data.styles?.position || "relative",
      },
    });
    if (el && data.src && el.tagName === "IMG") el.setAttribute("src", data.src);
  }

  function duplicateSelection() {
    copySelection();
    pasteClipboard();
  }

  function deleteSelection() {
    const els = [...ctx.session.selected];
    if (!els.length) return;
    const blocked = els.filter((el) => !ctx.selection.canMutate(el, "delete"));
    if (blocked.length === els.length) {
      ctx.content.setStatus(ctx.selection.isShell(els[0]) ? "Shell-elementen kun je niet verwijderen" : "Element is gelocked", "dirty");
      return;
    }
    ctx.commands.capture("verwijderen", () => {
      const content = ctx.content.ensure();
      for (const el of els) {
        if (!ctx.selection.canMutate(el, "delete")) continue;
        if (el.dataset.lvbId) {
          content.nodes = content.nodes.filter((n) => n.id !== el.dataset.lvbId);
          el.remove();
        } else {
          ctx.content.applyProp(el, "display", "none");
          ctx.content.patchEntry(ctx.selection.selectorFor(el), { hide: true });
        }
      }
      ctx.store.setState({ content: ctx.content.ensure() });
    });
    ctx.selection.clear();
    ctx.content.setStatus("Verwijderd / verborgen", "ok");
  }

  function toggleLock(el = ctx.session.primary) {
    if (!el) return;
    const selector = ctx.selection.selectorFor(el);
    const next = !ctx.selection.isLocked(el);
    ctx.commands.capture(next ? "lock" : "unlock", () => {
      if (next) el.dataset.lvbLocked = "1";
      else delete el.dataset.lvbLocked;
      ctx.content.patchEntry(selector, { locked: next });
    });
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    ctx.content.setStatus(next ? "Gelocked" : "Unlocked", "ok");
    ctx.chrome?.schedulePaint?.();
  }

  function setHidden(el, hidden) {
    if (!el) return;
    ctx.commands.capture(hidden ? "verbergen" : "tonen", () => {
      ctx.content.applyProp(el, "display", hidden ? "none" : "");
      ctx.content.patchEntry(ctx.selection.selectorFor(el), { hide: hidden });
      if (!hidden) el.style.removeProperty("display");
    });
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
  }

  function bumpZ(dir) {
    const el = ctx.session.primary;
    if (!el || !ctx.selection.canMutate(el)) return;
    const current = parseInt(el.style.zIndex || getComputedStyle(el).zIndex, 10);
    const z = (Number.isFinite(current) ? current : 1) + dir;
    ctx.commands.capture("z-index", () => {
      el.style.zIndex = String(z);
      ctx.content.applyProp(el, "z-index", String(z));
    });
  }

  function createComponent() {
    const el = ctx.session.primary;
    if (!el) {
      ctx.content.setStatus("Geen selectie", "dirty");
      return;
    }
    const name = ctx.selection.labelFor(el);
    ctx.commands.capture("component", () => {
      const content = ctx.content.ensure();
      const id = uid("cmp");
      const clone = el.cloneNode(true);
      clone.removeAttribute("data-lvb-id");
      delete clone.dataset.lvbId;
      const component = {
        id,
        name,
        html: clone.outerHTML,
        defaultStyles: {
          position: el.style.position,
          left: el.style.left,
          top: el.style.top,
          width: el.style.width,
          height: el.style.height,
        },
        variant: "",
      };
      content.components.push(component);
      el.dataset.lvbComponentId = id;
      const node = content.nodes.find((n) => n.id === el.dataset.lvbId);
      if (node) node.componentId = id;
      ctx.store.setState({ content });
      ctx.content.markContentDirty();
    });
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    ctx.content.setStatus("Component gemaakt", "ok");
  }

  function insertComponent(id) {
    const component = ctx.content.ensure().components.find((c) => c.id === id);
    if (!component) return;
    insertWidget({
      html: component.html,
      label: component.name || "component",
      styles: component.defaultStyles || {},
      componentId: component.id,
      variant: component.variant || "",
    });
  }

  function updateMaster(id, html, variant) {
    ctx.commands.capture("master", () => {
      const content = ctx.content.ensure();
      const component = content.components.find((c) => c.id === id);
      if (!component) return;
      component.html = html;
      if (variant != null) component.variant = variant;
      document.querySelectorAll(`[data-lvb-component-id="${CSS.escape(id)}"]`).forEach((el) => {
        if (ctx.selection.isBuilderNode(el)) return;
        const keepStyle = el.getAttribute("style");
        const keepId = el.dataset.lvbId || "";
        const keepLabel = el.dataset.lvbLabel || "";
        const keepVariant = variant || el.dataset.lvbVariant || "";
        const wrap = document.createElement("div");
        wrap.innerHTML = String(html || "").trim();
        const next = wrap.firstElementChild;
        if (!next) return;
        if (keepStyle) next.setAttribute("style", keepStyle);
        if (keepId) next.dataset.lvbId = keepId;
        next.dataset.lvbComponentId = id;
        if (keepLabel) next.dataset.lvbLabel = keepLabel;
        if (keepVariant) next.dataset.lvbVariant = keepVariant;
        el.replaceWith(next);
        ctx.selection.replaceElement(el, next);
        const node = content.nodes.find((n) => n.id === keepId);
        if (node) {
          node.html = next.outerHTML;
          node.componentId = id;
          node.variant = keepVariant || undefined;
        }
      });
      ctx.store.setState({ content });
      ctx.content.markContentDirty();
    });
    ctx.content.setStatus("Instances bijgewerkt", "ok");
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
  }

  function renameComponent(id, name) {
    const content = ctx.content.ensure();
    const component = content.components.find((c) => c.id === id);
    if (!component) return;
    ctx.commands.capture("component-naam", () => {
      component.name = name;
      ctx.store.setState({ content });
      ctx.content.markContentDirty();
    });
  }

  async function uploadFile(file, mode = "insert") {
    ctx.content.setStatus("Image uploaden…", "");
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error("Bestand lezen mislukt"));
      reader.readAsDataURL(file);
    });
    const uploaded = await ctx.api.upload(file.name, dataUrl);
    if (mode === "replace" && ctx.session.primary?.tagName === "IMG") {
      const el = ctx.session.primary;
      const oldSrc = el.getAttribute("src") || "";
      ctx.commands.capture("image", () => {
        el.setAttribute("src", uploaded.url);
        ctx.content.patchEntry(ctx.selection.selectorFor(el), { src: uploaded.url });
      });
      if (oldSrc && oldSrc !== uploaded.url && !el.dataset.lvbId) {
        try {
          await ctx.api.replaceText(oldSrc, uploaded.url);
        } catch (err) {
          ctx.content.setStatus(String(err.message || err), "dirty");
        }
      }
      ctx.content.setStatus("Image vervangen", "ok");
    } else {
      insertImageAtUrl(uploaded.url, file.name);
    }
    return uploaded.url;
  }

  return {
    PRESETS,
    insertWidget,
    insertPreset,
    insertImageAtUrl,
    copySelection,
    pasteClipboard,
    duplicateSelection,
    deleteSelection,
    toggleLock,
    setHidden,
    bumpZ,
    createComponent,
    insertComponent,
    updateMaster,
    renameComponent,
    uploadFile,
  };
}
