import { useCallback, useEffect, useMemo, useState } from "react";
import { media } from "../assets/media";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import type {
  AnalyticsAgentsResponse,
  AnalyticsDatasetsResponse,
  AnalyticsOverview,
  AnalyticsToolsResponse,
  AnalyticsTrainingResponse,
  SystemTelemetryResponse,
} from "../types/api";

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

const RANGES = ["1h", "24h", "7d", "30d", "90d"] as const;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function formatCollectedAt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const ageMs = Date.now() - t;
  const sec = Math.floor(ageMs / 1000);
  if (sec < 60) return `${sec}s geleden`;
  const min = Math.floor(sec / 60);
  if (min < 120) return `${min}m geleden`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${hr}h geleden`;
  return new Date(t).toLocaleString();
}

function jobTotal(
  entry: { total?: number } | number | undefined,
): number {
  if (entry == null) return 0;
  if (typeof entry === "number") return entry;
  return entry.total ?? 0;
}

function formatWindow(from: string, to: string): string {
  try {
    const f = new Date(from);
    const t = new Date(to);
    return `${f.toLocaleDateString()} – ${t.toLocaleDateString()}`;
  } catch {
    return `${from} – ${to}`;
  }
}

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
    default:
      return <path d="M7 5h10v14H7zM9 8h6M9 12h6M9 16h4" />;
  }
}

function EmptyCard({ title, message }: { title: string; message: string }) {
  return (
    <article className="lv-panel lv-an-card">
      <div className="lv-an-card-head">
        <div className="lv-section-label">{title}</div>
      </div>
      <p className="lv-muted" style={{ padding: "1rem", margin: 0 }}>{message}</p>
    </article>
  );
}

type JobStatusCounts = {
  total: number;
  completed: number;
  failed: number;
  running: number;
  cancelled: number;
  other?: number;
};

function asJobCounts(raw: Record<string, number> | undefined): JobStatusCounts {
  if (!raw) {
    return { total: 0, completed: 0, failed: 0, running: 0, cancelled: 0 };
  }
  return {
    total: raw.total ?? 0,
    completed: raw.completed ?? 0,
    failed: raw.failed ?? 0,
    running: raw.running ?? 0,
    cancelled: raw.cancelled ?? 0,
    other: raw.other ?? 0,
  };
}

function StatusBars({
  title,
  counts,
}: {
  title: string;
  counts: JobStatusCounts;
}) {
  const denom = counts.total || 1;
  const rows = [
    { label: "Completed", n: counts.completed, color: "#20DC8C" },
    { label: "Running", n: counts.running, color: "#22C9D6" },
    { label: "Failed", n: counts.failed, color: "#e05c5c" },
    { label: "Cancelled", n: counts.cancelled, color: "#696964" },
  ];
  return (
    <article className="lv-panel lv-an-card">
      <div className="lv-an-card-head">
        <div className="lv-section-label">{title}</div>
        <span className="lv-muted">{counts.total} in window</span>
      </div>
      {counts.total === 0 ? (
        <p className="lv-muted" style={{ padding: "1rem" }}>Geen records in dit bereik.</p>
      ) : (
        <div className="lv-an-agent-bars" style={{ padding: "0 1rem 1rem" }}>
          {rows.map((row) => (
            <div key={row.label} className="lv-an-agent-row">
              <span>{row.label}</span>
              <div className="lv-an-bar">
                <span style={{ width: `${(row.n / denom) * 100}%`, background: row.color }} />
              </div>
              <strong>{row.n}</strong>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

export function AnalyticsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [range, setRange] = useState<(typeof RANGES)[number]>("7d");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [agentsData, setAgentsData] = useState<AnalyticsAgentsResponse | null>(null);
  const [trainingData, setTrainingData] = useState<AnalyticsTrainingResponse | null>(null);
  const [datasetsData, setDatasetsData] = useState<AnalyticsDatasetsResponse | null>(null);
  const [toolsData, setToolsData] = useState<AnalyticsToolsResponse | null>(null);
  const [telemetry, setTelemetry] = useState<SystemTelemetryResponse | null>(null);

  const collectedAt = useMemo(() => {
    switch (tab) {
      case "Agent Activity":
        return agentsData?.collectedAt ?? overview?.collectedAt;
      case "Tasks & Tools":
        return toolsData?.collectedAt ?? overview?.collectedAt;
      case "Knowledge Growth":
        return datasetsData?.collectedAt ?? overview?.collectedAt;
      case "Usage":
        return trainingData?.collectedAt ?? overview?.collectedAt;
      case "System Resources":
        return telemetry?.collectedAt ?? overview?.collectedAt;
      default:
        return overview?.collectedAt;
    }
  }, [tab, overview, agentsData, trainingData, datasetsData, toolsData, telemetry]);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.analyticsOverview(range);
      setOverview(res.overview);
    } catch (err) {
      setOverview(null);
      setError(errMsg(err, "Analytics overview unavailable"));
    } finally {
      setLoading(false);
    }
  }, [range]);

  const loadTabData = useCallback(async () => {
    try {
      if (tab === "Agent Activity") {
        const res = await api.analyticsAgents(range);
        setAgentsData(res.agents);
      } else if (tab === "Usage") {
        const res = await api.analyticsTraining(range);
        setTrainingData(res.training);
      } else if (tab === "Knowledge Growth") {
        const res = await api.analyticsDatasets(range);
        setDatasetsData(res.datasets);
      } else if (tab === "Tasks & Tools") {
        const res = await api.analyticsTools(range);
        setToolsData(res.tools);
      } else if (tab === "System Resources") {
        const res = await api.systemTelemetry();
        setTelemetry(res);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load analytics section"));
    }
  }, [tab, range]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    void loadTabData();
  }, [loadTabData]);

  const kpis = useMemo(() => {
    if (!overview) return [];
    const t = overview.totals;
    return [
      { label: "Training jobs", value: String(jobTotal(t.trainingJobs)) },
      { label: "Dataset jobs", value: String(jobTotal(t.datasetJobs)) },
      { label: "Agent missions", value: String(jobTotal(t.agentMissions)) },
      { label: "Capability jobs", value: String(jobTotal(t.capabilityJobs)) },
      { label: "Approvals", value: String(jobTotal(t.approvals)) },
      { label: "Verification reports", value: String(jobTotal(t.verificationReports)) },
    ];
  }, [overview]);

  const agentBars = useMemo(() => {
    const rows = agentsData?.agents ?? [];
    const total = rows.reduce((s, a) => s + a.total, 0) || 1;
    return rows.map((a) => ({
      name: a.name ?? a.agentId,
      pct: Math.round((a.total / total) * 1000) / 10,
      total: a.total,
      completed: a.completed,
      failed: a.failed,
    }));
  }, [agentsData]);

  const toolRows = useMemo(() => toolsData?.capabilities ?? [], [toolsData]);

  const trainingMethods = useMemo(() => trainingData?.byMethod ?? [], [trainingData]);

  const windowLabel = overview ? formatWindow(overview.from, overview.to) : "—";

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
                onClick={() => setTab(item)}
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
            <span className="lv-an-date" style={{ cursor: "default" }}>
              <svg className="lv-icon" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="4" y="5" width="16" height="15" rx="2" />
                <path d="M8 3v4M16 3v4M4 10h16" />
              </svg>
              <span>{windowLabel}</span>
            </span>
          </div>
        </div>

        <p className="lv-muted" style={{ margin: "0 0 1rem", fontSize: "0.85rem" }} role="status">
          {loading ? "Loading…" : null}
          {error ? <span style={{ color: "var(--lv-red, #c44)" }}>{error}</span> : null}
          {!loading && !error && collectedAt ? (
            <span>
              Data collected {collectedAt} · stale {formatCollectedAt(collectedAt)}
            </span>
          ) : null}
        </p>

        {tab === "Overview" && (
          <>
            <section className="lv-an-kpi-row">
              {overview ? (
                kpis.map((item) => (
                  <article key={item.label} className="lv-an-kpi">
                    <div className="lv-an-kpi-label">{item.label}</div>
                    <div className="lv-an-kpi-value">{item.value}</div>
                    <div className="lv-an-kpi-delta">window total</div>
                  </article>
                ))
              ) : (
                <EmptyCard title="Overview" message="Overview data not available." />
              )}
            </section>

            {overview?.statusBreakdown ? (
              <section className="lv-an-lower" style={{ marginTop: "1rem" }}>
                <StatusBars title="Training jobs" counts={asJobCounts(overview.statusBreakdown.training)} />
                <StatusBars title="Dataset jobs" counts={asJobCounts(overview.statusBreakdown.datasets)} />
                <StatusBars title="Agent missions" counts={asJobCounts(overview.statusBreakdown.agents)} />
                <StatusBars title="Capability jobs" counts={asJobCounts(overview.statusBreakdown.jobs)} />
              </section>
            ) : null}

            <section className="lv-an-bottom" style={{ marginTop: "1rem" }}>
              <EmptyCard
                title="Cost estimation"
                message="Cost is not collected by the analytics API (no invented dollars)."
              />
            </section>
          </>
        )}

        {tab === "Usage" && (
          <section className="lv-an-lower">
            {trainingData ? (
              <>
                <StatusBars title="Training jobs by status" counts={asJobCounts(trainingData.byStatus)} />
                <article className="lv-panel lv-an-card">
                  <div className="lv-an-card-head">
                    <div className="lv-section-label">Methods</div>
                    <span className="lv-muted">{trainingData.checkpoints} checkpoints in window</span>
                  </div>
                  {trainingMethods.length === 0 ? (
                    <p className="lv-muted" style={{ padding: "1rem" }}>No training methods recorded.</p>
                  ) : (
                    <ul className="lv-an-tool-list">
                      {trainingMethods.map((m) => (
                        <li key={m.method}>
                          <span>{m.method}</span>
                          <strong>{m.count}</strong>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
              </>
            ) : (
              <EmptyCard title="Usage" message="Training analytics unavailable." />
            )}
          </section>
        )}

        {tab === "Model Performance" && (
          <EmptyCard
            title="Model Performance"
            message="No model performance time series is exposed yet. Request volume, response time, and token charts are not synthesized."
          />
        )}

        {tab === "Agent Activity" && (
          <section className="lv-an-lower">
            <article className="lv-panel lv-an-card">
              <div className="lv-an-card-head">
                <div className="lv-section-label">Missions by agent</div>
              </div>
              {agentBars.length === 0 ? (
                <p className="lv-muted" style={{ padding: "1rem" }}>No agent missions in this window.</p>
              ) : (
                <div className="lv-an-agent-bars">
                  {agentBars.map((item) => (
                    <div key={item.name} className="lv-an-agent-row">
                      <span>{item.name}</span>
                      <div className="lv-an-bar">
                        <span style={{ width: `${item.pct}%` }} />
                      </div>
                      <strong>{item.total}</strong>
                    </div>
                  ))}
                </div>
              )}
            </article>
          </section>
        )}

        {tab === "System Resources" && (
          <section className="lv-an-mid">
            {telemetry ? (
              <article className="lv-panel lv-an-card">
                <div className="lv-an-card-head">
                  <div className="lv-section-label">Live telemetry</div>
                  <span className="lv-muted">
                    {telemetry.truth.measured ? "measured" : "unavailable"}
                    {telemetry.truth.synthetic ? " (partial)" : ""}
                  </span>
                </div>
                <div className="lv-an-resources">
                  <div className="lv-an-resource">
                    <div className="lv-an-resource-meta">
                      <span>CPU</span>
                      <strong>
                        {telemetry.dashboard.cpuPct != null ? `${telemetry.dashboard.cpuPct.toFixed(1)}%` : "—"}
                      </strong>
                    </div>
                    <div className="lv-an-bar">
                      <span style={{ width: `${telemetry.dashboard.cpuPct ?? 0}%` }} />
                    </div>
                  </div>
                  <div className="lv-an-resource">
                    <div className="lv-an-resource-meta">
                      <span>Memory</span>
                      <strong>
                        {telemetry.dashboard.ramPct != null ? `${telemetry.dashboard.ramPct.toFixed(1)}%` : "—"}
                      </strong>
                    </div>
                    <div className="lv-an-bar">
                      <span style={{ width: `${telemetry.dashboard.ramPct ?? 0}%` }} />
                    </div>
                  </div>
                  <div className="lv-an-resource">
                    <div className="lv-an-resource-meta">
                      <span>GPU</span>
                      <strong>
                        {telemetry.dashboard.gpuPct != null ? `${telemetry.dashboard.gpuPct.toFixed(1)}%` : "—"}
                      </strong>
                    </div>
                    <div className="lv-an-bar">
                      <span style={{ width: `${telemetry.dashboard.gpuPct ?? 0}%` }} />
                    </div>
                  </div>
                  {telemetry.gpu.devices.map((d) => (
                    <div key={d.index} className="lv-an-resource">
                      <div className="lv-an-resource-meta">
                        <span>{d.name}</span>
                        <strong>
                          {d.vramUtilizationPct != null ? `${d.vramUtilizationPct.toFixed(0)}% VRAM` : "VRAM —"}
                        </strong>
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            ) : (
              <EmptyCard title="System Resources" message="Telemetry not available on this host." />
            )}
          </section>
        )}

        {tab === "Tasks & Tools" && (
          <section className="lv-an-lower">
            <article className="lv-panel lv-an-card">
              <div className="lv-an-card-head">
                <div className="lv-section-label">Capability executions</div>
                {toolsData ? (
                  <span className="lv-muted">{toolsData.approvals.total ?? 0} approvals in window</span>
                ) : null}
              </div>
              {toolRows.length === 0 ? (
                <p className="lv-muted" style={{ padding: "1rem" }}>No capability jobs in this window.</p>
              ) : (
                <ul className="lv-an-tool-list">
                  {toolRows.map((item) => (
                    <li key={item.capabilityId}>
                      <span className="lv-an-tool-icon">
                        <svg className="lv-icon" viewBox="0 0 24 24">
                          <ToolIcon kind="code" />
                        </svg>
                      </span>
                      <span>{item.capabilityId}</span>
                      <strong>{item.total}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          </section>
        )}

        {tab === "Knowledge Growth" && (
          <section className="lv-an-lower">
            {datasetsData ? (
              <>
                <section className="lv-an-kpi-row">
                  <article className="lv-an-kpi">
                    <div className="lv-an-kpi-label">Datasets</div>
                    <div className="lv-an-kpi-value">{datasetsData.inventory.datasets}</div>
                  </article>
                  <article className="lv-an-kpi">
                    <div className="lv-an-kpi-label">Versions</div>
                    <div className="lv-an-kpi-value">{datasetsData.inventory.versions}</div>
                  </article>
                  <article className="lv-an-kpi">
                    <div className="lv-an-kpi-label">Indexes</div>
                    <div className="lv-an-kpi-value">{datasetsData.inventory.indexes}</div>
                  </article>
                </section>
                <StatusBars title="Dataset jobs" counts={asJobCounts(datasetsData.jobsByStatus)} />
                <article className="lv-panel lv-an-card">
                  <div className="lv-an-card-head">
                    <div className="lv-section-label">Job types</div>
                  </div>
                  {datasetsData.jobsByType.length === 0 ? (
                    <p className="lv-muted" style={{ padding: "1rem" }}>No dataset jobs in window.</p>
                  ) : (
                    <ul className="lv-an-tool-list">
                      {datasetsData.jobsByType.map((j) => (
                        <li key={j.jobType}>
                          <span>{j.jobType}</span>
                          <strong>{j.count}</strong>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
              </>
            ) : (
              <EmptyCard title="Knowledge Growth" message="Dataset analytics unavailable." />
            )}
          </section>
        )}

        {tab === "Custom" && (
          <EmptyCard title="Custom" message="No custom analytics views configured." />
        )}

        <p className="lv-footer-quote">“What gets measured, gets mastered.” — LEVIATHAN</p>
      </main>
    </AppShell>
  );
}
