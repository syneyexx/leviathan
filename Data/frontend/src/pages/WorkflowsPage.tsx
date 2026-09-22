import { useState } from "react";
import { tradingHeroes } from "../assets/tradingAssets";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import { Panel, TradingHero } from "./trading/shared";

const FILTERS = ["All", "Active", "Drafts", "Templates", "Shared", "Favourites"] as const;

const TRIGGERS = [
  { id: "manual", name: "Manual Trigger", cat: "System", color: "#22c9d6", icon: "M" },
  { id: "schedule", name: "Schedule Trigger", cat: "Schedule", color: "#a78bfa", icon: "S" },
  { id: "webhook", name: "Webhook Trigger", cat: "Data", color: "#34d399", icon: "W" },
  { id: "market", name: "Market Event", cat: "Trading", color: "#fbbf24", icon: "Δ" },
  { id: "agent", name: "Agent Completion", cat: "Agents", color: "#67e8f9", icon: "A" },
  { id: "file", name: "File Ingested", cat: "Data", color: "#f472b6", icon: "F" },
  { id: "alert", name: "Risk Alert", cat: "Risk", color: "#f87171", icon: "!" },
  { id: "chat", name: "Chat Intent", cat: "System", color: "#94a3b8", icon: "C" },
] as const;

const RUNS = [
  { status: "Success", workflow: "Customer Research Pipeline", trigger: "Webhook", duration: "2m 14s", when: "2 min ago" },
  { status: "Success", workflow: "Daily Research Digest", trigger: "Schedule", duration: "48s", when: "1h ago" },
  { status: "Failed", workflow: "Content Pipeline", trigger: "Manual", duration: "12s", when: "3h ago" },
  { status: "Success", workflow: "Risk Alert Relay", trigger: "Risk Alert", duration: "6s", when: "5h ago" },
  { status: "Success", workflow: "Weekly Intelligence Report", trigger: "Schedule", duration: "4m 02s", when: "1d ago" },
] as const;

const TEMPLATES = [
  { name: "Research Assistant", desc: "Query → LLM → Vault" },
  { name: "Content Pipeline", desc: "Brief → Draft → Publish" },
  { name: "Market Alert Chain", desc: "Signal → Validate → Notify" },
  { name: "Agent Handoff", desc: "Plan → Delegate → Review" },
  { name: "Knowledge Sync", desc: "Ingest → Chunk → Embed" },
] as const;

const SCHEDULE = [
  { name: "Daily Research Digest", when: "Every day · 07:00 UTC", on: true },
  { name: "Weekly Intelligence Report", when: "Mon · 09:00 UTC", on: true },
  { name: "Portfolio Risk Sweep", when: "Weekdays · 16:30 UTC", on: true },
  { name: "Model Health Ping", when: "Every 15 min", on: false },
] as const;

const VERSIONS = [
  { ver: "v1.4.0", note: "Added Slack notification branch", when: "2h ago" },
  { ver: "v1.3.2", note: "Temperature default 0.3", when: "Yesterday" },
  { ver: "v1.3.1", note: "Webhook auth header fix", when: "Apr 18" },
  { ver: "v1.3.0", note: "Vector store write step", when: "Apr 12" },
  { ver: "v1.2.4", note: "Initial deploy to production", when: "Apr 02" },
] as const;

type NodeId = "trigger" | "processor" | "llm" | "store" | "report" | "notify";

