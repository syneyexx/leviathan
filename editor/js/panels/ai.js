/**
 * Leviathan Visual Builder — AI instructie (production-ready UI).
 * Apply only after explicit confirmation. 501 keeps the flow without writing.
 */

export function createAi(ctx) {
  let notes = "Nog geen resultaat. Niets wordt geschreven zonder Toepassen.";
  let draft = "";
  let preview = null;
  return {
    id: "ai",
    title: "AI",
    zone: "right",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      return `${ctx.store.getState().sel}|${notes.length}|${preview ? 1 : 0}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("input", (event) => {
        if (event.target.dataset?.role === "ai-instruction") draft = event.target.value;
      });
      host.addEventListener("click", async (event) => {
        if (event.target.closest("[data-act='ai-clear']")) {
          preview = null;
          notes = "Concept gewist.";
          this._sig = null;
          this.render();
          return;
        }
        if (!event.target.closest("[data-act='ai-apply']")) return;
        const nodes = ctx.selection.mutable("edit");
        const node = nodes[0] || ctx.session.primary;
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
        const scope = nodes.length > 1 ? `${nodes.length} elementen` : node ? ctx.selection.labelFor(node) : "geen selectie";
        notes = `Bezig… (${scope})`;
        preview = null;
        this._sig = null;
        this.render();
        try {
          const data = await ctx.api.editorAi({ selectionHtml, selectionCss, instruction, scope });
          preview = {
            cssDecls: data.cssDecls || null,
            html: typeof data.html === "string" ? data.html : null,
            notes: data.notes || "",
          };
          applyResult(ctx, nodes.length ? nodes : node ? [node] : [], data);
          notes = data.notes || "Toegepast (undo beschikbaar).";
          preview = null;
        } catch (err) {
          const status = err.status || err.payload?.status;
          if (status === 501 || /501|not implemented|niet beschikbaar/i.test(String(err.message || ""))) {
            notes = "AI-model niet verbonden (501). Instructie bewaard — er is niets geschreven.";
          } else {
            notes = err.payload?.notes || err.message || "AI niet beschikbaar";
          }
          ctx.content.setStatus(notes, "dirty");
        }
        this._sig = null;
        this.render();
      });
    },
    render() {
      if (!this.host) return;
      const count = ctx.session.selected.length;
      const label = count > 1 ? `${count} elementen` : ctx.session.primary ? ctx.selection.labelFor(ctx.session.primary) : "geen selectie";
      this.host.innerHTML = `<p class="lvb-muted">Context: <b>${escapeNote(label)}</b>. Stuurt HTML + CSS + instructie. <b>Toepassen</b> is de enige write — undo blijft gelden.</p>
        <textarea data-role="ai-instruction" rows="6" placeholder="Bijv. maak de titel gouden Cinzel en meer tracking…">${escapeNote(draft)}</textarea>
        <div class="lvb-chip-row">
          <button type="button" class="lvb-btn lvb-btn-primary" data-act="ai-apply">Toepassen</button>
          <button type="button" class="lvb-chip" data-act="ai-clear">Wis</button>
        </div>
        ${preview?.cssDecls ? `<div class="lvb-section">Voorstel CSS</div><pre class="lvb-ai-preview">${escapeNote(JSON.stringify(preview.cssDecls, null, 2))}</pre>` : ""}
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

function applyResult(ctx, nodes, data) {
  if (!data || data.error) return;
  ctx.commands.capture("ai", () => {
    for (const node of nodes) {
      if (data.cssDecls && typeof data.cssDecls === "object") {
        for (const [key, value] of Object.entries(data.cssDecls)) {
          if (typeof value === "string") ctx.content.applyProp(node, key, value);
        }
      }
      if (node?.dataset?.lvbId && typeof data.html === "string" && data.html.trim() && nodes.length === 1) {
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
    }
  });
  ctx.content.setStatus(data.notes || "AI toegepast", "ok");
  ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
  ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
}
