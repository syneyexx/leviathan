import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { media } from "../assets/media";
import { sparklinePath, useSystemTelemetry } from "../hooks/useSystemTelemetry";
import { AppShell } from "../layouts/AppShell";
import type { CodingStatusResponse, Conversation, HealthResponse } from "../types/api";

const FEATURES = [
  {
    key: "research",
    title: "Deep Research",
    subtitle: "Analyze complex topics",
    to: "/research",
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
    to: "/coding",
    icon: <path d="M4 18V8l8-4 8 4v10l-8 4-8-4z" />,
  },
  {
    key: "analyze",
    title: "Data Analysis",
    subtitle: "Explore datasets",
    to: "/datasets",
    icon: <path d="M5 19V9M12 19V5M19 19v-7" />,
  },
  {
    key: "create",
    title: "Chat / Plan",
    subtitle: "Start a conversation",
    to: "/chat",
    icon: <path d="M5 19l4-8 3 4 3-6 4 10" />,
  },
] as const;

type AgentRow = {
  title: string;
  meta: string;
  tone: string;
  statusLabel: string;
  online: boolean | null;
  to: string;
  icon: ReactNode;
};

function formatRelative(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function gaugeDisplay(value: number | null | undefined, available: boolean): string {
  if (!available || value == null || !Number.isFinite(value)) return "N/A";
  return `${Math.round(value)}%`;
}

export function CommandPage() {
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [codingStatus, setCodingStatus] = useState<CodingStatusResponse | null>(null);
  const { sample, error: telemetryError, history } = useSystemTelemetry({ enabled: true });

  const loadConversations = useCallback(async () => {
    try {
      const data = await api.listConversations({ limit: 5 });
      setConversations(data.conversations.slice(0, 5));
      setConversationsError(null);
    } catch (err) {
      setConversations([]);
      setConversationsError(err instanceof Error ? err.message : "Unavailable");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((value) => {
        if (!cancelled) setHealth(value);
      })
      .catch(() => {
        if (!cancelled) setHealth(null);
      });
    api
      .codingStatus()
      .then((value) => {
        if (!cancelled) setCodingStatus(value);
      })
      .catch(() => {
        if (!cancelled) setCodingStatus(null);
      });
    void loadConversations();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadConversations();
    }, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [loadConversations]);

  const sendToChat = () => {
    const text = prompt.trim();
    if (!text) {
      navigate("/chat");
      return;
    }
    navigate("/chat", { state: { draft: text } });
  };

  const agentsEnabled = Boolean(health?.agents?.enabled);
  const codingEnabled = Boolean(codingStatus?.enabled && codingStatus?.agents_enabled);
  const llmLabel = health?.llm.available ? health.llm.model ?? "Ready" : "Offline";
  const pendingApprovals = health?.approvals?.pending ?? 0;

  const agents: AgentRow[] = [
    {
      title: "Research Agent",
      meta: agentsEnabled ? "Agents runtime enabled" : "Agents runtime disabled",
      tone: "blue",
      statusLabel: agentsEnabled ? "Enabled" : "Disabled",
      online: agentsEnabled,
      to: "/agents",
      icon: (
        <>
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3-3" />
        </>
      ),
    },
    {
      title: "Coding Agent",
      meta: codingStatus
        ? codingEnabled
          ? "Coding control plane ready"
          : "Coding feature disabled"
        : "Coding status unknown",
      tone: "cyan",
      statusLabel: codingStatus == null ? "Unknown" : codingEnabled ? "Enabled" : "Disabled",
      online: codingStatus == null ? null : codingEnabled,
      to: "/coding",
      icon: (
        <>
          <path d="M8 7h8v10H8z" />
          <path d="M10 10h4M10 13h3" />
        </>
      ),
    },
    {
      title: "LLM Gateway",
      meta: health?.llm.available
        ? health.llm.model ?? "Model ready"
        : health?.llm.error ?? "LLM unavailable",
      tone: "warn",
      statusLabel: health?.llm.available ? "Ready" : "Unavailable",
      online: health ? Boolean(health.llm.available) : null,
      to: "/models",
      icon: <path d="M5 19V9M12 19V5M19 19v-7" />,
    },
    {
      title: "Approvals",
      meta: `${pendingApprovals} pending`,
      tone: "gold",
      statusLabel: health ? "Measured" : "Unknown",
      online: health ? true : null,
      to: "/status",
      icon: <rect x="5" y="7" width="14" height="10" rx="2" />,
    },
  ];

  const dash = sample?.dashboard;
  const gauges = [
    {
      label: "GPU",
      value: dash?.gpuPct ?? null,
      available: Boolean(sample?.gpu.available && dash?.gpuPct != null),
      tone: "cyan",
    },
    {
      label: "CPU",
      value: dash?.cpuPct ?? null,
      available: Boolean(sample?.cpu.available && dash?.cpuPct != null),
      tone: "cyan",
    },
    {
      label: "RAM",
      value: dash?.ramPct ?? null,
      available: Boolean(sample?.memory.available && dash?.ramPct != null),
      tone: "cyan",
    },
    {
      label: "VRAM",
      value: dash?.vramPct ?? null,
      available: Boolean(sample?.gpu.available && dash?.vramPct != null),
      tone: "gold",
    },
  ] as const;

  const spark = sparklinePath(history, "cpuPct");
  const stale =
    sample?.ageMs != null && sample.ageMs > 5000
      ? ` · stale ${Math.round(sample.ageMs / 1000)}s`
      : "";

  return (
    <AppShell activeMode="explore">
      <main className="lv-main">
        <section className="lv-hero">
          <div className="lv-hero-media">
            <img src={media.hero} alt="" width={1400} height={380} />
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
          <div className="lv-prompt">
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
                onClick={() => navigate(feature.to)}
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
              <div className="lv-section-label">Laatste gesprekken</div>
              <button className="lv-link" type="button" onClick={() => navigate("/chat")}>
                View all →
              </button>
            </div>
            <div className="lv-project-list">
              {conversationsError ? (
                <div className="lv-chat-empty" style={{ padding: "12px 4px" }}>
                  <strong>Conversations unavailable</strong>
                  <span>{conversationsError}</span>
                </div>
              ) : conversations.length === 0 ? (
                <div className="lv-chat-empty" style={{ padding: "12px 4px" }}>
                  <strong>Nog geen gesprekken</strong>
                  <span>Start een nieuw gesprek</span>
                  <button
                    className="lv-link"
                    type="button"
                    style={{ marginTop: 8 }}
                    onClick={() => navigate("/chat")}
                  >
                    Nieuw gesprek →
                  </button>
                </div>
              ) : (
                conversations.map((conversation) => (
                  <button
                    key={conversation.id}
                    className="lv-project-row"
                    type="button"
                    onClick={() =>
                      navigate(`/chat?conversation=${encodeURIComponent(conversation.id)}`)
                    }
                  >
                    <span className="lv-thumb lv-thumb-icon" aria-hidden="true">
                      <svg className="lv-icon" viewBox="0 0 24 24">
                        <path d="M5 6h14v10H8l-3 3V6z" />
                      </svg>
                    </span>
                    <span>
                      <strong>{conversation.title}</strong>
                      <small>
                        {conversation.pinned ? "Pinned · " : ""}
                        {formatRelative(conversation.updated_at)}
                      </small>
                    </span>
                    <svg className="lv-icon" viewBox="0 0 24 24">
                      <path d="M9 6l6 6-6 6" />
                    </svg>
                  </button>
                ))
              )}
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-card-head">
              <div className="lv-section-label">System Performance</div>
              <button className="lv-link" type="button" onClick={() => navigate("/status")}>
                View all →
              </button>
            </div>
            <div className="lv-gauges" title={telemetryError ?? `Live telemetry${stale}`}>
              {gauges.map((gauge) => (
                <div className="lv-gauge" key={gauge.label}>
                  <div
                    className={`lv-ring ${gauge.tone}`}
                    style={{
                      ["--p" as string]: gauge.available ? Math.round(gauge.value ?? 0) : 0,
                    }}
                  >
                    <b>{gaugeDisplay(gauge.value, gauge.available)}</b>
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
                {spark ? (
                  <>
                    <path d={spark.area} fill="url(#sparkFill)" />
                    <polyline
                      fill="none"
                      stroke="#22C9D6"
                      strokeWidth="1.6"
                      points={spark.line}
                    />
                  </>
                ) : (
                  <text x="12" y="34" fill="currentColor" opacity="0.45" fontSize="11">
                    Waiting for telemetry…
                  </text>
                )}
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
                {agentsEnabled ? "Agents flag ON" : "Agents flag OFF"}
              </span>
            </div>
            <div className="lv-agent-list">
              {agents.map((agent) => (
                <button
                  key={agent.title}
                  className="lv-agent-row"
                  type="button"
                  onClick={() => navigate(agent.to)}
                >
                  <span className={`lv-agent-icon ${agent.tone}`}>
                    <svg className="lv-icon" viewBox="0 0 24 24">
                      {agent.icon}
                    </svg>
                  </span>
                  <span>
                    <strong>{agent.title}</strong>
                    <small>
                      {agent.meta} · {agent.statusLabel}
                    </small>
                  </span>
                  <span
                    className={
                      agent.online === true
                        ? "lv-status-online"
                        : agent.online === false
                          ? "lv-status-offline"
                          : "lv-status-offline"
                    }
                    title={agent.statusLabel}
                  />
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
            <img src={media.globe} alt="World activity globe" width={208} height={208} />
          </div>
          <div className="lv-world-stats">
            <div className="lv-world-stat">
              <span>Control plane</span>
              <strong>{health?.ok ? "Online" : health ? "Degraded" : "Unknown"}</strong>
            </div>
            <div className="lv-world-stat">
              <span>LLM</span>
              <strong className="amber">{llmLabel}</strong>
            </div>
            <div className="lv-world-stat">
              <span>Approvals</span>
              <strong>{pendingApprovals} pending</strong>
            </div>
            <div className="lv-world-stat">
              <span>Capabilities</span>
              <strong>{health?.capabilities?.registered ?? "—"}</strong>
            </div>
          </div>
        </article>

        <div className="lv-section-label">Quick Tools</div>
        <div className="lv-tools-grid">
          {[
            {
              label: "Nieuw gesprek",
              to: "/chat",
              icon: <path d="M12 5v14M5 12h14" />,
            },
            {
              label: "Coding Agent",
              to: "/coding",
              icon: <path d="M4 18V8l8-4 8 4v10l-8 4-8-4z" />,
            },
            {
              label: "Deep Research",
              to: "/research",
              icon: (
                <>
                  <circle cx="11" cy="11" r="7" />
                  <path d="M20 20l-3-3" />
                </>
              ),
            },
            {
              label: "Datasets",
              to: "/datasets",
              icon: <path d="M12 16V5M8 9l4-4 4 4M5 19h14" />,
            },
          ].map((tool) => (
            <button
              key={tool.label}
              className="lv-tool"
              type="button"
              onClick={() => navigate(tool.to)}
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
