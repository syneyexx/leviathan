import { useMemo, useState } from "react";
import { media } from "../assets/media";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const TABS = [
  "Overview",
  "Usage",
  "Model Performance",
  "Agent Activity",
  "System Resources",
  "Tasks & Tools",
  "Knowledge Growth",
  "Custom",
] as const;

const RANGES = ["24h", "7d", "30d", "90d", "1y"] as const;

const KPI = [
  { label: "Total Requests", value: "12,482", delta: "+18.4%", good: true },
  { label: "Avg. Response Time", value: "1.24s", delta: "-22.1%", good: true, down: true },
  { label: "Total Tokens", value: "4.8M", delta: "+36.7%", good: true },
  { label: "Active Agents", value: "6 / 10", delta: "+2", good: true },
  { label: "Tool Executions", value: "3,421", delta: "+28.3%", good: true },
] as const;

const REQUEST_VOLUME = [
  { day: "Sep 10", requests: 980, tokens: 620 },
  { day: "Sep 11", requests: 1240, tokens: 780 },
  { day: "Sep 12", requests: 1520, tokens: 940 },
  { day: "Sep 13", requests: 1180, tokens: 710 },
  { day: "Sep 14", requests: 1680, tokens: 1100 },
  { day: "Sep 15", requests: 1420, tokens: 880 },
  { day: "Sep 16", requests: 1860, tokens: 1280 },
  { day: "Sep 17", requests: 1602, tokens: 1020 },
] as const;

const RESPONSE_TIME = [2.4, 1.9, 2.8, 1.6, 1.35, 1.8, 1.1, 1.24] as const;

const RESOURCES = [
  { label: "CPU Usage", value: "32%", pct: 32 },
  { label: "Memory Usage", value: "6.8 / 32 GB", pct: 21 },
  { label: "VRAM Usage", value: "4.2 / 16 GB", pct: 26 },
  { label: "Disk Usage", value: "124 / 512 GB", pct: 24 },
] as const;

const MODEL_USAGE = [
  { name: "Qwen3-14B", pct: 38.2, color: "#22C9D6" },
  { name: "Llama3.1-8B", pct: 24.1, color: "#4285E8" },
  { name: "Hermes-3", pct: 18.6, color: "#D6A957" },
  { name: "Qwen2.5-7B", pct: 12.4, color: "#20DC8C" },
  { name: "Others", pct: 6.7, color: "#696964" },
] as const;

const AGENT_ACTIVITY = [
  { name: "Research", pct: 42 },
  { name: "Trading", pct: 28 },
  { name: "Analysis", pct: 18 },
  { name: "System", pct: 8 },
  { name: "Coding", pct: 6 },
  { name: "Others", pct: 4 },
] as const;

const TOOL_USAGE = [
  { name: "Web Search", count: "1,482", icon: "search" },
  { name: "File System", count: "892", icon: "folder" },
  { name: "Data Analysis", count: "641", icon: "chart" },
  { name: "Browser", count: "420", icon: "globe" },
  { name: "Code Execution", count: "318", icon: "code" },
  { name: "Knowledge Base", count: "276", icon: "book" },
] as const;

const TOKEN_SERIES = [1.8, 2.2, 2.9, 2.4, 3.6, 3.1, 4.4, 4.8] as const;
const COST_SERIES = [2.1, 3.4, 4.8, 3.2, 5.6, 4.9, 6.8, 5.4] as const;

const RECENT = [
  { time: "2m ago", text: "Research agent completed analysis", tone: "ok" },
  { time: "8m ago", text: "Model Qwen3-14B loaded into VRAM", tone: "info" },
  { time: "14m ago", text: "Tool Web Search executed (142ms)", tone: "ok" },
  { time: "21m ago", text: "Trading agent paused — approval pending", tone: "warn" },
  { time: "36m ago", text: "Knowledge index rebuilt (+128 docs)", tone: "ok" },
] as const;

const TOP_CHATS = [
  { title: "Trading strategy analysis", messages: 482 },
  { title: "HADES architecture review", messages: 313 },
  { title: "Market regime classification", messages: 268 },
  { title: "Agent tool-routing design", messages: 214 },
  { title: "Neuro residual calibration", messages: 187 },
] as const;

