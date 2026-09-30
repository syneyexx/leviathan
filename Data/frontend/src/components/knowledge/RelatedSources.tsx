import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

/**
 * Related sources for the selected document — GET .../related.
 * Renders an honest empty state when nothing is related, never a fabricated relation.
 */
export function RelatedSources({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  return (
    <section className="lv-v2-kl-related" aria-label="Gerelateerde bronnen">
      <header className="lv-v2-kl-related__head">
        <h4>Gerelateerde Bronnen ({ws.related.length})</h4>
        {ws.related.length ? (
          <button type="button" className="lv-v2-kl-more" onClick={() => ws.setDetailTab("relaties")}>
            Alles bekijken
          </button>
        ) : null}
      </header>
      <ul>
        {ws.related.map((r) => (
          <li key={r.id}>
            <button type="button" onClick={() => ws.setSelectedId(r.id)}>
              <strong>{r.title}</strong>
              <span>
                {r.library_type_label || r.library_type} · {ws.formatBytes(r.size_bytes)}
              </span>
              <em>{r.relationship_kind || "related"}</em>
            </button>
          </li>
        ))}
        {!ws.related.length ? <li className="lv-v2-kl-muted">Geen gerelateerde bronnen</li> : null}
      </ul>
    </section>
  );
}
