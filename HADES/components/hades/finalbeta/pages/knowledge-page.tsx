/** FINALBETA Knowledge Library — live knowledge API (visual shell preserved). */
"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useHadesKnowledge } from "@/components/hades/features/knowledge/hooks/useHadesKnowledge";
import { formatDate, hadesApi, type KnowledgeMatch } from "@/lib/hades-api";
import { FbIcon } from "../icons";
import {
  KNOWLEDGE_ACTIONS,
  KNOWLEDGE_FILTERS,
  KNOWLEDGE_TAGS,
} from "../mocks/knowledge";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

type DocStatus = "indexed" | "processing" | "failed";

type DocView = {
  id: string;
  name: string;
  meta: string;
  type: string;
  typeTone: string;
  collection: string;
  collectionTone: string;
  status: DocStatus;
  statusLabel: string;
  modified: string;
  size: string;
  pages?: number;
  language: string;
  source: string;
  sourceType: string;
  confidence: number;
  tags: string[];
  summary: string;
  chunks: number | null;
};

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function statusTone(status: DocStatus) {
  if (status === "indexed") return "green";
  if (status === "processing") return "gold";
  return "red";
}

function typeIcon(type: string) {
  if (type === "WEB") return "globe";
  if (type === "MD") return "book";
  return "file";
}

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function DocRow({
  doc,
  active,
  onSelect,
}: {
  doc: DocView;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <tr className={active ? "active" : undefined} onClick={onSelect}>
      <td className="kl-check">
        <input type="checkbox" checked={active} readOnly aria-label={`Selecteer ${doc.name}`} />
      </td>
      <td className="kl-name">
        <span className={`kl-type-ico ${doc.typeTone}`}>
          <FbIcon name={typeIcon(doc.type)} size={13} />
        </span>
        <span className="kl-name-copy">
          <strong>{doc.name}</strong>
          <small>{doc.meta}</small>
        </span>
      </td>
      <td>
        <span className={`kl-type-pill ${doc.typeTone}`}>{doc.type}</span>
      </td>
      <td>
        <span className={`kl-col-pill ${doc.collectionTone}`}>{doc.collection}</span>
      </td>
      <td>
        <span className={`kl-status ${statusTone(doc.status)}`}>
          <i />
          {doc.statusLabel}
        </span>
      </td>
      <td className="kl-modified">{doc.modified}</td>
      <td className="kl-row-menu">
        <button type="button" aria-label="Meer" data-toast="Meer acties" onClick={(e) => e.stopPropagation()}>
          <FbIcon name="more" size={14} />
        </button>
      </td>
    </tr>
  );
}

