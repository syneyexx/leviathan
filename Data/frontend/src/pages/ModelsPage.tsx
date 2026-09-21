import { useMemo, useState } from "react";
import { media } from "../assets/media";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

type ModelRow = {
  id: string;
  name: string;
  subtitle: string;
  type: string;
  typeTone: string;
  size: string;
  context: string;
  status: "Ready" | "Downloaded";
  source: string;
};

const ACTIONS = [
  { title: "Model Hub", subtitle: "Browse & download", tone: "research" },
  { title: "Add Local Model", subtitle: "Import from file", tone: "build" },
  { title: "Manage Models", subtitle: "View, edit, organize", tone: "analyze" },
  { title: "Fine-Tuning", subtitle: "Train & customize", tone: "create" },
  { title: "Model Performance", subtitle: "Compare & benchmark", tone: "research" },
] as const;

const TABS = ["All Models", "Local Models", "Downloaded", "HuggingFace", "Ollama", "Custom", "Fine-tuned"] as const;

const MODELS: ModelRow[] = [
  {
    id: "qwen",
    name: "Qwen2.5-Coder-7B-Instruct",
    subtitle: "Advanced coding capabilities",
    type: "Instruct",
    typeTone: "blue",
    size: "7B",
    context: "128K",
    status: "Ready",
    source: "HuggingFace",
  },
  {
    id: "llama",
    name: "Llama 3.1 8B Instruct",
    subtitle: "General purpose assistant",
    type: "Instruct",
    typeTone: "cyan",
    size: "8B",
    context: "128K",
    status: "Ready",
    source: "Ollama",
  },
  {
    id: "mixtral",
    name: "Mixtral 8x7B Instruct",
    subtitle: "High performance MoE model",
    type: "Instruct",
    typeTone: "purple",
    size: "46.7B",
    context: "32K",
    status: "Downloaded",
    source: "HuggingFace",
  },
  {
    id: "phi",
    name: "Phi-4 Mini",
    subtitle: "Compact reasoning model",
    type: "Custom",
    typeTone: "gold",
    size: "3.8B",
    context: "16K",
    status: "Ready",
    source: "Local",
  },
  {
    id: "deepseek",
    name: "DeepSeek-Coder-V2",
    subtitle: "Repository-scale coding",
    type: "Instruct",
    typeTone: "green",
    size: "16B",
    context: "128K",
    status: "Downloaded",
    source: "HuggingFace",
  },
  {
    id: "hades",
    name: "HADES-Coder-7B-SFT",
    subtitle: "Fine-tuned Leviathan coding mind",
    type: "Fine-tuned",
    typeTone: "amber",
    size: "7B",
    context: "32K",
    status: "Ready",
    source: "Custom",
  },
];

const QUICK = [
  { label: "Download Model", icon: <path d="M12 5v10M8 11l4 4 4-4M5 19h14" /> },
  { label: "Import GGUF", icon: <path d="M12 16V5M8 9l4-4 4 4M5 19h14" /> },
  { label: "Convert Model", icon: <path d="M4 12h16M12 4l8 8-8 8" /> },
  { label: "Merge Models", icon: <path d="M8 8h8v8H8zM4 12h4M16 12h4" /> },
  { label: "Run Benchmark", icon: <path d="M5 19V9M12 19V5M19 19v-7" /> },
  { label: "View Logs", icon: <path d="M5 7h14M5 12h10M5 17h8" /> },
];

const RECENT = [
  { name: "Qwen2.5-Coder-7B", time: "2m ago" },
  { name: "Llama 3.1 8B", time: "15m ago" },
  { name: "HADES-Coder-7B-SFT", time: "1h ago" },
  { name: "Mixtral 8x7B", time: "3h ago" },
  { name: "Phi-4 Mini", time: "Yesterday" },
];

