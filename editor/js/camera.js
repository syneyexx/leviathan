/**
 * Leviathan Visual Builder — camera.
 * Zoom/pan is a visual transform on #root and is never written to saved CSS.
 */

import { clamp } from "./geometry.js";
import { ZOOM_MAX, ZOOM_MIN } from "./constants.js";

export function createCamera(ctx) {
  function root() {
    return document.getElementById("root");
  }

  function layoutOrigin() {
    const el = root();
    if (!el) return { x: 0, y: 0 };
    const rect = el.getBoundingClientRect();
    const { panX, panY } = ctx.store.getState();
    return { x: rect.left - panX, y: rect.top - panY };
  }

  function apply() {
    const el = root();
    if (!el) return;
    const { zoom, panX, panY } = ctx.store.getState();
    const identity = Math.abs(zoom - 1) < 0.001 && Math.abs(panX) < 0.5 && Math.abs(panY) < 0.5;
    if (identity) {
      el.style.transform = "";
      el.style.transformOrigin = "";
    } else {
      el.style.transformOrigin = "0 0";
      el.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
    }
    ctx.chrome?.syncCamera?.();
    ctx.chrome?.schedulePaint?.();
  }

  function setCamera(partial) {
    const s = ctx.store.getState();
    const zoom = clamp(partial.zoom ?? s.zoom ?? 1, ZOOM_MIN, ZOOM_MAX);
    const panX = partial.panX ?? s.panX ?? 0;
    const panY = partial.panY ?? s.panY ?? 0;
    ctx.store.setState({ zoom, panX, panY });
    apply();
  }

  function zoomAt(clientX, clientY, nextZoom) {
    const s = ctx.store.getState();
    const origin = layoutOrigin();
    const z = clamp(nextZoom, ZOOM_MIN, ZOOM_MAX);
    const safe = s.zoom || 1;
    const localX = (clientX - origin.x - s.panX) / safe;
    const localY = (clientY - origin.y - s.panY) / safe;
    setCamera({
      zoom: z,
      panX: clientX - origin.x - localX * z,
      panY: clientY - origin.y - localY * z,
    });
  }

  function reset() {
    setCamera({ zoom: 1, panX: 0, panY: 0 });
    ctx.content?.setStatus("Zoom 100%", "ok");
  }

  function fitWidth() {
    const el = document.querySelector(".lv-app") || root();
    if (!el) return;
    const origin = layoutOrigin();
    const z = clamp((window.innerWidth - 80) / Math.max(el.offsetWidth, 1), ZOOM_MIN, ZOOM_MAX);
    setCamera({
      zoom: z,
      panX: (window.innerWidth - el.offsetWidth * z) / 2 - origin.x,
      panY: 28 - origin.y,
    });
    ctx.content?.setStatus("Passend op breedte", "ok");
  }

  function fitSelection() {
    const el = ctx.session.primary;
    if (!el) {
      ctx.content?.setStatus("Geen selectie", "dirty");
      return;
    }
    const rect = el.getBoundingClientRect();
    const s = ctx.store.getState();
    const origin = layoutOrigin();
    const safe = s.zoom || 1;
    const localW = Math.max(rect.width / safe, 1);
    const localH = Math.max(rect.height / safe, 1);
    const localX = (rect.left - origin.x - s.panX) / safe;
    const localY = (rect.top - origin.y - s.panY) / safe;
    const z = clamp(Math.min((window.innerWidth * 0.62) / localW, (window.innerHeight * 0.62) / localH), ZOOM_MIN, ZOOM_MAX);
    setCamera({
      zoom: z,
      panX: window.innerWidth / 2 - (localX + localW / 2) * z - origin.x,
      panY: window.innerHeight / 2 - (localY + localH / 2) * z - origin.y,
    });
    ctx.content?.setStatus("Passend op selectie", "ok");
  }

  function screenToLocal(x, y) {
    const s = ctx.store.getState();
    const origin = layoutOrigin();
    const safe = s.zoom || 1;
    return { x: (x - origin.x - s.panX) / safe, y: (y - origin.y - s.panY) / safe };
  }

  function localToScreen(x, y) {
    const s = ctx.store.getState();
    const origin = layoutOrigin();
    return { x: origin.x + s.panX + x * (s.zoom || 1), y: origin.y + s.panY + y * (s.zoom || 1) };
  }

  function setBreakpoint(id) {
    document.body.classList.remove("lvb-bp-tablet", "lvb-bp-mobile");
    if (id === "tablet" || id === "mobile") document.body.classList.add(`lvb-bp-${id}`);
    ctx.store.setState({ breakpoint: id });
    ctx.content.reapply();
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    const label = id === "tablet" ? "Tablet" : id === "mobile" ? "Mobile" : "Desktop";
    ctx.content.setStatus(`Viewport ${label}`, "ok");
  }

  return {
    apply,
    setCamera,
    zoomAt,
    reset,
    fitWidth,
    fitSelection,
    layoutOrigin,
    screenToLocal,
    localToScreen,
    setBreakpoint,
  };
}
