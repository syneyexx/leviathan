import { useMemo, useState } from "react";
import { onderzoekHeroes } from "../assets/onderzoekKennisAssets";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import { OkBars, OkGauge, OkHero, OkIcon, OkPanel, OkProgress } from "./onderzoek/ok-shared";

type ActionId = "overzicht" | "importeren" | "verwerken" | "analyseren" | "splitsen" | "governance" | "exporteren";

type DatasetRow = {
  id: string;
  name: string;
  source: string;
  format: string;
  size: string;
  status: "Klaar" | "Verwerkt" | "Bezig";
  updated: string;
};

const ACTIONS: { id: ActionId; title: string; subtitle: string; icon: string }[] = [
  { id: "overzicht", title: "Dataset overzicht", subtitle: "Statistieken & status", icon: "M4 6h16M4 12h16M4 18h10" },
  { id: "importeren", title: "Importeren", subtitle: "Bestanden, API's, bronnen", icon: "M12 16V5M8 9l4-4 4 4M5 19h14" },
  { id: "verwerken", title: "Verwerken", subtitle: "Cleanen, verrijken, transformeren", icon: "M12 3v3M12 18v3M3 12h3M18 12h3M6.3 6.3l2.1 2.1M15.6 15.6l2.1 2.1M17.7 6.3l-2.1 2.1M8.4 15.6l-2.1 2.1" },
  { id: "analyseren", title: "Analyseren", subtitle: "Distributies & kwaliteit", icon: "M4 19V9M10 19V5M16 19v-7M20 19H3" },
  { id: "splitsen", title: "Splitsen", subtitle: "Train / Validation / Test", icon: "M4 6h6v12H4zM14 6h6v5h-6zM14 14h6v4h-6z" },
  { id: "governance", title: "Governance", subtitle: "Toegang, beleid & compliance", icon: "M12 3l8 4v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V7l8-4z" },
  { id: "exporteren", title: "Exporteren", subtitle: "Naar training & gebruik", icon: "M12 4v11M8 11l4 4 4-4M5 19h14" },
];

const SOURCES = [
  { id: "all", label: "Alle datasets", count: 248 },
  { id: "internal", label: "Interne data", count: 62 },
  { id: "open", label: "Open datasets", count: 54 },
  { id: "hf", label: "Hugging Face", count: 38 },
  { id: "web", label: "Web scraping", count: 27 },
  { id: "docs", label: "Documenten", count: 25 },
  { id: "apis", label: "APIs", count: 18 },
  { id: "db", label: "Databases", count: 12 },
  { id: "synth", label: "Synthetisch", count: 8 },
  { id: "streams", label: "Streams", count: 4 },
] as const;

const DATASETS: DatasetRow[] = [
  { id: "atlas", name: "atlas_knowledge_corpus", source: "Intern", format: "Parquet", size: "124 GB", status: "Klaar", updated: "2u geleden" },
  { id: "wiki", name: "nl_wiki_2024", source: "Open", format: "JSONL", size: "18.4 GB", status: "Klaar", updated: "5u geleden" },
  { id: "code", name: "code_instructions_v2", source: "Hugging Face", format: "Parquet", size: "6.2 GB", status: "Verwerkt", updated: "12m geleden" },
  { id: "crawl", name: "common_crawl_nl", source: "Web", format: "Parquet", size: "86 GB", status: "Bezig", updated: "3m geleden" },
  { id: "filings", name: "financial_filings_eu", source: "API", format: "CSV", size: "2.1 GB", status: "Klaar", updated: "1d geleden" },
];

const QUEUE = [
  { name: "common_crawl_2024.parquet", pct: 68, eta: "12m resterend" },
  { name: "youtube_transcripts.zip", pct: 42, eta: "28m resterend" },
  { name: "pdf_documents_batch", pct: 18, eta: "1h 12m resterend" },
] as const;

