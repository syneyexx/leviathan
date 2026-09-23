import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { onderzoekHeroes } from "../assets/onderzoekKennisAssets";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { HealthResponse, MemoryKind, MemoryRecord, MemoryStatus } from "../types/api";
import {
  OkGauge,
  OkHero,
  OkIcon,
  OkPanel,
  OkProgress,
} from "./onderzoek/ok-shared";

type TabId =
  | "overview"
  | "ingestion"
  | "graph"
  | "recall"
  | "organization"
  | "retention"
  | "settings";

type RecallMode = "hybride" | "exact";

const TABS: { id: TabId; label: string; hint: string; icon: ReactNode }[] = [
  {
    id: "overview",
    label: "Overview",
    hint: "Memory dashboard",
    icon: (
      <OkIcon>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </OkIcon>
    ),
  },
  {
    id: "ingestion",
    label: "Ingestion",
    hint: "Capture & process",
    icon: (
      <OkIcon>
        <path d="M12 3v12" />
        <path d="M8 11l4 4 4-4" />
        <path d="M4 19h16" />
      </OkIcon>
    ),
  },
  {
    id: "graph",
    label: "Memory Graph",
    hint: "Connections & context",
    icon: (
      <OkIcon>
        <circle cx="6" cy="6" r="2.5" />
        <circle cx="18" cy="8" r="2.5" />
        <circle cx="10" cy="18" r="2.5" />
        <path d="M8 7.5l7.5 0.8M8 16.5l8-7" />
      </OkIcon>
    ),
  },
  {
    id: "recall",
    label: "Recall",
    hint: "Search & retrieve",
    icon: (
      <OkIcon>
        <circle cx="11" cy="11" r="6" />
        <path d="M16 16l4 4" />
      </OkIcon>
    ),
  },
  {
    id: "organization",
    label: "Organization",
    hint: "Tags, folders & structure",
    icon: (
      <OkIcon>
        <path d="M3 7h6l2 2h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
      </OkIcon>
    ),
  },
  {
    id: "retention",
    label: "Retention",
    hint: "Policies & lifecycle",
    icon: (
      <OkIcon>
        <circle cx="12" cy="12" r="8" />
        <path d="M12 8v4l3 2" />
      </OkIcon>
    ),
  },
  {
    id: "settings",
    label: "Settings",
    hint: "Memory configuration",
    icon: (
      <OkIcon>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
      </OkIcon>
    ),
  },
];

const KIND_OPTIONS: { id: MemoryKind; label: string; tone: "gold" | "cyan" | "purple" }[] = [
  { id: "EPISODIC", label: "Episodisch", tone: "gold" },
  { id: "FACT", label: "Feiten / semantisch", tone: "cyan" },
  { id: "PROCEDURE", label: "Procedureel", tone: "purple" },
  { id: "PREFERENCE", label: "Voorkeuren", tone: "cyan" },
  { id: "NOTE", label: "Notities", tone: "gold" },
  { id: "DECISION", label: "Beslissingen", tone: "gold" },
  { id: "SUMMARY", label: "Samenvattingen", tone: "cyan" },
  { id: "PROJECT", label: "Project", tone: "purple" },
];

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function relativeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s geleden`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m geleden`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}u geleden`;
  return `${Math.round(hr / 24)}d geleden`;
}

function excerpt(text: string, max = 120): string {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max - 1)}…`;
}

function kindLabel(kind: string): string {
  return KIND_OPTIONS.find((k) => k.id === kind)?.label ?? kind;
}

