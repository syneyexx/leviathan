/**
 * LEVIATHAN STUDIO — AI panel with Generate → Review → Apply.
 */

export function createAi(ctx) {
  let host;
  let proposal = null;

  return {
    id: "ai",
    title: "AI",
    zone: "right",
    bind(el) {
      host = el;
    },
    signature() {
      return `${ctx.store.getState().sel}|${proposal?.id || ""}|${ctx.store.getState().uiEpoch}`;
    },
    render() {
      if (!host) return;
      const primary = ctx.session.primary;
      host.innerHTML = `
        <h3>AI Design Copilot</h3>
        <p class="lvb-muted">Modes: Explain · Propose · Apply. Modelbeschikbaarheid is een expliciete capability.</p>
        <div class="lvb-field"><label>Mode</label>
          <select data-role="mode">
            <option value="explain">Explain selection</option>
            <option value="propose">Propose improvements</option>
            <option value="apply">Apply instruction</option>
          </select>
        </div>
        <div class="lvb-field"><label>Scope</label>
          <select data-role="scope">
            <option value="selection">Selectie</option>
            <option value="component">Component</option>
            <option value="page">Pagina (expliciet)</option>
          </select>
        </div>
        <div class="lvb-field" style="grid-template-columns:1fr"><label>Instructie</label>
          <textarea data-role="instruction" rows="4" placeholder="Bijv. verbeter spacing zonder layout te breken"></textarea>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="lvb-btn lvb-btn-primary" data-role="generate">Genereren</button>
          <button type="button" class="lvb-btn" data-role="apply" ${proposal ? "" : "disabled"}>Toepassen</button>
          <button type="button" class="lvb-btn" data-role="cancel">Annuleren</button>
        </div>
        <div data-role="notes" class="lvb-muted" style="margin-top:10px"></div>
        <pre data-role="diff" style="margin-top:8px;font-family:var(--studio-mono);font-size:11px;white-space:pre-wrap;color:var(--studio-text-muted)"></pre>`;

      const notes = host.querySelector("[data-role='notes']");
      const diff = host.querySelector("[data-role='diff']");
      if (proposal) {
        notes.textContent = proposal.notes || "Voorstel klaar voor review";
        diff.textContent = JSON.stringify(proposal.preview || proposal.patches || {}, null, 2);
      }

      host.querySelector("[data-role='generate']").addEventListener("click", async () => {
        const mode = host.querySelector("[data-role='mode']").value;
        const scope = host.querySelector("[data-role='scope']").value;
        const instruction = host.querySelector("[data-role='instruction']").value.trim();
        notes.textContent = "Bezig…";
        diff.textContent = "";
        proposal = null;

        if (mode === "explain") {
          if (!primary) {
            notes.textContent = "Geen selectie — kies een element voor deterministische uitleg.";
            diff.textContent = "";
            return;
          }
          const info = ctx.studio?.explainLayout?.(primary);
          notes.textContent = "Deterministische uitleg (geen AI-output).";
          diff.textContent = JSON.stringify(info, null, 2);
          return;
        }

        try {
          const body = {
            instruction: instruction || mode,
            mode,
            scope,
            revision: ctx.store.getState().contentRevision || 0,
            nodeIds: ctx.selection.keys(),
            selectionHtml: primary?.outerHTML?.slice(0, 4000) || "",
            selectionCss: primary ? ctx.content.rawDecls(primary) : "",
          };
          await ctx.api.editorAi(body);
          notes.textContent = "Onverwacht succes zonder contract";
        } catch (err) {
          if (err.status === 501 || err.payload?.unavailable) {
            notes.textContent = `Unavailable: ${err.payload?.reason || err.message}. Deterministische checks en handmatige editing blijven werken.`;
            diff.textContent = JSON.stringify(err.payload?.contract || {}, null, 2);
            return;
          }
          notes.textContent = String(err.message || err);
        }
      });

      host.querySelector("[data-role='apply']").addEventListener("click", () => {
        if (!proposal?.patches) {
          notes.textContent = "Geen gevalideerd voorstel om toe te passen";
          return;
        }
        // Apply would be one undoable transaction — none while unavailable
        notes.textContent = "Geen toepasbaar voorstel";
      });

      host.querySelector("[data-role='cancel']").addEventListener("click", () => {
        proposal = null;
        notes.textContent = "Geannuleerd — niets geschreven";
        diff.textContent = "";
      });
    },
  };
}