const PREVIEW_BY_ID: Record<string, { id: string; title: string; content: string; source: string; date: string }[]> = {
  atlas: [
    { id: "ak-001", title: "Atlas governance charter", content: "Beleidskaders voor kennisdeling…", source: "internal", date: "2024-09-12" },
    { id: "ak-002", title: "Knowledge graph edges v2", content: "Relaties tussen entiteiten…", source: "pipeline", date: "2024-09-14" },
    { id: "ak-003", title: "NL policy digest", content: "Samenvatting wetgeving…", source: "ingest", date: "2024-09-15" },
    { id: "ak-004", title: "RAG eval fixtures", content: "Gouden antwoorden set…", source: "eval", date: "2024-09-16" },
  ],
  wiki: [
    { id: "nw-101", title: "Nederlandse geschiedenis", content: "Artikel excerpt…", source: "wikipedia", date: "2024-08-01" },
    { id: "nw-102", title: "Taalvariatie", content: "Dialectcorpus…", source: "wikipedia", date: "2024-08-03" },
  ],
  code: [
    { id: "ci-01", title: "instruction_pair", content: "Write a FastAPI endpoint…", source: "hf", date: "2024-07-20" },
    { id: "ci-02", title: "instruction_pair", content: "Refactor async worker…", source: "hf", date: "2024-07-21" },
  ],
  crawl: [
    { id: "cc-01", title: "nl_domain_batch", content: "Gecrawlde HTML snippet…", source: "web", date: "2024-09-17" },
  ],
  filings: [
    { id: "ff-01", title: "Q2 earnings note", content: "EU filing extract…", source: "api", date: "2024-06-30" },
  ],
};

const QUALITY = [
  ["Volledigheid", "98.2%"],
  ["Consistentie", "94.1%"],
  ["Duplicaten", "1.8%"],
  ["Ongeldige waarden", "2.1%"],
  ["Schema validatie", "99.5%"],
] as const;

const TAGS = ["kennis", "nederlands", "documenten", "productie", "rag", "atlas"] as const;
const DIST = [8, 14, 22, 36, 54, 70, 78, 62, 44, 28, 18, 12, 9, 6];

function statusTone(status: DatasetRow["status"]) {
  if (status === "Klaar") return "green";
  if (status === "Verwerkt") return "gold";
  return "cyan";
}

