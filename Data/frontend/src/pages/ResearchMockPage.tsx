import { useState } from "react";
import { mediaPageArt, mediaPageHeroes } from "../assets/mediaPagesAssets";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import { PageHero, Panel, Pill } from "./media/mr-shared";

const ACTIONS = [
  { id: "web", title: "Web Research", desc: "Live crawl + synthesis" },
  { id: "academic", title: "Academic Search", desc: "Papers & citations" },
  { id: "data", title: "Data Analysis", desc: "Tables · stats · models" },
  { id: "knowledge", title: "Knowledge Synthesis", desc: "Vault → insight" },
] as const;

const INPUT_TABS = ["Query", "Files", "URLs", "Datasets", "Code", "Images"] as const;

const SOURCES = [
  "ArXiv",
  "PubMed",
  "Wikipedia",
  "News Wire",
  "SEC Filings",
  "GitHub",
  "Patents",
  "Internal Vault",
  "Datasets Hub",
] as const;

const MODES = [
  { id: "quick", title: "Quick", desc: "Fast answers · light sources" },
  { id: "deep", title: "Deep", desc: "Multi-hop · recommended", recommended: true },
  { id: "academic", title: "Academic", desc: "Peer-reviewed focus" },
  { id: "data", title: "Data", desc: "Numeric & tabular" },
  { id: "comparative", title: "Comparative", desc: "Side-by-side claims" },
  { id: "trend", title: "Trend", desc: "Temporal signals" },
] as const;

const ACTIVE = [
  { id: "a1", title: "Macro liquidity regime shift", progress: 78 },
  { id: "a2", title: "Neural edge briefing corpus", progress: 54 },
  { id: "a3", title: "Competitor content velocity", progress: 32 },
  { id: "a4", title: "Evidence hash reconciliation", progress: 91 },
] as const;

const FINDINGS = [
  { tag: "CLAIM", text: "Funding rates compressed 18% WoW across majors." },
  { tag: "PAPER", text: "ArXiv 2409.112 — residual stream routing improves recall." },
  { tag: "SIGNAL", text: "Creator posts mentioning ‘discipline’ +42% in 7d." },
] as const;

const TOOLS = [
  "Summarize",
  "Cite",
  "Compare",
  "Extract",
  "Map Graph",
  "Export",
] as const;

const GRAPH_NODES = [
  { label: "Liquidity", style: { top: "12%", left: "18%" } },
  { label: "Evidence", style: { top: "18%", right: "14%" } },
  { label: "Personas", style: { bottom: "16%", left: "12%" } },
  { label: "Markets", style: { bottom: "14%", right: "18%" } },
  { label: "Media", style: { top: "48%", left: "6%" } },
  { label: "Vault", style: { top: "46%", right: "8%" } },
] as const;

