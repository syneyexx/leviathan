import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";
import { KL_NAV, KL_STATUS_LABELS } from "../../pages/knowledge/constants";

function kpiValue(ws: KnowledgeLibraryWorkspace, key: string): { value: string; sub: string } {
  const o = ws.overview;
  if (!o && ws.overviewError) return { value: "—", sub: "Fout / stale" };
  if (!o) return { value: "…", sub: "Laden" };
  switch (key) {
    case "sources":
      return {
        value: o.total_sources.toLocaleString("nl-NL"),
        sub: "canonical Knowledge sources",
      };
    case "size": {
      const size = ws.formatBytes(o.measured_bytes);
      const cov =
        o.size_coverage_percent != null ? `${o.size_coverage_percent}% gemeten` : "dekking onbekend";
      const unk = o.unknown_size_sources ? ` · ${o.unknown_size_sources} ongemeten` : "";
      return { value: size, sub: `${cov}${unk}` };
    }
    case "types":
      return {
        value: String(o.source_type_count),
        sub: "genormaliseerde types met bronnen",
      };
    case "embed": {
      if (o.embedding.status === "NOT_CONFIGURED") return { value: "N/A", sub: "NOT CONFIGURED" };
      if (o.embedding.status === "UNAVAILABLE") return { value: "N/A", sub: "UNAVAILABLE" };
      if (o.embedding.coverage_percent == null) return { value: "—", sub: o.embedding.status };
      return {
        value: `${o.embedding.coverage_percent}%`,
        sub: `${o.embedding.chunks_embedded}/${o.embedding.chunks_total} chunks`,
      };
    }
    case "latest": {
      const li = o.latest_ingestion;
      if (!li?.created_at) return { value: "—", sub: "geen ingestie" };
      const stamp = new Date(li.created_at);
      const label = Number.isNaN(stamp.getTime())
        ? li.created_at
        : stamp.toLocaleString("nl-NL", { dateStyle: "medium", timeStyle: "medium" });
      return { value: label, sub: ws.relativeAge(li.created_at) };
    }
    default:
      return { value: "—", sub: "" };
  }
}

