import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

/** Bounded recent ingestion history — GET /api/knowledge/library/ingestion/recent. */
export function RecentIngestions({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  return (
    <div className="lv-v2-kl-recent">
      <header>
        <h4>Recente Ingesties</h4>
      </header>
      <ul>
        {ws.recentIngestions.map((r) => (
          <li key={r.source_id}>
            <time>{r.created_at ? new Date(r.created_at).toLocaleTimeString("nl-NL") : "—"}</time>
            <strong>{r.filename}</strong>
            <span>{ws.formatBytes(r.size_bytes)}</span>
            <em>{r.status}</em>
          </li>
        ))}
        {!ws.recentIngestions.length ? <li className="lv-v2-kl-muted">Nog geen ingesties</li> : null}
      </ul>
    </div>
  );
}
