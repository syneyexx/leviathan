import { useMemo, useState } from "react";
import { AppShell } from "../../layouts/AppShell";
import {
  KLIB_CONTEXT,
  KLIB_CURATIE,
  KLIB_DOMAINS,
  KLIB_FOOTER,
  KLIB_GOVERNANCE,
  KLIB_GRAPH_STATS,
  KLIB_HERO,
  KLIB_INGEST_QUEUE,
  KLIB_KPIS,
  KLIB_RECENT,
  KLIB_SEARCH_FILTERS,
  KLIB_SEARCH_TOGGLES,
  KLIB_TABS,
  KLIB_TOP_TOPICS,
  type KlibTabId,
} from "../../mocks/knowledge-library-pixel";
import { useAppToast } from "../../state/useAppToast";
import { PxHero, PxIcon, PxKpi, PxSwitch } from "./pixel-shared";

function KnowledgeGraph() {
  const nodes = useMemo(
    () => [
      { x: 50, y: 28, r: 5, tone: "gold" },
      { x: 28, y: 42, r: 4, tone: "cyan" },
      { x: 72, y: 38, r: 4, tone: "cyan" },
      { x: 40, y: 58, r: 3.5, tone: "gold" },
      { x: 62, y: 56, r: 3.5, tone: "gold" },
    ],
    [],
  );
  const edges = [
    [0, 1],
    [0, 2],
    [0, 3],
    [1, 3],
    [2, 4],
    [3, 4],
  ];
  return (
    <svg className="lv-px-graph" viewBox="0 0 100 72" role="img" aria-label="Kennisgrafiek">
      {edges.map(([a, b], i) => {
        const na = nodes[a]!;
        const nb = nodes[b]!;
        return (
          <line
            key={i}
            x1={na.x}
            y1={na.y}
            x2={nb.x}
            y2={nb.y}
            stroke="rgba(34, 201, 214, 0.35)"
            strokeWidth="0.8"
          />
        );
      })}
      {nodes.map((n, i) => (
        <circle key={i} cx={n.x} cy={n.y} r={n.r} className={`lv-px-graph-node is-${n.tone}`} fill="currentColor" />
      ))}
    </svg>
  );
}

export function KnowledgeLibraryPixelPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<KlibTabId>("overzicht");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRecent, setSelectedRecent] = useState(KLIB_RECENT[0]!.id);
  const [toggles, setToggles] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(KLIB_SEARCH_TOGGLES.map((t) => [t.id, t.defaultOn])),
  );

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Knowledge Library"
      searchPlaceholder="Zoek kennis, domeinen, bronnen..."
      systemItems={["KNOWLEDGE", "482K ITEMS", "98% RAG", "SYNC"]}
      layout="wide"
      pageClass="lv-app--pixel-knowledge"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-stack">
          <PxHero title={KLIB_HERO.title} subtitle={KLIB_HERO.subtitle} quote={KLIB_HERO.quote} />

          <nav className="lv-px-tabs" aria-label="Knowledge Library secties">
            {KLIB_TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`lv-px-tab lv-px-tab-rich${tab === item.id ? " is-active" : ""}`}
                onClick={() => {
                  setTab(item.id);
                  if (item.id !== "overzicht") toast(`${item.label} (demo)`);
                }}
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
            {KLIB_KPIS.map((kpi) => (
              <PxKpi
                key={kpi.id}
                label={kpi.label}
                value={kpi.value}
                hint={`▲ ${kpi.delta} · ${kpi.hint}`}
                hintTone="cyan"
                icon={kpi.icon}
                spark={kpi.sparkline ?? undefined}
              />
            ))}
          </div>

          <div className="lv-px-mid-grid">
            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">
                <PxIcon name="folder" /> Kennisdomeinen
              </h2>
              <ul className="lv-px-domain-list">
                {KLIB_DOMAINS.map((domain) => (
                  <li key={domain.id}>
                    <button type="button" className="lv-px-domain-row" onClick={() => toast(domain.label)}>
                      <PxIcon name={domain.icon} />
                      <span>{domain.label}</span>
                      <span className="lv-px-domain-count">{domain.count}</span>
                      <PxIcon name="chevron" />
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Recent toegevoegd</h2>
              {KLIB_RECENT.map((item) => (
                <div
                  key={item.id}
                  className={`lv-px-recent-item${item.id === selectedRecent ? " is-active" : ""}`}
                  onClick={() => setSelectedRecent(item.id)}
                  onKeyDown={(e) => e.key === "Enter" && setSelectedRecent(item.id)}
                  role="button"
                  tabIndex={0}
                >
                  <strong style={{ fontSize: 11 }}>{item.title}</strong>
                  <p style={{ margin: "4px 0", fontSize: 10, color: "var(--lv-text-secondary)" }}>{item.excerpt}</p>
                  <div style={{ display: "flex", gap: 8, fontSize: 9, color: "var(--lv-text-muted)" }}>
                    <span>{item.kind}</span>
                    <span>{item.ago}</span>
                  </div>
                </div>
              ))}
            </section>
          </div>

          <div className="lv-px-mid-grid">
            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Zoeken &amp; verkennen</h2>
              <div className="lv-px-filters">
                <label className="lv-px-search" style={{ flex: "1 1 100%" }}>
                  <PxIcon name="search" />
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Zoek in kennisbibliotheek..."
                    aria-label="Zoek query"
                  />
                </label>
                <select className="lv-px-select" defaultValue={KLIB_SEARCH_FILTERS.domains[0]}>
                  {KLIB_SEARCH_FILTERS.domains.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
                <select className="lv-px-select" defaultValue={KLIB_SEARCH_FILTERS.periods[0]}>
                  {KLIB_SEARCH_FILTERS.periods.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
                <button type="button" className="lv-px-btn is-gold" onClick={() => toast("Zoeken gestart")}>
                  Zoeken
                </button>
              </div>
              {KLIB_SEARCH_TOGGLES.map((toggle) => (
                <div key={toggle.id} className="lv-px-toggle-row">
                  <span>{toggle.label}</span>
                  <PxSwitch
                    label={toggle.label}
                    on={!!toggles[toggle.id]}
                    onToggle={() => {
                      setToggles((prev) => ({ ...prev, [toggle.id]: !prev[toggle.id] }));
                      toast(toggle.label);
                    }}
                  />
                </div>
              ))}
            </section>

            <section className="lv-px-panel">
              <div className="lv-px-panel-head">
                <h2 className="lv-px-panel-title">{KLIB_CONTEXT.title}</h2>
                <span className="lv-px-pill is-gold">{KLIB_CONTEXT.badge}</span>
              </div>
              <div className="lv-px-pills" style={{ marginBottom: 8 }}>
                {KLIB_CONTEXT.tags.map((t) => (
                  <span key={t} className="lv-px-pill is-cyan">{t}</span>
                ))}
              </div>
              <p style={{ fontSize: 10, lineHeight: 1.5 }}>{KLIB_CONTEXT.summary}</p>
              <div className="lv-px-action-list" style={{ marginTop: 10 }}>
                {KLIB_CONTEXT.actions.map((a) => (
                  <button key={a.id} type="button" onClick={() => toast(a.label)}>
                    <PxIcon name={a.icon} />
                    <span>{a.label}</span>
                  </button>
                ))}
              </div>
            </section>
          </div>

          <div className="lv-px-mid-grid">
            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Semantisch netwerk</h2>
              <KnowledgeGraph />
              <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                <dt>Concepten</dt>
                <dd>{KLIB_GRAPH_STATS.concepts}</dd>
                <dt>Relaties</dt>
                <dd>{KLIB_GRAPH_STATS.relations}</dd>
                <dt>Entiteiten</dt>
                <dd>{KLIB_GRAPH_STATS.entities}</dd>
                <dt>Clusters</dt>
                <dd>{KLIB_GRAPH_STATS.clusters}</dd>
              </dl>
            </section>

            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Ingest wachtrij</h2>
              {KLIB_INGEST_QUEUE.map((item) => (
                <div key={item.id} className="lv-px-queue-item">
                  <div className="lv-px-queue-top">
                    <strong>{item.name}</strong>
                    <span>{item.statusLabel}</span>
                  </div>
                  {item.progress != null ? (
                    <div className="lv-px-progress">
                      <i style={{ width: `${item.progress}%` }} />
                    </div>
                  ) : null}
                </div>
              ))}
            </section>
          </div>

          <div className="lv-px-widgets">
            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Governance</h2>
              {KLIB_GOVERNANCE.map((m) => (
                <div key={m.id} className="lv-px-bench-metric">
                  <span>{m.label}</span>
                  <b>{m.value}</b>
                </div>
              ))}
            </section>
            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Top onderwerpen</h2>
              {KLIB_TOP_TOPICS.map((t) => (
                <div key={t.rank} className="lv-px-queue-top" style={{ padding: "6px 0" }}>
                  <span>
                    {t.rank}. {t.label}
                  </span>
                  <span style={{ color: t.trendUp ? "var(--lv-cyan)" : "var(--lv-danger)" }}>
                    {t.volume} {t.trend}
                  </span>
                </div>
              ))}
            </section>
            <section className="lv-px-panel">
              <h2 className="lv-px-panel-title">Curatie</h2>
              {KLIB_CURATIE.map((c) => (
                <div key={c.id} className="lv-px-bench-metric">
                  <span>{c.label}</span>
                  <b>{c.value}</b>
                </div>
              ))}
            </section>
          </div>

          <footer className="lv-px-page-footer">
            <span>{KLIB_FOOTER.left}</span>
            <span>{KLIB_FOOTER.right}</span>
          </footer>
        </div>
      </main>
    </AppShell>
  );
}
