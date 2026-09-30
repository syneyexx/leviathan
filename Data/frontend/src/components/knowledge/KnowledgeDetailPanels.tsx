import { api } from "../../api/client";
import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";
import { KL_STATUS_LABELS } from "../../pages/knowledge/constants";

export function KnowledgeSelectedPanel({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const doc = ws.selected;
  return (
    <aside className="lv-v2-kl-detail" aria-label="Geselecteerde bron">
      <header className="lv-v2-kl-detail__head">
        <h3>Geselecteerde Bron</h3>
        {ws.detailLoading ? <span className="lv-v2-kl-muted">Laden…</span> : null}
        {ws.detailError ? <span className="lv-v2-kl-warn">{ws.detailError}</span> : null}
      </header>

      {!doc ? (
        <p className="lv-v2-kl-muted">Geen bron geselecteerd</p>
      ) : (
        <>
          <div className="lv-v2-kl-detail__meta">
            <strong>{doc.title}</strong>
            <p>
              {doc.library_type_label || doc.library_type}
              {" · "}
              {doc.size_measured ? ws.formatBytes(doc.size_bytes) : "—"}
              {doc.page_count != null ? ` · ${doc.page_count} pagina's` : ""}
            </p>
            <p className="lv-v2-kl-muted">
              Toegevoegd {doc.created_at ? new Date(doc.created_at).toLocaleString("nl-NL") : "—"}
              {" · "}
              Gewijzigd {doc.updated_at ? new Date(doc.updated_at).toLocaleString("nl-NL") : "—"}
            </p>
            <span className={`lv-v2-kl-status is-${(doc.status || "").toLowerCase()}`}>
              <i />
              {KL_STATUS_LABELS[doc.status] || doc.status}
            </span>
          </div>

          <div className="lv-v2-kl-detail__actions">
            <button type="button" className="is-primary" onClick={() => ws.setDetailTab("preview")}>
              Openen
            </button>
            <a href={api.knowledgeLibraryDownloadUrl(doc.id)} download>
              Download
            </a>
            <button type="button" onClick={() => void ws.onShare()}>
              Delen
            </button>
            <button type="button" aria-label="Meer" onClick={() => void ws.onDeleteSelected()}>
              ⋯
            </button>
          </div>

          <div className="lv-v2-kl-detail__tabs" role="tablist">
            {(
              [
                ["preview", "Preview"],
                ["metadata", "Metadata"],
                ["inhoud", "Inhoud"],
                ["embeddings", "Embeddings"],
                ["relaties", "Relaties"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={ws.detailTab === id}
                className={ws.detailTab === id ? "is-active" : undefined}
                onClick={() => ws.setDetailTab(id)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="lv-v2-kl-detail__body">
            {ws.detailTab === "preview" ? (
              <PreviewBody ws={ws} />
            ) : null}
            {ws.detailTab === "metadata" ? (
              <dl className="lv-v2-kl-meta-grid">
                <dt>ID</dt>
                <dd>{doc.id}</dd>
                <dt>Type</dt>
                <dd>{doc.library_type}</dd>
                <dt>MIME</dt>
                <dd>{doc.mime_type || "—"}</dd>
                <dt>Hash</dt>
                <dd>{doc.content_hash || "—"}</dd>
                <dt>Parser</dt>
                <dd>{doc.parser || "—"}</dd>
                <dt>Source</dt>
                <dd>{doc.source}</dd>
                <dt>Tags</dt>
                <dd>{doc.tags.length ? doc.tags.map((t) => `#${t}`).join(" ") : "—"}</dd>
              </dl>
            ) : null}
            {ws.detailTab === "inhoud" ? (
              <div className="lv-v2-kl-chunks">
                <p className="lv-v2-kl-muted">
                  {ws.chunks.length} / {ws.chunkTotal} chunks (bounded)
                </p>
                {ws.chunks.map((c) => (
                  <article key={String(c.chunk_id)}>
                    <header>
                      Chunk {String(c.chunk_index)} · {String(c.token_estimate ?? "—")} tokens
                    </header>
                    <pre>{String(c.content || "")}</pre>
                  </article>
                ))}
              </div>
            ) : null}
            {ws.detailTab === "embeddings" ? (
              <dl className="lv-v2-kl-meta-grid">
                <dt>Status</dt>
                <dd>{ws.embeddings?.embedding_status ?? "—"}</dd>
                <dt>Coverage</dt>
                <dd>
                  {ws.embeddings?.coverage_percent != null
                    ? `${ws.embeddings.coverage_percent}%`
                    : "—"}
                </dd>
                <dt>Chunks</dt>
                <dd>
                  {ws.embeddings
                    ? `${ws.embeddings.chunks_embedded} / ${ws.embeddings.chunks_total}`
                    : "—"}
                </dd>
                <dt>Provider</dt>
                <dd>{ws.embeddings?.provider_id || "—"}</dd>
                <dt>Dimensions</dt>
                <dd>{ws.embeddings?.dimensions ?? "—"}</dd>
              </dl>
            ) : null}
            {ws.detailTab === "relaties" ? (
              <ul className="lv-v2-kl-rel-list">
                {ws.relations.map((r) => (
                  <li key={String(r.atom_id)}>
                    <strong>{String(r.relation_class)}</strong>
                    <span>
                      {String(r.subject_ref)} → {String(r.object_ref)}
                    </span>
                    <em>explicit</em>
                  </li>
                ))}
                {!ws.relations.length ? <li className="lv-v2-kl-muted">Geen expliciete relaties</li> : null}
              </ul>
            ) : null}
          </div>
        </>
      )}

      <section className="lv-v2-kl-related" aria-label="Gerelateerde bronnen">
        <header>
          <h4>Gerelateerde Bronnen ({ws.related.length})</h4>
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
    </aside>
  );
}

function PreviewBody({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const kind = String(ws.preview?.preview_kind || "text");
  const doc = ws.selected;
  if (!doc) return null;
  if (kind === "pdf" || kind === "image") {
    return (
      <iframe
        title="Source preview"
        className="lv-v2-kl-preview-frame"
        src={api.knowledgeLibraryContentUrl(doc.id)}
      />
    );
  }
  return (
    <pre className="lv-v2-kl-preview-text">{String(ws.preview?.text || "Geen preview beschikbaar")}</pre>
  );
}

export function KnowledgeIngestionPanels({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const pct =
    ws.activeProgress && typeof ws.activeProgress.progress_pct === "number"
      ? ws.activeProgress.progress_pct
      : null;
  const measured = ws.activeProgress?.measured === true;
  const phase = String(ws.activeProgress?.phase || ws.activeProgress?.status || "—");

  return (
    <section className="lv-v2-kl-bottom" aria-label="Ingestie">
      <div className="lv-v2-kl-ingest-progress">
        <header>
          <h4>Ingestie Voortgang</h4>
          {ws.ingestionError ? <span className="lv-v2-kl-warn">{ws.ingestionError}</span> : null}
        </header>
        {ws.activeIngestionId ? (
          <>
            <p>
              Processing: {String(ws.activeProgress?.filename || ws.activeIngestionId)} · {phase}
            </p>
            <div className="lv-v2-kl-progress">
              <div
                style={{
                  width: measured && pct != null ? `${Math.max(0, Math.min(100, pct))}%` : "0%",
                }}
              />
            </div>
            <p className="lv-v2-kl-muted">
              {measured && pct != null ? `${pct}%` : "UNMEASURED"}
              {" · "}
              ETA {ws.activeProgress?.eta_seconds != null ? `${ws.activeProgress.eta_seconds}s` : "onbekend"}
            </p>
            <div className="lv-v2-kl-detail__actions">
              <button type="button" onClick={() => void ws.onCancelIngestion()} disabled={ws.busy}>
                Cancel
              </button>
              <button type="button" onClick={() => void ws.onRetryIngestion()} disabled={ws.busy}>
                Retry
              </button>
            </div>
          </>
        ) : (
          <p className="lv-v2-kl-muted">Geen actieve ingestie</p>
        )}
      </div>

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
    </section>
  );
}
