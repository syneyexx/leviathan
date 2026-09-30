import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

/** Left sidebar "Bron Types" filter — counts come from the library overview, never invented. */
export function SourceTypeSidebar({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const counts = ws.overview?.source_type_counts ?? [];
  const total = ws.overview?.total_sources ?? ws.total;
  return (
    <div className="lv-v2-kl-side-block">
      <h3>Bron Types</h3>
      <button
        type="button"
        className={!ws.typeFilter ? "is-active" : undefined}
        onClick={() => ws.setTypeFilter("")}
      >
        <span>Alle bronnen</span>
        <em>{total.toLocaleString("nl-NL")}</em>
      </button>
      {counts.map((t) => (
        <button
          key={t.id}
          type="button"
          className={ws.typeFilter === t.id ? "is-active" : undefined}
          onClick={() => ws.setTypeFilter(t.id)}
        >
          <span>{t.label}</span>
          <em>{t.count.toLocaleString("nl-NL")}</em>
        </button>
      ))}
      {!counts.length && !ws.overview ? <p className="lv-v2-kl-muted">…</p> : null}
      {!counts.length && ws.overview ? <p className="lv-v2-kl-muted">Geen getypeerde bronnen</p> : null}
    </div>
  );
}
