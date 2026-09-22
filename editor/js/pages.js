/**
 * LEVIATHAN STUDIO — page / route switcher.
 * Navigates the real React SPA while keeping the editor overlay alive.
 * Selection + camera are scoped per pathname.
 * History is GLOBAL with scoped patches (undo on A never clobbers later B edits incorrectly).
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
  let readyWait = 0;

  function pathKey(p = location.pathname) {
    return String(p || "/").replace(/\/$/, "") || "/";
  }

  function stash() {
    const key = pathKey(current);
    pageBags.set(key, {
      selected: ctx.selection.keys(),
      zoom: ctx.store.getState().zoom,
      panX: ctx.store.getState().panX,
      panY: ctx.store.getState().panY,
    });
  }

  function restoreBag(bag) {
    if (!bag) return;
    if (bag.zoom != null || bag.panX != null) {
      ctx.camera.setCamera({
        zoom: bag.zoom ?? 1,
        panX: bag.panX ?? 0,
        panY: bag.panY ?? 0,
      });
    }
    if (bag.selected?.length) ctx.selection.reselect(bag.selected);
  }

  function waitForRoute(done) {
    clearTimeout(readyWait);
    let frames = 0;
    const tick = () => {
      frames += 1;
      const root = document.getElementById("root");
      const ready = root && (root.querySelector(".lv-app, main, [data-page]") || frames > 12);
      if (ready) {
        done();
        return;
      }
      readyWait = requestAnimationFrame(tick);
    };
    readyWait = requestAnimationFrame(tick);
  }

  function afterNavigate(next) {
    waitForRoute(() => {
      ctx.content.reapply?.();
      const bag = pageBags.get(next);
      if (bag) restoreBag(bag);
      ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
      ctx.store.setState({ uiEpoch: ctx.session.uiEpoch, page: next });
      ctx.chrome?.schedulePaint?.();
      ctx.chrome?.invalidateAll?.();
      navigating = false;
    });
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
    afterNavigate(next);
  }

  function labelFor(path) {
    const hit = EDITOR_PAGES.find((p) => pathKey(p.path) === pathKey(path));
    return hit?.label || path;
  }

  function currentPage() {
    return pathKey(location.pathname);
  }

  /** Prefer live router routes when the app exposes them. */
  function discoverRoutes() {
    const fromApp = ctx.session?.routeList;
    if (Array.isArray(fromApp) && fromApp.length) return fromApp;
    return EDITOR_PAGES;
  }

  function attach() {
    window.addEventListener("popstate", () => {
      if (navigating) return;
      const next = pathKey(location.pathname);
      if (next === pathKey(current)) return;
      stash();
      current = next;
      ctx.store.setState({ page: next });
      afterNavigate(next);
    });
  }

  return {
    EDITOR_PAGES,
    go,
    labelFor,
    currentPage,
    attach,
    stash,
    discoverRoutes,
  };
}
