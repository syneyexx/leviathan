import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const TABS = ["Chat", "Code", "Research", "Analyze", "Create", "Plan", "Automate", "More"] as const;

const FEATURES = [
  {
    key: "research",
    title: "Deep Research",
    subtitle: "Analyze complex topics",
    icon: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3-3" />
      </>
    ),
  },
  {
    key: "build",
    title: "Build Anything",
    subtitle: "Generate & improve code",
    icon: <path d="M4 18V8l8-4 8 4v10l-8 4-8-4z" />,
  },
  {
    key: "analyze",
    title: "Data Analysis",
    subtitle: "Find insights in your data",
    icon: <path d="M5 19V9M12 19V5M19 19v-7" />,
  },
  {
    key: "create",
    title: "Create Content",
    subtitle: "Images, video, text & more",
    icon: <path d="M5 19l4-8 3 4 3-6 4 10" />,
  },
] as const;

const PROJECTS = [
  { title: "Trading AI", meta: "Updated 2h ago", image: "/assets/project-1.jpg" },
  { title: "Autonomous Agents", meta: "Updated 5h ago", image: "/assets/project-2.jpg" },
  { title: "Market Analysis", meta: "Updated 1d ago", image: "/assets/project-3.jpg" },
] as const;

const AGENTS = [
  {
    title: "Research Agent",
    meta: "Analyzing market trends…",
    tone: "blue",
    icon: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3-3" />
      </>
    ),
  },
  {
    title: "Code Agent",
    meta: "Working on optimization…",
    tone: "cyan",
    icon: (
      <>
        <path d="M8 7h8v10H8z" />
        <path d="M10 10h4M10 13h3" />
      </>
    ),
  },
  {
    title: "Trading Agent",
    meta: "Monitoring live feeds…",
    tone: "warn",
    icon: <path d="M5 19V9M12 19V5M19 19v-7" />,
  },
  {
    title: "Media Agent",
    meta: "Rendering assets…",
    tone: "gold",
    icon: <rect x="5" y="7" width="14" height="10" rx="2" />,
  },
] as const;