function ToolIcon({ kind }: { kind: string }) {
  switch (kind) {
    case "search":
      return (
        <>
          <circle cx="11" cy="11" r="6" />
          <path d="M16 16l4 4" />
        </>
      );
    case "folder":
      return (
        <>
          <path d="M4 9h16v9H4z" />
          <path d="M4 9l1.6-2.8h5L12 9" />
        </>
      );
    case "chart":
      return <path d="M5 19V10M12 19V6M19 19v-5" />;
    case "globe":
      return (
        <>
          <circle cx="12" cy="12" r="8" />
          <path d="M4 12h16M12 4c2.5 2.8 2.5 13.2 0 16M12 4c-2.5 2.8-2.5 13.2 0 16" />
        </>
      );
    case "code":
      return <path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13 6l-2 12" />;
    default:
      return <path d="M7 5h10v14H7zM9 8h6M9 12h6M9 16h4" />;
  }
}

function Donut({
  segments,
  center,
  sub,
}: {
  segments: readonly { pct: number; color: string }[];
  center: string;
  sub: string;
}) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const arcs = segments.reduce<Array<{ color: string; len: number; offset: number }>>((acc, seg) => {
    const len = (seg.pct / 100) * c;
    const offset = acc.reduce((sum, item) => sum + item.len, 0);
    acc.push({ color: seg.color, len, offset });
    return acc;
  }, []);
  return (
    <svg className="lv-an-donut" viewBox="0 0 120 120" aria-hidden="true">
      <circle cx="60" cy="60" r={r} fill="none" stroke="rgba(214,169,87,0.12)" strokeWidth="12" />
      {arcs.map((arc, i) => (
        <circle
          key={i}
          cx="60"
          cy="60"
          r={r}
          fill="none"
          stroke={arc.color}
          strokeWidth="12"
          strokeDasharray={`${arc.len} ${c - arc.len}`}
          strokeDashoffset={-arc.offset}
          strokeLinecap="butt"
          transform="rotate(-90 60 60)"
        />
      ))}
      <text x="60" y="56" textAnchor="middle" className="lv-an-donut-value">
        {center}
      </text>
      <text x="60" y="72" textAnchor="middle" className="lv-an-donut-sub">
        {sub}
      </text>
    </svg>
  );
}

function SuccessRing({ value }: { value: number }) {
  const r = 28;
  const c = 2 * Math.PI * r;
  const len = (value / 100) * c;
  return (
    <svg className="lv-an-success-ring" viewBox="0 0 72 72" aria-hidden="true">
      <circle cx="36" cy="36" r={r} fill="none" stroke="rgba(34,201,214,0.15)" strokeWidth="6" />
      <circle
        cx="36"
        cy="36"
        r={r}
        fill="none"
        stroke="#22C9D6"
        strokeWidth="6"
        strokeDasharray={`${len} ${c - len}`}
        strokeLinecap="round"
        transform="rotate(-90 36 36)"
        filter="drop-shadow(0 0 6px rgba(34,201,214,0.55))"
      />
      <text x="36" y="39" textAnchor="middle" className="lv-an-success-text">
        {value.toFixed(1)}%
      </text>
    </svg>
  );
}

