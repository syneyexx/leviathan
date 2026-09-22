/** FINALBETA Knowledge Library — pixel mock (content area). */
"use client";

import { useMemo, useState } from "react";
import { sparkPath } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
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
  type KlibIngestItem,
  type KlibSearchMode,
  type KlibTabId,
} from "../mocks/knowledge-library-pixel";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function KlibSparkline({ values }: { values: number[] }) {
  const d = sparkPath(values, 72, 22);
  return (
    <svg className="klib-kpi-spark" viewBox="0 0 72 22" aria-hidden="true">
      <path d={d} fill="none" stroke="#3ac7ee" strokeWidth="1.6" />
    </svg>
  );
}

function KlibNetworkGraph() {
  const nodes = useMemo(
    () => [
      { x: 50, y: 28, r: 5, tone: "gold" },
      { x: 28, y: 42, r: 4, tone: "cyan" },
      { x: 72, y: 38, r: 4, tone: "cyan" },
      { x: 40, y: 58, r: 3.5, tone: "gold" },
      { x: 62, y: 56, r: 3.5, tone: "gold" },
      { x: 18, y: 62, r: 3, tone: "muted" },
      { x: 84, y: 52, r: 3, tone: "muted" },
    ],
    [],
  );
  const edges = [
    [0, 1],
    [0, 2],
    [0, 3],
    [0, 4],
    [1, 3],
    [2, 4],
    [1, 5],
    [2, 6],
    [3, 4],
  ];
  return (
    <svg className="klib-graph-viz" viewBox="0 0 100 72" role="img" aria-label="Kennisgrafiek">
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
            stroke="rgba(58, 199, 238, 0.35)"
            strokeWidth="0.8"
          />
        );
      })}
      {nodes.map((n, i) => (
        <circle
          key={i}
          cx={n.x}
          cy={n.y}
          r={n.r}
          className={`klib-graph-node ${n.tone}`}
          fill="currentColor"
        />
      ))}
    </svg>
  );
}

function ingestBarClass(status: KlibIngestItem["status"]) {
  if (status === "gereed") return "done";
  if (status === "wachtrij") return "queue";
  return "active";
}