export function ResearchMockPage() {
  const toast = useAppToast();
  const [inputTab, setInputTab] = useState<(typeof INPUT_TABS)[number]>("Query");
  const [query, setQuery] = useState(
    "Map the relationship between creator discipline narratives and audience retention across YT/TT over the last 90 days.",
  );
  const [depth, setDepth] = useState("deep");
  const [scope, setScope] = useState("web-knowledge");
  const [mode, setMode] = useState<(typeof MODES)[number]["id"]>("deep");

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Search knowledge, papers, datasets, web..."
      systemItems={["SYSTEMS ONLINE", "AI", "TOOLS", "AGENTS", "SYNC"]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={mediaPageHeroes.research} title="RESEARCH" imageOnly />

        <section className="lv-rs-actions" aria-label="Research actions">
          {ACTIONS.map((action) => (
            <button
              key={action.id}
              type="button"
              className="lv-rs-action"
              onClick={() => toast(`${action.title} selected`)}
            >
              <span>
                <strong>{action.title}</strong>
                <small>{action.desc}</small>
              </span>
              <Pill tone="gold">→</Pill>
            </button>
          ))}
        </section>

        <section className="lv-rs-layout">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Panel title="Research Input">
              <div className="lv-mr-tabs" role="tablist">
                {INPUT_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    className={`lv-mr-tab${inputTab === tab ? " is-active" : ""}`}
                    onClick={() => setInputTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
              </div>
              <textarea
                className="lv-rs-textarea"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label={`${inputTab} input`}
                placeholder={`Enter ${inputTab.toLowerCase()}…`}
              />
              <div className="lv-mr-toolbar">
                <select
                  className="lv-mr-select"
                  value={depth}
                  onChange={(e) => setDepth(e.target.value)}
                  aria-label="Research depth"
                >
                  <option value="quick">Deep Research: Quick</option>
                  <option value="deep">Deep Research: Deep</option>
                  <option value="exhaustive">Deep Research: Exhaustive</option>
                </select>
                <select
                  className="lv-mr-select"
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                  aria-label="Source scope"
                >
                  <option value="web">Web</option>
                  <option value="knowledge">Knowledge</option>
                  <option value="web-knowledge">Web + Knowledge</option>
                </select>
                <button
                  type="button"
                  className="lv-mr-btn lv-mr-btn--gold"
                  onClick={() => toast("Research started")}
                >
                  Start Research
                </button>
              </div>
            </Panel>

            <Panel title="Knowledge Sources">
              <div className="lv-rs-sources">
                {SOURCES.map((src) => (
                  <button
                    key={src}
                    type="button"
                    className="lv-rs-source"
                    onClick={() => toast(`${src} toggled`)}
                  >
                    {src}
                  </button>
                ))}
              </div>
            </Panel>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Panel title="Research Modes">
              <div className="lv-rs-modes">
                {MODES.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    className={`lv-rs-mode${mode === m.id ? " is-active" : ""}`}
                    onClick={() => setMode(m.id)}
                  >
                    <strong>
                      {m.title}
                      {"recommended" in m && m.recommended ? (
                        <Pill tone="gold"> recommended</Pill>
                      ) : null}
                    </strong>
                    <small>{m.desc}</small>
                  </button>
                ))}
              </div>
            </Panel>

            <Panel title="Research Insights">
              <div className="lv-rs-graph" aria-label="HADES knowledge graph">
                {GRAPH_NODES.map((node) => (
                  <span key={node.label} className="lv-rs-node" style={node.style}>
                    {node.label}
                  </span>
                ))}
                <span className="lv-rs-node is-core">HADES</span>
              </div>
              <p className="lv-mr-muted" style={{ margin: 0, fontSize: 11 }}>
                Active mode · {MODES.find((m) => m.id === mode)?.title} · {scope.replace("-", " + ")}
              </p>
            </Panel>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Panel title="Active Research">
              {ACTIVE.map((item) => (
                <div key={item.id} className="lv-rs-active-item">
                  <span>{item.title}</span>
                  <span className="lv-rs-ring" style={{ borderTopColor: item.progress > 70 ? "#4ade80" : undefined }}>
                    {item.progress}%
                  </span>
                </div>
              ))}
            </Panel>

            <Panel title="Recent Findings">
              {FINDINGS.map((f) => (
                <div key={f.text} className="lv-rs-active-item">
                  <span>
                    <Pill tone="cyan">{f.tag}</Pill> {f.text}
                  </span>
                </div>
              ))}
            </Panel>

            <Panel title="Quick Tools">
              <div className="lv-rs-tools">
                {TOOLS.map((tool) => (
                  <button
                    key={tool}
                    type="button"
                    className="lv-rs-tool"
                    onClick={() => toast(`${tool} ready`)}
                  >
                    {tool}
                  </button>
                ))}
              </div>
            </Panel>

            <blockquote className="lv-rs-quote">
              <img src={mediaPageArt.researchBust} alt="" />
              <span>“Evidence first. Narrative second. Leviathan never invents mastery.”</span>
            </blockquote>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