export function AnalyticsPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [range, setRange] = useState<(typeof RANGES)[number]>("7d");

  const maxReq = useMemo(() => Math.max(...REQUEST_VOLUME.map((d) => d.requests)), []);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Analytics Mode"
      searchPlaceholder="Search analytics, metrics, performance, usage..."
      layout="wide"
      pageClass="lv-app--analytics"
    >
      <main className="lv-main lv-an-main">
        <section className="lv-an-hero" aria-label="Analytics">
          <img src={media.analyticsHero} alt="" width={1400} height={220} />
        </section>

        <div className="lv-an-controls">
          <div className="lv-an-tabs" role="tablist" aria-label="Analytics sections">
            {TABS.map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={tab === item}
                className={`lv-an-tab${tab === item ? " is-active" : ""}`}
                onClick={() => {
                  setTab(item);
                  if (item !== "Overview") toast(item);
                }}
              >
                {item}
              </button>
            ))}
          </div>
          <div className="lv-an-ranges">
            {RANGES.map((item) => (
              <button
                key={item}
                type="button"
                className={`lv-an-range${range === item ? " is-active" : ""}`}
                onClick={() => setRange(item)}
              >
                {item}
              </button>
            ))}
            <button type="button" className="lv-an-date" onClick={() => toast("Date range")}>
              <svg className="lv-icon" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="4" y="5" width="16" height="15" rx="2" />
                <path d="M8 3v4M16 3v4M4 10h16" />
              </svg>
              <span>Sep 10, 2026 – Sep 17, 2026</span>
              <svg className="lv-icon lv-an-chev" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M7 10l5 5 5-5" />
              </svg>
            </button>
          </div>
        </div>

        <section className="lv-an-kpi-row">
          {KPI.map((item) => (
            <article key={item.label} className="lv-an-kpi">
              <div className="lv-an-kpi-label">{item.label}</div>
              <div className="lv-an-kpi-value">{item.value}</div>
              <div className={`lv-an-kpi-delta${item.good ? " is-good" : ""}`}>
                <span aria-hidden="true">{"down" in item && item.down ? "↓" : "↑"}</span>
                {item.delta}
              </div>
            </article>
          ))}
          <article className="lv-an-kpi lv-an-kpi--success">
            <div>
              <div className="lv-an-kpi-label">Success Rate</div>
              <div className="lv-an-kpi-value">98.7%</div>
              <div className="lv-an-kpi-delta is-good">
                <span aria-hidden="true">↑</span>+0.9%
              </div>
            </div>
            <SuccessRing value={98.7} />
          </article>
        </section>

        <section className="lv-an-mid">
          <article className="lv-panel lv-an-card lv-an-card--volume">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Request Volume</div>
              <div className="lv-an-legend">
                <span>
                  <i className="lv-an-swatch cyan" />
                  Requests
                </span>
                <span>
                  <i className="lv-an-swatch gold" />
                  Tokens
                </span>
              </div>
            </div>
            <div className="lv-an-chart">
              <svg viewBox="0 0 520 180" className="lv-an-svg" role="img" aria-label="Request volume chart">
                {[0, 1, 2, 3, 4].map((i) => (
                  <line
                    key={i}
                    x1="36"
                    x2="508"
                    y1={20 + i * 32}
                    y2={20 + i * 32}
                    stroke="rgba(214,169,87,0.1)"
                    strokeWidth="1"
                  />
                ))}
                {REQUEST_VOLUME.map((d, i) => {
                  const x = 52 + i * 58;
                  const hReq = (d.requests / maxReq) * 120;
                  const hTok = (d.tokens / maxReq) * 120;
                  return (
                    <g key={d.day}>
                      <rect x={x} y={148 - hReq} width="16" height={hReq} rx="3" fill="#22C9D6" opacity="0.92" />
                      <rect x={x + 20} y={148 - hTok} width="16" height={hTok} rx="3" fill="#D6A957" opacity="0.75" />
                      <text x={x + 18} y="168" textAnchor="middle" className="lv-an-axis">
                        {d.day.replace("Sep ", "")}
                      </text>
                    </g>
                  );
                })}
                <text x="28" y="28" textAnchor="end" className="lv-an-axis">
                  2K
                </text>
                <text x="28" y="92" textAnchor="end" className="lv-an-axis">
                  1K
                </text>
                <text x="28" y="152" textAnchor="end" className="lv-an-axis">
                  0
                </text>
              </svg>
            </div>
          </article>

          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Response Time</div>
            </div>
            <div className="lv-an-chart">
              <svg viewBox="0 0 280 180" className="lv-an-svg" role="img" aria-label="Response time chart">
                {[0, 1, 2, 3, 4].map((i) => (
                  <line
                    key={i}
                    x1="28"
                    x2="268"
                    y1={24 + i * 30}
                    y2={24 + i * 30}
                    stroke="rgba(214,169,87,0.1)"
                    strokeWidth="1"
                  />
                ))}
                <polyline
                  fill="none"
                  stroke="#22C9D6"
                  strokeWidth="2"
                  points={RESPONSE_TIME.map((v, i) => {
                    const x = 40 + i * 30;
                    const y = 144 - (v / 4) * 110;
                    return `${x},${y}`;
                  }).join(" ")}
                />
                {RESPONSE_TIME.map((v, i) => {
                  const x = 40 + i * 30;
                  const y = 144 - (v / 4) * 110;
                  return <circle key={i} cx={x} cy={y} r="3.2" fill="#0a0c0b" stroke="#22C9D6" strokeWidth="1.6" />;
                })}
                <text x="20" y="28" textAnchor="end" className="lv-an-axis">
                  4s
                </text>
                <text x="20" y="148" textAnchor="end" className="lv-an-axis">
                  0s
                </text>
              </svg>
            </div>
          </article>

          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">System Resources</div>
            </div>
            <div className="lv-an-resources">
              {RESOURCES.map((item) => (
                <div key={item.label} className="lv-an-resource">
                  <div className="lv-an-resource-meta">
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </div>
                  <div className="lv-an-bar">
                    <span style={{ width: `${item.pct}%` }} />
                  </div>
                </div>
              ))}
              <div className="lv-an-network">
                <div className="lv-an-resource-meta">
                  <span>Network</span>
                  <strong>12.4 ↑ / 3.1 ↓ MB/s</strong>
                </div>
                <svg viewBox="0 0 200 28" className="lv-an-spark" aria-hidden="true">
                  <polyline
                    fill="none"
                    stroke="#22C9D6"
                    strokeWidth="1.5"
                    points="0,20 20,16 40,18 60,10 80,14 100,8 120,12 140,6 160,11 180,7 200,9"
                  />
                </svg>
              </div>
            </div>
          </article>
        </section>

        <section className="lv-an-lower">
          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Model Usage</div>
            </div>
            <div className="lv-an-model-usage">
              <Donut segments={MODEL_USAGE} center="4.8M" sub="Tokens" />
              <ul className="lv-an-legend-list">
                {MODEL_USAGE.map((m) => (
                  <li key={m.name}>
                    <i style={{ background: m.color }} />
                    <span>{m.name}</span>
                    <strong>{m.pct}%</strong>
                  </li>
                ))}
              </ul>
            </div>
          </article>

          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Agent Activity</div>
            </div>
            <div className="lv-an-agent-bars">
              {AGENT_ACTIVITY.map((item) => (
                <div key={item.name} className="lv-an-agent-row">
                  <span>{item.name}</span>
                  <div className="lv-an-bar">
                    <span style={{ width: `${item.pct}%` }} />
                  </div>
                  <strong>{item.pct}%</strong>
                </div>
              ))}
            </div>
          </article>

          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Tool Usage</div>
            </div>
            <ul className="lv-an-tool-list">
              {TOOL_USAGE.map((item) => (
                <li key={item.name}>
                  <span className="lv-an-tool-icon">
                    <svg className="lv-icon" viewBox="0 0 24 24">
                      <ToolIcon kind={item.icon} />
                    </svg>
                  </span>
                  <span>{item.name}</span>
                  <strong>{item.count}</strong>
                </li>
              ))}
            </ul>
          </article>

          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Recent Activity</div>
            </div>
            <ul className="lv-an-activity">
              {RECENT.map((item) => (
                <li key={item.time + item.text}>
                  <span className={`lv-an-dot ${item.tone}`} />
                  <div>
                    <strong>{item.text}</strong>
                    <small>{item.time}</small>
                  </div>
                </li>
              ))}
            </ul>
          </article>
        </section>

        <section className="lv-an-bottom">
          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Token Usage Over Time</div>
            </div>
            <div className="lv-an-chart">
              <svg viewBox="0 0 420 140" className="lv-an-svg" role="img" aria-label="Token usage over time">
                <defs>
                  <linearGradient id="tokFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22C9D6" stopOpacity="0.45" />
                    <stop offset="100%" stopColor="#22C9D6" stopOpacity="0.02" />
                  </linearGradient>
                </defs>
                <path
                  d={`M28,${120 - (TOKEN_SERIES[0] / 5) * 90} ${TOKEN_SERIES.map((v, i) => {
                    const x = 28 + i * 52;
                    const y = 120 - (v / 5) * 90;
                    return `L${x},${y}`;
                  }).join(" ")} L${28 + 7 * 52},128 L28,128 Z`}
                  fill="url(#tokFill)"
                />
                <polyline
                  fill="none"
                  stroke="#22C9D6"
                  strokeWidth="2"
                  points={TOKEN_SERIES.map((v, i) => `${28 + i * 52},${120 - (v / 5) * 90}`).join(" ")}
                />
              </svg>
            </div>
          </article>

          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Cost Estimation</div>
            </div>
            <div className="lv-an-chart">
              <svg viewBox="0 0 320 140" className="lv-an-svg" role="img" aria-label="Daily cost estimation">
                {COST_SERIES.map((v, i) => {
                  const h = (v / 8) * 100;
                  const x = 28 + i * 36;
                  return (
                    <rect key={i} x={x} y={118 - h} width="22" height={h} rx="3" fill="#20DC8C" opacity="0.85" />
                  );
                })}
                <text x="16" y="24" className="lv-an-axis">
                  $8
                </text>
                <text x="16" y="120" className="lv-an-axis">
                  $0
                </text>
              </svg>
            </div>
          </article>

          <article className="lv-panel lv-an-card">
            <div className="lv-an-card-head">
              <div className="lv-section-label">Top Conversations</div>
            </div>
            <ul className="lv-an-top-chats">
              {TOP_CHATS.map((item) => (
                <li key={item.title}>
                  <button type="button" onClick={() => toast(item.title)}>
                    <span>{item.title}</span>
                    <strong>{item.messages}</strong>
                  </button>
                </li>
              ))}
            </ul>
          </article>
        </section>

        <p className="lv-footer-quote">“What gets measured, gets mastered.” — LEVIATHAN</p>
      </main>
    </AppShell>
  );
}
