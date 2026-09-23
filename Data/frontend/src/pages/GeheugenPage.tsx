import { useEffect, useState, type ReactNode } from "react";
import { onderzoekHeroes } from "../assets/onderzoekKennisAssets";
import { api } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { HealthResponse } from "../types/api";
import {
  OkBars,
  OkGauge,
  OkHero,
  OkIcon,
  OkPanel,
  OkProgress,
  OkSpark,
} from "./onderzoek/ok-shared";

type TabId =
  | "overview"
  | "ingestion"
  | "graph"
  | "recall"
  | "organization"
  | "retention"
  | "settings";

type RecallMode = "semantisch" | "hybride" | "exact";

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

const HEALTH_STATS = [
  { value: "—", label: "Total Memories" },
  { value: "unmeasured", label: "Integrity Score" },
  { value: "unmeasured", label: "Avg. Recall Time" },
  { value: "unmeasured", label: "Availability" },
] as const;

/** Decorative spark only — not a measured growth series. */
const GROWTH_POINTS = [42, 48, 45, 52, 58, 55, 63, 68, 66, 74, 78, 82] as const;

const MEMORY_TYPES = [
  {
    id: "episodic",
    title: "Episodisch Geheugen",
    count: "482K",
    blurb: "Specifieke gebeurtenissen en ervaringen",
    tone: "gold" as const,
  },
  {
    id: "semantic",
    title: "Semantisch Geheugen",
    count: "612K",
    blurb: "Feiten, concepten en algemene kennis",
    tone: "cyan" as const,
  },
  {
    id: "procedural",
    title: "Procedureel Geheugen",
    count: "128K",
    blurb: "Vaardigheden, patronen en werkwijzen",
    tone: "purple" as const,
  },
];

const TRACES = [
  {
    id: "t1",
    title: "Project scope besproken voor Atlas platform",
    tags: ["Episodisch", "Projecten", "Atlas"],
    ago: "12m ago",
  },
  {
    id: "t2",
    title: "Uitleg over vector embeddings en similariteit",
    tags: ["Semantisch", "AI", "Embeddings"],
    ago: "34m ago",
  },
  {
    id: "t3",
    title: "Gebruikersvoorkeur: compacte antwoorden in chat",
    tags: ["Procedureel", "Voorkeuren"],
    ago: "1u ago",
  },
  {
    id: "t4",
    title: "Analyse van Q3 onderzoeksresultaten",
    tags: ["Episodisch", "Research", "Q3"],
    ago: "2u ago",
  },
  {
    id: "t5",
    title: "Definitie van retrieval-augmented generation (RAG)",
    tags: ["Semantisch", "RAG", "Architectuur"],
    ago: "3u ago",
  },
];

const QUEUE = [
  { id: "q1", name: "research_notes_atlas.md", kind: "Markdown · 48 KB", status: "Processing" as const },
  { id: "q2", name: "conversation_2024-09-17.json", kind: "JSON · 112 KB", status: "Queued" as const },
  { id: "q3", name: "whitepaper_rag.pdf", kind: "PDF · 2.4 MB", status: "Queued" as const },
];

const TIERS = [
  { id: "hot", label: "Hot (Active)", count: "124K", value: 18, tone: "red" as const },
  { id: "warm", label: "Warm (Recent)", count: "412K", value: 52, tone: "cyan" as const },
  { id: "cold", label: "Cold (Archive)", count: "664K", value: 78, tone: "muted" as const },
];

const INTEGRITY = [
  { label: "Data consistency", value: "99.8%" },
  { label: "Embedding integrity", value: "99.6%" },
  { label: "Link validation", value: "99.9%" },
  { label: "Corruption scan", value: "Clean" },
  { label: "Last full check", value: "Sep 17, 2024 02:14" },
];

const PINS = [
  { id: "p1", title: "LEVIATHAN missie", hint: "Kernwaarden & richting", shortcut: "Alt+1" },
  { id: "p2", title: "Gebruikersvoorkeuren", hint: "Stijl, toon, format", shortcut: "Alt+2" },
  { id: "p3", title: "Architectuur principes", hint: "System design rules", shortcut: "Alt+3" },
  { id: "p4", title: "Lessen uit vorige projecten", hint: "Retrospectives", shortcut: "Alt+4" },
];