export function CommandPage() {
  const navigate = useNavigate();
  const toast = useAppToast();
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]>("Chat");
  const [prompt, setPrompt] = useState("");

  const sendToChat = () => {
    const text = prompt.trim();
    if (!text) {
      navigate("/chat");
      return;
    }
    navigate("/chat", { state: { draft: text } });
  };

  return (
    <AppShell activeMode="explore">
      <main className="lv-main">
        <section className="lv-hero">
          <div className="lv-hero-media">
            <img src="/assets/hero.jpg" alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <div className="lv-hero-kicker">
              <span />
              Welcome to
              <span />
            </div>
            <h1 className="lv-hero-title">Leviathan</h1>
            <p className="lv-hero-sub">“A mind that sees further”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Explore</span>
            <span>Build</span>
            <span>Automate</span>
            <span>Dominate</span>
          </div>
        </section>

        <section className="lv-command">
          <div className="lv-tabs" role="tablist">
            {TABS.map((tab) => (
              <button
                key={tab}
                className={`lv-tab${activeTab === tab ? " is-active" : ""}`}
                type="button"
                onClick={() => {
                  setActiveTab(tab);
                  if (tab === "Chat") return;
                  toast(tab);
                }}
              >
                {tab === "Chat" ? (
                  <>
                    <span className="lv-tab-dot" />
                    Chat
                    <svg className="lv-icon lv-tab-chev" viewBox="0 0 24 24">
                      <path d="M7 10l5 5 5-5" />
                    </svg>
                  </>
                ) : (
                  tab
                )}
              </button>
            ))}
          </div>

          <div className="lv-prompt">
            <button
              className="lv-prompt-attach"
              type="button"
              aria-label="Attach"
              onClick={() => toast("Attach")}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M8 12l6-6a3 3 0 114 4l-8 8a4.2 4.2 0 11-6-6l8-8" />
              </svg>
            </button>
            <textarea
              rows={1}
              placeholder="Ask Leviathan anything..."
              aria-label="Ask Leviathan"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  sendToChat();
                }
              }}
            />
            <button className="lv-auto" type="button" onClick={() => toast("Auto")}>
              Auto{" "}
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M7 10l5 5 5-5" />
              </svg>
            </button>
            <button
              className="lv-prompt-send lv-button-primary"
              type="button"
              aria-label="Send"
              onClick={sendToChat}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M5 12h12M13 6l6 6-6 6" />
              </svg>
            </button>
          </div>

          <div className="lv-feature-row">
            {FEATURES.map((feature) => (
              <button
                key={feature.key}
                className="lv-feature"
                type="button"
                onClick={() => toast(feature.title)}
              >
                <span className={`lv-feature-icon ${feature.key}`}>
                  <svg className="lv-icon" viewBox="0 0 24 24">
                    {feature.icon}
                  </svg>
                </span>
                <span className="lv-feature-copy">
                  <strong>{feature.title}</strong>
                  <small>{feature.subtitle}</small>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="lv-lower">
          <article className="lv-panel lv-card">
            <div className="lv-card-head">
              <div className="lv-section-label">Recent Projects</div>
              <button className="lv-link" type="button" onClick={() => toast("View all")}>
                View all →
              </button>
            </div>
            <div className="lv-project-list">
              {PROJECTS.map((project) => (
                <button
                  key={project.title}
                  className="lv-project-row"
                  type="button"
                  onClick={() => toast(project.title)}
                >
                  <img className="lv-thumb" src={project.image} alt="" />
                  <span>
                    <strong>{project.title}</strong>
                    <small>{project.meta}</small>
                  </span>
                  <svg className="lv-icon" viewBox="0 0 24 24">
                    <path d="M9 6l6 6-6 6" />
                  </svg>
                </button>
              ))}
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-card-head">
              <div className="lv-section-label">System Performance</div>
              <button className="lv-link" type="button" onClick={() => toast("View all")}>
                View all →
              </button>
            </div>
            <div className="lv-gauges">
              {[
                { label: "GPU", value: 34, tone: "cyan" },
                { label: "CPU", value: 12, tone: "cyan" },
                { label: "RAM", value: 28, tone: "cyan" },
                { label: "VRAM", value: 41, tone: "gold" },
              ].map((gauge) => (
                <div className="lv-gauge" key={gauge.label}>
                  <div className={`lv-ring ${gauge.tone}`} style={{ ["--p" as string]: gauge.value }}>
                    <b>{gauge.value}%</b>
                  </div>
                  <span>{gauge.label}</span>
                </div>
              ))}
            </div>
            <div className="lv-spark" aria-hidden="true">
              <svg viewBox="0 0 320 60" preserveAspectRatio="none">
                <defs>
                  <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22C9D6" stopOpacity="0.28" />
                    <stop offset="100%" stopColor="#22C9D6" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path
                  d="M0,42 L18,38 36,44 54,30 72,36 90,20 108,28 126,16 144,26 162,22 180,32 198,18 216,24 234,14 252,20 270,12 288,18 304,10 320,16 L320,60 L0,60 Z"
                  fill="url(#sparkFill)"
                />
                <polyline
                  fill="none"
                  stroke="#22C9D6"
                  strokeWidth="1.6"
                  points="0,42 18,38 36,44 54,30 72,36 90,20 108,28 126,16 144,26 162,22 180,32 198,18 216,24 234,14 252,20 270,12 288,18 304,10 320,16"
                />
              </svg>
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-card-head">
              <div className="lv-section-label">Active Agents</div>
              <span className="lv-online-count">
                <svg className="lv-icon" viewBox="0 0 24 24">
                  <path d="M5 12a7 7 0 0114 0" />
                  <path d="M8 12a4 4 0 018 0" />
                  <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
                </svg>
                12 online
              </span>
            </div>
            <div className="lv-agent-list">
              {AGENTS.map((agent) => (
                <button
                  key={agent.title}
                  className="lv-agent-row"
                  type="button"
                  onClick={() => toast(agent.title)}
                >
                  <span className={`lv-agent-icon ${agent.tone}`}>
                    <svg className="lv-icon" viewBox="0 0 24 24">
                      {agent.icon}
                    </svg>
                  </span>
                  <span>
                    <strong>{agent.title}</strong>
                    <small>{agent.meta}</small>
                  </span>
                  <span className="lv-status-online" />
                  <svg className="lv-icon" viewBox="0 0 24 24">
                    <path d="M9 6l6 6-6 6" />
                  </svg>
                </button>
              ))}
            </div>
          </article>
        </section>
      </main>

      <aside className="lv-right">
        <article className="lv-panel lv-panel-premium lv-world">
          <div className="lv-section-label">World View</div>
          <div className="lv-world-view">
            <img src="/assets/globe.jpg" alt="World activity globe" width={208} height={208} />
          </div>
          <div className="lv-world-stats">
            <div className="lv-world-stat">
              <span>Global Activity</span>
              <strong>Online</strong>
            </div>
            <div className="lv-world-stat">
              <span>Markets</span>
              <strong className="amber">Live</strong>
            </div>
            <div className="lv-world-stat">
              <span>AI Compute</span>
              <strong>Optimal</strong>
            </div>
            <div className="lv-world-stat">
              <span>Network</span>
              <strong>Online</strong>
            </div>
          </div>
        </article>

        <div className="lv-section-label">Quick Tools</div>
        <div className="lv-tools-grid">
          {[
            { label: "New Project", icon: <path d="M12 5v14M5 12h14" /> },
            { label: "Upload", icon: <path d="M12 16V5M8 9l4-4 4 4M5 19h14" /> },
            {
              label: "Web Search",
              icon: (
                <>
                  <circle cx="11" cy="11" r="7" />
                  <path d="M20 20l-3-3" />
                </>
              ),
            },
            {
              label: "Run Agent",
              icon: (
                <>
                  <circle cx="12" cy="8" r="3" />
                  <path d="M5 19c1.5-3 4-4.5 7-4.5S17.5 16 19 19" />
                </>
              ),
            },
          ].map((tool) => (
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

        <blockquote className="lv-quote">“The ocean remembers everything.”</blockquote>
      </aside>
    </AppShell>
  );
}
