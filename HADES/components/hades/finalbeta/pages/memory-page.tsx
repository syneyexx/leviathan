/** FINALBETA Memory — live memories API (visual shell preserved). */
"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useHadesMemory } from "@/components/hades/features/memory/hooks/useHadesMemory";
import { formatBytes, formatDate } from "@/lib/hades-api";
import { donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import {
  MEMORY_ACTIONS,
  MEMORY_HEALTH_CHECKS,
  MEMORY_TAGS,
} from "../mocks/memory";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

type MemoryTone = "purple" | "green" | "cyan" | "gold" | "blue";

type MemoryRowView = {
  id: string;
  title: string;
  summary: string;
  ago: string;
  kindLabel: string;
  tone: MemoryTone;
  icon: string;
  status: string;
  created: string;
  lastUsed: string;
  relevance: number;
  relevanceLabel: string;
  project: string;
  tags: string[];
  source: string;
  links: number;
  content: string[];
  related: Array<{ title: string; ago: string; icon: string; tone: string }>;
  kind: string;
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

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function relativeAgo(iso: string | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = Date.now() - t;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "zojuist";
  if (mins < 60) return `${mins}m geleden`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}u geleden`;
  const days = Math.floor(hours / 24);
  return `${days}d geleden`;
}

function toneForScope(scope: string | undefined, collection: string): MemoryTone {
  const s = String(scope || "").toLowerCase();
  if (s === "global") return "gold";
  if (s === "session") return "cyan";
  if (s === "project") return "green";
  const c = collection.toLowerCase();
  if (c.includes("voorkeur") || c.includes("prefer")) return "purple";
  return "blue";
}

function kindLabelFor(scope: string | undefined, collection: string): string {
  const s = String(scope || "").toLowerCase();
  if (s === "global") return "Persistent";
  if (s === "session") return "Sessie";
  if (s === "project") return "Project";
  if (collection.toLowerCase().includes("voorkeur")) return "Voorkeur";
  return collection || "Herinnering";
}

function iconFor(scope: string | undefined): string {
  const s = String(scope || "").toLowerCase();
  if (s === "global") return "bolt";
  if (s === "session") return "clock";
  if (s === "project") return "folder";
  return "book";
}

function toRowView(card: {
  id: string;
  title: string;
  summary: string;
  content: string;
  collection: string;
  tags: string[];
  source: string;
  scope?: string;
  created_at: string;
  updated_at: string;
}): MemoryRowView {
  const tone = toneForScope(card.scope, card.collection);
  const lines = String(card.content || "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 8);
  return {
    id: card.id,
    title: card.title,
    summary: card.summary || lines[0] || "—",
    ago: relativeAgo(card.updated_at || card.created_at),
    kindLabel: kindLabelFor(card.scope, card.collection),
    tone,
    icon: iconFor(card.scope),
    status: "Actief",
    created: formatDate(card.created_at),
    lastUsed: formatDate(card.updated_at),
    relevance: 70,
    relevanceLabel: "Live",
    project: card.collection || "Algemeen",
    tags: card.tags || [],
    source: card.source || "—",
    links: 0,
    content: lines.length ? lines : [card.summary || "Geen inhoud"],
    related: [],
    kind: String(card.scope || "project"),
  };
}

function MemoryRow({
  memory,
  active,
  onSelect,
}: {
  memory: MemoryRowView;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" className={`mem-row${active ? " active" : ""}`} onClick={onSelect}>
      <span className={`mem-row-ico ${memory.tone}`}>
        <FbIcon name={memory.icon} size={14} />
      </span>
      <span className="mem-row-copy">
        <strong>{memory.title}</strong>
        <small>{memory.summary}</small>
      </span>
      <span className="mem-row-ago">{memory.ago}</span>
      <span className={`mem-chip ${memory.tone}`}>{memory.kindLabel}</span>
      <span className="mem-row-menu" aria-hidden="true">
        <FbIcon name="more" size={14} />
      </span>
    </button>
  );
}

export function MemoryPage({ onNavigate }: Props) {
  const [now, setNow] = useState(() => new Date());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [localSearch, setLocalSearch] = useState("");

  const memory = useHadesMemory("");
  const {
    cards,
    stats,
    collections,
    query,
    setQuery,
    loading,
    error,
    refresh,
    create,
    remove,
  } = memory;

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const rows = useMemo(() => cards.map(toRowView), [cards]);

  useEffect(() => {
    if (!rows.length) {
      setSelectedId(null);
      return;
    }
    setSelectedId((current) => (current && rows.some((r) => r.id === current) ? current : rows[0]!.id));
  }, [rows]);

  const selected = rows.find((item) => item.id === selectedId) ?? null;

  const categorySlices = useMemo(() => {
    const counts = {
      persistent: 0,
      project: 0,
      preference: 0,
      fact: 0,
      session: 0,
    };
    for (const card of cards) {
      const scope = String(card.scope || "").toLowerCase();
      const col = String(card.collection || "").toLowerCase();
      if (scope === "global") counts.persistent += 1;
      else if (scope === "session") counts.session += 1;
      else if (scope === "project") counts.project += 1;
      else if (col.includes("voorkeur") || col.includes("prefer")) counts.preference += 1;
      else counts.fact += 1;
    }
    return [
      { label: "Persistente herinneringen", count: counts.persistent, color: "#f0b429" },
      { label: "Projectherinneringen", count: counts.project, color: "#20e38d" },
      { label: "Persoonlijke voorkeuren", count: counts.preference, color: "#9b5cff" },
      { label: "Feiten & context", count: counts.fact, color: "#1aa4ff" },
      { label: "Sessiegeheugen", count: counts.session, color: "#20c8e8" },
    ];
  }, [cards]);

  const total = stats?.items ?? categorySlices.reduce((sum, slice) => sum + slice.count, 0);
  const donut = donutSegments(categorySlices.map((s) => ({ ...s })));

  const liveStats = [
    {
      id: "total",
      label: "Totaal herinneringen",
      value: loading && !cards.length ? "…" : String(stats?.items ?? cards.length),
      hint: `${stats?.collections ?? collections.length} collecties`,
      icon: "database",
      tone: "cyan" as const,
    },
    {
      id: "indexed",
      label: "Geïndexeerd",
      value: loading && !cards.length ? "…" : String(stats?.indexed ?? cards.length),
      hint: "Beschikbaar voor retrieval",
      icon: "bolt",
      tone: "gold" as const,
    },
    {
      id: "collections",
      label: "Collecties",
      value: loading && !cards.length ? "…" : String(stats?.collections ?? collections.length),
      hint: collections.slice(0, 3).join(", ") || "geen collecties",
      icon: "folder",
      tone: "green" as const,
    },
    {
      id: "storage",
      label: "Database",
      value: stats?.database_bytes != null ? formatBytes(stats.database_bytes) : "—",
      hint: "Lokale SQLite opslag",
      icon: "database",
      tone: "blue" as const,
    },
    {
      id: "health",
      label: "Geheugen gezondheid",
      value: error ? "Fout" : loading ? "…" : "OK",
      hint: error ? error.message : "Live API verbonden",
      icon: "shield",
      tone: error ? ("gold" as const) : ("green" as const),
    },
  ];

  const projectCards = useMemo(() => {
    const map = new Map<string, number>();
    for (const card of cards) {
      const key = card.collection || "Algemeen";
      map.set(key, (map.get(key) || 0) + 1);
    }
    const tones: MemoryTone[] = ["gold", "cyan", "green", "purple"];
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([title, count], index) => ({
        title,
        count,
        tone: tones[index % tones.length]!,
      }));
  }, [cards]);

  async function onSearch() {
    setQuery(localSearch.trim());
  }

  async function onCreate() {
    const title = draftTitle.trim() || "Nieuwe herinnering";
    const content = draftContent.trim() || title;
    setBusy(true);
    try {
      const item = await create({
        title,
        content,
        summary: content.slice(0, 160),
        collection: "Algemeen",
        tags: [],
        source: "Handmatig",
        scope: "project",
      });
      setSelectedId(item.id);
      setDraftOpen(false);
      setDraftTitle("");
      setDraftContent("");
      toast.success("Herinnering aangemaakt");
    } catch (err) {
      toast.error(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!selected) return;
    setBusy(true);
    try {
      await remove(selected.id);
      toast.success("Herinnering verwijderd");
    } catch (err) {
      toast.error(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const body = (
    <div className="memory-page" data-live="memory">
      <div className="memory-welcome">
        <div className="memory-welcome-copy">
          <h1>Geheugen</h1>
          <p>Je persoonlijke context, voorkeuren en projectkennis. HADES onthoudt wat belangrijk is.</p>
        </div>
        <div className="memory-welcome-mid">“Context turns information into intelligence.”</div>
        <div className="memory-clock">
          <div className="memory-clock-copy">
            <div className="date">
              {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
            </div>
            <div className="time">
              {pad(now.getHours())}:{pad(now.getMinutes())}
            </div>
          </div>
          <FbIcon name="bolt" size={22} className="memory-sun" />
        </div>
      </div>

      {error ? (
        <div className="card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Geheugen laden mislukt.</strong> {error.message}{" "}
          <button type="button" className="btn btn-sm btn-outline" onClick={() => void refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="memory-stats">
        {liveStats.map((stat) => (
          <article key={stat.id} className="memory-stat card">
            <span className={`memory-stat-ico ${stat.tone}`}>
              <FbIcon name={stat.icon} size={16} />
            </span>
            <div>
              <div className="memory-stat-label">{stat.label}</div>
              <div className="memory-stat-value">{stat.value}</div>
              <div className="memory-stat-hint">{stat.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="memory-toolbar">
        <label className="memory-search">
          <FbIcon name="search" size={14} />
          <input
            value={localSearch}
            onChange={(event) => setLocalSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void onSearch();
            }}
            placeholder="Zoek in herinneringen..."
            aria-label="Zoek in herinneringen"
          />
        </label>
        <button type="button" className="memory-filter" data-toast="Filter types">
          Alle types
          <FbIcon name="chevron" size={12} />
        </button>
        <button type="button" className="memory-filter" data-toast="Filter projecten">
          Alle projecten
          <FbIcon name="chevron" size={12} />
        </button>
        <button type="button" className="memory-filter" data-toast="Filter tags">
          Alle tags
          <FbIcon name="chevron" size={12} />
        </button>
        <button type="button" className="memory-filter" data-toast="Sorteren">
          Nieuwste eerst
          <FbIcon name="chevron" size={12} />
        </button>
        <button type="button" className="btn btn-gold memory-search-btn" onClick={() => void onSearch()}>
          Zoeken
        </button>
      </div>

      <div className="memory-mid">
        <section className="card memory-recent">
          <div className="memory-panel-head">
            <div>
              <h2>Recente herinneringen</h2>
              <p>
                {loading && !rows.length
                  ? "Laden…"
                  : `${rows.length} resultaten${query ? ` voor “${query}”` : ""}`}
              </p>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-gold"
              disabled={busy}
              onClick={() => setDraftOpen(true)}
            >
              <FbIcon name="plus" size={12} />
              Nieuwe herinnering
            </button>
          </div>
          {draftOpen ? (
            <div className="memory-draft" style={{ padding: "0 12px 12px", display: "grid", gap: 8 }}>
              <input
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                placeholder="Titel"
                aria-label="Titel nieuwe herinnering"
              />
              <textarea
                value={draftContent}
                onChange={(e) => setDraftContent(e.target.value)}
                placeholder="Inhoud"
                rows={3}
                aria-label="Inhoud nieuwe herinnering"
              />
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" className="btn btn-sm btn-gold" disabled={busy} onClick={() => void onCreate()}>
                  Opslaan
                </button>
                <button type="button" className="btn btn-sm btn-outline" disabled={busy} onClick={() => setDraftOpen(false)}>
                  Annuleren
                </button>
              </div>
            </div>
          ) : null}
          <div className="memory-recent-list">
            {loading && !rows.length ? (
              <p className="muted" style={{ padding: 16 }}>
                Herinneringen laden…
              </p>
            ) : null}
            {!loading && !rows.length ? (
              <p className="muted" style={{ padding: 16 }}>
                Geen herinneringen gevonden. Maak een nieuwe herinnering aan.
              </p>
            ) : null}
            {rows.map((item) => (
              <MemoryRow
                key={item.id}
                memory={item}
                active={item.id === selected?.id}
                onSelect={() => setSelectedId(item.id)}
              />
            ))}
          </div>
        </section>

        <div className="memory-side-stack">
          <section className="card memory-cats">
            <div className="memory-panel-head compact">
              <h2>Geheugen categorieën</h2>
            </div>
            <div className="memory-cats-body">
              <div className="memory-donut-wrap">
                <svg viewBox="0 0 42 42" className="memory-donut" aria-hidden="true">
                  <circle cx="21" cy="21" r="14" fill="none" stroke="rgba(74,163,255,0.12)" strokeWidth="5" />
                  {donut.map((seg, index) => (
                    <circle
                      key={categorySlices[index]!.label}
                      cx="21"
                      cy="21"
                      r="14"
                      fill="none"
                      stroke={seg.color}
                      strokeWidth="5"
                      strokeDasharray={seg.dash}
                      strokeDashoffset={seg.offset}
                      transform="rotate(-90 21 21)"
                    />
                  ))}
                </svg>
                <div className="memory-donut-center">
                  <strong>{total.toLocaleString("nl-NL")}</strong>
                  <span>totaal</span>
                </div>
              </div>
              <ul className="memory-cat-legend">
                {categorySlices.map((slice) => (
                  <li key={slice.label}>
                    <i style={{ background: slice.color }} />
                    <span>{slice.label}</span>
                    <b>{slice.count.toLocaleString("nl-NL")}</b>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="card memory-tags">
            <div className="memory-panel-head compact">
              <h2>Populaire tags</h2>
              <button type="button" className="memory-link" data-toast="Alle tags">
                Alles bekijken
              </button>
            </div>
            <div className="memory-tag-cloud">
              {MEMORY_TAGS.map((item) => (
                <button key={item.tag} type="button" className="memory-tag" data-toast={item.tag}>
                  {item.tag} <b>{item.count}</b>
                </button>
              ))}
            </div>
          </section>

          <section className="card memory-health">
            <div className="memory-panel-head compact">
              <h2>Geheugen gezondheid</h2>
            </div>
            <div className="memory-health-body">
              <div className="memory-health-gauge">
                <span className="memory-health-ico">
                  <FbIcon name="shield" size={18} />
                </span>
                <div>
                  <strong>{error ? "—" : "OK"}</strong>
                  <span>{error ? "Fout" : "Live"}</span>
                </div>
              </div>
              <ul className="memory-health-list">
                {MEMORY_HEALTH_CHECKS.map((check) => (
                  <li key={check.label}>
                    <span>{check.label}</span>
                    <b className={check.tone}>{check.value}</b>
                  </li>
                ))}
                <li className="memory-storage">
                  <div className="memory-storage-top">
                    <span>Opslaggebruik</span>
                    <b>{stats?.database_bytes != null ? formatBytes(stats.database_bytes) : "—"}</b>
                  </div>
                  <div className="memory-storage-bar">
                    <i style={{ width: stats?.database_bytes ? "40%" : "0%" }} />
                  </div>
                </li>
              </ul>
            </div>
          </section>
        </div>
      </div>

      <div className="memory-bottom">
        <section className="card memory-chats">
          <div className="memory-panel-head compact">
            <h2>Gekoppelde gesprekken</h2>
          </div>
          <ul className="memory-chat-list">
            <li>
              <FbIcon name="chat" size={14} />
              <div>
                <strong>Geen gekoppelde gesprekken</strong>
                <small>Koppelingen verschijnen wanneer chat-context wordt gepromoveerd</small>
              </div>
              <b>0</b>
            </li>
          </ul>
        </section>

        <section className="card memory-projects">
          <div className="memory-panel-head compact">
            <h2>Project herinneringen</h2>
          </div>
          <div className="memory-project-grid">
            {projectCards.length ? (
              projectCards.map((project) => (
                <button
                  key={project.title}
                  type="button"
                  className={`memory-project ${project.tone}`}
                  onClick={() => {
                    setLocalSearch(project.title);
                    setQuery(project.title);
                  }}
                >
                  <FbIcon name="folder" size={16} />
                  <strong>{project.title}</strong>
                  <span>{project.count} herinneringen</span>
                </button>
              ))
            ) : (
              <p className="muted" style={{ padding: 8 }}>
                Nog geen projectcollecties.
              </p>
            )}
          </div>
        </section>

        <section className="card memory-actions">
          <div className="memory-panel-head compact">
            <h2>Snelle acties</h2>
          </div>
          <div className="memory-action-grid">
            {MEMORY_ACTIONS.map((action) => (
              <button
                key={action.label}
                type="button"
                className="memory-action"
                onClick={() => {
                  if (action.label === "Nieuwe herinnering") setDraftOpen(true);
                  else toast.message(action.label);
                }}
              >
                <FbIcon name={action.icon} size={15} />
                <span>{action.label}</span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = selected ? (
    <>
      <div className="memory-insp-head">
        <div>
          <h3 className="insp-title">Herinnering details</h3>
        </div>
        <button type="button" className="memory-insp-close" aria-label="Sluiten" data-toast="Gesloten">
          ×
        </button>
      </div>

      <section className="insp-section">
        <div className="insp-card memory-identity">
          <span className={`mem-row-ico lg ${selected.tone}`}>
            <FbIcon name={selected.icon} size={18} />
          </span>
          <div>
            <h2>{selected.title}</h2>
            <span className={`mem-chip ${selected.tone}`}>{selected.kindLabel}</span>
          </div>
        </div>
      </section>

      <section className="insp-section">
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Type</span>
            <span className="v">{selected.kindLabel}</span>
          </div>
          <div className="detail-row">
            <span className="k">Status</span>
            <span className="v green">● {selected.status}</span>
          </div>
          <div className="detail-row">
            <span className="k">Aangemaakt</span>
            <span className="v">{selected.created}</span>
          </div>
          <div className="detail-row">
            <span className="k">Laatst gebruikt</span>
            <span className="v">{selected.lastUsed}</span>
          </div>
          <div className="detail-row memory-relevance-row">
            <span className="k">Relevantie</span>
            <span className="v memory-relevance">
              <span className="memory-relevance-bar">
                <i style={{ width: `${selected.relevance}%` }} />
              </span>
              {selected.relevanceLabel}
            </span>
          </div>
          <div className="detail-row">
            <span className="k">Project</span>
            <span className="v">{selected.project}</span>
          </div>
          <div className="detail-row">
            <span className="k">Tags</span>
            <span className="v memory-insp-tags">
              {selected.tags.length
                ? selected.tags.map((tag) => <span key={tag}>{tag}</span>)
                : "—"}
            </span>
          </div>
          <div className="detail-row">
            <span className="k">Bron</span>
            <span className="v">{selected.source}</span>
          </div>
          <div className="detail-row">
            <span className="k">Koppelingen</span>
            <span className="v">{selected.links} gerelateerde items</span>
          </div>
        </div>
      </section>

      <section className="insp-section">
        <div className="memory-insp-section-head">
          <h3 className="insp-title">Inhoud</h3>
          <button type="button" className="btn btn-sm btn-outline" data-toast="Bewerken">
            Bewerken
          </button>
        </div>
        <div className="insp-card">
          <ul className="memory-content-list">
            {selected.content.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      </section>

      <div className="memory-insp-actions">
        <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={() => void onDelete()}>
          Verwijderen
        </button>
        <button type="button" className="btn btn-sm btn-outline" data-toast="Meer acties">
          Meer acties
          <FbIcon name="chevron" size={12} />
        </button>
      </div>
    </>
  ) : (
    <>
      <div className="memory-insp-head">
        <h3 className="insp-title">Herinnering details</h3>
      </div>
      <section className="insp-section">
        <div className="insp-card">
          <p className="muted">{loading ? "Laden…" : "Selecteer een herinnering."}</p>
        </div>
      </section>
    </>
  );

  const footer = (
    <footer className="dash-footer memory-footer">
      <span>HADES FINALBETA v0.9.0&nbsp;&nbsp;|&nbsp;&nbsp;Knowledge Platform</span>
      <span className="motto">
        Build a smarter tomorrow. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="memory"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="memory-app"
      mainClassName="memory-main"
      footer={footer}
    />
  );
}
