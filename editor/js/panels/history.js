/**
 * LEVIATHAN STUDIO — History timeline + checkpoints.
 */

export function createHistoryPanel(ctx) {
  let host;

  return {
    id: "history",
    title: "History",
    zone: "bottom",
    bind(el) {
      host = el;
    },
    signature() {
      return `${ctx.store.getState().historyDepth}|${ctx.store.getState().historyLabel}|${ctx.commands._debug?.().index}`;
    },
    render() {
      if (!host) return;
      const rows = ctx.commands.getTimeline?.() || [];
      host.innerHTML = `<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
          <h3 style="margin:0">History</h3>
          <button type="button" class="lvb-btn" data-role="checkpoint">Named checkpoint</button>
        </div>
        <div data-role="list"></div>`;
      const list = host.querySelector("[data-role='list']");
      list.innerHTML = rows
        .slice()
        .reverse()
        .map(
          (r) => `<div class="lvb-issue" data-sev="${r.checkpoint ? "warning" : "info"}">
            <strong>${r.label}</strong>
            <span class="lvb-muted">${r.page || "—"} · ${new Date(r.at).toLocaleTimeString()}${r.checkpoint ? " · checkpoint" : ""}</span>
          </div>`,
        )
        .join("") || `<p class="lvb-muted">Nog geen history</p>`;
      host.querySelector("[data-role='checkpoint']").addEventListener("click", () => {
        const name = prompt("Checkpoint naam", "Voor responsive redesign");
        if (name) ctx.studio?.createCheckpoint?.(name);
      });
    },
  };
}
