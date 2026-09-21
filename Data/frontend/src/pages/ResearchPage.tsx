import { useState, type ReactNode } from "react";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const ACTIONS: { title: string; subtitle: string; tone: string; icon: ReactNode }[] = [
  {
    title: "Web Research",
    subtitle: "Search the web with AI",
    tone: "research",
    icon: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3-3" />
      </>
    ),
  },
  {
    title: "Academic Search",
    subtitle: "Papers, journals, arXiv",
    tone: "build",
    icon: (
      <>
        <path d="M3 10l9-5 9 5-9 5-9-5z" />
        <path d="M7 12v5c2 1.5 4 2 5 2s3-.5 5-2v-5" />
      </>
    ),
  },
  {
    title: "Data Analysis",
    subtitle: "Analyze files & datasets",
    tone: "analyze",
    icon: <path d="M5 19V9M12 19V5M19 19v-7" />,
  },
  {
    title: "Knowledge Synthesis",
    subtitle: "Turn information into insight",
    tone: "create",
    icon: (
      <>
        <circle cx="8" cy="10" r="2.5" />
        <circle cx="16" cy="8" r="2.5" />
        <circle cx="14" cy="16" r="2.5" />
        <path d="M10 11l4-2M15 10l-1 4" />
      </>
    ),
  },
];

const INPUT_TABS = ["Query", "Files", "URLs", "Datasets", "Code", "Images"] as const;

const MODES = [
  { id: "quick", title: "Quick Search", subtitle: "Fast answers", recommended: false },
  { id: "deep", title: "Deep Research", subtitle: "Multi-step analysis", recommended: true },
  { id: "academic", title: "Academic Mode", subtitle: "Focus on scientific papers", recommended: false },
  { id: "data", title: "Data Analysis", subtitle: "Analyze & visualize datasets", recommended: false },
  { id: "compare", title: "Comparative Analysis", subtitle: "Compare sources", recommended: false },
  { id: "trend", title: "Trend Analysis", subtitle: "Find patterns over time", recommended: false },
] as const;

const SOURCES = [
  { label: "Web Search", tone: "cyan" },
  { label: "arXiv", tone: "coral" },
  { label: "PubMed", tone: "green" },
  { label: "HuggingFace", tone: "amber" },
  { label: "GitHub", tone: "gold" },
  { label: "YouTube", tone: "coral" },
  { label: "Reddit", tone: "amber" },
  { label: "News", tone: "blue" },
  { label: "Custom Sources", tone: "purple" },
] as const;

const ACTIVE = [
  { title: "Quantum Computing 2026", progress: 72, tone: "cyan" },
  { title: "AI Agent Architectures", progress: 48, tone: "gold" },
  { title: "Market Trend Analysis", progress: 91, tone: "green" },
  { title: "HADES vs Competitors", progress: 36, tone: "purple" },
  { title: "Neural Network Efficiency", progress: 67, tone: "blue" },
] as const;

const FINDINGS = [
  { title: "A Survey of LLM Agent Architectures", meta: "arXiv · 2h ago" },
  { title: "Quantum Computing Market Analysis", meta: "Report · 5h ago" },
  { title: "Efficient Training Methods for LLMs", meta: "Nature · 1d ago" },
  { title: "Comparative RAG Benchmarks 2026", meta: "Blog · 1d ago" },
  { title: "Tool-Use Failure Modes in Agents", meta: "arXiv · 2d ago" },
] as const;

const QUICK_TOOLS = [
  { label: "Summarize", icon: <path d="M5 7h14M5 12h10M5 17h12" /> },
  { label: "Extract Data", icon: <path d="M8 6h8v4H8zM6 14h12v4H6z" /> },
  {
    label: "Generate Report",
    icon: (
      <>
        <path d="M7 4h7l4 4v12H7z" />
        <path d="M14 4v4h4" />
      </>
    ),
  },
  { label: "Create Timeline", icon: <path d="M4 12h16M8 8v8M16 8v8" /> },
  {
    label: "Find Patterns",
    icon: (
      <>
        <circle cx="8" cy="12" r="2.5" />
        <circle cx="16" cy="8" r="2.5" />
        <circle cx="16" cy="16" r="2.5" />
        <path d="M10 11l4-2M10 13l4 2" />
      </>
    ),
  },
  { label: "Export Results", icon: <path d="M12 5v10M8 11l4 4 4-4M5 19h14" /> },
] as const;