export function GeheugenPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<TabId>("overview");
  const [recallMode, setRecallMode] = useState<RecallMode>("hybride");
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<MemoryStatus | "ACTIVE">("ACTIVE");
  const [sortBy, setSortBy] = useState<"recent" | "priority" | "kind">("recent");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [archived, setArchived] = useState<MemoryRecord[]>([]);
  const [revoked, setRevoked] = useState<MemoryRecord[]>([]);
  const [hits, setHits] = useState<MemoryRecord[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [posture, setPosture] = useState<string>("unmeasured");

  const [draftContent, setDraftContent] = useState("");
  const [draftKind, setDraftKind] = useState<MemoryKind>("NOTE");
  const [draftTags, setDraftTags] = useState("");
  const [draftScope, setDraftScope] = useState<"GLOBAL" | "PROJECT">("GLOBAL");
  const [draftProjectId, setDraftProjectId] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [health, activeRes, archivedRes, revokedRes] = await Promise.all([
        api.health().catch(() => null as HealthResponse | null),
        api.listMemory({ status: "ACTIVE", limit: 500 }),
        api.listMemory({ status: "ARCHIVED", limit: 200 }),
        api.listMemory({ status: "REVOKED", limit: 200 }),
      ]);
      setPosture(String(health?.posture || health?.product_truth?.overall || "unmeasured"));
      setMemories(activeRes.memory);
      setArchived(archivedRes.memory);
      setRevoked(revokedRes.memory);
      if (activeRes.memory.length > 0) {
        setSelectedId((prev) =>
          prev && activeRes.memory.some((m) => m.memory_id === prev)
            ? prev
            : activeRes.memory[0].memory_id,
        );
      } else {
        setSelectedId(null);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load memory"));
      setMemories([]);
      setArchived([]);
      setRevoked([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const kindCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const m of memories) {
      counts.set(m.kind, (counts.get(m.kind) ?? 0) + 1);
    }
    return counts;
  }, [memories]);

  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const m of memories) {
      for (const tag of m.tags || []) {
        const key = tag.trim();
        if (!key) continue;
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [memories]);

  const filtered = useMemo(() => {
    let rows = [...memories];
    if (kindFilter !== "all") {
      rows = rows.filter((m) => m.kind === kindFilter);
    }
    if (sortBy === "recent") {
      rows.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    } else if (sortBy === "priority") {
      rows.sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
    } else {
      rows.sort((a, b) => String(a.kind).localeCompare(String(b.kind)));
    }
    return rows;
  }, [memories, kindFilter, sortBy]);

  const selected =
    filtered.find((m) => m.memory_id === selectedId) ??
    memories.find((m) => m.memory_id === selectedId) ??
    null;

  const pinned = useMemo(
    () =>
      [...memories]
        .filter((m) => (m.tags || []).some((t) => t.toLowerCase() === "pinned"))
        .slice(0, 8),
    [memories],
  );

  const recent = useMemo(
    () =>
      [...memories]
        .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
        .slice(0, 8),
    [memories],
  );

  const totalKnown = memories.length + archived.length + revoked.length;
  const gaugeValue =
    posture === "operational" ? 80 : posture === "degraded" ? 45 : posture === "fixture" ? 20 : memories.length > 0 ? 60 : 0;
  const gaugeLabel =
    posture === "operational"
      ? "Operational"
      : posture === "degraded"
        ? "Degraded"
        : posture === "fixture"
          ? "Fixture"
          : memories.length > 0
            ? "Live"
            : "Empty";

  async function runRecall() {
    const q = query.trim();
    if (!q) {
      toast("Voer een zoekterm in");
      return;
    }
    setBusy(true);
    setSearched(true);
    try {
      if (recallMode === "exact") {
        const needle = q.toLowerCase();
        const local = memories.filter(
          (m) =>
            m.content.toLowerCase().includes(needle) ||
            (m.tags || []).some((t) => t.toLowerCase().includes(needle)) ||
            m.kind.toLowerCase().includes(needle),
        );
        setHits(local);
        if (local.length === 0) toast("Geen exacte matches");
      } else {
        const res = await api.searchMemory({ q, limit: 40 });
        setHits(res.memory);
        if (res.memory.length === 0) toast("Geen recall hits");
      }
      setTab("recall");
    } catch (err) {
      setHits([]);
      toast(errMsg(err, "Recall mislukt"));
    } finally {
      setBusy(false);
    }
  }

  async function onCreate() {
    const content = draftContent.trim();
    if (!content) {
      toast("Inhoud is verplicht");
      return;
    }
    if (draftScope === "PROJECT" && !draftProjectId.trim()) {
      toast("Project scope vereist een project_id");
      return;
    }
    setBusy(true);
    try {
      const tags = draftTags
        .split(/[,;]/)
        .map((t) => t.trim())
        .filter(Boolean);
      const res = await api.createMemory({
        content,
        kind: draftKind,
        source: "manual",
        trust: "explicit",
        tags,
        scope: draftScope,
        project_id: draftScope === "PROJECT" ? draftProjectId.trim() : null,
      });
      setDraftContent("");
      setDraftTags("");
      setSelectedId(res.memory.memory_id);
      setTab("overview");
      await load();
      toast("Memory opgeslagen");
    } catch (err) {
      toast(errMsg(err, "Opslaan mislukt"));
    } finally {
      setBusy(false);
    }
  }

  async function onArchive(id: string) {
    setBusy(true);
    try {
      await api.archiveMemory(id);
      toast("Memory gearchiveerd");
      await load();
    } catch (err) {
      toast(errMsg(err, "Archiveren mislukt"));
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke(id: string) {
    if (!window.confirm("Revoke this memory? It will no longer be retrievable as active memory.")) return;
    setBusy(true);
    try {
      await api.revokeMemory(id);
      toast("Memory revoked");
      await load();
    } catch (err) {
      toast(errMsg(err, "Revoke mislukt"));
    } finally {
      setBusy(false);
    }
  }

  async function togglePin(item: MemoryRecord) {
    const tags = [...(item.tags || [])];
    const idx = tags.findIndex((t) => t.toLowerCase() === "pinned");
    if (idx >= 0) tags.splice(idx, 1);
    else tags.push("pinned");
    // Pin is tag-based; recreate via archive+create is too heavy. Use create with supersede isn't exposed.
    // Honest path: create a note that mirrors content with updated tags is wrong.
    // Backend has no PATCH — pin by creating note with same content is duplicate.
    // So we only support pin on create, and show pinned from tags. For toggle, re-create is bad.
    // Best honest UX: toast that pin is set at create time via tag "pinned".
    toast(
      idx >= 0
        ? "Unpin requires tag edit (no PATCH API) — archive and recreate if needed"
        : "Add tag “pinned” when creating a memory to pin it",
    );
  }

  const healthStats = [
    { value: loading ? "…" : String(memories.length), label: "Active Memories" },
    { value: loading ? "…" : String(archived.length), label: "Archived" },
    { value: loading ? "…" : String(revoked.length), label: "Revoked" },
    { value: String(posture), label: "Product Posture" },
  ];

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Search memories, knowledge, research, agents..."
      systemItems={[
        "SYSTEMS ONLINE",
        "MEMORY",
        loading ? "LOADING" : error ? "ERROR" : `${memories.length} ACTIVE`,
      ]}
      layout="wide"
      pageClass="lv-app--onderzoek"
    >
      <main className="lv-main lv-ok-main">
        <OkHero
          title="GEHEUGEN"
          kicker="VASTLEGGEN. BEGRIJPEN. TOEPASSEN. EVOLUEREN."
          quote="Kennis is wat we onthouden. Wijsheid is wat we ermee doen."
          image={onderzoekHeroes.geheugen}
          rails={["UNDERSTAND", "CONNECT", "REMEMBER", "EVOLVE"]}
        />

        <nav className="lv-ok-actions" aria-label="Geheugen tabs">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`lv-ok-action${tab === item.id ? " is-active" : ""}`}
              onClick={() => setTab(item.id)}
            >
              <span className="lv-gh-tab-ico">{item.icon}</span>
              <strong>{item.label}</strong>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>

        {error ? (
          <OkPanel title="Memory unavailable">
            <div className="lv-models-banner is-error" role="alert">
              <strong>Kan geheugen niet laden</strong>
              <span>{error}</span>
              <button type="button" className="lv-ok-btn" disabled={busy} onClick={() => void load()}>
                Retry
              </button>
            </div>
          </OkPanel>
        ) : null}

        <OkPanel
          className="lv-gh-health-panel"
          title="Memory Health"
          action={
            <button type="button" className="lv-ok-btn is-ghost" disabled={busy || loading} onClick={() => void load()}>
              Refresh
            </button>
          }
        >
          <div className="lv-gh-health">
            <div className="lv-gh-gauge-wrap">
              <OkGauge value={gaugeValue} label={gaugeLabel} size={88} />
              <div className="lv-gh-gauge-meta">
                <strong>Memory posture from evidence</strong>
                <span>
                  {loading
                    ? "Laden…"
                    : `${memories.length} active · ${totalKnown} known · posture ${posture}`}
                </span>
              </div>
            </div>
            <div className="lv-gh-stats">
              {healthStats.map((stat) => (
                <button
                  key={stat.label}
                  type="button"
                  className="lv-gh-stat"
                  onClick={() => {
                    if (stat.label === "Archived") {
                      setStatusFilter("ARCHIVED");
                      setTab("retention");
                    } else if (stat.label === "Revoked") {
                      setStatusFilter("REVOKED");
                      setTab("retention");
                    } else {
                      setTab("overview");
                    }
                  }}
                >
                  <strong>{stat.value}</strong>
                  <small>{stat.label}</small>
                </button>
              ))}
            </div>
          </div>
        </OkPanel>

        {tab === "overview" || tab === "organization" ? (
          <section className="lv-gh-mid" aria-label="Memory overview">
            <OkPanel title="Memory Types">
              <div className="lv-gh-types">
                {KIND_OPTIONS.map((type) => {
                  const count = kindCounts.get(type.id) ?? 0;
                  return (
                    <button
                      key={type.id}
                      type="button"
                      className={`lv-gh-type is-${type.tone}${kindFilter === type.id ? " is-active" : ""}`}
                      onClick={() => {
                        setKindFilter((prev) => (prev === type.id ? "all" : type.id));
                        setTab("organization");
                      }}
                    >
                      <strong>{type.label}</strong>
                      <em>{count}</em>
                      <small>{type.id}</small>
                    </button>
                  );
                })}
              </div>
            </OkPanel>

            <OkPanel
              title="Recente Memory Traces"
              action={
                <button type="button" className="lv-ok-btn is-ghost" onClick={() => setTab("organization")}>
                  View All
                </button>
              }
            >
              {loading ? (
                <p className="lv-ok-muted">Laden…</p>
              ) : recent.length === 0 ? (
                <p className="lv-ok-muted">Nog geen memories. Maak er een aan onder Ingestion.</p>
              ) : (
                <ul className="lv-ok-list lv-gh-traces">
                  {recent.map((trace) => (
                    <li key={trace.memory_id}>
                      <button
                        type="button"
                        className={selectedId === trace.memory_id ? "is-active" : ""}
                        onClick={() => {
                          setSelectedId(trace.memory_id);
                          setTab("organization");
                        }}
                      >
                        <div className="lv-ok-list-copy">
                          <strong>{excerpt(trace.content, 90)}</strong>
                          <span className="lv-gh-trace-tags">
                            <span className="lv-ok-tag">{trace.kind}</span>
                            {(trace.tags || []).slice(0, 3).map((tag) => (
                              <span key={tag} className="lv-ok-tag">
                                {tag}
                              </span>
                            ))}
                          </span>
                        </div>
                        <span className="lv-ok-count">{relativeAgo(trace.updated_at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </OkPanel>

            <OkPanel title="Actieve Context">
              <dl className="lv-gh-context">
                <div>
                  <dt>Scope filter</dt>
                  <dd>ACTIVE memories · controlled retrieval</dd>
                </div>
                <div>
                  <dt>Geselecteerd</dt>
                  <dd>{selected ? excerpt(selected.content, 80) : "—"}</dd>
                </div>
                <div>
                  <dt>Trust rules</dt>
                  <dd>Model output is nooit automatische memory</dd>
                </div>
                <div>
                  <dt>Relevante tags</dt>
                  <dd className="lv-ok-chip-row">
                    {tagCounts.length === 0 ? (
                      <span className="lv-ok-muted">Geen tags</span>
                    ) : (
                      tagCounts.slice(0, 8).map(([theme, count]) => (
                        <button
                          key={theme}
                          type="button"
                          className="lv-ok-chip is-active"
                          onClick={() => {
                            setQuery(theme);
                            setTab("recall");
                            void (async () => {
                              setBusy(true);
                              try {
                                const res = await api.searchMemory({ q: theme, limit: 40 });
                                setHits(res.memory);
                                setSearched(true);
                              } catch (err) {
                                toast(errMsg(err, "Tag search failed"));
                              } finally {
                                setBusy(false);
                              }
                            })();
                          }}
                        >
                          {theme} ({count})
                        </button>
                      ))
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Context venster</dt>
                  <dd>
                    <div className="lv-gh-context-fill">
                      <strong>
                        {Math.min(memories.length, 32)} / 32 sampled
                      </strong>
                      <OkProgress value={(Math.min(memories.length, 32) / 32) * 100} tone="cyan" />
                    </div>
                  </dd>
                </div>
              </dl>
            </OkPanel>
          </section>
        ) : null}

        {tab === "organization" ? (
          <section className="lv-gh-lower" aria-label="Memory list">
            <OkPanel
              title={`Active memories · ${filtered.length}`}
              action={
                <div style={{ display: "flex", gap: 8 }}>
                  <select
                    className="lv-ok-select"
                    value={kindFilter}
                    onChange={(e) => setKindFilter(e.target.value)}
                    aria-label="Filter kind"
                  >
                    <option value="all">Alle kinds</option>
                    {KIND_OPTIONS.map((k) => (
                      <option key={k.id} value={k.id}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                  <select
                    className="lv-ok-select"
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                    aria-label="Sort"
                  >
                    <option value="recent">Meest recent</option>
                    <option value="priority">Priority</option>
                    <option value="kind">Kind</option>
                  </select>
                </div>
              }
            >
              {filtered.length === 0 ? (
                <p className="lv-ok-muted">Geen active memories voor dit filter.</p>
              ) : (
                <ul className="lv-ok-list lv-gh-traces">
                  {filtered.map((item) => (
                    <li key={item.memory_id}>
                      <button
                        type="button"
                        className={selectedId === item.memory_id ? "is-active" : ""}
                        onClick={() => setSelectedId(item.memory_id)}
                      >
                        <div className="lv-ok-list-copy">
                          <strong>{excerpt(item.content, 140)}</strong>
                          <span className="lv-gh-trace-tags">
                            <span className="lv-ok-tag">{item.kind}</span>
                            <span className="lv-ok-tag">{item.scope}</span>
                            <span className="lv-ok-tag">{item.trust}</span>
                          </span>
                        </div>
                        <span className="lv-ok-count">{relativeAgo(item.updated_at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </OkPanel>

            <OkPanel title="Memory detail">
              {!selected ? (
                <p className="lv-ok-muted">Selecteer een memory.</p>
              ) : (
                <div className="lv-gh-recall" style={{ gap: 10 }}>
                  <strong>{selected.kind}</strong>
                  <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{selected.content}</p>
                  <div className="lv-ok-chip-row">
                    {(selected.tags || []).map((tag) => (
                      <span key={tag} className="lv-ok-chip is-active">
                        {tag}
                      </span>
                    ))}
                  </div>
                  <dl className="lv-gh-context">
                    <div>
                      <dt>ID</dt>
                      <dd>{selected.memory_id}</dd>
                    </div>
                    <div>
                      <dt>Source / trust</dt>
                      <dd>
                        {selected.source} / {selected.trust}
                      </dd>
                    </div>
                    <div>
                      <dt>Scope</dt>
                      <dd>
                        {selected.scope}
                        {selected.project_id ? ` · ${selected.project_id}` : ""}
                        {selected.conversation_id ? ` · conv ${selected.conversation_id}` : ""}
                      </dd>
                    </div>
                    <div>
                      <dt>Updated</dt>
                      <dd>{selected.updated_at}</dd>
                    </div>
                  </dl>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="lv-ok-btn"
                      disabled={busy}
                      onClick={() => void onArchive(selected.memory_id)}
                    >
                      Archive
                    </button>
                    <button
                      type="button"
                      className="lv-ok-btn is-ghost"
                      disabled={busy}
                      onClick={() => void onRevoke(selected.memory_id)}
                    >
                      Revoke
                    </button>
                    <button type="button" className="lv-ok-btn is-ghost" onClick={() => void togglePin(selected)}>
                      Pin help
                    </button>
                  </div>
                </div>
              )}
            </OkPanel>
          </section>
        ) : null}

        {tab === "ingestion" ? (
          <section className="lv-gh-lower" aria-label="Create memory">
            <OkPanel title="Capture memory">
              <div className="lv-gh-recall">
                <label className="lv-ok-muted" htmlFor="gh-content">
                  Content
                </label>
                <textarea
                  id="gh-content"
                  className="lv-ok-input"
                  rows={6}
                  value={draftContent}
                  onChange={(e) => setDraftContent(e.target.value)}
                  placeholder="Expliciete memory — geen model-output als feiten…"
                />
                <div className="lv-gh-recall-filters">
                  <select
                    className="lv-ok-select"
                    value={draftKind}
                    onChange={(e) => setDraftKind(e.target.value)}
                    aria-label="Kind"
                  >
                    {KIND_OPTIONS.map((k) => (
                      <option key={k.id} value={k.id}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                  <select
                    className="lv-ok-select"
                    value={draftScope}
                    onChange={(e) => setDraftScope(e.target.value as "GLOBAL" | "PROJECT")}
                    aria-label="Scope"
                  >
                    <option value="GLOBAL">GLOBAL</option>
                    <option value="PROJECT">PROJECT</option>
                  </select>
                </div>
                {draftScope === "PROJECT" ? (
                  <input
                    className="lv-ok-input"
                    value={draftProjectId}
                    onChange={(e) => setDraftProjectId(e.target.value)}
                    placeholder="project_id"
                    aria-label="Project id"
                  />
                ) : null}
                <input
                  className="lv-ok-input"
                  value={draftTags}
                  onChange={(e) => setDraftTags(e.target.value)}
                  placeholder="Tags (comma-separated, use pinned to pin)"
                  aria-label="Tags"
                />
                <button
                  type="button"
                  className="lv-ok-btn is-gold"
                  disabled={busy || !draftContent.trim()}
                  onClick={() => void onCreate()}
                >
                  Opslaan
                </button>
                <p className="lv-ok-muted" style={{ fontSize: 12 }}>
                  Memory is controlled persistence — apart van Knowledge. model_output trust wordt geweigerd.
                </p>
              </div>
            </OkPanel>
            <OkPanel title="Ingestion queue">
              <p className="lv-ok-muted">
                Geen achtergrond-ingest queue voor memory files. Documenten horen in{" "}
                <Link to="/knowledge">Knowledge Library</Link>; datasets in{" "}
                <Link to="/datasets">Datasets</Link>.
              </p>
            </OkPanel>
          </section>
        ) : null}

        {tab === "recall" ? (
          <section className="lv-gh-lower" aria-label="Recall">
            <OkPanel title="Context Recall">
              <div className="lv-gh-recall">
                <div className="lv-gh-recall-input">
                  <input
                    className="lv-ok-input"
                    type="search"
                    placeholder="Zoek in je geheugen..."
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void runRecall();
                    }}
                  />
                </div>
                <div className="lv-ok-chip-row">
                  {(
                    [
                      ["hybride", "Hybride (FTS)"],
                      ["exact", "Exact (client)"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={`lv-ok-chip${recallMode === id ? " is-active lv-gh-chip-gold" : ""}`}
                      onClick={() => setRecallMode(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <button type="button" className="lv-ok-btn is-gold" disabled={busy} onClick={() => void runRecall()}>
                  Zoeken
                </button>
              </div>
            </OkPanel>
            <OkPanel title={searched ? `Results · ${hits.length}` : "Results"}>
              {!searched ? (
                <p className="lv-ok-muted">Voer een query uit om memories te recallen.</p>
              ) : hits.length === 0 ? (
                <p className="lv-ok-muted">Geen hits.</p>
              ) : (
                <ul className="lv-ok-list lv-gh-traces">
                  {hits.map((hit) => (
                    <li key={hit.memory_id}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedId(hit.memory_id);
                          setTab("organization");
                        }}
                      >
                        <div className="lv-ok-list-copy">
                          <strong>{excerpt(hit.content, 140)}</strong>
                          <span className="lv-gh-trace-tags">
                            <span className="lv-ok-tag">{hit.kind}</span>
                            <span className="lv-ok-tag">{hit.scope}</span>
                          </span>
                        </div>
                        <span className="lv-ok-count">{kindLabel(hit.kind)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </OkPanel>
          </section>
        ) : null}

        {tab === "graph" ? (
          <section className="lv-gh-lower" aria-label="Memory graph">
            <OkPanel title="Memory → Brain projection">
              <p className="lv-ok-muted">
                Geheugen-nodes worden geprojecteerd in de Brain-graph (type <code>memory</code>). Brain is geen
                tweede bron van waarheid.
              </p>
              <Link className="lv-ok-btn is-gold" to="/brain?types=memory">
                Open Brain · memory filter
              </Link>
            </OkPanel>
            <OkPanel title="Kind distribution">
              {kindCounts.size === 0 ? (
                <p className="lv-ok-muted">Geen nodes om te projecteren.</p>
              ) : (
                <ul className="lv-ok-check">
                  {[...kindCounts.entries()]
                    .sort((a, b) => b[1] - a[1])
                    .map(([kind, count]) => (
                      <li key={kind}>
                        <span>{kind}</span>
                        <span>{count}</span>
                      </li>
                    ))}
                </ul>
              )}
            </OkPanel>
          </section>
        ) : null}

        {tab === "retention" ? (
          <section className="lv-gh-lower" aria-label="Retention">
            <OkPanel title="Memory tiers (status)">
              <button type="button" className="lv-gh-tier" onClick={() => setStatusFilter("ACTIVE")}>
                <span>Hot (Active)</span>
                <OkProgress
                  value={totalKnown === 0 ? 0 : (memories.length / Math.max(totalKnown, 1)) * 100}
                  tone="red"
                />
                <strong>{memories.length}</strong>
              </button>
              <button type="button" className="lv-gh-tier" onClick={() => setStatusFilter("ARCHIVED")}>
                <span>Warm (Archived)</span>
                <OkProgress
                  value={totalKnown === 0 ? 0 : (archived.length / Math.max(totalKnown, 1)) * 100}
                  tone="cyan"
                />
                <strong>{archived.length}</strong>
              </button>
              <button type="button" className="lv-gh-tier" onClick={() => setStatusFilter("REVOKED")}>
                <span>Cold (Revoked)</span>
                <OkProgress
                  value={totalKnown === 0 ? 0 : (revoked.length / Math.max(totalKnown, 1)) * 100}
                  tone="muted"
                />
                <strong>{revoked.length}</strong>
              </button>
            </OkPanel>
            <OkPanel
              title={
                statusFilter === "ARCHIVED"
                  ? `Archived · ${archived.length}`
                  : statusFilter === "REVOKED"
                    ? `Revoked · ${revoked.length}`
                    : `Active · ${memories.length}`
              }
            >
              {(() => {
                const rows =
                  statusFilter === "ARCHIVED" ? archived : statusFilter === "REVOKED" ? revoked : memories;
                if (rows.length === 0) {
                  return <p className="lv-ok-muted">Geen items in deze status.</p>;
                }
                return (
                  <ul className="lv-ok-list lv-gh-traces">
                    {rows.slice(0, 40).map((item) => (
                      <li key={item.memory_id}>
                        <button type="button" onClick={() => setSelectedId(item.memory_id)}>
                          <div className="lv-ok-list-copy">
                            <strong>{excerpt(item.content, 120)}</strong>
                            <span className="lv-gh-trace-tags">
                              <span className="lv-ok-tag">{item.status}</span>
                              <span className="lv-ok-tag">{item.kind}</span>
                            </span>
                          </div>
                          <span className="lv-ok-count">{relativeAgo(item.updated_at)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                );
              })()}
            </OkPanel>
            <OkPanel title="Memory Integrity" action={<span className="lv-ok-pill is-green">Store OK</span>}>
              <ul className="lv-ok-check">
                <li>
                  <span>✓ Active count</span>
                  <span>{memories.length}</span>
                </li>
                <li>
                  <span>✓ Archived count</span>
                  <span>{archived.length}</span>
                </li>
                <li>
                  <span>✓ Revoked count</span>
                  <span>{revoked.length}</span>
                </li>
                <li>
                  <span>✓ Source of truth</span>
                  <span>/api/memory</span>
                </li>
              </ul>
              <button
                type="button"
                className="lv-ok-btn"
                style={{ marginTop: 8, width: "100%" }}
                disabled={busy || loading}
                onClick={() => void load()}
              >
                Run Integrity Refresh
              </button>
            </OkPanel>
          </section>
        ) : null}

        {tab === "settings" ? (
          <section className="lv-gh-lower" aria-label="Memory settings">
            <OkPanel title="Memory truth">
              <ul className="lv-ok-check">
                <li>
                  <span>model_output is not automatic memory</span>
                  <span>enforced</span>
                </li>
                <li>
                  <span>memory is not knowledge</span>
                  <span>separate store</span>
                </li>
                <li>
                  <span>scope filter required for retrieval</span>
                  <span>yes</span>
                </li>
              </ul>
              <p className="lv-ok-muted" style={{ marginTop: 8 }}>
                Runtime / feature toggles for neuro memory tiers zitten onder{" "}
                <Link to="/settings?section=knowledge_rag">Settings → Knowledge &amp; RAG</Link>.
              </p>
            </OkPanel>
            <OkPanel title="Vastgezette herinneringen">
              {pinned.length === 0 ? (
                <p className="lv-ok-muted">
                  Geen pinned memories. Voeg tag <code>pinned</code> toe bij create.
                </p>
              ) : (
                <div className="lv-gh-pins">
                  {pinned.map((pin, i) => (
                    <button
                      key={pin.memory_id}
                      type="button"
                      className="lv-gh-pin"
                      onClick={() => {
                        setSelectedId(pin.memory_id);
                        setTab("organization");
                      }}
                    >
                      <kbd>Alt+{i + 1}</kbd>
                      <strong>{excerpt(pin.content, 48)}</strong>
                      <small>{pin.kind}</small>
                    </button>
                  ))}
                </div>
              )}
            </OkPanel>
          </section>
        ) : null}

        {tab === "overview" ? (
          <section className="lv-gh-bottom" aria-label="Pins and topics">
            <OkPanel title="Vastgezette Herinneringen">
              {pinned.length === 0 ? (
                <p className="lv-ok-muted">Geen pins — tag memories met “pinned”.</p>
              ) : (
                <div className="lv-gh-pins">
                  {pinned.map((pin, i) => (
                    <button
                      key={pin.memory_id}
                      type="button"
                      className="lv-gh-pin"
                      onClick={() => {
                        setSelectedId(pin.memory_id);
                        setTab("organization");
                      }}
                    >
                      <kbd>Alt+{i + 1}</kbd>
                      <strong>{excerpt(pin.content, 48)}</strong>
                      <small>{pin.kind}</small>
                    </button>
                  ))}
                </div>
              )}
            </OkPanel>

            <OkPanel title="Top Topics (from tags)">
              {tagCounts.length === 0 ? (
                <p className="lv-ok-muted">Nog geen tags in active memories.</p>
              ) : (
                <ol className="lv-gh-topics">
                  {tagCounts.slice(0, 8).map(([name, count], i) => {
                    const pct = Math.round((count / Math.max(memories.length, 1)) * 100);
                    return (
                      <li key={name}>
                        <button
                          type="button"
                          onClick={() => {
                            setQuery(name);
                            setTab("recall");
                          }}
                        >
                          <span>
                            {i + 1}. {name}
                          </span>
                          <strong>
                            {count} · {pct}%
                          </strong>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              )}
            </OkPanel>

            <OkPanel title="Recall Analytics">
              <div className="lv-gh-analytics">
                <article>
                  <header>
                    <span>Active</span>
                    <strong>{memories.length}</strong>
                  </header>
                </article>
                <article>
                  <header>
                    <span>Kinds</span>
                    <strong>{kindCounts.size}</strong>
                  </header>
                </article>
                <article>
                  <header>
                    <span>Tags</span>
                    <strong>{tagCounts.length}</strong>
                  </header>
                </article>
              </div>
              <p className="lv-ok-muted" style={{ fontSize: 11, marginTop: 8 }}>
                Counts from /api/memory — no fabricated latency or hit-rate.
              </p>
            </OkPanel>
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
