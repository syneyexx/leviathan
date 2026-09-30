import { api } from "../../api/client";
import { KL_STATUS_LABELS } from "../../pages/knowledge/constants";
import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";
import { RelatedSources } from "./RelatedSources";

function PreviewBody({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const kind = String(ws.preview?.preview_kind || "text");
  const doc = ws.selected;
  if (!doc) return null;
  if (kind === "pdf" || kind === "image") {
    return (
      <iframe
        title="Source preview"
        className="lv-v2-kl-preview-frame"
        src={String(ws.preview?.content_url || api.knowledgeLibraryContentUrl(doc.id))}
      />
    );
  }
  if (kind === "cover" || kind === "html") {
    return (
      <iframe
        title="Source preview"
        className="lv-v2-kl-preview-frame"
        srcDoc={String(ws.preview?.html || "")}
      />
    );
  }
  return <pre className="lv-v2-kl-preview-text">{String(ws.preview?.text || "Geen preview beschikbaar")}</pre>;
}

/**
 * Right panel — selected source detail, real actions (open/download/share/
 * delete), and preview/metadata/inhoud/embeddings/relaties tabs. Tabs that
 * depend on Wave 3 endpoints degrade to an honest empty/UNAVAILABLE state
 * instead of fabricated content when the backend has nothing to report.
 */
export function SelectedSourcePanel({ ws }: { ws: KnowledgeLibraryWorkspace }) {
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
            {ws.detailTab === "preview" ? <PreviewBody ws={ws} /> : null}
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
                {!ws.chunks.length ? (
                  <p className="lv-v2-kl-muted">Geen chunks beschikbaar voor deze bron.</p>
                ) : null}
              </div>
            ) : null}
            {ws.detailTab === "embeddings" ? (
              <dl className="lv-v2-kl-meta-grid">
                <dt>Status</dt>
                <dd>{ws.embeddings?.embedding_status ?? "UNAVAILABLE"}</dd>
                <dt>Coverage</dt>
                <dd>{ws.embeddings?.coverage_percent != null ? `${ws.embeddings.coverage_percent}%` : "—"}</dd>
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
                {!ws.relations.length ? (
                  <li className="lv-v2-kl-muted">Geen expliciete relaties</li>
                ) : null}
              </ul>
            ) : null}
          </div>
        </>
      )}

      <RelatedSources ws={ws} />
    </aside>
  );
}
