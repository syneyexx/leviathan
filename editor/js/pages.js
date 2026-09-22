/**
 * Leviathan Visual Editor — page / route switcher.
 * Navigates the real React SPA while keeping the editor overlay alive.
 * Undo history, selection keys, and camera are scoped per pathname.
 */

export const EDITOR_PAGES = [
  { path: "/", label: "Command" },
  { path: "/chat", label: "Chat" },
  { path: "/coding", label: "Coding" },
  { path: "/tasks", label: "Taken" },
  { path: "/research", label: "Research" },
  { path: "/brain", label: "Brain" },
  { path: "/memory", label: "Geheugen" },
  { path: "/knowledge", label: "Knowledge" },
  { path: "/evidence", label: "Evidence" },
  { path: "/datasets", label: "Bestanden" },
  { path: "/models", label: "Modellen" },
  { path: "/training", label: "Training" },
  { path: "/analytics", label: "Stats" },
  { path: "/media", label: "Media" },
  { path: "/media/youtube", label: "YouTube" },
  { path: "/media/tiktok", label: "TikTok" },
  { path: "/media/instagram", label: "Instagram" },
  { path: "/media/facebook", label: "Facebook" },
  { path: "/agents", label: "Agents" },
  { path: "/trading", label: "Trading" },
  { path: "/tools", label: "Modules" },
  { path: "/performance", label: "Performance" },
  { path: "/mcp", label: "MCP" },
  { path: "/workflows", label: "Workflows" },
  { path: "/console", label: "Console" },
  { path: "/settings", label: "Settings" },
];

export function createPages(ctx) {
  /** @type {Map<string, object>} */
  const pageBags = new Map();
  let current = location.pathname || "/";
  let navigating = false;

  function pathKey(p = location.pathname) {
    return String(p || "/").replace(/\/$/, "") || "/";
  }

  function stash() {
    const key = pathKey(current);
    pageBags.set(key, {
      selected: ctx.selection.keys(),
      history: ctx.commands.exportStack?.() || null,
      zoom: ctx.store.getState().zoom,
      panX: ctx.store.getState().panX,
      panY: ctx.store.getState().panY,
    });
  }

  function restoreBag(bag) {
    if (!bag) return;
    if (bag.history && ctx.commands.importStack) ctx.commands.importStack(bag.history);
    else ctx.commands.reset?.();
    if (bag.zoom != null || bag.panX != null) {
      ctx.camera.setCamera({
        zoom: bag.zoom ?? 1,
        panX: bag.panX ?? 0,
        panY: bag.panY ?? 0,
      });
    }
    if (bag.selected?.length) ctx.selection.reselect(bag.selected);
  }

  function go(path) {
    const next = pathKey(path);
    if (next === pathKey(location.pathname) || navigating) return;
    navigating = true;
    stash();
    ctx.selection.clear();
    ctx.session.hoverEl = null;
    ctx.session.measure = { a: null, b: null, live: null, between: null };
    ctx.session._snapGuides = null;
    ctx.session._marquee = null;
    ctx.session.dropEl = null;
    ctx.chrome?.clearGuides?.();

    // Prefer React Router client navigation so the SPA stays mounted
    try {
      const state = { lvbEditor: true };
      window.history.pushState(state, "", next);
      window.dispatchEvent(new PopStateEvent("popstate", { state }));
    } catch {
      window.location.assign(next);
      return;
    }

    current = next;
    ctx.store.setState({ page: next });
    ctx.content.setStatus(`Pagina ${labelFor(next)}`, "ok");

    // Re-apply overrides after React paints the new route
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        ctx.content.reapply?.();
        const bag = pageBags.get(next);
        if (bag) restoreBag(bag);
        else ctx.commands.reset?.();
        ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
        ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
        ctx.chrome?.schedulePaint?.();
        ctx.chrome?.invalidateAll?.();
        navigating = false;
      });
    });
  }

  function labelFor(path) {
    const hit = EDITOR_PAGES.find((p) => pathKey(p.path) === pathKey(path));
    return hit?.label || path;
  }

  function currentPage() {
    return pathKey(location.pathname);
  }

  function attach() {
    window.addEventListener("popstate", () => {
      if (navigating) return;
      const next = pathKey(location.pathname);
      if (next === pathKey(current)) return;
      stash();
      current = next;
      ctx.store.setState({ page: next });
      requestAnimationFrame(() => {
        ctx.content.reapply?.();
        const bag = pageBags.get(next);
        if (bag) restoreBag(bag);
        ctx.chrome?.schedulePaint?.();
        ctx.chrome?.invalidateAll?.();
      });
    });
  }

  return {
    EDITOR_PAGES,
    go,
    labelFor,
    currentPage,
    attach,
    stash,
  };
}