export function DatasetsPage() {
  const toast = useAppToast();
  const [action, setAction] = useState<ActionId>("overzicht");
  const [sourceId, setSourceId] = useState("all");
  const [selectedId, setSelectedId] = useState(DATASETS[0].id);
  const [query, setQuery] = useState("");
  const [bron, setBron] = useState("all");
  const [formaat, setFormaat] = useState("all");
  const [status, setStatus] = useState("all");
  const [importTab, setImportTab] = useState("upload");
  const [previewTab, setPreviewTab] = useState<"voorbeeld" | "schema" | "stats">("voorbeeld");
  const [shuffle, setShuffle] = useState(true);
  const [stratified, setStratified] = useState(true);
  const [dedupe, setDedupe] = useState(false);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return DATASETS.filter((row) => {
      if (q && !row.name.includes(q) && !row.source.toLowerCase().includes(q)) return false;
      if (bron !== "all" && row.source.toLowerCase() !== bron) return false;
      if (formaat !== "all" && row.format.toLowerCase() !== formaat) return false;
      if (status !== "all" && row.status.toLowerCase() !== status) return false;
      return true;
    });
  }, [query, bron, formaat, status]);

  const selected = DATASETS.find((row) => row.id === selectedId) ?? DATASETS[0];
  const preview = PREVIEW_BY_ID[selected.id] ?? PREVIEW_BY_ID.atlas;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Zoek datasets, bronnen, formaten, onderwerpen..."
      systemItems={["SYSTEMS ONLINE", "LLM", "NEURAL", "MEMORY", "TOOLS"]}
      layout="wide"
      pageClass="lv-app--onderzoek"
    >
      <main className="lv-main lv-ok-main">
        <OkHero
          title="DATASETS"
          kicker="VERZAMELEN. VALIDEREN. STRUCTUREREN. TRAINEN."
          quote="Data is de grondstof van inzicht. Kwaliteit vandaag, intelligentie morgen."
          image={onderzoekHeroes.datasets}
          rails={["RUWE DATA", "BETERE MODELLEN", "DIEPER INZICHT", "GROTERE IMPACT"]}
        />

        <section className="lv-ok-actions" aria-label="Dataset acties">
          {ACTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`lv-ok-action${action === item.id ? " is-active" : ""}`}
              onClick={() => {
                setAction(item.id);
                toast(`${item.title} geopend`);
              }}
            >
              <span className="lv-ok-action-ico">
                <OkIcon>
                  <path d={item.icon} />
                </OkIcon>
              </span>
              <strong>{item.title}</strong>
              <small>{item.subtitle}</small>
            </button>
          ))}
        </section>

        <section className="lv-ok-kpis is-5" aria-label="Dataset KPI's">
          <article className="lv-ok-kpi">
            <span className="lv-ok-kpi-label">Totaal Datasets</span>
            <span className="lv-ok-kpi-value">248</span>
            <span className="lv-ok-kpi-meta">+12% vs. vorige maand</span>
          </article>
          <article className="lv-ok-kpi">
            <span className="lv-ok-kpi-label">Totaal Records</span>
            <span className="lv-ok-kpi-value">186.4M</span>
            <span className="lv-ok-kpi-meta">+28% · +40.7M records</span>
          </article>
          <article className="lv-ok-kpi">
            <span className="lv-ok-kpi-label">Opslag Gebruikt</span>
            <span className="lv-ok-kpi-value">842 GB</span>
            <span className="lv-ok-kpi-meta is-muted">van 2.0 TB · 42%</span>
            <OkProgress value={42} />
          </article>
          <article className="lv-ok-kpi">
            <span className="lv-ok-kpi-label">Actieve Imports</span>
            <span className="lv-ok-kpi-value">3</span>
            <span className="lv-ok-kpi-meta is-muted">2 bezig, 1 in wachtrij</span>
          </article>
          <article className="lv-ok-kpi">
            <span className="lv-ok-kpi-label">Klaar voor Training</span>
            <span className="lv-ok-kpi-value">76%</span>
            <span className="lv-ok-kpi-meta is-muted">189 van 248 datasets</span>
          </article>
        </section>

        <section className="lv-ds-mid">
          <OkPanel title="Data Bronnen & Collecties">
            <ul className="lv-ok-list">
              {SOURCES.map((source) => (
                <li key={source.id}>
                  <button
                    type="button"
                    className={sourceId === source.id ? "is-active" : undefined}
                    onClick={() => {
                      setSourceId(source.id);
                      toast(`${source.label} gefilterd`);
                    }}
                  >
                    <span className="lv-ok-list-copy">
                      <strong>{source.label}</strong>
                    </span>
                    <span className="lv-ok-count">{source.count}</span>
                  </button>
                </li>
              ))}
            </ul>
            <button
              className="lv-ok-btn is-gold"
              type="button"
              style={{ marginTop: 8, width: "100%" }}
              onClick={() => toast("Nieuwe collectie")}
            >
              + Nieuwe collectie
            </button>
          </OkPanel>

          <OkPanel title="Datasets" action={<span className="lv-ok-muted">{rows.length} zichtbaar</span>} className="lv-ds-table-panel">
            <div className="lv-ds-filters">
              <input
                className="lv-ok-input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Zoek datasets..."
              />
              <select className="lv-ok-select" value={bron} onChange={(e) => setBron(e.target.value)}>
                <option value="all">Alle bronnen</option>
                <option value="intern">Intern</option>
                <option value="open">Open</option>
                <option value="hugging face">Hugging Face</option>
                <option value="web">Web</option>
                <option value="api">API</option>
              </select>
              <select className="lv-ok-select" value={formaat} onChange={(e) => setFormaat(e.target.value)}>
                <option value="all">Alle formaten</option>
                <option value="parquet">Parquet</option>
                <option value="jsonl">JSONL</option>
                <option value="csv">CSV</option>
              </select>
              <select className="lv-ok-select" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="all">Alle statussen</option>
                <option value="klaar">Klaar</option>
                <option value="verwerkt">Verwerkt</option>
                <option value="bezig">Bezig</option>
              </select>
              <select className="lv-ok-select" defaultValue="recent">
                <option value="recent">Laatst bijgewerkt</option>
                <option value="name">Naam A–Z</option>
                <option value="size">Grootte</option>
              </select>
            </div>
            <div className="lv-ok-table-wrap lv-ds-table-wrap">
              <table className="lv-ok-table">
                <thead>
                  <tr>
                    <th>Naam</th>
                    <th>Bron</th>
                    <th>Formaat</th>
                    <th>Grootte</th>
                    <th>Status</th>
                    <th>Bijgewerkt</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.id}
                      className={selectedId === row.id ? "is-active" : undefined}
                      onClick={() => setSelectedId(row.id)}
                    >
                      <td>{row.name}</td>
                      <td>{row.source}</td>
                      <td>{row.format}</td>
                      <td>{row.size}</td>
                      <td>
                        <span className={`lv-ok-pill is-${statusTone(row.status)}`}>{row.status}</span>
                      </td>
                      <td>{row.updated}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </OkPanel>

          <div className="lv-ds-right">
            <OkPanel title="Importeren van Data">
              <div className="lv-ok-chip-row" style={{ marginBottom: 8 }}>
                {[
                  ["upload", "Bestand uploaden"],
                  ["hf", "Hugging Face"],
                  ["url", "URL"],
                  ["archive", "Archief"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`lv-ok-chip${importTab === id ? " is-active" : ""}`}
                    onClick={() => setImportTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="lv-ok-dropzone">
                <OkIcon>
                  <path d="M12 16V5M8 9l4-4 4 4M5 19h14" />
                </OkIcon>
                <strong>Sleep bestanden hierheen</strong>
                <span>CSV, JSON, Parquet, PDF · of</span>
                <button className="lv-ok-btn is-gold" type="button" onClick={() => toast(`Import via ${importTab}`)}>
                  Bestanden selecteren
                </button>
              </div>
            </OkPanel>

            <OkPanel title="Verwerkingsqueue">
              <div className="lv-ok-queue">
                {QUEUE.map((item) => (
                  <div key={item.name} className="lv-ok-queue-item">
                    <header>
                      <strong>{item.name}</strong>
                      <span className="lv-ok-muted">
                        {item.pct}% · {item.eta}
                      </span>
                    </header>
                    <OkProgress value={item.pct} />
                  </div>
                ))}
              </div>
            </OkPanel>
          </div>
        </section>

        <section className="lv-ds-bottom">
          <OkPanel
            title={`Data Voorbeeld · ${selected.name}`}
            action={
              <div className="lv-ok-chip-row">
                {(["voorbeeld", "schema", "stats"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`lv-ok-chip${previewTab === tab ? " is-active" : ""}`}
                    onClick={() => setPreviewTab(tab)}
                  >
                    {tab === "voorbeeld" ? "Voorbeeld data" : tab === "schema" ? "Schema" : "Statistieken"}
                  </button>
                ))}
              </div>
            }
          >
            {previewTab === "voorbeeld" ? (
              <div className="lv-ok-table-wrap">
                <table className="lv-ok-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Titel</th>
                      <th>Content</th>
                      <th>Bron</th>
                      <th>Datum</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((row) => (
                      <tr key={row.id}>
                        <td>{row.id}</td>
                        <td>{row.title}</td>
                        <td>{row.content}</td>
                        <td>{row.source}</td>
                        <td>{row.date}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : previewTab === "schema" ? (
              <p className="lv-ok-muted">id:string · title:string · content:text · source:enum · date:date</p>
            ) : (
              <p className="lv-ok-muted">1.84M rijen · 5 kolommen · null-ratio 0.7% · avg tokens 1.2K</p>
            )}
          </OkPanel>

          <OkPanel title="Data Kwaliteit">
            <div className="lv-ds-quality">
              <OkGauge value={92} label="Kwaliteitsscore" />
              <ul className="lv-ok-check">
                {QUALITY.map(([label, value]) => (
                  <li key={label}>
                    <span>{label}</span>
                    <span>{value}</span>
                  </li>
                ))}
              </ul>
            </div>
          </OkPanel>

          <OkPanel title="Splitsen & Transformeren">
            <div className="lv-ok-split" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="lv-ds-split-legend">
              <span>Train 70%</span>
              <span>Validation 15%</span>
              <span>Test 15%</span>
            </div>
            <label className="lv-ds-check">
              <input type="checkbox" checked={shuffle} onChange={(e) => setShuffle(e.target.checked)} /> Shuffle data
            </label>
            <label className="lv-ds-check">
              <input type="checkbox" checked={stratified} onChange={(e) => setStratified(e.target.checked)} /> Stratified split
            </label>
            <label className="lv-ds-check">
              <input type="checkbox" checked={dedupe} onChange={(e) => setDedupe(e.target.checked)} /> Deduplicate
            </label>
          </OkPanel>

          <OkPanel title="Distributie Analyse">
            <p className="lv-ok-muted" style={{ marginTop: 0 }}>
              Token lengte
            </p>
            <OkBars values={DIST} height={64} />
            <div className="lv-ds-dist-stats">
              <span>Gemiddelde: 1.2K</span>
              <span>Mediaan: 892</span>
              <span>Max: 16K</span>
            </div>
          </OkPanel>
        </section>

        <section className="lv-ds-footer">
          <OkPanel
            title="Versies & Lineage"
            action={
              <button className="lv-ok-btn is-ghost" type="button" onClick={() => toast("Lineage")}>
                Bekijk lineage
              </button>
            }
          >
            <div className="lv-ok-flow">
              <span>v2.0 Ruwe data</span>
              <em>→</em>
              <span>Cleanen</span>
              <em>→</em>
              <span>Verrijken</span>
              <em>→</em>
              <span>v2.1 Huidige versie</span>
            </div>
          </OkPanel>

          <OkPanel title="Tags & Metadata">
            <div className="lv-ok-chip-row">
              {TAGS.map((tag) => (
                <span key={tag} className="lv-ok-tag">
                  {tag}
                </span>
              ))}
              <button className="lv-ok-btn is-ghost" type="button" onClick={() => toast("Tag toevoegen")}>
                + Tag toevoegen
              </button>
            </div>
          </OkPanel>

          <OkPanel title="Governance & Toegang">
            <div className="lv-ok-chip-row" style={{ marginBottom: 8 }}>
              <span className="lv-ok-pill is-cyan">Intern</span>
              <span className="lv-ok-pill is-green">AVG OK</span>
            </div>
            <ul className="lv-ok-check">
              <li>
                <span>Owner</span>
                <span>Research Team</span>
              </li>
              <li>
                <span>Toegang</span>
                <span>Restricted</span>
              </li>
              <li>
                <span>Retentie</span>
                <span>365 dagen</span>
              </li>
            </ul>
          </OkPanel>

          <OkPanel title="Exporteren">
            <div className="lv-ds-export">
              <button className="lv-ok-btn is-gold" type="button" onClick={() => toast("Exporteren naar training")}>
                Exporteren naar training
              </button>
              <button className="lv-ok-btn" type="button" onClick={() => toast("Downloaden")}>
                Downloaden
              </button>
              <button className="lv-ok-btn is-ghost" type="button" onClick={() => toast("Delen")}>
                Delen
              </button>
            </div>
          </OkPanel>
        </section>
      </main>
    </AppShell>
  );
}
