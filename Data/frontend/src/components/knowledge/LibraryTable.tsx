import { KL_STATUS_LABELS } from "../../pages/knowledge/constants";
import { knowledgeTypeBadge } from "../../pages/knowledge/typeBadge";
import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

/**
 * Bounded library rows table/grid. `showSource` renders the provenance
 * column for the "Bronnen" nav view — same bounded data, source-forward
 * projection (not a second data source).
 */
export function LibraryTable({
  ws,
  showSource = false,
}: {
  ws: KnowledgeLibraryWorkspace;
  showSource?: boolean;
}) {
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
        {ws.items.map((row) => {
          const badge = knowledgeTypeBadge(row);
          return (
            <button
              key={row.id}
              type="button"
              role="listitem"
              className={ws.selectedId === row.id ? "is-selected" : undefined}
              onClick={() => ws.setSelectedId(row.id)}
            >
              <strong>{row.title}</strong>
              <span className={`lv-v2-kl-type is-${badge.tone}`}>{badge.short}</span>
              <span>{ws.formatBytes(row.size_bytes)}</span>
              {showSource ? <span>{row.source}</span> : null}
            </button>
          );
        })}
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
            {showSource ? <th>Bron</th> : null}
            <th>Grootte</th>
            <th>Laatst gewijzigd</th>
            <th>Tags</th>
            <th>Status</th>
            <th aria-label="Menu" />
          </tr>
        </thead>
        <tbody>
          {ws.items.map((row) => {
            const badge = knowledgeTypeBadge(row);
            return (
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
                <td className="lv-v2-kl-title">
                  <span className={`lv-v2-kl-row-ico is-${row.library_type}`} aria-hidden />
                  {row.title}
                </td>
                <td>
                  <span className={`lv-v2-kl-type is-${badge.tone}`}>{badge.short}</span>
                </td>
                {showSource ? <td>{row.source}</td> : null}
                <td>{row.size_measured ? ws.formatBytes(row.size_bytes) : "—"}</td>
                <td>
                  {row.updated_at
                    ? new Date(row.updated_at).toLocaleString("nl-NL", {
                        day: "2-digit",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : "—"}
                </td>
                <td className="lv-v2-kl-tags">
                  {row.tags.slice(0, 3).map((t, i) => (
                    <span key={t} className={`lv-v2-kl-tag-chip lv-v2-kl-tag-chip--${i % 6}`}>
                      #{t}
                    </span>
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
            );
          })}
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
