/**
 * LEVIATHAN STUDIO — pages panel (left rail context).
 */

export function createPagesPanel(ctx) {
  let host;

  return {
    id: "pages",
    title: "Pages",
    zone: "left",
    bind(el) {
      host = el;
    },
    signature() {
      return `${ctx.pages?.currentPage?.()}|${ctx.store.getState().uiEpoch}`;
    },
    render() {
      if (!host) return;
      const pages = ctx.pages?.discoverRoutes?.() || [];
      const cur = ctx.pages?.currentPage?.();
      host.innerHTML = `<h3>Pages</h3>
        <input type="search" placeholder="Zoek pagina…" data-role="page-filter" aria-label="Zoek pagina" />
        <div data-role="page-list"></div>`;
      const list = host.querySelector("[data-role='page-list']");
      const draw = (q = "") => {
        const query = q.trim().toLowerCase();
        list.innerHTML = pages
          .filter((p) => !query || p.label.toLowerCase().includes(query) || p.path.includes(query))
          .map(
            (p) =>
              `<button type="button" class="lvb-layer-row${p.path.replace(/\/$/, "") === cur ? " is-active" : ""}" data-go="${p.path}" style="width:100%;border:0;background:transparent;color:inherit;text-align:left">
                <span>${p.label}</span><span class="lvb-muted" style="margin-left:auto;font-family:var(--studio-mono)">${p.path}</span>
              </button>`,
          )
          .join("");
      };
      draw();
      host.querySelector("[data-role='page-filter']").addEventListener("input", (e) => draw(e.target.value));
      list.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-go]");
        if (btn) ctx.pages.go(btn.dataset.go);
      });
    },
  };
}