const TOPICS = [
  { name: "AI / LLM", pct: 28 },
  { name: "RAG", pct: 17 },
  { name: "Projecten", pct: 14 },
  { name: "Architectuur", pct: 11 },
];

const SEARCH_BARS = [38, 52, 44, 61, 48, 72, 58] as const;
const HIT_SPARK = [88, 90, 89, 91, 92, 93, 94] as const;
const LATENCY_SPARK = [18, 16, 15, 14, 13, 12, 12] as const;

export function GeheugenPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<TabId>("overview");
  const [recallMode, setRecallMode] = useState<RecallMode>("hybride");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [sortBy, setSortBy] = useState("relevance");
  const [selectedTrace, setSelectedTrace] = useState(TRACES[0].id);
  const [selectedType, setSelectedType] = useState(MEMORY_TYPES[0].id);
  const [contextFill] = useState(12);
  const [posture, setPosture] = useState<string>("unmeasured");
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [healthStats, setHealthStats] = useState<Array<{ value: string; label: string }>>(
    [...HEALTH_STATS],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [health, mem] = await Promise.all([
          api.health().catch(() => null as HealthResponse | null),
          api.listMemory({ limit: 500 }).catch(() => null),
        ]);
        if (cancelled) return;
        const overall = health?.posture || health?.product_truth?.overall || "unmeasured";
        setPosture(String(overall));
        const count = mem?.memory?.length ?? null;
        setMemoryCount(count);
        setHealthStats([
          {
            value: count == null ? "—" : String(count),
            label: "Active Memories (sampled)",
          },
          { value: "unmeasured", label: "Integrity Score" },
          { value: "unmeasured", label: "Avg. Recall Time" },
          { value: String(overall), label: "Product Posture" },
        ]);
      } catch {
        if (!cancelled) setPosture("unmeasured");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function switchTab(id: TabId) {
    setTab(id);
    toast(`Geheugen · ${TABS.find((t) => t.id === id)?.label ?? id}`);
  }

  function runRecall() {
    toast(`Recall (${recallMode}): “${query.trim() || "geheugen"}” — results follow evidence, not demo latency`);
  }

  const gaugeValue =
    posture === "operational" ? 80 : posture === "degraded" ? 45 : posture === "fixture" ? 20 : 0;
  const gaugeLabel =
    posture === "operational"
      ? "Operational"
      : posture === "degraded"
        ? "Degraded"
        : posture === "fixture"
          ? "Fixture"
          : "Unmeasured";

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Search memories, knowledge, research, agents..."
      systemItems={["SYSTEMS ONLINE", "LLM", "NEURAL", "MEMORY", "TOOLS"]}
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
              onClick={() => switchTab(item.id)}
            >
              <span className="lv-gh-tab-ico">{item.icon}</span>
              <strong>{item.label}</strong>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>

        <OkPanel className="lv-gh-health-panel" title="Memory Health">
          <div className="lv-gh-health">
            <div className="lv-gh-gauge-wrap">
              <OkGauge value={gaugeValue} label={gaugeLabel} size={88} />
              <div className="lv-gh-gauge-meta">
                <strong>Memory posture from evidence</strong>
                <span>
                  {memoryCount == null
                    ? "Counts unmeasured until /api/memory responds"
                    : `${memoryCount} active memories sampled · posture ${posture}`}
                </span>
              </div>
            </div>
            <div className="lv-gh-stats">
              {healthStats.map((stat) => (
                <button
                  key={stat.label}
                  type="button"
                  className="lv-gh-stat"
                  onClick={() => toast(`${stat.label}: ${stat.value}`)}
                >
                  <strong>{stat.value}</strong>
                  <small>{stat.label}</small>
                </button>
              ))}
            </div>
            <div className="lv-gh-growth">
              <div className="lv-gh-growth-head">
                <strong>fixture</strong>
                <span>Growth spark (decorative)</span>
              </div>
              <OkSpark points={GROWTH_POINTS} width={140} height={40} />
            </div>
          </div>
        </OkPanel>

        <section className="lv-gh-mid" aria-label="Memory overview">
          <OkPanel
            title="Memory Types"
            action={
              <button type="button" className="lv-ok-btn is-ghost" onClick={() => toast("Memory types · Manage")}>
                Manage
              </button>
            }
          >
            <div className="lv-gh-types">
              {MEMORY_TYPES.map((type) => (
                <button
                  key={type.id}
                  type="button"
                  className={`lv-gh-type is-${type.tone}${selectedType === type.id ? " is-active" : ""}`}
                  onClick={() => {
                    setSelectedType(type.id);
                    toast(`${type.title}: ${type.count}`);
                  }}
                >
                  <strong>{type.title}</strong>
                  <em>{type.count}</em>
                  <small>{type.blurb}</small>
                </button>
              ))}
            </div>
          </OkPanel>

          <OkPanel
            title="Recente Memory Traces"
            action={
              <button type="button" className="lv-ok-btn is-ghost" onClick={() => toast("Alle memory traces")}>
                View All
              </button>
            }
          >
            <ul className="lv-ok-list lv-gh-traces">
              {TRACES.map((trace) => (
                <li key={trace.id}>
                  <button
                    type="button"
                    className={selectedTrace === trace.id ? "is-active" : ""}
                    onClick={() => {
                      setSelectedTrace(trace.id);
                      toast(trace.title);
                    }}
                  >
                    <div className="lv-ok-list-copy">
                      <strong>{trace.title}</strong>
                      <span className="lv-gh-trace-tags">
                        {trace.tags.map((tag) => (
                          <span key={tag} className="lv-ok-tag">
                            {tag}
                          </span>
                        ))}
                      </span>
                    </div>
                    <span className="lv-ok-count">{trace.ago}</span>
                  </button>
                </li>
              ))}
            </ul>
          </OkPanel>

          <OkPanel title="Actieve Context">
            <dl className="lv-gh-context">
              <div>
                <dt>Huidige sessie</dt>
                <dd>
                  Research &amp; Knowledge <span className="lv-ok-muted">(23m)</span>
                </dd>
              </div>
              <div>
                <dt>Actief project</dt>
                <dd>
                  LEVIATHAN Platform <span className="lv-ok-muted">(3d)</span>
                </dd>
              </div>
              <div>
                <dt>Gebruiker intentie</dt>
                <dd>Onderzoek en documentatie</dd>
              </div>
              <div>
                <dt>Relevante thema&apos;s</dt>
                <dd className="lv-ok-chip-row">
                  {["AI", "Geheugen", "Architectuur", "RAG"].map((theme) => (
                    <button
                      key={theme}
                      type="button"
                      className="lv-ok-chip is-active"
                      onClick={() => toast(`Thema: ${theme}`)}
                    >
                      {theme}
                    </button>
                  ))}
                </dd>
              </div>
              <div>
                <dt>Context venster</dt>
                <dd>
                  <div className="lv-gh-context-fill">
                    <strong>
                      {contextFill} / 32 items
                    </strong>
                    <OkProgress value={(contextFill / 32) * 100} tone="cyan" />
                  </div>
                </dd>
              </div>
            </dl>
          </OkPanel>
        </section>

        <section className="lv-gh-lower" aria-label="Ingestion and integrity">
          <OkPanel
            title="Memory Ingestion Queue"
            action={<span className="lv-ok-pill is-cyan">Live · {QUEUE.length} items</span>}
          >
            <div className="lv-ok-queue">
              {QUEUE.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="lv-gh-queue-row"
                  onClick={() => toast(`${item.name}: ${item.status}`)}
                >
                  <div className="lv-ok-list-copy">
                    <strong>{item.name}</strong>
                    <small>{item.kind}</small>
                  </div>
                  <span className={`lv-ok-pill ${item.status === "Processing" ? "is-cyan" : "is-gold"}`}>
                    {item.status}
                  </span>
                </button>
              ))}
            </div>
          </OkPanel>

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
                    if (e.key === "Enter") runRecall();
                  }}
                />
                <kbd>CTRL F</kbd>
              </div>
              <div className="lv-ok-chip-row">
                {(
                  [
                    ["semantisch", "Semantisch"],
                    ["hybride", "Hybride"],
                    ["exact", "Exact"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`lv-ok-chip${recallMode === id ? " is-active lv-gh-chip-gold" : ""}`}
                    onClick={() => {
                      setRecallMode(id);
                      toast(`Recall mode: ${label}`);
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="lv-gh-recall-filters">
                <select
                  className="lv-ok-select"
                  value={typeFilter}
                  onChange={(e) => {
                    setTypeFilter(e.target.value);
                    toast(`Filter type: ${e.target.value}`);
                  }}
                >
                  <option value="all">Alle types</option>
                  <option value="episodic">Episodisch</option>
                  <option value="semantic">Semantisch</option>
                  <option value="procedural">Procedureel</option>
                </select>
                <select
                  className="lv-ok-select"
                  value={sortBy}
                  onChange={(e) => {
                    setSortBy(e.target.value);
                    toast(`Sortering: ${e.target.value}`);
                  }}
                >
                  <option value="relevance">Relevantie</option>
                  <option value="recent">Meest recent</option>
                  <option value="strength">Sterkte</option>
                </select>
              </div>
              <button type="button" className="lv-ok-btn is-gold" onClick={runRecall}>
                Zoeken
              </button>
            </div>
          </OkPanel>

          <OkPanel title="Memory Tiers">
            {TIERS.map((tier) => (
              <button
                key={tier.id}
                type="button"
                className="lv-gh-tier"
                onClick={() => toast(`${tier.label}: ${tier.count}`)}
              >
                <span>{tier.label}</span>
                <OkProgress value={tier.value} tone={tier.tone} />
                <strong>{tier.count}</strong>
              </button>
            ))}
          </OkPanel>

          <OkPanel title="Memory Integrity" action={<span className="lv-ok-pill is-green">Healthy</span>}>
            <ul className="lv-ok-check">
              {INTEGRITY.map((row) => (
                <li key={row.label}>
                  <span>✓ {row.label}</span>
                  <span>{row.value}</span>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="lv-ok-btn"
              style={{ marginTop: 8, width: "100%" }}
              onClick={() =>
                toast("Integrity check gestart — resultaat volgt uit evidence, niet uit aannames")
              }
            >
              Run Integrity Check
            </button>
          </OkPanel>
        </section>

        <section className="lv-gh-bottom" aria-label="Pins and analytics">
          <OkPanel title="Vastgezette Herinneringen">
            <div className="lv-gh-pins">
              {PINS.map((pin) => (
                <button
                  key={pin.id}
                  type="button"
                  className="lv-gh-pin"
                  onClick={() => toast(`Pin geopend: ${pin.title}`)}
                >
                  <kbd>{pin.shortcut}</kbd>
                  <strong>{pin.title}</strong>
                  <small>{pin.hint}</small>
                </button>
              ))}
            </div>
          </OkPanel>

          <OkPanel title="Recall Analytics (7D)">
            <div className="lv-gh-analytics">
              <article>
                <header>
                  <span>Searches</span>
                  <strong>1,842</strong>
                  <em className="is-up">+18%</em>
                </header>
                <OkBars values={SEARCH_BARS} height={44} />
              </article>
              <article>
                <header>
                  <span>Hit Rate</span>
                  <strong>94%</strong>
                  <em className="is-up">+3%</em>
                </header>
                <OkSpark points={HIT_SPARK} width={120} height={36} />
              </article>
              <article>
                <header>
                  <span>Avg Latency</span>
                  <strong>12ms</strong>
                  <em className="is-up">−24%</em>
                </header>
                <OkSpark points={LATENCY_SPARK} width={120} height={36} color="#20DC8C" />
              </article>
            </div>
          </OkPanel>

          <OkPanel title="Top Topics">
            <ol className="lv-gh-topics">
              {TOPICS.map((topic, i) => (
                <li key={topic.name}>
                  <button type="button" onClick={() => toast(`Topic: ${topic.name} (${topic.pct}%)`)}>
                    <span>
                      {i + 1}. {topic.name}
                    </span>
                    <strong>{topic.pct}%</strong>
                  </button>
                </li>
              ))}
            </ol>
          </OkPanel>
        </section>
      </main>
    </AppShell>
  );
}