const INSIGHT_TABS = ["Overview", "Key Findings", "Sources", "Related Topics"] as const;

const GRAPH_NODES: {
  id: string;
  label: string;
  x: number;
  y: number;
  r: number;
  core?: boolean;
}[] = [
  { id: "hades", label: "HADES", x: 220, y: 120, r: 22, core: true },
  { id: "agents", label: "AI Agents", x: 90, y: 60, r: 11 },
  { id: "opt", label: "Optimization", x: 340, y: 50, r: 11 },
  { id: "nn", label: "Neural Networks", x: 360, y: 140, r: 12 },
  { id: "llm", label: "Large Language Models", x: 300, y: 210, r: 12 },
  { id: "qf", label: "Quantitative Finance", x: 120, y: 200, r: 12 },
  { id: "rag", label: "RAG Systems", x: 60, y: 130, r: 10 },
];

const GRAPH_EDGES: [string, string][] = [
  ["hades", "agents"],
  ["hades", "opt"],
  ["hades", "nn"],
  ["hades", "llm"],
  ["hades", "qf"],
  ["hades", "rag"],
  ["agents", "llm"],
  ["nn", "opt"],
];

export function ResearchPage() {
  const toast = useAppToast();
  const [inputTab, setInputTab] = useState<(typeof INPUT_TABS)[number]>("Query");
  const [mode, setMode] = useState<(typeof MODES)[number]["id"]>("deep");
  const [insightTab, setInsightTab] = useState<(typeof INSIGHT_TABS)[number]>("Overview");
  const [query, setQuery] = useState("");

  const nodeMap = Object.fromEntries(GRAPH_NODES.map((node) => [node.id, node]));

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Search knowledge, papers, datasets, web..."
      systemItems={["AI", "Tools", "Agents", "Sync"]}
      layout="wide"
      pageClass="lv-app--research"
    >
      <main className="lv-main lv-research-main">
        <section className="lv-page-hero lv-research-hero">
          <div className="lv-hero-media">
            <img src="/assets/hero-research.jpg" alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <h1 className="lv-hero-title">Research</h1>
            <p className="lv-hero-kicker" style={{ marginTop: 6 }}>
              Explore. Analyze. Discover.
            </p>
            <p className="lv-page-quote">
              Turn information into intelligence. Search the world, analyze data, and let Leviathan
              uncover insights that others miss.
            </p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Knowledge</span>
            <span>Insight</span>
            <span>Patterns</span>
            <span>Breakthroughs</span>
            <span>Real-World Intelligence</span>
          </div>
        </section>

        <div className="lv-action-row lv-action-row-4">
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

        <div className="lv-research-mid">
          <article className="lv-panel lv-card lv-research-input">
            <div className="lv-tabs" role="tablist">
              {INPUT_TABS.map((item) => (
                <button
                  key={item}
                  className={`lv-tab${inputTab === item ? " is-active" : ""}`}
                  type="button"
                  onClick={() => setInputTab(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <label className="lv-form-field full">
              <span>What would you like to research?</span>
              <textarea
                className="lv-research-textarea"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Ask a question, paste a paper, add a file, or enter a topic..."
                rows={6}
              />
            </label>
            <div className="lv-research-input-foot">
              <select className="lv-select" defaultValue="deep" aria-label="Research depth">
                <option value="deep">Deep Research</option>
                <option value="quick">Quick Search</option>
                <option value="academic">Academic</option>
              </select>
              <select className="lv-select" defaultValue="web" aria-label="Sources">
                <option value="web">Web + Knowledge</option>
                <option value="academic">Academic Only</option>
                <option value="local">Local Knowledge</option>
              </select>
              <button
                className="lv-btn lv-btn-gold"
                type="button"
                onClick={() => toast(query.trim() || "Start Research")}
              >
                Start Research →
              </button>
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Research Modes</div>
            <div className="lv-mode-grid">
              {MODES.map((item) => (
                <button
                  key={item.id}
                  className={`lv-mode-card${mode === item.id ? " is-active" : ""}${item.recommended ? " is-recommended" : ""}`}
                  type="button"
                  onClick={() => setMode(item.id)}
                >
                  {item.recommended ? <span className="lv-mode-badge">Recommended</span> : null}
                  <strong>{item.title}</strong>
                  <small>{item.subtitle}</small>
                </button>
              ))}
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-card-head">
              <div className="lv-section-label">Active Research</div>
              <button className="lv-link" type="button" onClick={() => toast("View all")}>
                View all →
              </button>
            </div>
            <div className="lv-active-list">
              {ACTIVE.map((item) => (
                <button
                  key={item.title}
                  className="lv-active-row"
                  type="button"
                  onClick={() => toast(item.title)}
                >
                  <span>{item.title}</span>
                  <div className={`lv-ring ${item.tone === "gold" ? "gold" : "cyan"}`} style={{ ["--p" as string]: item.progress }}>
                    <b>{item.progress}%</b>
                  </div>
                </button>
              ))}
            </div>
          </article>
        </div>

        <div className="lv-research-bottom">
          <article className="lv-panel lv-card">
            <div className="lv-card-head">
              <div className="lv-section-label">Knowledge Sources</div>
              <button className="lv-link" type="button" onClick={() => toast("Manage sources")}>
                Manage →
              </button>
            </div>
            <div className="lv-source-grid">
              {SOURCES.map((source) => (
                <button
                  key={source.label}
                  className="lv-source-card"
                  type="button"
                  onClick={() => toast(source.label)}
                >
                  <span className={`lv-feature-icon ${source.tone === "gold" ? "create" : source.tone === "cyan" ? "analyze" : "research"}`}>
                    <svg className="lv-icon" viewBox="0 0 24 24">
                      {source.label === "Custom Sources" ? (
                        <path d="M12 5v14M5 12h14" />
                      ) : (
                        <>
                          <circle cx="12" cy="12" r="7" />
                          <path d="M12 8v8M8 12h8" />
                        </>
                      )}
                    </svg>
                  </span>
                  <strong>{source.label}</strong>
                </button>
              ))}
            </div>
          </article>

          <article className="lv-panel lv-card lv-insights-card">
            <div className="lv-card-head">
              <div className="lv-section-label">Research Insights</div>
              <div className="lv-tabs">
                {INSIGHT_TABS.map((item) => (
                  <button
                    key={item}
                    className={`lv-tab${insightTab === item ? " is-active" : ""}`}
                    type="button"
                    onClick={() => setInsightTab(item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="lv-insights-graph">
              <svg viewBox="0 0 440 260" role="img" aria-label="Research insights graph">
                {GRAPH_EDGES.map(([a, b]) => {
                  const from = nodeMap[a];
                  const to = nodeMap[b];
                  return (
                    <line
                      key={`${a}-${b}`}
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      stroke="rgba(214,169,87,0.35)"
                      strokeWidth="1"
                    />
                  );
                })}
                {GRAPH_NODES.map((node) => (
                  <g key={node.id} className="lv-graph-node">
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={node.r}
                      fill={node.core ? "rgba(240,200,117,0.25)" : "rgba(34,201,214,0.12)"}
                      stroke={node.core ? "#F0C875" : "rgba(214,169,87,0.55)"}
                      strokeWidth={node.core ? 2 : 1}
                    />
                    <text
                      x={node.x}
                      y={node.y + node.r + 14}
                      textAnchor="middle"
                      className={`lv-graph-label${node.core ? " core" : ""}`}
                    >
                      {node.label}
                    </text>
                  </g>
                ))}
              </svg>
            </div>
          </article>

          <div className="lv-research-side-stack">
            <article className="lv-panel lv-card">
              <div className="lv-section-label">Recent Findings</div>
              <div className="lv-recent-list">
                {FINDINGS.map((item) => (
                  <button
                    key={item.title}
                    className="lv-recent-row lv-finding-row"
                    type="button"
                    onClick={() => toast(item.title)}
                  >
                    <span>
                      <strong>{item.title}</strong>
                      <small>{item.meta}</small>
                    </span>
                  </button>
                ))}
              </div>
            </article>

            <div className="lv-section-label">Quick Tools</div>
            <div className="lv-tools-grid-compact">
              {QUICK_TOOLS.map((tool) => (
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

            <article className="lv-panel lv-card lv-quote-card">
              <img src="/assets/bust-quote.jpg" alt="" width={56} height={40} />
              <p className="lv-footer-quote" style={{ textAlign: "left", margin: 0 }}>
                “The more you know, the further you see.” — LEVIATHAN
              </p>
            </article>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