export function KnowledgePage({ onNavigate }: Props) {
  const [tab, setTab] = useState<KlibTabId>("overzicht");
  const [searchMode, setSearchMode] = useState<KlibSearchMode>("hybride");
  const [searchQuery, setSearchQuery] = useState("");
  const [topicRange, setTopicRange] = useState<"7d" | "30d">("7d");
  const [selectedRecent, setSelectedRecent] = useState(KLIB_RECENT[0]!.id);
  const [toggles, setToggles] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(KLIB_SEARCH_TOGGLES.map((t) => [t.id, t.defaultOn])),
  );

  const activeRecent = KLIB_RECENT.find((r) => r.id === selectedRecent) ?? KLIB_RECENT[0]!;

  const body = (
    <div className="klib-page">
      <header className="klib-hero">
        <div className="klib-hero-inner">
          <div className="klib-hero-main">
            <h1>{KLIB_HERO.title}</h1>
            <p className="klib-hero-sub">{KLIB_HERO.subtitle}</p>
          </div>
          <p className="klib-hero-quote">“{KLIB_HERO.quote}”</p>
        </div>
      </header>

      <nav className="klib-tabs" aria-label="Knowledge Library secties">
        {KLIB_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`klib-tab${tab === item.id ? " active" : ""}`}
            onClick={() => setTab(item.id)}
            data-toast={tab === item.id ? undefined : `${item.label} (demo)`}
          >
            <span className="klib-tab-ico">
              <FbIcon name={item.icon} size={14} />
            </span>
            <span className="klib-tab-copy">
              <strong>{item.label}</strong>
              <small>{item.sub}</small>
            </span>
          </button>
        ))}
      </nav>

      <div className="klib-kpi-row">
        {KLIB_KPIS.map((kpi) => (
          <article key={kpi.id} className="klib-kpi">
            <span className="klib-kpi-ico">
              <FbIcon name={kpi.icon} size={15} />
            </span>
            <div className="klib-kpi-body">
              <div className="klib-kpi-label">{kpi.label}</div>
              <div className="klib-kpi-value-row">
                <span className="klib-kpi-value">{kpi.value}</span>
                <span className="klib-kpi-delta">▲ {kpi.delta}</span>
              </div>
              <div className="klib-kpi-hint">{kpi.hint}</div>
            </div>
            {kpi.sparkline ? <KlibSparkline values={[...kpi.sparkline]} /> : null}
          </article>
        ))}
      </div>

      <div className="klib-mid-grid">
        <section className="klib-card klib-domains" aria-label="Kennisdomeinen">
          <div className="klib-card-head">
            <FbIcon name="folder" size={14} />
            <h2>Kennisdomeinen</h2>
          </div>
          <ul className="klib-domain-list">
            {KLIB_DOMAINS.map((domain) => (
              <li key={domain.id}>
                <button type="button" className="klib-domain-row" data-toast={domain.label}>
                  <span className="klib-domain-ico">
                    <FbIcon name={domain.icon} size={13} />
                  </span>
                  <span className="klib-domain-label">{domain.label}</span>
                  <span className="klib-domain-count">{domain.count}</span>
                  <FbIcon name="chevron" size={12} className="klib-domain-chev" />
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="klib-btn-ghost" data-toast="Nieuw domein">
            <FbIcon name="plus" size={12} />
            Nieuw domein
          </button>
        </section>

        <section className="klib-card klib-recent" aria-label="Recente kennisitems">
          <div className="klib-card-head">
            <FbIcon name="clock" size={14} />
            <h2>Recente Kennisitems</h2>
          </div>
          <ul className="klib-recent-list">
            {KLIB_RECENT.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={`klib-recent-row${selectedRecent === item.id ? " active" : ""}`}
                  onClick={() => setSelectedRecent(item.id)}
                >
                  <span className="klib-recent-ico">
                    <FbIcon name={item.icon} size={14} />
                  </span>
                  <span className="klib-recent-copy">
                    <strong>{item.title}</strong>
                    <span className="klib-recent-excerpt">{item.excerpt}</span>
                    <span className="klib-recent-meta">
                      <em>{item.ago}</em>
                      <span className="klib-recent-kind">{item.kind}</span>
                    </span>
                  </span>
                  <span className="klib-recent-menu" aria-hidden="true">
                    <FbIcon name="more" size={14} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="klib-card klib-search" aria-label="Kennis zoeken en ophalen">
          <div className="klib-card-head">
            <FbIcon name="search" size={14} />
            <h2>Kennis Zoeken &amp; Ophalen</h2>
          </div>
          <label className="klib-search-field">
            <FbIcon name="search" size={13} />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Zoek concepten, documenten, entiteiten…"
              aria-label="Zoek in kennisbibliotheek"
            />
          </label>
          <div className="klib-mode-row" role="tablist" aria-label="Zoekmodus">
            {(["hybride", "semantisch", "exact"] as KlibSearchMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                role="tab"
                aria-selected={searchMode === mode}
                className={`klib-mode${searchMode === mode ? " active" : ""}`}
                onClick={() => setSearchMode(mode)}
              >
                {mode === "hybride" ? "Hybride" : mode === "semantisch" ? "Semantisch" : "Exact"}
              </button>
            ))}
          </div>
          <div className="klib-filter-row">
            <select className="klib-select" aria-label="Domein filter" defaultValue={KLIB_SEARCH_FILTERS.domains[0]}>
              {KLIB_SEARCH_FILTERS.domains.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
            <select className="klib-select" aria-label="Brontype filter" defaultValue={KLIB_SEARCH_FILTERS.sourceTypes[0]}>
              {KLIB_SEARCH_FILTERS.sourceTypes.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
            <select className="klib-select" aria-label="Periode filter" defaultValue={KLIB_SEARCH_FILTERS.periods[0]}>
              {KLIB_SEARCH_FILTERS.periods.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          </div>
          <button type="button" className="klib-btn-gold" data-toast="Zoeken (demo)">
            Zoeken
          </button>
          <div className="klib-toggle-grid">
            {KLIB_SEARCH_TOGGLES.map((toggle) => (
              <label key={toggle.id} className="klib-toggle-row">
                <span>{toggle.label}</span>
                <button
                  type="button"
                  className={`switch${toggles[toggle.id] ? " on" : ""}`}
                  aria-pressed={toggles[toggle.id]}
                  onClick={() => setToggles((prev) => ({ ...prev, [toggle.id]: !prev[toggle.id] }))}
                  data-toast={toggle.label}
                />
              </label>
            ))}
          </div>
        </section>
      </div>

      <div className="klib-bottom-grid">
        <section className="klib-card klib-ingest" aria-label="Broningestie queue">
          <div className="klib-card-head">
            <FbIcon name="upload" size={14} />
            <h2>Broningestie Queue</h2>
          </div>
          <ul className="klib-ingest-list">
            {KLIB_INGEST_QUEUE.map((item) => (
              <li key={item.id} className="klib-ingest-item">
                <div className="klib-ingest-top">
                  <span className="klib-ingest-name">{item.name}</span>
                  <span className={`klib-ingest-status ${item.status}`}>{item.statusLabel}</span>
                </div>
                <div className="klib-ingest-bar" aria-hidden="true">
                  <i
                    className={ingestBarClass(item.status)}
                    style={{ width: `${item.progress ?? (item.status === "wachtrij" ? 8 : 0)}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="klib-card klib-graph" aria-label="Kennisgrafiek">
          <div className="klib-card-head">
            <FbIcon name="link" size={14} />
            <h2>Kennisgrafiek</h2>
          </div>
          <div className="klib-graph-body">
            <KlibNetworkGraph />
            <dl className="klib-graph-stats">
              <div>
                <dt>Concepten</dt>
                <dd>{KLIB_GRAPH_STATS.concepts}</dd>
              </div>
              <div>
                <dt>Relaties</dt>
                <dd>{KLIB_GRAPH_STATS.relations}</dd>
              </div>
              <div>
                <dt>Entiteiten</dt>
                <dd>{KLIB_GRAPH_STATS.entities}</dd>
              </div>
              <div>
                <dt>Clusters</dt>
                <dd>{KLIB_GRAPH_STATS.clusters}</dd>
              </div>
            </dl>
          </div>
        </section>

        <section className="klib-card klib-governance" aria-label="Validatie en governance">
          <div className="klib-card-head">
            <FbIcon name="shield" size={14} />
            <h2>Validatie &amp; Governance</h2>
            <span className="klib-health">
              <i /> Gezond
            </span>
          </div>
          <ul className="klib-gov-list">
            {KLIB_GOVERNANCE.map((row) => (
              <li key={row.id}>
                <span>{row.label}</span>
                <b className={row.tone}>{row.value}</b>
              </li>
            ))}
          </ul>
          <button type="button" className="klib-btn-outline" data-toast="Kwaliteitsrapport">
            Kwaliteitsrapport bekijken
          </button>
        </section>

        <section className="klib-card klib-topics" aria-label="Top onderwerpen">
          <div className="klib-card-head">
            <FbIcon name="chart" size={14} />
            <h2>Top Onderwerpen</h2>
            <div className="klib-range-toggle">
              <button
                type="button"
                className={topicRange === "7d" ? "active" : ""}
                onClick={() => setTopicRange("7d")}
              >
                7d
              </button>
              <button
                type="button"
                className={topicRange === "30d" ? "active" : ""}
                onClick={() => setTopicRange("30d")}
              >
                30d
              </button>
            </div>
          </div>
          <ol className="klib-topic-list">
            {KLIB_TOP_TOPICS.map((topic) => (
              <li key={topic.rank}>
                <span className="klib-topic-rank">{topic.rank}</span>
                <span className="klib-topic-label">{topic.label}</span>
                <span className="klib-topic-vol">{topic.volume}</span>
                <span className={`klib-topic-trend${topic.trendUp ? " up" : " down"}`}>{topic.trend}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="klib-card klib-curation" aria-label="Curatie en tagging">
          <div className="klib-card-head">
            <FbIcon name="sliders" size={14} />
            <h2>Curatie &amp; Tagging</h2>
          </div>
          <ul className="klib-cur-list">
            {KLIB_CURATIE.map((row) => (
              <li key={row.id}>
                <span>{row.label}</span>
                <b>{row.value}</b>
              </li>
            ))}
          </ul>
          <button type="button" className="klib-btn-outline" data-toast="Tags beheren">
            Tags beheren
          </button>
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <section className="insp-section klib-insp">
        <div className="klib-insp-head">
          <h3 className="insp-title">Context &amp; Inzichten</h3>
          <span className="klib-badge-new">{KLIB_CONTEXT.badge}</span>
        </div>
        <div className="insp-card">
          <h4 className="klib-insp-title">{KLIB_CONTEXT.title}</h4>
          <div className="klib-insp-tags">
            {KLIB_CONTEXT.tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
          <p className="klib-insp-summary">{KLIB_CONTEXT.summary}</p>
          {activeRecent ? (
            <p className="klib-insp-selected">
              Geselecteerd: <strong>{activeRecent.title}</strong>
            </p>
          ) : null}
          <ul className="klib-insp-actions">
            {KLIB_CONTEXT.actions.map((action) => (
              <li key={action.id}>
                <button type="button" className="klib-insp-action" data-toast={action.label}>
                  <FbIcon name={action.icon} size={13} />
                  <span>{action.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Snelkoppeling</h3>
        <div className="insp-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <button className="btn btn-sm btn-outline btn-block" type="button" onClick={() => onNavigate("research")}>
            Research
          </button>
          <button className="btn btn-sm btn-gold btn-block" type="button" onClick={() => onNavigate("evidence")}>
            Evidence Vault
          </button>
        </div>
      </section>
    </>
  );

  const footer = (
    <footer className="klib-footer">
      <span>{KLIB_FOOTER.left}</span>
      <span className="klib-footer-dots" aria-hidden="true">
        <i /><i /><i />
      </span>
      <span className="klib-footer-right">{KLIB_FOOTER.right}</span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="knowledge"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="klib-app"
      mainClassName="klib-main"
      footer={footer}
    />
  );
}
