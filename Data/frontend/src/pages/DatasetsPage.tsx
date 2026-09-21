import { useMemo, useState, type ReactNode } from "react";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type DatasetRow = {
  id: string;
  name: string;
  subtitle: string;
  type: string;
  typeTone: string;
  size: string;
  samples: string;
  status: "Processed" | "Indexed" | "Processing" | "Generated";
  updated: string;
};

const ACTIONS: { title: string; subtitle: string; tone: string; icon: ReactNode }[] = [
  {
    title: "Browse Hub",
    subtitle: "Explore public datasets",
    tone: "research",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M4 12h16M12 4c2.5 2.8 2.5 13.2 0 16M12 4c-2.5 2.8-2.5 13.2 0 16" />
      </>
    ),
  },
  {
    title: "Upload Dataset",
    subtitle: "Add your own data",
    tone: "build",
    icon: <path d="M12 16V5M8 9l4-4 4 4M5 19h14" />,
  },
  {
    title: "Import from Source",
    subtitle: "HuggingFace, GitHub, URLs...",
    tone: "analyze",
    icon: (
      <>
        <ellipse cx="12" cy="6" rx="7" ry="3" />
        <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
        <path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
      </>
    ),
  },
  {
    title: "Process & Clean",
    subtitle: "Prepare for training",
    tone: "create",
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" />
      </>
    ),
  },
  {
    title: "Create Dataset",
    subtitle: "Build synthetic data",
    tone: "research",
    icon: <path d="M12 5v14M5 12h14" />,
  },
];

const TABS = [
  "My Datasets",
  "HuggingFace",
  "Local Files",
  "GitHub",
  "Web Sources",
  "Synthetic",
  "Favorites",
] as const;

const DATASETS: DatasetRow[] = [
  {
    id: "hades",
    name: "HADES-Code-Instruction",
    subtitle: "Instruction pairs for coding agents",
    type: "Text",
    typeTone: "blue",
    size: "4.2 GB",
    samples: "1.2M",
    status: "Processed",
    updated: "2h ago",
  },
  {
    id: "trading",
    name: "Trading_Market_Data_2000_2024",
    subtitle: "OHLCV + macro features",
    type: "Time Series",
    typeTone: "purple",
    size: "18.6 GB",
    samples: "42M",
    status: "Indexed",
    updated: "5h ago",
  },
  {
    id: "multimodal",
    name: "Multimodal_Images",
    subtitle: "Vision corpus with captions",
    type: "Image",
    typeTone: "amber",
    size: "86 GB",
    samples: "3.4M",
    status: "Processing",
    updated: "12m ago",
  },
  {
    id: "synthetic",
    name: "Synthetic_Reasoning",
    subtitle: "Generated chain-of-thought traces",
    type: "Text",
    typeTone: "blue",
    size: "1.1 GB",
    samples: "890K",
    status: "Generated",
    updated: "1d ago",
  },
  {
    id: "arxiv",
    name: "arXiv_CS_Abstracts_2020_2026",
    subtitle: "Paper abstracts + metadata",
    type: "Text",
    typeTone: "blue",
    size: "620 MB",
    samples: "410K",
    status: "Processed",
    updated: "2d ago",
  },
  {
    id: "audio",
    name: "Voice_Commands_EN",
    subtitle: "Speech clips for tool calling",
    type: "Audio",
    typeTone: "cyan",
    size: "12.4 GB",
    samples: "240K",
    status: "Indexed",
    updated: "3d ago",
  },
];

const PROCESSING = [
  { label: "Ingestion Queue", tone: "cyan" },
  { label: "Data Cleaning", tone: "gold" },
  { label: "Format Conversion", tone: "blue" },
  { label: "Chunking", tone: "purple" },
  { label: "Embedding Generation", tone: "green" },
  { label: "Quality Analysis", tone: "amber" },
];

const QUICK = [
  { label: "Upload Files", icon: <path d="M12 16V5M8 9l4-4 4 4M5 19h14" /> },
  { label: "From URL", icon: <path d="M10 14l4-4M8 12a4 4 0 015.6-5.6l2 2a4 4 0 01-5.6 5.6l-1-1" /> },
  {
    label: "HuggingFace",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M8 14c1.2 1.4 2.6 2 4 2s2.8-.6 4-2" />
      </>
    ),
  },
  { label: "GitHub", icon: <path d="M9 19c-4 1.5-4-2-6-2m12 4v-3.5a3 3 0 00-.7-2C16.5 17 20 16 20 11a4 4 0 00-1-2.9 3.7 3.7 0 00-.1-2.9S17.7 5 20 7a7 7 0 01-4-.9 7 7 0 00-8 0A7 7 0 014 7c2.3-2 3.2-2 3.2-2a3.7 3.7 0 00-.1 2.9A4 4 0 006 11c0 5 3.5 6 3.7 6.5a3 3 0 00-.7 2.5V21" /> },
  { label: "Create Synthetic", icon: <path d="M12 5v14M5 12h14" /> },
  {
    label: "Process All",
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
      </>
    ),
  },
  { label: "View Logs", icon: <path d="M5 7h14M5 12h10M5 17h8" /> },
  {
    label: "Settings",
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 4v2M12 18v2M4 12h2M18 12h2" />
      </>
    ),
  },
];