export function KnowledgeKpis({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const cards = [
    { key: "sources", title: "Totale Bronnen" },
    { key: "size", title: "Totale Grootte" },
    { key: "types", title: "Bron Types" },
    { key: "embed", title: "Embedding Status" },
    { key: "latest", title: "Laatste Ingestie" },
  ];
  return (
    <section className="lv-v2-kl-kpis" aria-label="Knowledge Library KPIs">
      {cards.map((c) => {
        const v = kpiValue(ws, c.key);
        return (
          <article key={c.key} className="lv-v2-kl-kpi">
            <header>{c.title}</header>
            <strong>{v.value}</strong>
            <span>{v.sub}</span>
          </article>
        );
      })}
    </section>
  );
}

export function KnowledgeNav({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  return (
    <nav className="lv-v2-kl-nav" aria-label="Knowledge Library views">
      {KL_NAV.map((item) => (
        <button
          key={item.id}
          type="button"
          className={ws.view === item.id ? "is-active" : undefined}
          onClick={() => ws.onNav(item.id)}
        >
          {item.label}
        </button>
      ))}
    </nav>
  );
}

export function KnowledgeTypeSidebar({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const counts = ws.overview?.source_type_counts ?? [];
  const total = ws.overview?.total_sources ?? ws.total;
  return (
    <aside className="lv-v2-kl-side" aria-label="Bron filters">
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

      <div className="lv-v2-kl-side-block">
        <h3>
          Tags
          <button
            type="button"
            className="lv-v2-kl-icon-btn"
            aria-label="Tag toevoegen aan selectie"
            onClick={() => void ws.onBulkTag()}
            disabled={!ws.checked.size}
          >
            +
          </button>
        </h3>
        {(ws.tagsExpanded ? ws.overview?.top_tags ?? [] : (ws.overview?.top_tags ?? []).slice(0, 10)).map(
          (t) => (
            <button
              key={t.tag}
              type="button"
              className={ws.tagFilter === t.tag ? "is-active" : undefined}
              onClick={() => ws.setTagFilter(ws.tagFilter === t.tag ? "" : t.tag)}
            >
              <span>#{t.tag}</span>
              <em>{t.count.toLocaleString("nl-NL")}</em>
            </button>
          ),
        )}
        {(ws.overview?.tag_vocabulary_size ?? 0) > 10 ? (
          <button type="button" className="lv-v2-kl-more" onClick={() => ws.setTagsExpanded((v) => !v)}>
            {ws.tagsExpanded ? "Toon minder" : "Toon meer"}
          </button>
        ) : null}
        {ws.overview && !(ws.overview.top_tags?.length) ? (
          <p className="lv-v2-kl-muted">Geen tags</p>
        ) : null}
      </div>
    </aside>
  );
}

export function KnowledgeLibraryTable({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  if (ws.loading && !ws.items.length) {
    return <div className="lv-v2-kl-skeleton">Laden…</div>;
  }
  if (ws.error && !ws.items.length) {
    return (
      <div className="lv-v2-kl-error">
        <p>{ws.error}</p>
        <button type="button" onClick={() => void ws.refresh()}>
          Opnieuw
        </button>
      </div>
    );
  }
  if (!ws.items.length) {
    return <div className="lv-v2-kl-empty">Geen bronnen in de library.</div>;
  }

  if (ws.viewMode === "grid") {
    return (
      <div className="lv-v2-kl-grid" role="list">
        {ws.items.map((row) => (
          <button
            key={row.id}
            type="button"
            role="listitem"
            className={ws.selectedId === row.id ? "is-selected" : undefined}
            onClick={() => ws.setSelectedId(row.id)}
          >
            <strong>{row.title}</strong>
            <span className={`lv-v2-kl-type is-${row.library_type}`}>{row.library_type_label || row.library_type}</span>
            <span>{ws.formatBytes(row.size_bytes)}</span>
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="lv-v2-kl-table-wrap">
      <table className="lv-v2-kl-table">
        <thead>
          <tr>
            <th aria-label="Select" />
            <th>Titel</th>
            <th>Type</th>
            <th>Grootte</th>
            <th>Laatst gewijzigd</th>
            <th>Tags</th>
            <th>Status</th>
            <th aria-label="Menu" />
          </tr>
        </thead>
        <tbody>
          {ws.items.map((row) => (
            <tr
              key={row.id}
              className={ws.selectedId === row.id ? "is-selected" : undefined}
              onClick={() => ws.setSelectedId(row.id)}
            >
              <td onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={ws.checked.has(row.id)}
                  onChange={() => ws.toggleCheck(row.id)}
                  aria-label={`Selecteer ${row.title}`}
                />
              </td>
              <td className="lv-v2-kl-title">{row.title}</td>
              <td>
                <span className={`lv-v2-kl-type is-${row.library_type}`}>
                  {(row.library_type_label || row.library_type).toUpperCase()}
                </span>
              </td>
              <td>{row.size_measured ? ws.formatBytes(row.size_bytes) : "—"}</td>
              <td>{row.updated_at ? new Date(row.updated_at).toLocaleString("nl-NL") : "—"}</td>
              <td className="lv-v2-kl-tags">
                {row.tags.slice(0, 3).map((t) => (
                  <span key={t}>#{t}</span>
                ))}
              </td>
              <td>
                <span className={`lv-v2-kl-status is-${(row.status || "").toLowerCase()}`}>
                  <i />
                  {KL_STATUS_LABELS[row.status] || row.status}
                </span>
              </td>
              <td>
                <button
                  type="button"
                  className="lv-v2-kl-icon-btn"
                  aria-label="Acties"
                  onClick={(e) => {
                    e.stopPropagation();
                    ws.setSelectedId(row.id);
                  }}
                >
                  ⋯
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {ws.hasMore ? (
        <button
          type="button"
          className="lv-v2-kl-more"
          onClick={() => void ws.loadLibrary({ offset: ws.offset + 50, quiet: true })}
        >
          Meer laden ({ws.total.toLocaleString("nl-NL")} totaal)
        </button>
      ) : null}
    </div>
  );
}
