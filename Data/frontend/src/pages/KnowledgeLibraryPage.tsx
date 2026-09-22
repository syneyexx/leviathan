import { useState } from "react";
import { onderzoekHeroes } from "../assets/onderzoekKennisAssets";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import { OkBars, OkHero, OkIcon, OkPanel, OkProgress, OkSpark } from "./onderzoek/ok-shared";

type TabId =
  | "overzicht"
  | "zoeken"
  | "bronnen"
  | "netwerk"
  | "curatie"
  | "governance"
  | "instellingen";

type SearchMode = "hybride" | "semantisch" | "exact";

const TABS: { id: TabId; title: string; subtitle: string; icon: string }[] = [
  { id: "overzicht", title: "Overzicht", subtitle: "Kennisbibliotheek", icon: "M4 6h16M4 12h16M4 18h10" },
  { id: "zoeken", title: "Zoeken & Verkennen", subtitle: "Vind kennis", icon: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10-2-4.35-4.35" },
  { id: "bronnen", title: "Bronnen", subtitle: "Ingestie & connecties", icon: "M8 12h.01M12 12h.01M16 12h.01M9 16a7 7 0 1 1 6 0" },
  { id: "netwerk", title: "Semantisch Netwerk", subtitle: "Relaties & context", icon: "M8 8h.01M16 8h.01M8 16h.01M16 16h.01M9 9l6 6M15 9l-6 6" },
  { id: "curatie", title: "Curatie", subtitle: "Tags, labels & taxonomie", icon: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" },
  { id: "governance", title: "Governance", subtitle: "Validatie & kwaliteit", icon: "M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4Z" },
  { id: "instellingen", title: "Instellingen", subtitle: "Voorkeuren & beheer", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1l2-1.5-2-3.5-2.4 1a7.6 7.6 0 0 0-1.7-1L13 3h-2l-.2 2.5a7.6 7.6 0 0 0-1.7 1L6.7 5.5l-2 3.5 2 1.5a7.4 7.4 0 0 0 0 2l-2 1.5 2 3.5 2.4-1a7.6 7.6 0 0 0 1.7 1L11 21h2l.2-2.5a7.6 7.6 0 0 0 1.7-1l2.4 1 2-3.5-2-1.5c.1-.3.1-.7.1-1Z" },
];

const DOMAINS = [
  { name: "Strategie & Organisatie", sub: "Beleid, roadmap, besluitvorming", count: "48.2K", pct: 72 },
  { name: "Technologie & Innovatie", sub: "Architectuur, AI, platformen", count: "62.1K", pct: 88 },
  { name: "Markt & Concurrentie", sub: "Trends, peers, positionering", count: "38.4K", pct: 58 },
  { name: "Juridisch & Compliance", sub: "Regelgeving, AI Act, contracts", count: "22.7K", pct: 34 },
  { name: "Product & Engineering", sub: "Specs, releases, technische docs", count: "51.0K", pct: 76 },
  { name: "Mens & Cultuur", sub: "Talent, processen, organisatie", count: "18.9K", pct: 28 },
] as const;

const RECENT = [
  { title: "AI Governance Framework", when: "2u geleden", type: "Whitepaper", tags: ["Governance", "AI Act", "Policy"] },
  { title: "Marktanalyse Generatieve AI", when: "4u geleden", type: "Rapport", tags: ["Markt", "GenAI", "Analyse"] },
  { title: "RAG Architectuur Notities", when: "6u geleden", type: "Notitie", tags: ["RAG", "Vector", "Retrieval"] },
  { title: "EU AI Act Samenvatting", when: "1d geleden", type: "Briefing", tags: ["EU", "Compliance", "Wet"] },
  { title: "Leviathan Knowledge Spec", when: "2d geleden", type: "Spec", tags: ["Leviathan", "Kennis", "Design"] },
] as const;

const QUEUE = [
  { name: "McKinsey - State of AI 2024.pdf", status: "Verwerken", pct: 87, tone: "cyan" as const },
  { name: "Zendesk Knowledge Base", status: "In wachtrij", pct: 12, tone: "gold" as const },
  { name: "Policy.md", status: "Gereed", pct: 100, tone: "green" as const },
] as const;

const GOVERNANCE = [
  ["Gevalideerde items", "94%"],
  ["Betrouwbare bronnen", "98%"],
  ["Handmatige validatie", "12%"],
  ["Open issues", "3%"],
  ["Verouderde items", "6%"],
] as const;

const TOPICS_7D = [
  { rank: 1, name: "Generatieve AI", count: "12.4K", delta: "+24%" },
  { rank: 2, name: "AI Governance", count: "8.1K", delta: "+18%" },
  { rank: 3, name: "Digitale Transformatie", count: "6.7K", delta: "+11%" },
  { rank: 4, name: "RAG & Retrieval", count: "5.2K", delta: "+31%" },
  { rank: 5, name: "EU AI Act", count: "4.8K", delta: "+9%" },
] as const;

const TOPICS_30D = [
  { rank: 1, name: "Generatieve AI", count: "48.2K", delta: "+41%" },
  { rank: 2, name: "Digitale Transformatie", count: "29.6K", delta: "+16%" },
  { rank: 3, name: "AI Governance", count: "27.1K", delta: "+22%" },
  { rank: 4, name: "Cloud Strategie", count: "18.4K", delta: "+7%" },
  { rank: 5, name: "Data Privacy", count: "15.9K", delta: "+13%" },
] as const;

const CURATION = [
  { label: "Ongetagde items", value: "342" },
  { label: "Suggesties", value: "124" },
  { label: "Te reviewen", value: "28" },
  { label: "Nieuwe tags", value: "17" },
] as const;

const SEARCH_OPTS = [
  { id: "syn", label: "Synoniemen & uitbreidingen" },
  { id: "concept", label: "Conceptuele matching" },
  { id: "cross", label: "Cross-domein zoeken" },
  { id: "cite", label: "Bronvermelding tonen" },
] as const;

const INSIGHT_ACTIONS = [
  { id: "sum", label: "Samenvatting genereren", path: "M4 6h16M4 12h10M4 18h14" },
  { id: "rel", label: "Gerelateerde kennis", path: "M8 8h.01M16 8h.01M8 16h.01M16 16h.01M9 9l6 6M15 9l-6 6" },
  { id: "trend", label: "Trends analyseren", path: "M3 17l6-6 4 4 7-8" },
] as const;

const SPARK = [18, 24, 22, 30, 28, 36, 42, 40, 48, 52];
const BARS = [20, 28, 24, 36, 44, 40, 52, 48];

export function KnowledgeLibraryPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<TabId>("overzicht");
  const [mode, setMode] = useState<SearchMode>("hybride");
  const [query, setQuery] = useState("");
  const [topicRange, setTopicRange] = useState<"7d" | "30d">("7d");
  const [opts, setOpts] = useState<Record<string, boolean>>({
    syn: true,
    concept: true,
    cross: false,
    cite: true,
  });

  const topics = topicRange === "7d" ? TOPICS_7D : TOPICS_30D;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Zoek kennis, documenten, concepten, bronnen..."
      systemItems={["SYSTEMS ONLINE", "LLM", "RAG", "MEMORY", "TOOLS"]}
      layout="wide"
      pageClass="lv-app--onderzoek"
    >
      <main className="lv-main lv-ok-main">
        <OkHero
          title="KNOWLEDGE LIBRARY"
          kicker="VERZAMELEN. STRUCTUREREN. VERBINDEN. TOEPASSEN."
          quote="Kennis krijgt pas waarde wanneer het in verband wordt gebracht."
          image={onderzoekHeroes.knowledge}
          rails={["ALLE KENNIS", "ÉÉN ECOSYSTEEM", "DIEPERE INZICHTEN", "GROTERE IMPACT"]}
        />

        <section className="lv-ok-actions" aria-label="Knowledge navigatie">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`lv-ok-action${tab === item.id ? " is-active" : ""}`}
              onClick={() => {
                setTab(item.id);
                toast(`${item.title} geopend`);
              }}
            >
              <OkIcon>
                <path d={item.icon} />
              </OkIcon>
              <strong>{item.title}</strong>
              <small>{item.subtitle}</small>
            </button>
          ))}
        </section>

        <section className="lv-ok-kpis is-4" aria-label="Knowledge KPI's">
          <article className="lv-ok-kpi">
            <div className="lv-kl-kpi-top">
              <span className="lv-ok-kpi-label">Totaal Kennisitems</span>
              <OkIcon>
                <path d="M7 3h7l5 5v13H7V3Z M14 3v5h5" />
              </OkIcon>
            </div>
            <span className="lv-ok-kpi-value">482K</span>
            <span className="lv-ok-kpi-meta">↑ +12% · kennisitems in bibliotheek</span>
          </article>
          <article className="lv-ok-kpi">
            <div className="lv-kl-kpi-top">
              <span className="lv-ok-kpi-label">Geïndexeerde Bronnen</span>
              <OkIcon>
                <path d="M4 7h16M4 12h16M4 17h16" />
              </OkIcon>
            </div>
            <span className="lv-ok-kpi-value">1.2K</span>
            <span className="lv-ok-kpi-meta">↑ +8% · documenten, systemen, feeds</span>
          </article>
          <article className="lv-ok-kpi">
            <div className="lv-kl-kpi-top">
              <span className="lv-ok-kpi-label">Zoeknauwkeurigheid</span>
              <OkIcon>
                <circle cx="12" cy="12" r="7" />
                <circle cx="12" cy="12" r="2.5" />
              </OkIcon>
            </div>
            <span className="lv-ok-kpi-value">98%</span>
            <span className="lv-ok-kpi-meta">↑ +3% · relevante resultaten (RAG)</span>
          </article>
          <article className="lv-ok-kpi">
            <div className="lv-kl-kpi-top">
              <span className="lv-ok-kpi-label">Update Velociteit</span>
              <OkIcon>
                <path d="M3 12h4l2-6 4 12 2-6h6" />
              </OkIcon>
            </div>
            <span className="lv-ok-kpi-value">1.3K</span>
            <span className="lv-ok-kpi-meta">↑ +28% · nieuwe items / week</span>
            <div className="lv-kl-kpi-charts">
              <OkSpark points={SPARK} width={88} height={28} />
              <OkBars values={BARS} height={28} />
            </div>
          </article>
        </section>

        <section className="lv-kl-mid">
          <OkPanel title="Kennisdomeinen">
            <ul className="lv-ok-list lv-kl-domains">
              {DOMAINS.map((d) => (
                <li key={d.name}>
                  <button type="button" onClick={() => toast(`Domein · ${d.name}`)}>
                    <span className="lv-ok-list-copy">
                      <strong>{d.name}</strong>
                      <small>{d.sub}</small>
                      <OkProgress value={d.pct} />
                    </span>
                    <span className="lv-ok-count">{d.count}</span>
                  </button>
                </li>
              ))}
            </ul>
            <button
              className="lv-ok-btn is-gold"
              type="button"
              style={{ marginTop: 8, width: "100%" }}
              onClick={() => toast("Nieuw domein")}
            >
              + Nieuw domein
            </button>
          </OkPanel>

          <OkPanel title="Recente Kennisitems" action={<span className="lv-ok-muted">Laatste 48u</span>}>
            <ul className="lv-ok-list lv-kl-recent">
              {RECENT.map((item) => (
                <li key={item.title}>
                  <button type="button" className="lv-kl-recent-row" onClick={() => toast(item.title)}>
                    <span className="lv-kl-recent-ico" aria-hidden="true">
                      <OkIcon>
                        <path d="M7 3h7l5 5v13H7V3Z M14 3v5h5" />
                      </OkIcon>
                    </span>
                    <span className="lv-ok-list-copy">
                      <strong>{item.title}</strong>
                      <small>
                        {item.when} · {item.type}
                      </small>
                      <span className="lv-ok-chip-row">
                        {item.tags.map((t) => (
                          <span key={t} className="lv-ok-tag">
                            {t}
                          </span>
                        ))}
                      </span>
                    </span>
                    <span className="lv-kl-more" aria-hidden="true">
                      ···
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </OkPanel>

          <OkPanel title="Kennis Zoeken & Ophalen">
            <div className="lv-kl-search">
              <input
                className="lv-ok-input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Stel je vraag of zoek in de kennisbibliotheek..."
              />
              <div className="lv-ok-chip-row">
                {(
                  [
                    ["hybride", "Hybride"],
                    ["semantisch", "Semantisch"],
                    ["exact", "Exact"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`lv-ok-chip${mode === id ? " is-active" : ""}`}
                    onClick={() => setMode(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="lv-kl-filters">
                <select className="lv-ok-select" defaultValue="all">
                  <option value="all">Alle domeinen</option>
                  <option value="tech">Technologie</option>
                  <option value="markt">Markt</option>
                </select>
                <select className="lv-ok-select" defaultValue="all">
                  <option value="all">Alle brontypes</option>
                  <option value="pdf">PDF</option>
                  <option value="web">Web</option>
                </select>
                <select className="lv-ok-select" defaultValue="all">
                  <option value="all">Alle periodes</option>
                  <option value="7d">7 dagen</option>
                  <option value="30d">30 dagen</option>
                </select>
                <button
                  className="lv-ok-btn is-gold"
                  type="button"
                  onClick={() => toast(query.trim() ? `Zoeken · ${query}` : `Zoeken · ${mode}`)}
                >
                  Zoeken
                </button>
              </div>
              <div className="lv-kl-opts">
                <span className="lv-ok-muted">Zoekopties</span>
                {SEARCH_OPTS.map((opt) => (
                  <label key={opt.id} className="lv-kl-toggle">
                    <input
                      type="checkbox"
                      checked={!!opts[opt.id]}
                      onChange={(e) => setOpts((prev) => ({ ...prev, [opt.id]: e.target.checked }))}
                    />
                    <span>{opt.label}</span>
                  </label>
                ))}
              </div>
            </div>
          </OkPanel>

          <OkPanel
            title="Context & Inzichten"
            action={<span className="lv-ok-pill is-cyan">Nieuw</span>}
          >
            <div className="lv-kl-insight">
              <h3>Generatieve AI in de Zorg</h3>
              <div className="lv-ok-chip-row">
                <span className="lv-ok-tag">Zorg</span>
                <span className="lv-ok-tag">AI</span>
                <span className="lv-ok-tag">Implementatie</span>
              </div>
              <p className="lv-ok-muted">
                24 gerelateerde documenten · clusters rond adoptie, compliance en klinische toepassingen.
              </p>
              <div className="lv-kl-insight-actions">
                {INSIGHT_ACTIONS.map((a) => (
                  <button key={a.id} type="button" className="lv-ok-btn" onClick={() => toast(a.label)}>
                    <OkIcon>
                      <path d={a.path} />
                    </OkIcon>
                    {a.label}
                  </button>
                ))}
              </div>
            </div>
          </OkPanel>
        </section>

        <section className="lv-kl-bottom">
          <OkPanel title="Broningestie Queue">
            <div className="lv-ok-queue">
              {QUEUE.map((item) => (
                <div key={item.name} className="lv-ok-queue-item">
                  <header>
                    <strong>{item.name}</strong>
                    <span className={`lv-ok-pill is-${item.tone}`}>{item.status}</span>
                  </header>
                  <OkProgress value={item.pct} tone={item.tone} />
                </div>
              ))}
            </div>
          </OkPanel>

          <OkPanel title="Kennisgrafiek" action={<button className="lv-ok-btn is-ghost" type="button" onClick={() => toast("Grafiek openen")}>Openen</button>}>
            <div className="lv-kl-graph" aria-hidden="true">
              <svg className="lv-kl-graph-svg" viewBox="0 0 280 120" width="100%" height="120">
                <g stroke="rgba(34,201,214,0.35)" strokeWidth="1">
                  <line x1="40" y1="60" x2="110" y2="30" />
                  <line x1="40" y1="60" x2="120" y2="90" />
                  <line x1="110" y1="30" x2="180" y2="50" />
                  <line x1="120" y1="90" x2="180" y2="50" />
                  <line x1="180" y1="50" x2="240" y2="28" />
                  <line x1="180" y1="50" x2="250" y2="85" />
                  <line x1="110" y1="30" x2="70" y2="20" />
                </g>
                <circle cx="40" cy="60" r="7" fill="#22c9d6" />
                <circle cx="110" cy="30" r="6" fill="#d6a957" />
                <circle cx="120" cy="90" r="5" fill="#22c9d6" />
                <circle cx="180" cy="50" r="8" fill="#d6a957" />
                <circle cx="240" cy="28" r="4" fill="#22c9d6" />
                <circle cx="250" cy="85" r="5" fill="#22c9d6" />
                <circle cx="70" cy="20" r="3.5" fill="#d6a957" />
              </svg>
              <span className="lv-kl-graph-node" style={{ left: "8%", top: "42%" }}>
                AI
              </span>
              <span className="lv-kl-graph-node" style={{ left: "58%", top: "28%" }}>
                RAG
              </span>
              <span className="lv-kl-graph-node" style={{ left: "72%", top: "68%" }}>
                Policy
              </span>
            </div>
            <div className="lv-kl-graph-stats">
              <span>
                <strong>12.4K</strong> Concepten
              </span>
              <span>
                <strong>48.7K</strong> Relaties
              </span>
            </div>
          </OkPanel>

          <OkPanel
            title="Validatie & Governance"
            action={<span className="lv-ok-pill is-green">Gezond</span>}
          >
            <ul className="lv-ok-check">
              {GOVERNANCE.map(([label, value]) => (
                <li key={label}>
                  <span>{label}</span>
                  <span>{value}</span>
                </li>
              ))}
            </ul>
            <button
              className="lv-ok-btn"
              type="button"
              style={{ marginTop: 8, width: "100%" }}
              onClick={() => toast("Kwaliteitsrapport")}
            >
              Kwaliteitsrapport bekijken
            </button>
          </OkPanel>

          <OkPanel
            title="Top Onderwerpen"
            action={
              <div className="lv-ok-chip-row">
                {(["7d", "30d"] as const).map((r) => (
                  <button
                    key={r}
                    type="button"
                    className={`lv-ok-chip${topicRange === r ? " is-active" : ""}`}
                    onClick={() => setTopicRange(r)}
                  >
                    {r}
                  </button>
                ))}
              </div>
            }
          >
            <ol className="lv-kl-rank">
              {topics.map((t) => (
                <li key={t.name}>
                  <button type="button" onClick={() => toast(t.name)}>
                    <span className="lv-kl-rank-n">{t.rank}</span>
                    <span className="lv-ok-list-copy">
                      <strong>{t.name}</strong>
                    </span>
                    <span className="lv-ok-count">{t.count}</span>
                    <span className="lv-ok-kpi-meta">{t.delta}</span>
                  </button>
                </li>
              ))}
            </ol>
          </OkPanel>

          <OkPanel title="Curatie & Tagging">
            <ul className="lv-kl-curation">
              {CURATION.map((c) => (
                <li key={c.label}>
                  <span>{c.label}</span>
                  <strong>{c.value}</strong>
                </li>
              ))}
            </ul>
            <button
              className="lv-ok-btn is-gold"
              type="button"
              style={{ marginTop: 8, width: "100%" }}
              onClick={() => toast("Tags beheren")}
            >
              Tags beheren
            </button>
          </OkPanel>
        </section>
      </main>
    </AppShell>
  );
}
