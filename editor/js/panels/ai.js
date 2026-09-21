/**
 * Leviathan Visual Builder — AI instructie.
 * Apply only after explicit confirmation. 501 keeps the flow without writing.
 */

export function createAi(ctx) {
  let notes = "Nog geen resultaat. Niets wordt geschreven zonder Toepassen.";
  let draft = "";
  return {
    id: "ai",
    title: "AI",
    zone: "right",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      return `${ctx.store.getState().sel}|${notes.length}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("input", (event) => {
        if (event.target.dataset?.role === "ai-instruction") draft = event.target.value;
      });
      host.addEventListener("click", async (event) => {
        if (!event.target.closest("[data-act='ai-apply']")) return;
        const node = ctx.session.primary;
        const instruction = (host.querySelector("[data-role='ai-instruction']")?.value || draft).trim();
        draft = instruction;
        if (!instruction) {
          notes = "Schrijf eerst een instructie.";
          this._sig = null;
          this.render();
          return;
        }
        const selectionHtml = node ? node.outerHTML : "";
        const selectionCss = node ? ctx.content.rawDecls(node) : "";
        notes = "Bezig…";
        this._sig = null;
        this.render();
        try {
          const data = await ctx.api.editorAi({ selectionHtml, selectionCss, instruction });
          applyResult(ctx, node, data);
          notes = data.notes || "Toegepast.";
        } catch (err) {
          notes = err.payload?.notes || err.message || "AI niet beschikbaar";
          ctx.content.setStatus(notes, "dirty");
        }
        this._sig = null;
        this.render();
      });
    },
    render() {
      if (!this.host) return;
      this.host.innerHTML = `<p class="lvb-muted">Stuurt selectie-HTML, CSS en je instructie. Toepassen is de bevestiging — er is geen auto-write.</p>
        <textarea data-role="ai-instruction" rows="6" placeholder="Bijv. maak de titel gouden Cinzel en meer tracking…">${escapeNote(draft)}</textarea>
        <button type="button" class="lvb-btn lvb-btn-primary" data-act="ai-apply">Toepassen</button>
        <p class="lvb-ai-notes">${escapeNote(notes)}</p>`;
    },
  };
}

function escapeNote(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function applyResult(ctx, node, data) {
  if (!data || data.error) return;
  ctx.commands.capture("ai", () => {
    if (node && data.cssDecls && typeof data.cssDecls === "object") {
      for (const [key, value] of Object.entries(data.cssDecls)) {
        if (typeof value === "string") ctx.content.applyProp(node, key, value);
      }
    }
    if (node?.dataset?.lvbId && typeof data.html === "string" && data.html.trim()) {
      const keepStyle = node.getAttribute("style");
      const id = node.dataset.lvbId;
      const wrap = document.createElement("div");
      wrap.innerHTML = data.html.trim();
      const next = wrap.firstElementChild;
      if (next) {
        next.dataset.lvbId = id;
        if (keepStyle) next.setAttribute("style", keepStyle);
        if (node.dataset.lvbComponentId) next.dataset.lvbComponentId = node.dataset.lvbComponentId;
        node.replaceWith(next);
        ctx.selection.replaceElement(node, next);
        const content = ctx.content.ensure();
        const entry = content.nodes.find((n) => n.id === id);
        if (entry) entry.html = next.outerHTML;
        ctx.store.setState({ content });
        ctx.content.markContentDirty();
      }
    }
  });
  ctx.content.setStatus(data.notes || "AI toegepast", "ok");
  ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
  ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
}