export function KnowledgePage({ onNavigate }: Props) {
  const [now, setNow] = useState(() => new Date());
  const [query, setQuery] = useState("");
  const [collectionId, setCollectionId] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pageNum, setPageNum] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchMatches, setSearchMatches] = useState<KnowledgeMatch[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const { docs: liveDocs, stats, sources, loading, error, refresh, deleteSource } = useHadesKnowledge();

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const docs: DocView[] = useMemo(
    () =>
      liveDocs.map((doc) => {
        const raw = doc.raw;
        const meta = (raw.metadata && typeof raw.metadata === "object" ? raw.metadata : {}) as Record<
          string,
          unknown
        >;
        return {
          id: doc.id,
          name: doc.name,
          meta: doc.meta,
          type: doc.type,
          typeTone: doc.typeTone,
          collection: doc.collection,
          collectionTone: doc.collectionTone,
          status: doc.status === "failed" ? "failed" : doc.status,
          statusLabel: doc.statusLabel,
          modified: formatDate(doc.updated === "—" ? null : doc.updated),
          size: typeof meta.size_bytes === "number" ? `${Math.round(Number(meta.size_bytes) / 1024)} KB` : "—",
          language: String(meta.language || "—"),
          source: String(raw.uri || raw.local_path || "—"),
          sourceType: String(raw.source_type || doc.type),
          confidence: doc.status === "indexed" ? 90 : doc.status === "failed" ? 20 : 50,
          tags: Array.isArray(meta.tags) ? (meta.tags as string[]).map(String) : [],
          summary: String(meta.summary || raw.title || "Geen samenvatting beschikbaar."),
          chunks: doc.chunks,
        };
      }),
    [liveDocs],
  );

  const collections = useMemo(() => {
    const map = new Map<string, number>();
    for (const doc of docs) {
      map.set(doc.collection, (map.get(doc.collection) || 0) + 1);
    }
    const items = [
      { id: "all", label: "Alle documenten", count: docs.length, icon: "folder" as const },
      ...Array.from(map.entries())
        .sort((a, b) => b[1] - a[1])
        .map(([label, count]) => ({
          id: label.toLowerCase().replace(/\s+/g, "-"),
          label,
          count,
          icon: "folder" as const,
        })),
    ];
    return items;
  }, [docs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const col = collections.find((item) => item.id === collectionId);
    let list = docs.filter((doc) => {
      if (collectionId === "trash") return false;
      if (col && collectionId !== "all" && doc.collection !== col.label) return false;
      return true;
    });
    if (searchMatches) {
      const ids = new Set(searchMatches.map((m) => m.source_id));
      list = list.filter((doc) => ids.has(doc.id));
    } else if (q) {
      list = list.filter(
        (doc) =>
          doc.name.toLowerCase().includes(q) ||
          doc.collection.toLowerCase().includes(q) ||
          doc.tags.some((tag) => tag.toLowerCase().includes(q)) ||
          doc.summary.toLowerCase().includes(q) ||
          doc.meta.toLowerCase().includes(q),
      );
    }
    return list;
  }, [query, collectionId, docs, collections, searchMatches]);

  useEffect(() => {
    if (!filtered.length) {
      setSelectedId(null);
      return;
    }
    setSelectedId((current) =>
      current && filtered.some((d) => d.id === current) ? current : filtered[0]!.id,
    );
  }, [filtered]);

  useEffect(() => {
    setPageNum(1);
  }, [query, collectionId, searchMatches, pageSize]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageDocs = filtered.slice((pageNum - 1) * pageSize, pageNum * pageSize);
  const selected = docs.find((doc) => doc.id === selectedId) ?? filtered[0] ?? null;

  const indexedCount = docs.filter((d) => d.status === "indexed").length;
  const processingCount = docs.filter((d) => d.status === "processing").length;
  const failedCount = docs.filter((d) => d.status === "failed").length;

  const liveStats = [
    {
      id: "total",
      label: "Totaal documenten",
      value: loading && !docs.length ? "…" : String(stats?.sources ?? docs.length),
      delta: null as string | null,
      deltaTone: null as string | null,
      hint: "Alle bronnen en formaten",
      icon: "file",
      tone: "cyan",
    },
    {
      id: "indexed",
      label: "Geïndexeerd",
      value: loading && !docs.length ? "…" : String(indexedCount),
      delta: docs.length ? `${Math.round((indexedCount / Math.max(1, docs.length)) * 100)}%` : null,
      deltaTone: "up",
      hint: `${stats?.chunks ?? 0} chunks`,
      icon: "database",
      tone: "green",
    },
    {
      id: "processing",
      label: "Bezig met verwerken",
      value: loading && !docs.length ? "…" : String(processingCount),
      delta: null,
      deltaTone: null,
      hint: "Ingestie en analyse",
      icon: "refresh",
      tone: "gold",
    },
    {
      id: "errors",
      label: "Foutmeldingen",
      value: loading && !docs.length ? "…" : String(failedCount),
      delta: null,
      deltaTone: null,
      hint: failedCount ? "Vereist aandacht" : "Geen fouten",
      icon: "shield",
      tone: "red",
    },
    {
      id: "size",
      label: "Token schatting",
      value: loading && !docs.length ? "…" : String(stats?.token_estimate ?? "—"),
      delta: null,
      deltaTone: null,
      hint: `${sources.length} bronnen geladen`,
      icon: "database",
      tone: "blue",
    },
  ];

  async function runSearch() {
    const q = query.trim();
    setSearchError(null);
    if (!q) {
      setSearchMatches(null);
      return;
    }
    setSearchBusy(true);
    try {
      const res = await hadesApi.searchKnowledge(q, 40);
      setSearchMatches(res.matches || []);
    } catch (err) {
      setSearchMatches(null);
      setSearchError(errMessage(err));
      toast.error(errMessage(err));
    } finally {
      setSearchBusy(false);
    }
  }

  async function runKnowledgeAction(actionId: string) {
    if (!selected) return;
    if (actionId === "chat") {
      onNavigate("chat");
      toast.message(`Chat geopend — document «${selected.name}» staat in de bibliotheek.`);
      return;
    }
    if (actionId === "open") {
      const uri = selected.source || selected.meta;
      if (uri.startsWith("http://") || uri.startsWith("https://") || uri.startsWith("file:")) {
        window.open(uri, "_blank", "noopener,noreferrer");
        return;
      }
      toast.message(`Bron: ${uri || selected.name}`);
      return;
    }
    if (actionId === "delete") {
      try {
        await deleteSource(selected.id);
        toast.success("Bron verwijderd.");
        setSelectedId(null);
        await refresh();
      } catch (err) {
        toast.error(errMessage(err));
      }
      return;
    }
    // Remaining actions have no dedicated backend endpoint yet — say so (F-10).
    toast.message(`«${actionId}» is nog niet aangesloten op een API.`);
  }

  const body = (
    <div className="knowledge-page" data-live="knowledge">
      <div className="knowledge-welcome">
        <div className="knowledge-welcome-copy">
          <h1>Knowledge Library</h1>
          <p>Centrale bibliotheek van alle documenten, kennis en inzichten. Zoek, organiseer en benut je kennis.</p>
        </div>
        <div className="knowledge-welcome-mid">“Knowledge organized today, intelligence tomorrow.”</div>
        <div className="knowledge-clock">
          <div className="knowledge-clock-copy">
            <div className="date">
              {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
            </div>
            <div className="time">
              {pad(now.getHours())}:{pad(now.getMinutes())}
            </div>
          </div>
          <FbIcon name="bolt" size={22} className="knowledge-sun" />
        </div>
      </div>

      {error ? (
        <div className="card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Knowledge laden mislukt.</strong> {error.message}{" "}
          <button type="button" className="btn btn-sm btn-outline" onClick={() => void refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="knowledge-stats">
        {liveStats.map((stat) => (
          <article key={stat.id} className="knowledge-stat card">
            <span className={`knowledge-stat-ico ${stat.tone}`}>
              <FbIcon name={stat.icon} size={16} />
            </span>
            <div className="knowledge-stat-body">
              <div className="knowledge-stat-label">{stat.label}</div>
              <div className="knowledge-stat-value-row">
                <span className="knowledge-stat-value">{stat.value}</span>
                {stat.delta ? (
                  <span className={`knowledge-stat-delta ${stat.deltaTone ?? ""}`}>{stat.delta}</span>
                ) : null}
              </div>
              <div className="knowledge-stat-hint">{stat.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="knowledge-toolbar">
        <label className="knowledge-search">
          <FbIcon name="search" size={14} />
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              if (!event.target.value.trim()) setSearchMatches(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") void runSearch();
            }}
            placeholder="Zoek in documenten, inhoud, samenvattingen, hashtags..."
            aria-label="Zoek in documenten"
          />
        </label>
        <button
          type="button"
          className="btn btn-gold knowledge-search-btn"
          disabled={searchBusy}
          onClick={() => void runSearch()}
        >
          {searchBusy ? "Zoeken…" : "Zoeken"}
        </button>
        {KNOWLEDGE_FILTERS.map((filter) => (
          <button key={filter} type="button" className="knowledge-filter" data-toast={filter}>
            {filter}
            <FbIcon name="chevron" size={12} />
          </button>
        ))}
        <button type="button" className="knowledge-filter-ico" aria-label="Filters" data-toast="Filters">
          <FbIcon name="sliders" size={14} />
        </button>
      </div>

      {searchError ? (
        <p className="muted" role="alert" style={{ marginBottom: 8 }}>
          Zoeken mislukt: {searchError} — lokale filter actief.
        </p>
      ) : null}
      {searchMatches ? (
        <p className="muted" style={{ marginBottom: 8 }}>
          {searchMatches.length} knowledge-matches · {filtered.length} bronnen
        </p>
      ) : null}

      <div className="knowledge-tags">
        {KNOWLEDGE_TAGS.map((tag) => (
          <button
            key={tag}
            type="button"
            className="knowledge-tag"
            onClick={() => {
              setQuery(tag);
              void runSearch();
            }}
          >
            {tag}
          </button>
        ))}
        <button type="button" className="knowledge-tag add" aria-label="Tag toevoegen" data-toast="Tag toevoegen">
          <FbIcon name="plus" size={12} />
        </button>
      </div>

      <div className="knowledge-split">
        <aside className="knowledge-side">
          <section className="card knowledge-collections">
            <div className="knowledge-panel-head">
              <h2>Collecties</h2>
              <button type="button" className="knowledge-link" data-toast="Nieuwe collectie">
                <FbIcon name="plus" size={11} />
              </button>
            </div>
            <ul className="knowledge-col-list">
              {collections.map((col) => (
                <li key={col.id}>
                  <button
                    type="button"
                    className={`knowledge-col-item${collectionId === col.id ? " active" : ""}`}
                    onClick={() => setCollectionId(col.id)}
                  >
                    <span className="knowledge-col-ico">
                      <FbIcon name={col.icon} size={13} />
                    </span>
                    <span className="knowledge-col-label">{col.label}</span>
                    <b>{col.count.toLocaleString("nl-NL")}</b>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="card knowledge-storage">
            <div className="knowledge-panel-head compact">
              <h2>Opslaggebruik</h2>
              <span>
                {stats?.chunks ?? 0} chunks
              </span>
            </div>
            <div className="knowledge-storage-bar">
              <i
                style={{
                  width: `${Math.min(100, docs.length ? (indexedCount / Math.max(1, docs.length)) * 100 : 0)}%`,
                }}
              />
            </div>
            <div className="knowledge-storage-meta">
              {docs.length
                ? `${Math.round((indexedCount / Math.max(1, docs.length)) * 100)}% geïndexeerd`
                : "Geen bronnen"}
            </div>
            <button type="button" className="btn btn-sm btn-outline btn-block" onClick={() => void refresh()}>
              Vernieuwen
            </button>
          </section>
        </aside>

        <section className="card knowledge-docs">
          <div className="knowledge-docs-head">
            <h2>
              Documenten <span>({filtered.length.toLocaleString("nl-NL")})</span>
            </h2>
            <div className="knowledge-docs-actions">
              <button type="button" className="btn btn-sm btn-gold" data-toast="Uploaden">
                <FbIcon name="upload" size={12} />
                Uploaden
              </button>
              <button type="button" className="btn btn-sm btn-outline" data-toast="Map aanmaken">
                <FbIcon name="folder" size={12} />
                Map aanmaken
              </button>
              <button type="button" className="btn btn-sm btn-outline" data-toast="Export">
                <FbIcon name="download" size={12} />
                Export
              </button>
              <button type="button" className="knowledge-icon-btn" aria-label="Meer" data-toast="Meer">
                <FbIcon name="more" size={14} />
              </button>
            </div>
          </div>

          <div className="knowledge-table-wrap">
            <table className="knowledge-table">
              <thead>
                <tr>
                  <th className="kl-check">
                    <input type="checkbox" aria-label="Alles selecteren" />
                  </th>
                  <th>Naam</th>
                  <th>Type</th>
                  <th>Collectie</th>
                  <th>Status</th>
                  <th>Laatst gewijzigd</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {loading && !docs.length ? (
                  <tr>
                    <td colSpan={7} className="muted">
                      Documenten laden…
                    </td>
                  </tr>
                ) : null}
                {!loading && !filtered.length ? (
                  <tr>
                    <td colSpan={7} className="muted">
                      Geen documenten gevonden.
                    </td>
                  </tr>
                ) : null}
                {pageDocs.map((doc) => (
                  <DocRow
                    key={doc.id}
                    doc={doc}
                    active={doc.id === selected?.id}
                    onSelect={() => setSelectedId(doc.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="knowledge-pagination">
            <span className="knowledge-page-info">
              {filtered.length
                ? `${(pageNum - 1) * pageSize + 1}–${Math.min(pageNum * pageSize, filtered.length)} van ${filtered.length} documenten`
                : "0 documenten"}
            </span>
            <div className="knowledge-pages" role="navigation" aria-label="Paginering">
              {Array.from({ length: Math.min(pageCount, 5) }, (_, i) => i + 1).map((n) => (
                <button
                  key={n}
                  type="button"
                  className={pageNum === n ? "active" : undefined}
                  onClick={() => setPageNum(n)}
                >
                  {n}
                </button>
              ))}
              {pageCount > 5 ? (
                <>
                  <span>…</span>
                  <button type="button" onClick={() => setPageNum(pageCount)}>
                    {pageCount}
                  </button>
                </>
              ) : null}
            </div>
            <label className="knowledge-rows">
              Rijen per pagina:
              <select
                value={String(pageSize)}
                aria-label="Rijen per pagina"
                onChange={(e) => setPageSize(Number(e.target.value))}
              >
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="50">50</option>
              </select>
            </label>
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = selected ? (
    <>
      <p className="knowledge-insp-quote">“From information to intelligence.”</p>

      <section className="insp-section">
        <div className="knowledge-insp-head">
          <h3 className="insp-title">Document details</h3>
          <button type="button" className="knowledge-insp-close" aria-label="Sluiten" data-toast="Gesloten">
            ×
          </button>
        </div>
        <div className="insp-card knowledge-identity">
          <span className={`kl-type-ico lg ${selected.typeTone}`}>
            <FbIcon name={typeIcon(selected.type)} size={18} />
          </span>
          <div>
            <h2>{selected.name}</h2>
            <div className="knowledge-identity-meta">
              <span className={`kl-type-pill ${selected.typeTone}`}>{selected.type}</span>
              <span className="knowledge-size-pill">{selected.size}</span>
            </div>
          </div>
        </div>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Collectie</span>
            <span className="v">{selected.collection}</span>
          </div>
          <div className="detail-row">
            <span className="k">Status</span>
            <span className={`v ${statusTone(selected.status)}`}>● {selected.statusLabel}</span>
          </div>
          <div className="detail-row">
            <span className="k">Laatst gewijzigd</span>
            <span className="v">{selected.modified}</span>
          </div>
          <div className="detail-row">
            <span className="k">Chunks</span>
            <span className="v">{selected.chunks ?? "—"}</span>
          </div>
          <div className="detail-row">
            <span className="k">Taal</span>
            <span className="v">{selected.language}</span>
          </div>
          <div className="detail-row">
            <span className="k">Bron</span>
            <span className="v">{selected.source}</span>
          </div>
          <div className="detail-row">
            <span className="k">Bron type</span>
            <span className="v">{selected.sourceType}</span>
          </div>
          <div className="detail-row knowledge-confidence-row">
            <span className="k">Gem. betrouwbaarheid</span>
            <span className="v knowledge-confidence">
              <span className="knowledge-confidence-bar">
                <i style={{ width: `${selected.confidence}%` }} />
              </span>
              {selected.confidence}%
            </span>
          </div>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Tags</h3>
        <div className="knowledge-insp-tags">
          {selected.tags.length ? selected.tags.map((tag) => <span key={tag}>{tag}</span>) : <span>—</span>}
          <button type="button" className="knowledge-tag add" aria-label="Tag toevoegen" data-toast="Tag toevoegen">
            <FbIcon name="plus" size={11} />
          </button>
        </div>
      </section>

      <section className="insp-section">
        <div className="knowledge-insp-section-head">
          <h3 className="insp-title">AI-samenvatting</h3>
          <button type="button" className="btn btn-sm btn-outline" data-toast="Bewerken">
            Bewerken
          </button>
        </div>
        <div className="insp-card">
          <p className="knowledge-summary">{selected.summary}</p>
        </div>
      </section>

      <section className="insp-section">
        <div className="knowledge-insp-section-head">
          <h3 className="insp-title">Broncollectie</h3>
          <button type="button" className="btn btn-sm btn-outline" data-toast="Naar collectie">
            Naar collectie
          </button>
        </div>
        <button type="button" className="knowledge-bron" data-toast={selected.collection}>
          <span className="knowledge-bron-ico">
            <FbIcon name="folder" size={14} />
          </span>
          {selected.collection}
        </button>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Acties</h3>
        <div className="knowledge-action-grid">
          {KNOWLEDGE_ACTIONS.map((action) => (
            <button
              key={action.id}
              type="button"
              className={`knowledge-action${"danger" in action && action.danger ? " danger" : ""}`}
              onClick={() => void runKnowledgeAction(action.id)}
            >
              <FbIcon name={action.icon} size={14} />
              <span>{action.label}</span>
            </button>
          ))}
        </div>
      </section>
    </>
  ) : (
    <>
      <p className="knowledge-insp-quote">“From information to intelligence.”</p>
      <section className="insp-section">
        <div className="insp-card">
          <p className="muted">{loading ? "Laden…" : "Selecteer een document."}</p>
        </div>
      </section>
    </>
  );

  const footer = (
    <footer className="dash-footer knowledge-footer">
      <span>HADES FINALBETA v0.9.0&nbsp;&nbsp;|&nbsp;&nbsp;Knowledge Library</span>
      <span className="motto">
        Build a smarter tomorrow. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="knowledge"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="knowledge-app"
      mainClassName="knowledge-main"
      footer={footer}
    />
  );
}
