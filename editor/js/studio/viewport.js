/**
 * LEVIATHAN STUDIO — Design vs Preview viewport.
 * Design: live DOM editing. Preview: same-origin iframe sized to breakpoint
 * so @media / vw / fixed positioning match normal runtime.
 */

import { BREAKPOINTS } from "../constants.js";

export function createViewport(ctx) {
  let frame = null;
  let mode = "design"; // design | preview
  let custom = { width: null, height: null };

  function ensureChrome() {
    const root = ctx.chrome?.ui?.()?.root;
    if (!root) return null;
    let host = root.querySelector("[data-role='viewport-frame']");
    if (!host) {
      host = document.createElement("div");
      host.className = "lvb-viewport-frame";
      host.dataset.role = "viewport-frame";
      host.hidden = true;
      host.innerHTML = `<div class="lvb-viewport-label" data-role="viewport-label"></div><iframe title="Leviathan preview" data-role="viewport-iframe" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>`;
      root.appendChild(host);
    }
    return host;
  }

  function sizeFor(bp) {
    if (custom.width) return { width: custom.width, height: custom.height || Math.round(window.innerHeight * 0.75) };
    if (bp === "mobile") return { width: 390, height: 844 };
    if (bp === "tablet") return { width: 834, height: 1112 };
    return { width: Math.min(1440, window.innerWidth - 420), height: Math.min(900, window.innerHeight - 120) };
  }

  function setMode(next) {
    mode = next === "preview" ? "preview" : "design";
    ctx.store.setState({ viewMode: mode });
    const host = ensureChrome();
    if (!host) return;
    if (mode === "design") {
      host.hidden = true;
      document.body.classList.remove("lvb-preview-mode");
      // Clear old max-width hack classes — preview owns viewport sizing
      document.body.classList.remove("lvb-bp-tablet", "lvb-bp-mobile");
      ctx.content?.setStatus?.("Design-modus", "ok");
      return;
    }
    document.body.classList.add("lvb-preview-mode");
    host.hidden = false;
    refresh();
    ctx.content?.setStatus?.("Preview-viewport (echte mediaqueries)", "ok");
  }

  function refresh() {
    const host = ensureChrome();
    if (!host || mode !== "preview") return;
    const bp = ctx.store.getState().breakpoint || "desktop";
    const size = sizeFor(bp);
    host.style.width = `${size.width}px`;
    host.style.height = `${size.height}px`;
    const label = host.querySelector("[data-role='viewport-label']");
    if (label) label.textContent = `${BREAKPOINTS[bp]?.label || bp} · ${size.width}×${size.height}`;
    const iframe = host.querySelector("[data-role='viewport-iframe']");
    if (!iframe) return;
    const url = new URL(location.href);
    url.searchParams.set("lvb_preview", "1");
    // Avoid editor overlay inside iframe
    if (iframe.dataset.src !== url.pathname + url.search) {
      iframe.dataset.src = url.pathname + url.search;
      iframe.src = url.toString().replace(/\/$/, "") || url.toString();
      // Prefer same path without editor — Vite injects editor only when LEVIATHAN_EDITOR=1
      // Preview iframe still has editor env; hide chrome via CSS + bridge flag
    }
    iframe.addEventListener(
      "load",
      () => {
        try {
          iframe.contentDocument?.documentElement?.classList.add("lvb-preview-doc");
          iframe.contentDocument?.body?.classList.add("lvb-preview-doc");
          // Hide nested editor if injected
          const nested = iframe.contentDocument?.getElementById("lvb-root");
          if (nested) nested.style.display = "none";
        } catch {
          /* cross-origin unlikely on same origin */
        }
      },
      { once: true },
    );
  }

  function setCustom(width, height) {
    custom = { width: width ? Number(width) : null, height: height ? Number(height) : null };
    refresh();
  }

  function setBreakpoint(id) {
    ctx.store.setState({ breakpoint: id });
    if (mode === "preview") {
      refresh();
    } else {
      // Design mode: apply breakpoint overrides from content model (not CSS max-width hack)
      document.body.classList.remove("lvb-bp-tablet", "lvb-bp-mobile");
      ctx.content.reapply();
      // Visual frame chrome only
      const host = ensureChrome();
      if (host && id !== "desktop") {
        const size = sizeFor(id);
        host.hidden = false;
        host.classList.add("is-design-frame");
        host.style.width = `${size.width}px`;
        host.style.height = "auto";
        host.style.minHeight = `${Math.min(size.height, window.innerHeight - 140)}px`;
        const iframe = host.querySelector("iframe");
        if (iframe) iframe.hidden = true;
        const label = host.querySelector("[data-role='viewport-label']");
        if (label) label.textContent = `Design frame · ${size.width}px (overrides via documentmodel)`;
      } else if (host) {
        host.hidden = true;
        host.classList.remove("is-design-frame");
      }
    }
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    const label = id === "tablet" ? "Tablet" : id === "mobile" ? "Mobile" : "Desktop";
    ctx.content.setStatus(`Viewport ${label} · ${mode}`, "ok");
  }

  return {
    setMode,
    refresh,
    setCustom,
    setBreakpoint,
    get mode() {
      return mode;
    },
  };
}
