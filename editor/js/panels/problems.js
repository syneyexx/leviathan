/**
 * LEVIATHAN STUDIO — Design Problems panel.
 */

export function createProblemsPanel(ctx) {
  let host;

  return {
    id: "problems",
    title: "Problems",
    zone: "right",
    bind(el) {
      host = el;
    },
    signature() {
      const s = ctx.store.getState();
      return `${s.issuesEpoch || 0}|${s.issueCount || 0}|${s.uiEpoch}`;
    },
    render() {
      if (!host) return;
      const rows = ctx.issues?.list?.() || [];
      const checked = 5;
      host.innerHTML = `<h3>Design Problems</h3>
        <p class="lvb-muted">${rows.length} findings · ${checked} rules · geen totaalscore</p>
        <input type="search" placeholder="Filter…" data-role="q" aria-label="Filter problemen" />
        <div data-role="list"></div>
        <button type="button" class="lvb-btn" data-role="rescan" style="margin-top:8px">Rescan</button>`;
      const list = host.querySelector("[data-role='list']");
      const draw = (q = "") => {
        const items = ctx.issues.list({ query: q });
        list.innerHTML = items.length
          ? items
              .map(
                (f) => `<button type="button" class="lvb-issue" data-sev="${f.severity}" data-id="${f.id}">
              <strong>${f.message}</strong>
              <span class="lvb-muted">${f.category} · ${f.rule}${f.nodeKey ? ` · ${f.nodeKey}` : ""}</span>
              <span class="lvb-muted">${f.evidence || ""}</span>
            </button>`,
              )
              .join("")
          : `<p class="lvb-muted">Geen bevindingen</p>`;
      };
      draw();
      host.querySelector("[data-role='q']").addEventListener("input", (e) => draw(e.target.value));
      host.querySelector("[data-role='rescan']").addEventListener("click", () => {
        ctx.issues.scanNow();
        draw(host.querySelector("[data-role='q']").value);
      });
      list.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-id]");
        if (btn) ctx.issues.focusFinding(btn.dataset.id);
      });
    },
  };
}
