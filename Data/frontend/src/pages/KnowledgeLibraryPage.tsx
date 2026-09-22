import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { KnowledgeChunk, KnowledgeDocument, KnowledgeSearchHit } from "../types/api";
import { PxHero, PxIcon, PxKpi } from "./pixel/pixel-shared";

type TabId = "documents" | "search" | "create";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function excerpt(text: string, max = 160): string {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max - 1)}…`;
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function KnowledgeLibraryPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<TabId>("documents");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeDocument | null>(null);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchSource, setSearchSource] = useState("");
  const [hits, setHits] = useState<KnowledgeSearchHit[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [source, setSource] = useState("manual");

  const sources = useMemo(() => {
    const counts = new Map<string, number>();
    for (const doc of documents) {
      const key = doc.source || "unknown";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [documents]);

  const readyCount = documents.filter((d) => (d.status ?? "READY").toUpperCase() === "READY").length;
  const failedCount = documents.filter((d) => (d.status ?? "").toUpperCase() === "FAILED").length;

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listKnowledgeDocuments();
      setDocuments(res.documents);
      if (res.documents.length === 0) {
        setSelectedId(null);
      } else if (!selectedId || !res.documents.some((d) => d.id === selectedId)) {
        setSelectedId(res.documents[0].id);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load knowledge documents"));
      setDocuments([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void loadDocuments();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial load

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setChunks([]);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setDetailError(null);
      try {
        const res = await api.getKnowledgeDocument(selectedId);
        if (cancelled) return;
        setDetail(res.document);
        setChunks(res.chunks);
      } catch (err) {
        if (!cancelled) {
          setDetail(null);
          setChunks([]);
          setDetailError(errMsg(err, "Failed to load document"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  async function onSearch() {
    const q = searchQuery.trim();
    if (!q) {
      toast("Enter a search query");
      return;
    }
    setBusy(true);
    setSearchError(null);
    setSearched(true);
    try {
      const res = await api.searchKnowledge({
        q,
        limit: 20,
        source: searchSource.trim() || undefined,
      });
      setHits(res.hits);
      if (res.hits.length === 0) toast("No matches");
    } catch (err) {
      setHits([]);
      setSearchError(errMsg(err, "Search failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onCreate() {
    if (!title.trim() || !content.trim()) {
      toast("Title and content are required");
      return;
    }
    setBusy(true);
    try {
      const res = await api.createKnowledgeDocument({
        title: title.trim(),
        content: content.trim(),
        source: source.trim() || "manual",
      });
      setTitle("");
      setContent("");
      setSource("manual");
      setSelectedId(res.document.id);
      setTab("documents");
      await loadDocuments();
      toast("Document saved");
    } catch (err) {
      toast(errMsg(err, "Failed to create document"));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(documentId: string) {
    if (!window.confirm("Delete this knowledge document?")) return;
    setBusy(true);
    try {
      await api.deleteKnowledgeDocument(documentId);
      if (selectedId === documentId) setSelectedId(null);
      await loadDocuments();
      toast("Document deleted");
    } catch (err) {
      toast(errMsg(err, "Failed to delete document"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Knowledge Library"
      searchPlaceholder="Search knowledge documents…"
      systemItems={[
        "KNOWLEDGE",
        `${documents.length} DOCS`,
        loading ? "LOADING" : error ? "ERROR" : "LIVE",
      ]}
      layout="wide"
      pageClass="lv-app--pixel-knowledge"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-stack">
          <PxHero
            title="KNOWLEDGE LIBRARY"
            subtitle="INGEST. INDEX. RETRIEVE. APPLY."
            quote="Empty until real documents exist — no fabricated library inventory."
          />

          <nav className="lv-px-tabs" aria-label="Knowledge Library sections">
            {(
              [
                { id: "documents" as const, label: "Documents", sub: "Library inventory", icon: "folder" },
                { id: "search" as const, label: "Search", sub: "Retrieve chunks", icon: "search" },
                { id: "create" as const, label: "Add", sub: "Write a document", icon: "plus" },
              ] as const
            ).map((item) => (
              <button
                key={item.id}
                type="button"
                className={`lv-px-tab lv-px-tab-rich${tab === item.id ? " is-active" : ""}`}
                onClick={() => setTab(item.id)}
              >
                <PxIcon name={item.icon} />
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.sub}</small>
                </span>
              </button>
            ))}
          </nav>

          <div className="lv-px-kpi-row">
            <PxKpi label="Documents" value={loading ? "…" : String(documents.length)} icon="book" hint="from /api/knowledge" />
            <PxKpi
              label="Ready"
              value={loading ? "…" : String(readyCount)}
              icon="checkcircle"
              hintTone="cyan"
              hint="ingest status READY"
            />
            <PxKpi
              label="Failed"
              value={loading ? "…" : String(failedCount)}
              icon="shield"
              hintTone={failedCount > 0 ? "red" : "muted"}
              hint={failedCount > 0 ? "needs attention" : "none"}
            />
            <PxKpi
              label="Sources"
              value={loading ? "…" : String(sources.length)}
              icon="database"
              hint="distinct source labels"
            />
          </div>

          {error ? (
            <section className="lv-px-panel" role="alert">
              <h2 className="lv-px-panel-title">Knowledge unavailable</h2>
              <p style={{ fontSize: 12 }}>{error}</p>
              <button type="button" className="lv-px-btn is-gold" disabled={busy} onClick={() => void loadDocuments()}>
                Retry
              </button>
            </section>
          ) : null}

          {tab === "documents" ? (
            <div className="lv-px-mid-grid">
              <section className="lv-px-panel" aria-label="Document list">
                <div className="lv-px-panel-head">
                  <h2 className="lv-px-panel-title">
                    <PxIcon name="folder" /> Documents
                  </h2>
                  <button type="button" className="lv-px-btn" disabled={busy || loading} onClick={() => void loadDocuments()}>
                    Refresh
                  </button>
                </div>
                {loading ? (
                  <p style={{ fontSize: 11, color: "var(--lv-text-muted)" }}>Loading documents…</p>
                ) : null}
                {!loading && documents.length === 0 ? (
                  <div className="lv-models-empty" style={{ padding: "24px 8px" }}>
                    <h2>NO DOCUMENTS</h2>
                    <p>The knowledge store is empty. Add a document or ingest from disk — nothing is invented here.</p>
                    <button type="button" className="lv-px-btn is-gold" onClick={() => setTab("create")}>
                      Add document
                    </button>
                  </div>
                ) : null}
                {!loading && documents.length > 0 ? (
                  <ul className="lv-px-domain-list">
                    {documents.map((doc) => (
                      <li key={doc.id}>
                        <button
                          type="button"
                          className={`lv-px-domain-row${doc.id === selectedId ? " is-active" : ""}`}
                          onClick={() => setSelectedId(doc.id)}
                        >
                          <PxIcon name="file" />
                          <span>
                            <strong style={{ display: "block", fontSize: 11 }}>{doc.title || doc.id}</strong>
                            <small style={{ color: "var(--lv-text-muted)" }}>
                              {doc.source} · {dash(doc.status)}
                            </small>
                          </span>
                          <span className="lv-px-domain-count">{formatBytes(doc.size_bytes ?? doc.content?.length)}</span>
                          <PxIcon name="chevron" />
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>

              <section className="lv-px-panel" aria-label="Document detail">
                <div className="lv-px-panel-head">
                  <h2 className="lv-px-panel-title">Detail</h2>
                  {selectedId ? (
                    <button
                      type="button"
                      className="lv-px-btn"
                      disabled={busy}
                      onClick={() => void onDelete(selectedId)}
                    >
                      <PxIcon name="trash" /> Delete
                    </button>
                  ) : null}
                </div>
                {detailError ? (
                  <p style={{ fontSize: 12, color: "var(--lv-danger)" }} role="alert">
                    {detailError}
                  </p>
                ) : null}
                {!selectedId ? (
                  <p style={{ fontSize: 11, color: "var(--lv-text-muted)" }}>Select a document to inspect.</p>
                ) : null}
                {detail ? (
                  <>
                    <strong style={{ fontSize: 13 }}>{detail.title}</strong>
                    <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                      <dt>ID</dt>
                      <dd>{detail.id}</dd>
                      <dt>Source</dt>
                      <dd>{dash(detail.source)}</dd>
                      <dt>Status</dt>
                      <dd>{dash(detail.status)}</dd>
                      <dt>Hash</dt>
                      <dd style={{ fontFamily: "monospace", fontSize: 10 }}>{dash(detail.content_hash)}</dd>
                      <dt>Updated</dt>
                      <dd>{dash(detail.updated_at)}</dd>
                      <dt>Chunks</dt>
                      <dd>{chunks.length}</dd>
                    </dl>
                    <p style={{ marginTop: 10, fontSize: 11, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                      {excerpt(detail.content, 800)}
                    </p>
                    {chunks.length > 0 ? (
                      <div style={{ marginTop: 12 }}>
                        <h3 className="lv-px-panel-title" style={{ fontSize: 11 }}>
                          Chunks · {chunks.length}
                        </h3>
                        <ol style={{ margin: 0, paddingLeft: 18, fontSize: 10, lineHeight: 1.45 }}>
                          {chunks.slice(0, 12).map((chunk) => (
                            <li key={chunk.chunk_id} style={{ marginBottom: 6 }}>
                              <span className="lv-px-pill is-cyan" style={{ marginRight: 6 }}>
                                #{chunk.chunk_index}
                              </span>
                              {excerpt(chunk.content, 120)}
                            </li>
                          ))}
                        </ol>
                        {chunks.length > 12 ? (
                          <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>
                            +{chunks.length - 12} more chunks
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                  </>
                ) : null}
              </section>
            </div>
          ) : null}

          {tab === "search" ? (
            <div className="lv-px-mid-grid">
              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">
                  <PxIcon name="search" /> Search &amp; retrieve
                </h2>
                <div className="lv-px-filters">
                  <label className="lv-px-search" style={{ flex: "1 1 100%" }}>
                    <PxIcon name="search" />
                    <input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && void onSearch()}
                      placeholder="Query the knowledge index…"
                      aria-label="Search query"
                    />
                  </label>
                  <input
                    className="lv-px-select"
                    value={searchSource}
                    onChange={(e) => setSearchSource(e.target.value)}
                    placeholder="Filter source (optional)"
                    aria-label="Source filter"
                    list="klib-sources"
                  />
                  <datalist id="klib-sources">
                    {sources.map(([src]) => (
                      <option key={src} value={src} />
                    ))}
                  </datalist>
                  <button type="button" className="lv-px-btn is-gold" disabled={busy} onClick={() => void onSearch()}>
                    Search
                  </button>
                </div>
                {searchError ? (
                  <p style={{ fontSize: 12, color: "var(--lv-danger)" }} role="alert">
                    {searchError}
                  </p>
                ) : null}
              </section>

              <section className="lv-px-panel" aria-label="Search results">
                <h2 className="lv-px-panel-title">Results · {hits.length}</h2>
                {!searched ? (
                  <p style={{ fontSize: 11, color: "var(--lv-text-muted)" }}>
                    Run a search against `/api/knowledge/search`. Results come from indexed chunks only.
                  </p>
                ) : null}
                {searched && hits.length === 0 && !searchError ? (
                  <div className="lv-models-empty" style={{ padding: "16px 4px" }}>
                    <h2>NO MATCHES</h2>
                    <p>Nothing in the index matched that query.</p>
                  </div>
                ) : null}
                {hits.map((hit) => (
                  <button
                    key={`${hit.document_id}-${hit.chunk_id ?? hit.chunk_index ?? hit.content.slice(0, 24)}`}
                    type="button"
                    className="lv-px-recent-item"
                    style={{ display: "block", width: "100%", textAlign: "left" }}
                    onClick={() => {
                      setSelectedId(hit.document_id);
                      setTab("documents");
                    }}
                  >
                    <strong style={{ fontSize: 11 }}>{hit.title || hit.document_id}</strong>
                    <p style={{ margin: "4px 0", fontSize: 10, color: "var(--lv-text-secondary)" }}>
                      {excerpt(hit.content, 180)}
                    </p>
                    <div style={{ display: "flex", gap: 8, fontSize: 9, color: "var(--lv-text-muted)" }}>
                      <span>{hit.source}</span>
                      {hit.score != null ? <span>score {hit.score.toFixed?.(3) ?? hit.score}</span> : null}
                      {hit.confidence != null ? <span>conf {hit.confidence}</span> : null}
                    </div>
                  </button>
                ))}
              </section>
            </div>
          ) : null}

          {tab === "create" ? (
            <section className="lv-px-panel" aria-label="Create knowledge document">
              <h2 className="lv-px-panel-title">
                <PxIcon name="plus" /> Add document
              </h2>
              <div className="lv-form-grid" style={{ marginTop: 8 }}>
                <div className="lv-form-field">
                  <label htmlFor="kl-title">Title</label>
                  <input
                    id="kl-title"
                    className="lv-input"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Document title"
                  />
                </div>
                <div className="lv-form-field">
                  <label htmlFor="kl-source">Source</label>
                  <input
                    id="kl-source"
                    className="lv-input"
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                    placeholder="manual"
                  />
                </div>
                <div className="lv-form-field full">
                  <label htmlFor="kl-content">Content</label>
                  <textarea
                    id="kl-content"
                    className="lv-input"
                    rows={10}
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder="Paste or write the document body…"
                  />
                </div>
                <div className="lv-form-actions full">
                  <button
                    type="button"
                    className="lv-px-btn is-gold"
                    disabled={busy || !title.trim() || !content.trim()}
                    onClick={() => void onCreate()}
                  >
                    Save document
                  </button>
                </div>
              </div>
            </section>
          ) : null}

          {sources.length > 0 && tab === "documents" ? (
            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Sources in library</h2>
              <ul className="lv-px-domain-list">
                {sources.map(([src, count]) => (
                  <li key={src}>
                    <div className="lv-px-domain-row">
                      <PxIcon name="database" />
                      <span>{src}</span>
                      <span className="lv-px-domain-count">{count}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <footer className="lv-px-page-footer">
            <span>Live knowledge · /api/knowledge</span>
            <span>{documents.length === 0 ? "Empty store" : `${documents.length} document(s)`}</span>
          </footer>
        </div>
      </main>
    </AppShell>
  );
}