export function WorkflowsPage() {
  const toast = useAppToast();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  const [selectedTrigger, setSelectedTrigger] = useState("webhook");
  const [activeNode, setActiveNode] = useState<NodeId>("llm");
  const [enabled, setEnabled] = useState(true);
  const [temperature, setTemperature] = useState(0.3);
  const [maxTokens, setMaxTokens] = useState(4000);
  const [schedOn, setSchedOn] = useState(() => Object.fromEntries(SCHEDULE.map((s) => [s.name, s.on])));

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Workflows Mode"
      searchPlaceholder="Search workflows, triggers, actions, templates..."
      systemItems={["SYSTEMS OPERATIONAL", "LLM", "Neural", "Memory", "Tools"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="WORKFLOWS"
          kicker="DESIGN. AUTOMATE. ORCHESTRATE."
          quote="“Turn complex ideas into effortless execution.” — LEVIATHAN"
          image={tradingHeroes.workflows}
          rails={["AUTOMATE", "AMPLIFY", "ORCHESTRATE", "SCALE", "BEYOND"]}
          objectPosition="center 35%"
        />
        <section className="lv-wf-toolbar" aria-label="Workflow filters">
          <select className="lv-tp-select" style={{ width: 140 }} defaultValue="My Workflows">
            <option>My Workflows</option>
            <option>Team Shared</option>
            <option>Archived</option>
          </select>
          <div className="lv-tp-tabs">
            {FILTERS.map((f) => (
              <button key={f} type="button" className={`lv-tp-chip${filter === f ? " is-active" : ""}`} onClick={() => setFilter(f)}>
                {f}
              </button>
            ))}
          </div>
          <input className="lv-tp-input grow" type="search" placeholder="Search workflows..." />
          <button type="button" className="lv-tp-btn lv-tp-btn--gold" onClick={() => toast("New workflow")}>
            + New Workflow
          </button>
        </section>

        <section className="lv-wf-workspace">
          <Panel title="Trigger Library">
            <input className="lv-tp-input" type="search" placeholder="Search triggers..." style={{ marginBottom: 8 }} />
            <div className="lv-wf-trigger-list">
              {TRIGGERS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`lv-wf-trigger${selectedTrigger === t.id ? " is-active" : ""}`}
                  onClick={() => setSelectedTrigger(t.id)}
                >
                  <span className="ico" style={{ background: `${t.color}22`, color: t.color, border: `1px solid ${t.color}55` }}>
                    {t.icon}
                  </span>
                  <span>
                    <strong>{t.name}</strong>
                    <span>{t.cat}</span>
                  </span>
                </button>
              ))}
            </div>
          </Panel>

          <Panel>
            <div className="lv-wf-canvas-head">
              <div>
                <h2>Customer Research Pipeline</h2>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                  <span className="lv-tp-pill is-live">Active</span>
                  <span className="lv-tp-muted">Last saved 2 minutes ago</span>
                </div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button type="button" className="lv-tp-btn" onClick={() => toast("Saved")}>
                  Save
                </button>
                <button type="button" className="lv-tp-btn lv-tp-btn--accent" onClick={() => toast("Test run")}>
                  Test Run
                </button>
                <button type="button" className="lv-tp-btn lv-tp-btn--gold" onClick={() => toast("Deployed")}>
                  Deploy
                </button>
              </div>
            </div>

            <div className="lv-wf-canvas">
              <div className="lv-wf-zoom">
                {["+", "−", "🔒", "▣"].map((icon) => (
                  <button key={icon} type="button" onClick={() => toast("Canvas control")} aria-label="Zoom control">
                    {icon}
                  </button>
                ))}
              </div>

              <div className="lv-wf-flow">
                <button
                  type="button"
                  className={`lv-wf-node is-trigger${activeNode === "trigger" ? " is-active" : ""}`}
                  onClick={() => setActiveNode("trigger")}
                >
                  <div className="top">
                    <strong>Trigger</strong>
                    <span className="dot" />
                  </div>
                  <small>Webhook</small>
                </button>
                <div className="lv-wf-link" />
                <button
                  type="button"
                  className={`lv-wf-node${activeNode === "processor" ? " is-active" : ""}`}
                  onClick={() => setActiveNode("processor")}
                >
                  <div className="top">
                    <strong>Data Processor</strong>
                    <span className="dot" />
                  </div>
                  <small>Clean &amp; Extract</small>
                </button>
                <div className="lv-wf-link" />
                <div className="lv-wf-branch">
                  <div className="lv-wf-col">
                    <button
                      type="button"
                      className={`lv-wf-node is-ai${activeNode === "llm" ? " is-active" : ""}`}
                      onClick={() => setActiveNode("llm")}
                    >
                      <div className="top">
                        <strong>LLM Analysis</strong>
                        <span className="dot" />
                      </div>
                      <small>Research &amp; Summarize</small>
                    </button>
                    <div className="lv-wf-link" />
                    <button
                      type="button"
                      className={`lv-wf-node is-store${activeNode === "store" ? " is-active" : ""}`}
                      onClick={() => setActiveNode("store")}
                    >
                      <div className="top">
                        <strong>Store Results</strong>
                        <span className="dot" />
                      </div>
                      <small>Vector Database</small>
                    </button>
                  </div>
                  <div className="lv-wf-col">
                    <button
                      type="button"
                      className={`lv-wf-node${activeNode === "report" ? " is-active" : ""}`}
                      onClick={() => setActiveNode("report")}
                    >
                      <div className="top">
                        <strong>Generate Report</strong>
                        <span className="dot" />
                      </div>
                      <small>Create Document</small>
                    </button>
                    <div className="lv-wf-link" />
                    <button
                      type="button"
                      className={`lv-wf-node is-notify${activeNode === "notify" ? " is-active" : ""}`}
                      onClick={() => setActiveNode("notify")}
                    >
                      <div className="top">
                        <strong>Send Notification</strong>
                        <span className="dot" />
                      </div>
                      <small>Email / Slack</small>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </Panel>

          <Panel title="Step Inspector" className="lv-wf-inspector">
            <div className="lv-wf-inspector-head">
              <strong style={{ color: "var(--lv-text-bright)" }}>
                {activeNode === "llm"
                  ? "LLM Analysis"
                  : activeNode === "trigger"
                    ? "Webhook Trigger"
                    : activeNode === "processor"
                      ? "Data Processor"
                      : activeNode === "store"
                        ? "Store Results"
                        : activeNode === "report"
                          ? "Generate Report"
                          : "Send Notification"}
              </strong>
              <label className="lv-wf-toggle">
                <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
                Enabled
              </label>
            </div>

            <div className="lv-tp-field">
              <label htmlFor="wf-model">Model</label>
              <select id="wf-model" className="lv-tp-select" defaultValue="Claude 3.5 Sonnet">
                <option>Claude 3.5 Sonnet</option>
                <option>GPT-4o</option>
                <option>Leviathan Core</option>
              </select>
            </div>

            <div className="lv-tp-field">
              <label htmlFor="wf-prompt">Prompt Template</label>
              <textarea
                id="wf-prompt"
                className="lv-tp-textarea"
                defaultValue={"Analyze the inbound research payload.\nExtract entities, thesis, and risks.\nReturn structured JSON for vault storage."}
              />
            </div>

            <div className="lv-tp-field">
              <label htmlFor="wf-temp">
                Temperature · {temperature.toFixed(1)}
              </label>
              <input
                id="wf-temp"
                className="lv-tp-slider"
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value))}
              />
            </div>

            <div className="lv-tp-field">
              <label htmlFor="wf-tokens">Max Tokens · {maxTokens.toLocaleString()}</label>
              <input
                id="wf-tokens"
                className="lv-tp-slider"
                type="range"
                min={500}
                max={8000}
                step={100}
                value={maxTokens}
                onChange={(e) => setMaxTokens(Number(e.target.value))}
              />
            </div>

            <details className="lv-wf-collapse" open>
              <summary>Input Variables</summary>
              <p>payload.body · payload.headers · context.user · memory.session</p>
            </details>
            <details className="lv-wf-collapse">
              <summary>Output</summary>
              <p>analysis.summary · analysis.entities · analysis.risk_score · analysis.citations</p>
            </details>
            <details className="lv-wf-collapse">
              <summary>Error Handling</summary>
              <p>Retry 3× with backoff · on failure notify Slack #ops · quarantine payload</p>
            </details>
          </Panel>
        </section>

        <section className="lv-wf-bottom">
          <Panel title="Run History">
            <table className="lv-tp-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Workflow</th>
                  <th>Trigger</th>
                  <th>Duration</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {RUNS.map((r) => (
                  <tr key={r.when + r.workflow}>
                    <td>
                      <span className={`lv-tp-pill${r.status === "Success" ? " is-live" : " is-bad"}`}>{r.status}</span>
                    </td>
                    <td>{r.workflow}</td>
                    <td>{r.trigger}</td>
                    <td>{r.duration}</td>
                    <td>{r.when}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Workflow Templates">
            {TEMPLATES.map((t) => (
              <div key={t.name} className="lv-wf-template">
                <div>
                  <strong style={{ color: "var(--lv-text-bright)" }}>{t.name}</strong>
                  <div className="lv-tp-muted">{t.desc}</div>
                </div>
                <button type="button" className="lv-tp-btn" onClick={() => toast(`Use ${t.name}`)}>
                  Use
                </button>
              </div>
            ))}
          </Panel>

          <Panel title="Scheduler">
            {SCHEDULE.map((s) => (
              <div key={s.name} className="lv-wf-schedule">
                <strong>{s.name}</strong>
                <label className="lv-wf-toggle">
                  <input
                    type="checkbox"
                    checked={!!schedOn[s.name]}
                    onChange={(e) => setSchedOn((prev) => ({ ...prev, [s.name]: e.target.checked }))}
                  />
                </label>
                <span className="lv-tp-muted">{s.when}</span>
                <span />
              </div>
            ))}
          </Panel>

          <Panel title="Versions">
            {VERSIONS.map((v) => (
              <div key={v.ver} className="lv-wf-version">
                <strong>{v.ver}</strong>
                <div>
                  <div>{v.note}</div>
                  <div className="lv-tp-muted">{v.when}</div>
                </div>
              </div>
            ))}
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