export function ModelsPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]>("All Models");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return MODELS.filter((model) => {
      if (tab === "Local Models" && model.source !== "Local" && model.source !== "Custom") return false;
      if (tab === "Downloaded" && model.status !== "Downloaded" && model.status !== "Ready") return false;
      if (tab === "HuggingFace" && model.source !== "HuggingFace") return false;
      if (tab === "Ollama" && model.source !== "Ollama") return false;
      if (tab === "Custom" && model.source !== "Custom" && model.type !== "Custom") return false;
      if (tab === "Fine-tuned" && model.type !== "Fine-tuned") return false;
      if (!q) return true;
      return `${model.name} ${model.subtitle} ${model.source}`.toLowerCase().includes(q);
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

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Models Mode"
      searchPlaceholder="Search models, tags, capabilities..."
      pageClass="lv-app--models"
    >
      <main className="lv-main">
        <section className="lv-page-hero">
          <div className="lv-hero-media">
            <img src={media.hero} alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <div className="lv-hero-kicker">
              <span />
              Power Intelligence
              <span />
            </div>
            <h1 className="lv-hero-title">Models</h1>
            <p className="lv-page-quote">“Multiple minds. A greater tomorrow.”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Load</span>
            <span>Compare</span>
            <span>Configure</span>
            <span>Fine-tune</span>
            <span>Deploy</span>
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
                  <path d="M12 4l8 4-8 4-8-4 8-4z" />
                  <path d="M4 12l8 4 8-4" />
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
            style={{ minWidth: 220, flex: 1 }}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter models…"
            aria-label="Filter models"
          />
          <select className="lv-select" defaultValue="all" aria-label="Type">
            <option value="all">All Types</option>
            <option value="instruct">Instruct</option>
            <option value="custom">Custom</option>
          </select>
          <select className="lv-select" defaultValue="all" aria-label="Size">
            <option value="all">All Sizes</option>
            <option value="7b">7B</option>
            <option value="8b">8B</option>
          </select>
          <select className="lv-select" defaultValue="all" aria-label="Status">
            <option value="all">All Status</option>
            <option value="ready">Ready</option>
            <option value="downloaded">Downloaded</option>
          </select>
          <select className="lv-select" defaultValue="newest" aria-label="Sort">
            <option value="newest">Sort: Newest</option>
            <option value="name">Sort: Name</option>
            <option value="size">Sort: Size</option>
          </select>
        </div>

        <div className="lv-models-table-wrap">
          <table className="lv-models-table">
            <thead>
              <tr>
                <th aria-label="Select" />
                <th>Name</th>
                <th>Type</th>
                <th>Size</th>
                <th>Context</th>
                <th>Status</th>
                <th>Source</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((model) => (
                <tr key={model.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(model.id)}
                      onChange={() => toggle(model.id)}
                      aria-label={`Select ${model.name}`}
                    />
                  </td>
                  <td>
                    <div className="lv-model-name">
                      <strong>{model.name}</strong>
                      <small>{model.subtitle}</small>
                    </div>
                  </td>
                  <td>
                    <span className={`lv-tag ${model.typeTone}`}>{model.type}</span>
                  </td>
                  <td>{model.size}</td>
                  <td>{model.context}</td>
                  <td>
                    <span className="lv-model-status">
                      <span
                        className={`lv-status-dot ${model.status === "Ready" ? "ready" : "downloaded"}`}
                      />
                      {model.status}
                    </span>
                  </td>
                  <td>{model.source}</td>
                  <td>
                    <div className="lv-row-actions">
                      <button
                        className="lv-icon-btn"
                        type="button"
                        aria-label="Load"
                        onClick={() => toast(`Load ${model.name}`)}
                      >
                        <svg className="lv-icon" viewBox="0 0 24 24">
                          <path d="M8 6l12 6-12 6V6z" />
                        </svg>
                      </button>
                      <button
                        className="lv-icon-btn"
                        type="button"
                        aria-label="More"
                        onClick={() => toast(`${model.name} options`)}
                      >
                        <svg className="lv-icon" viewBox="0 0 24 24">
                          <circle cx="6" cy="12" r="1.4" fill="currentColor" stroke="none" />
                          <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
                          <circle cx="18" cy="12" r="1.4" fill="currentColor" stroke="none" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="lv-stat-strip">
          <div className="lv-stat-card">
            <strong>12</strong>
            <span>Local Models</span>
          </div>
          <div className="lv-stat-card">
            <strong>28</strong>
            <span>Downloaded</span>
          </div>
          <div className="lv-stat-card">
            <strong>6</strong>
            <span>Custom Models</span>
          </div>
          <div className="lv-stat-card">
            <strong>142</strong>
            <span>Available Online</span>
          </div>
        </div>

        <p className="lv-footer-quote">
          “The right model for the right task unlocks infinite possibilities.” — LEVIATHAN
        </p>
      </main>

      <aside className="lv-right">
        <article className="lv-panel lv-card">
          <div className="lv-section-label">System Resources</div>
          <div className="lv-gauges">
            <div className="lv-gauge">
              <div className="lv-ring cyan" style={{ ["--p" as string]: 34 }}>
                <b>34%</b>
              </div>
              <span>CPU</span>
            </div>
            <div className="lv-gauge">
              <div className="lv-ring cyan" style={{ ["--p" as string]: 62 }}>
                <b>62%</b>
              </div>
              <span>GPU</span>
            </div>
            <div className="lv-gauge">
              <div className="lv-ring cyan" style={{ ["--p" as string]: 41 }}>
                <b>41%</b>
              </div>
              <span>RAM</span>
            </div>
            <div className="lv-gauge">
              <div className="lv-ring gold" style={{ ["--p" as string]: 68 }}>
                <b>68%</b>
              </div>
              <span>VRAM</span>
            </div>
          </div>
        </article>

        <article className="lv-panel lv-panel-premium lv-loaded-card">
          <div className="lv-card-head">
            <div className="lv-section-label">Loaded Model</div>
            <button className="lv-link" type="button" onClick={() => toast("Manage")}>
              Manage
            </button>
          </div>
          <h3 className="lv-loaded-name">Qwen2.5-Coder-7B-Instruct</h3>
          <div className="lv-toolbar">
            <span className="lv-tag blue">Instruct Model</span>
            <span className="lv-model-status">
              <span className="lv-status-dot ready" />
              Ready
            </span>
          </div>
          <div className="lv-meta-grid">
            <div className="lv-meta-item">
              <span>Parameters</span>
              <strong>7 Billion</strong>
            </div>
            <div className="lv-meta-item">
              <span>Context</span>
              <strong>128,000</strong>
            </div>
            <div className="lv-meta-item">
              <span>Quantization</span>
              <strong>Q4_K_M</strong>
            </div>
            <div className="lv-meta-item">
              <span>Size</span>
              <strong>4.1 GB</strong>
            </div>
            <div className="lv-meta-item">
              <span>Source</span>
              <strong>HuggingFace</strong>
            </div>
            <div className="lv-meta-item">
              <span>Last Used</span>
              <strong>2 minutes ago</strong>
            </div>
          </div>
          <div className="lv-detail-actions">
            <button className="lv-btn lv-btn-danger" type="button" onClick={() => toast("Unload")}>
              Unload
            </button>
            <button className="lv-btn" type="button" onClick={() => toast("Settings")}>
              Settings
            </button>
            <button
              className="lv-btn lv-btn-gold"
              style={{ gridColumn: "1 / -1" }}
              type="button"
              onClick={() => toast("Chat with Model")}
            >
              Chat with Model
            </button>
          </div>
        </article>

        <div className="lv-section-label">Quick Actions</div>
        <div className="lv-tools-grid-compact">
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
          <div className="lv-section-label">Recently Used</div>
          <div className="lv-recent-list">
            {RECENT.map((item) => (
              <button
                key={item.name}
                className="lv-recent-row"
                type="button"
                onClick={() => toast(item.name)}
              >
                <span>{item.name}</span>
                <time>{item.time}</time>
              </button>
            ))}
          </div>
        </article>
      </aside>
    </AppShell>
  );
}
