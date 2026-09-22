import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type KnowledgeDoc = {
  id: string;
  title?: string;
  content?: string;
  source?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  error?: string | null;
  size_bytes?: number | null;
};

type KnowledgeHit = {
  document_id?: string;
  title?: string;
  content?: string;
  score?: number;
  source?: string;
  chunk_id?: string;
  modality?: string;
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function KnowledgeLibraryPage() {
  const toast = useAppToast();
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ document: KnowledgeDoc; chunks: unknown[] } | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listKnowledgeDocuments();
      const list = (res.documents ?? []) as KnowledgeDoc[];
      setDocs(list);
      if (list.length && (!selectedId || !list.some((d) => d.id === selectedId))) {
        setSelectedId(list[0].id);
      }
      if (!list.length) setSelectedId(null);
    } catch (err) {
      setError(errMsg(err, "Failed to load knowledge documents"));
      setDocs([]);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    void api.getKnowledgeDocument(selectedId).then(
      (res) => {
        if (!cancelled) setDetail(res as { document: KnowledgeDoc; chunks: unknown[] });
      },
      (err) => {
        if (!cancelled) toast(errMsg(err, "Failed to load document"));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [selectedId, toast]);

  const selected = useMemo(
    () => docs.find((d) => d.id === selectedId) ?? detail?.document ?? null,
    [detail, docs, selectedId],
  );

  async function onSearch() {
    const query = q.trim();
    if (!query) {
      setHits([]);
      return;
    }
    setSearching(true);
    try {
      const res = await api.searchKnowledge({ q: query, limit: 40 });
      setHits((res.hits ?? []) as KnowledgeHit[]);
    } catch (err) {
      toast(errMsg(err, "Search failed"));
      setHits([]);
    } finally {
      setSearching(false);
    }
  }

  async function onCreate() {
    if (!title.trim() || !content.trim()) {
      toast("Title and content required");
      return;
    }
    setBusy(true);
    try {
      const res = await api.createKnowledgeDocument({
        title: title.trim(),
        content: content.trim(),
        source: "manual",
      });
      const doc = res.document as KnowledgeDoc;
      toast("Document ingested");
      setTitle("");
      setContent("");
      await load();
      if (doc?.id) setSelectedId(doc.id);
    } catch (err) {
      toast(errMsg(err, "Ingest failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(id: string) {
    if (!window.confirm(`Delete knowledge document ${id}?`)) return;
    setBusy(true);
    try {
      await api.deleteKnowledgeDocument(id);
      toast("Deleted");
      await load();
    } catch (err) {
      toast(errMsg(err, "Delete failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Knowledge Mode"
      searchPlaceholder="Search knowledge…"
      systemItems={["LLM", "Neural", "Memory", "Runtime"]}
      layout="wide"
    >
      <main className="lv-main" style={{ padding: "1.25rem", display: "grid", gap: "1rem" }}>
        <header>
          <h1 style={{ margin: 0 }}>Knowledge Library</h1>
          <p style={{ opacity: 0.75, margin: "0.35rem 0 0" }}>
            Authoritative documents from KnowledgeStore — no demo fixtures.
          </p>
        </header>

        {error ? <div role="alert">{error}</div> : null}

        <section style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <div>
            <h2>Documents ({docs.length})</h2>
            {loading ? <p>Loading…</p> : null}
            {!loading && docs.length === 0 ? <p>No documents yet.</p> : null}
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.5rem" }}>
              {docs.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(d.id)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "0.65rem 0.75rem",
                      border: selectedId === d.id ? "1px solid #c9a227" : "1px solid #333",
                      background: selectedId === d.id ? "rgba(201,162,39,0.12)" : "transparent",
                      color: "inherit",
                      cursor: "pointer",
                    }}
                  >
                    <strong>{d.title || d.id}</strong>
                    <div style={{ fontSize: "0.85rem", opacity: 0.7 }}>
                      {d.status || "—"} · {d.source || "—"}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h2>Detail</h2>
            {!selected ? (
              <p>Select a document</p>
            ) : (
              <div style={{ display: "grid", gap: "0.5rem" }}>
                <div>
                  <strong>{selected.title}</strong>
                </div>
                <div style={{ fontSize: "0.9rem", opacity: 0.75 }}>
                  id={selected.id} · status={selected.status || "—"} · source={selected.source || "—"}
                </div>
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    maxHeight: 280,
                    overflow: "auto",
                    background: "rgba(0,0,0,0.25)",
                    padding: "0.75rem",
                  }}
                >
                  {selected.content || detail?.document?.content || ""}
                </pre>
                <div style={{ fontSize: "0.85rem" }}>
                  Chunks: {detail?.chunks?.length ?? "—"}
                </div>
                <button type="button" disabled={busy} onClick={() => void onDelete(selected.id)}>
                  Delete
                </button>
              </div>
            )}
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <div>
            <h2>Search</h2>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void onSearch();
                }}
                placeholder="Keyword / hybrid query"
                style={{ flex: 1 }}
              />
              <button type="button" disabled={searching} onClick={() => void onSearch()}>
                {searching ? "…" : "Search"}
              </button>
            </div>
            <ul style={{ listStyle: "none", padding: 0 }}>
              {hits.map((h, i) => (
                <li key={`${h.chunk_id ?? h.document_id ?? i}`}>
                  <button
                    type="button"
                    onClick={() => h.document_id && setSelectedId(h.document_id)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      marginTop: "0.4rem",
                      background: "transparent",
                      color: "inherit",
                      border: "1px solid #333",
                      padding: "0.5rem",
                      cursor: "pointer",
                    }}
                  >
                    <div>
                      {h.title || h.document_id}{" "}
                      {h.score != null ? <span style={{ opacity: 0.6 }}>score={h.score.toFixed?.(3) ?? h.score}</span> : null}
                    </div>
                    <div style={{ fontSize: "0.85rem", opacity: 0.75 }}>
                      {(h.content || "").slice(0, 160)}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h2>Ingest text</h2>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title"
              style={{ width: "100%", marginBottom: "0.5rem" }}
            />
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Content"
              rows={8}
              style={{ width: "100%", marginBottom: "0.5rem" }}
            />
            <button type="button" disabled={busy} onClick={() => void onCreate()}>
              Ingest
            </button>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