const ACTIVITY = [
  { text: "Dataset processed — HADES-Code-Instruction", time: "5m ago" },
  { text: "Downloaded — Trading_Market_Data shard 3", time: "18m ago" },
  { text: "Processing — Multimodal_Images batch 12", time: "32m ago" },
  { text: "Indexed — Voice_Commands_EN", time: "1h ago" },
  { text: "Generated — Synthetic_Reasoning v2", time: "3h ago" },
];

const STORAGE_SLICES = [
  { label: "Text", pct: 48, color: "#4285E8" },
  { label: "Images", pct: 22, color: "#DB8A34" },
  { label: "Archives", pct: 12, color: "#9B8CFF" },
  { label: "Time Series", pct: 10, color: "#22C9D6" },
  { label: "Other", pct: 8, color: "#745522" },
];

function statusClass(status: DatasetRow["status"]) {
  if (status === "Processed") return "ready";
  if (status === "Indexed") return "downloaded";
  if (status === "Processing") return "running";
  return "queued";
}

export function DatasetsPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]>("My Datasets");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"list" | "grid">("list");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return DATASETS.filter((row) => {
      if (tab === "HuggingFace" && !row.name.toLowerCase().includes("hades") && row.id !== "arxiv") return false;
      if (tab === "Synthetic" && row.status !== "Generated") return false;
      if (tab === "Favorites" && row.id !== "hades" && row.id !== "trading") return false;
      if (!q) return true;
      return `${row.name} ${row.subtitle} ${row.type}`.toLowerCase().includes(q);
    });
  }, [query, tab]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const donutSegments = STORAGE_SLICES.reduce<
    { label: string; pct: number; color: string; dash: number; offset: number }[]
  >((acc, slice) => {
    const dash = (slice.pct / 100) * 100;
    const offset = acc.length === 0 ? 0 : acc[acc.length - 1].offset + acc[acc.length - 1].dash;
    acc.push({ ...slice, dash, offset });
    return acc;
  }, []);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Datasets Mode"
      searchPlaceholder="Search datasets, source, topic, or keyword..."
      systemItems={["AI", "Tools", "Storage", "Sync"]}
      pageClass="lv-app--datasets"
    >
      <main className="lv-main">
        <section className="lv-page-hero">
          <div className="lv-hero-media">
            <img src="/assets/hero-datasets.jpg" alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <h1 className="lv-hero-title">Datasets</h1>
            <p className="lv-hero-kicker" style={{ marginTop: 6 }}>
              Fuel Intelligence.
            </p>
            <p className="lv-page-quote">“Better data. A more intelligent tomorrow.”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Collect</span>
            <span>Process</span>
            <span>Curate</span>
            <span>Integrate</span>
            <span>Empower</span>
          </div>
        </section>

        <div className="lv-action-row">
          {ACTIONS.map((action) => (
            <button
              key={action.title}
              className="lv-action-card"
              type="button"
              onClick={() => toast(action.title)}
            >
              <span className={`lv-feature-icon ${action.tone}`}>
                <svg className="lv-icon" viewBox="0 0 24 24">
                  {action.icon}
                </svg>
              </span>
              <strong>{action.title}</strong>
              <small>{action.subtitle}</small>
            </button>
          ))}
        </div>

        <div className="lv-tabs" role="tablist">
          {TABS.map((item) => (
            <button
              key={item}
              className={`lv-tab${tab === item ? " is-active" : ""}`}
              type="button"
              onClick={() => setTab(item)}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="lv-toolbar">
          <input
            className="lv-input"
            style={{ minWidth: 200, flex: 1 }}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search datasets..."
            aria-label="Search datasets"
          />
          <select className="lv-select" defaultValue="all" aria-label="Type">
            <option value="all">All Types</option>
            <option value="text">Text</option>
            <option value="image">Image</option>
            <option value="timeseries">Time Series</option>
          </select>
          <select className="lv-select" defaultValue="all" aria-label="Size">
            <option value="all">All Sizes</option>
            <option value="small">&lt; 1 GB</option>
            <option value="medium">1–20 GB</option>
            <option value="large">&gt; 20 GB</option>
          </select>
          <select className="lv-select" defaultValue="all" aria-label="Status">
            <option value="all">All Status</option>
            <option value="processed">Processed</option>
            <option value="indexed">Indexed</option>
            <option value="processing">Processing</option>
          </select>
          <select className="lv-select" defaultValue="updated" aria-label="Sort">
            <option value="updated">Sort: Updated</option>
            <option value="name">Sort: Name</option>
            <option value="size">Sort: Size</option>
          </select>
          <div className="lv-view-toggle" role="group" aria-label="View">
            <button
              className={`lv-icon-btn${view === "list" ? " is-active" : ""}`}
              type="button"
              aria-label="List view"
              onClick={() => setView("list")}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M5 7h14M5 12h14M5 17h14" />
              </svg>
            </button>
            <button
              className={`lv-icon-btn${view === "grid" ? " is-active" : ""}`}
              type="button"
              aria-label="Grid view"
              onClick={() => setView("grid")}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M5 5h6v6H5zM13 5h6v6h-6M5 13h6v6H5M13 13h6v6h-6" />
              </svg>
            </button>
          </div>
        </div>

        <div className="lv-models-table-wrap">
          <table className="lv-models-table">
            <thead>
              <tr>
                <th aria-label="Select" />
                <th>Name</th>
                <th>Type</th>
                <th>Size</th>
                <th>Samples</th>
                <th>Status</th>
                <th>Last Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(row.id)}
                      onChange={() => toggle(row.id)}
                      aria-label={`Select ${row.name}`}
                    />
                  </td>
                  <td>
                    <div className="lv-model-name">
                      <strong>{row.name}</strong>
                      <small>{row.subtitle}</small>
                    </div>
                  </td>
                  <td>
                    <span className={`lv-tag ${row.typeTone}`}>{row.type}</span>
                  </td>
                  <td>{row.size}</td>
                  <td>{row.samples}</td>
                  <td>
                    <span className="lv-model-status">
                      <span className={`lv-status-dot ${statusClass(row.status)}`} />
                      {row.status}
                    </span>
                  </td>
                  <td>{row.updated}</td>
                  <td>
                    <button
                      className="lv-icon-btn"
                      type="button"
                      aria-label="More"
                      onClick={() => toast(`${row.name} options`)}
                    >
                      <svg className="lv-icon" viewBox="0 0 24 24">
                        <circle cx="6" cy="12" r="1.4" fill="currentColor" stroke="none" />
                        <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
                        <circle cx="18" cy="12" r="1.4" fill="currentColor" stroke="none" />
                      </svg>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="lv-datasets-footer">
          <div className="lv-quote-bust">
            <img src="/assets/bust-quote.jpg" alt="" width={72} height={48} />
            <p className="lv-footer-quote" style={{ textAlign: "left", margin: 0 }}>
              “Data is the foundation of real intelligence.” — LEVIATHAN
            </p>
          </div>
          <div className="lv-stat-strip">
            <div className="lv-stat-card">
              <strong>24</strong>
              <span>Total Datasets</span>
            </div>
            <div className="lv-stat-card">
              <strong>128M</strong>
              <span>Total Samples</span>
            </div>
            <div className="lv-stat-card">
              <strong>342 GB</strong>
              <span>Storage Used</span>
            </div>
            <div className="lv-stat-card">
              <strong>98%</strong>
              <span>Index Coverage</span>
            </div>
          </div>
        </div>
      </main>

      <aside className="lv-right">
        <article className="lv-panel lv-card">
          <div className="lv-section-label">Dataset Storage</div>
          <div className="lv-donut-wrap">
            <svg className="lv-donut" viewBox="0 0 42 42" aria-hidden="true">
              <circle cx="21" cy="21" r="15.915" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="5" />
              {donutSegments.map((seg) => (
                <circle
                  key={seg.label}
                  cx="21"
                  cy="21"
                  r="15.915"
                  fill="none"
                  stroke={seg.color}
                  strokeWidth="5"
                  strokeDasharray={`${seg.dash} ${100 - seg.dash}`}
                  strokeDashoffset={25 - seg.offset}
                  strokeLinecap="butt"
                />
              ))}
            </svg>
            <div className="lv-donut-legend">
              {STORAGE_SLICES.map((slice) => (
                <div key={slice.label} className="lv-donut-item">
                  <span style={{ background: slice.color }} />
                  {slice.label}
                  <b>{slice.pct}%</b>
                </div>
              ))}
            </div>
          </div>
          <div className="lv-storage-meter">
            <div className="lv-progress">
              <span style={{ width: "17%" }} />
            </div>
            <small>342 GB / 2 TB</small>
          </div>
        </article>

        <article className="lv-panel lv-card">
          <div className="lv-section-label">Data Processing</div>
          <div className="lv-process-list">
            {PROCESSING.map((step) => (
              <button
                key={step.label}
                className="lv-process-row"
                type="button"
                onClick={() => toast(step.label)}
              >
                <span className={`lv-process-icon ${step.tone}`} />
                <span>{step.label}</span>
                <svg className="lv-icon" viewBox="0 0 24 24">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </button>
            ))}
          </div>
        </article>

        <div className="lv-section-label">Quick Actions</div>
        <div className="lv-tools-grid-compact lv-tools-grid-4">
          {QUICK.map((tool) => (
            <button
              key={tool.label}
              className="lv-tool"
              type="button"
              onClick={() => toast(tool.label)}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                {tool.icon}
              </svg>
              {tool.label}
            </button>
          ))}
        </div>

        <article className="lv-panel lv-card">
          <div className="lv-section-label">Recent Activity</div>
          <div className="lv-recent-list">
            {ACTIVITY.map((item) => (
              <button
                key={item.text}
                className="lv-recent-row"
                type="button"
                onClick={() => toast(item.text)}
              >
                <span>{item.text}</span>
                <time>{item.time}</time>
              </button>
            ))}
          </div>
        </article>
      </aside>
    </AppShell>
  );
}
