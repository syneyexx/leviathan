"use client";

import { useMemo, useState } from "react";
import { formatBytes, sparkPath, type MetricRange } from "../hooks/dashboard-live-utils";
import { useDashboardLive } from "../hooks/use-dashboard-live";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import {
  PR_PERF_PERIODS,
  PR_PERF_QUOTE,
  PR_PERF_SHORTCUTS,
  PR_PERF_TABS,
  type PerfPeriod,
  type PerfTab,
} from "../mocks/pr-performance";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

const CHART_W = 320;
const CHART_H = 110;

function scaleValues(values: number[], max: number): number[] {
  const safe = Math.max(max, 1);
  return values.map((v) => Math.max(0, Math.min(100, (v / safe) * 100)));
}

function logScaleValues(values: number[], maxLog = 4): number[] {
  return values.map((v) => {
    const clamped = Math.max(1, v);
    const log = Math.log10(clamped);
    return Math.max(0, Math.min(100, (log / maxLog) * 100));
  });
}

function LineChart({
  series,
  max,
  log,
  yLabels,
  showStats,
}: {
  series: Array<{ id: string; label: string; color: string; values: number[] }>;
  max?: number;
  log?: boolean;
  yLabels: string[];
  showStats?: Array<{ label: string; value: string }>;
}) {
  const paths = useMemo(
    () =>
      series.map((s) => {
        const scaled = log ? logScaleValues(s.values) : scaleValues(s.values, max ?? 100);
        return { ...s, d: sparkPath(scaled, CHART_W, CHART_H) };
      }),
    [series, max, log],
  );

  return (
    <div className="prp-chart">
      <div className="prp-chart-y" aria-hidden="true">
        {yLabels.map((lab) => (
          <span key={lab}>{lab}</span>
        ))}
      </div>
      <div className="prp-chart-plot">
        <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" aria-hidden="true">
          {[0.25, 0.5, 0.75].map((t) => (
            <line
              key={t}
              x1="0"
              x2={CHART_W}
              y1={CHART_H * t}
              y2={CHART_H * t}
              stroke="rgba(90,140,180,0.16)"
              strokeWidth="1"
            />
          ))}
          {paths.map((p) => (
            <path key={p.id} d={p.d} fill="none" stroke={p.color} strokeWidth="1.8" />
          ))}
        </svg>
        <div className="prp-chart-x" aria-hidden="true">
          {["−", "", "", "nu"].map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </div>
        {showStats ? (
          <div className="prp-chart-stats">
            {showStats.map((stat) => (
              <div key={stat.label}>
                <span>{stat.label}</span>
                <strong>{stat.value}</strong>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function BarChart({
  series,
  max,
  yLabels,
  showStats,
}: {
  series: Array<{ id: string; label: string; color: string; values: number[] }>;
  max: number;
  yLabels: string[];
  showStats?: Array<{ label: string; value: string }>;
}) {
  const count = series[0]?.values.length ?? 0;
  const groupW = CHART_W / Math.max(count, 1);
  const barW = Math.max(3, (groupW - 4) / series.length);

  return (
    <div className="prp-chart">
      <div className="prp-chart-y" aria-hidden="true">
        {yLabels.map((lab) => (
          <span key={lab}>{lab}</span>
        ))}
      </div>
      <div className="prp-chart-plot">
        <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" aria-hidden="true">
          {[0.2, 0.4, 0.6, 0.8].map((t) => (
            <line
              key={t}
              x1="0"
              x2={CHART_W}
              y1={CHART_H * (1 - t)}
              y2={CHART_H * (1 - t)}
              stroke="rgba(90,140,180,0.16)"
              strokeWidth="1"
            />
          ))}
          {Array.from({ length: count }).map((_, di) => {
            const gx = di * groupW + 2;
            return (
              <g key={di}>
                {series.map((s, si) => {
                  const val = s.values[di] ?? 0;
                  const bh = (val / max) * (CHART_H - 4);
                  const x = gx + si * barW;
                  const y = CHART_H - bh;
                  return <rect key={s.id} x={x} y={y} width={barW - 1} height={Math.max(1, bh)} rx="1" fill={s.color} />;
                })}
              </g>
            );
          })}
        </svg>
        <div className="prp-chart-x" aria-hidden="true">
          {["−", "", "", "nu"].map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </div>
        {showStats ? (
          <div className="prp-chart-stats">
            {showStats.map((stat) => (
              <div key={stat.label}>
                <span>{stat.label}</span>
                <strong>{stat.value}</strong>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const d = useMemo(() => sparkPath(scaleValues(values, Math.max(...values, 1)), 88, 22), [values]);
  return (
    <svg className="prp-spark" viewBox="0 0 88 22" width="88" height="22" aria-hidden="true">
      <path d={d} fill="none" stroke={color} strokeWidth="1.6" />
    </svg>
  );
}

export function PerformancePage({ onNavigate }: Props) {
  const [tab, setTab] = useState<PerfTab>("overzicht");
  const [period, setPeriod] = useState<PerfPeriod>("1h");
  const [periodOpen, setPeriodOpen] = useState(false);
  const live = useDashboardLive();

  const rangeMap: Record<PerfPeriod, MetricRange> = {
    "1h": "1h",
    "6h": "1h",
    "24h": "24h",
    "7d": "24h",
  };

  const periodLabel = PR_PERF_PERIODS.find((p) => p.id === period)?.label ?? "Laatste 1 uur";
  const history = live.rangeHistory.length ? live.rangeHistory : live.history;
  const cpuSeries = history.map((s) => s.cpu).filter((v): v is number => typeof v === "number");
  const ramSeries = history.map((s) => s.ram).filter((v): v is number => typeof v === "number");
  const gpuSeries = history.map((s) => s.gpu).filter((v): v is number => typeof v === "number");
  const vramSeries = history.map((s) => s.vram).filter((v): v is number => typeof v === "number");

  const fmtPct = (v: number | null | undefined) => (typeof v === "number" ? `${Math.round(v)}%` : "—");
  const kpis = [
    {
      id: "cpu",
      label: "CPU",
      value: live.loading && live.cpuPercent == null ? "…" : fmtPct(live.cpuPercent),
      hint: live.hostname || "Local host",
      icon: "bolt" as const,
      tone: "cyan" as const,
      spark: cpuSeries.slice(-16),
      color: "#2dd4bf",
    },
    {
      id: "ram",
      label: "RAM",
      value: live.loading && live.ramPercent == null ? "…" : fmtPct(live.ramPercent),
      hint:
        live.ramUsedBytes != null && live.ramTotalBytes != null
          ? `${formatBytes(live.ramUsedBytes)} / ${formatBytes(live.ramTotalBytes)}`
          : "Geen RAM-telemetrie",
      icon: "database" as const,
      tone: "blue" as const,
      spark: ramSeries.slice(-16),
      color: "#60a5fa",
    },
    {
      id: "gpu",
      label: "GPU",
      value: live.gpuPercent == null ? "—" : fmtPct(live.gpuPercent),
      hint: live.gpuName || "Geen GPU-telemetrie",
      icon: "bolt" as const,
      tone: "gold" as const,
      spark: gpuSeries.slice(-16),
      color: "#f0b429",
    },
    {
      id: "vram",
      label: "VRAM",
      value: live.vramPercent == null ? "—" : fmtPct(live.vramPercent),
      hint:
        live.vramUsedBytes != null && live.vramTotalBytes != null
          ? `${formatBytes(live.vramUsedBytes)} / ${formatBytes(live.vramTotalBytes)}`
          : "Geen VRAM-telemetrie",
      icon: "database" as const,
      tone: "purple" as const,
      spark: vramSeries.slice(-16),
      color: "#9b5cff",
    },
  ];

  const cpuRamSeries = [
    { id: "cpu", label: "CPU", color: "#2dd4bf", values: cpuSeries.slice(-24).map((v) => v ?? 0) },
    { id: "ram", label: "RAM", color: "#60a5fa", values: ramSeries.slice(-24).map((v) => v ?? 0) },
  ];
  const gpuVramSeries = [
    { id: "gpu", label: "GPU", color: "#f0b429", values: gpuSeries.slice(-24).map((v) => v ?? 0) },
    { id: "vram", label: "VRAM", color: "#9b5cff", values: vramSeries.slice(-24).map((v) => v ?? 0) },
  ];

  const healthChecks = live.health?.checks || [];
  const lmOk = live.health?.lm_studio === "connected";
  const overall = live.health?.overall || (live.lastError ? "error" : live.health ? "ok" : "warn");

  const bottleBars = [
    { id: "cpu", label: "CPU", value: Math.round(live.cpuPercent ?? 0), tone: (live.cpuPercent ?? 0) > 85 ? "gold" : "cyan" },
    { id: "ram", label: "RAM", value: Math.round(live.ramPercent ?? 0), tone: (live.ramPercent ?? 0) > 85 ? "gold" : "blue" },
    { id: "gpu", label: "GPU", value: Math.round(live.gpuPercent ?? 0), tone: (live.gpuPercent ?? 0) > 85 ? "gold" : "cyan" },
    { id: "vram", label: "VRAM", value: Math.round(live.vramPercent ?? 0), tone: (live.vramPercent ?? 0) > 85 ? "gold" : "blue" },
  ];

  const hardwareRows = [
    { id: "host", label: "Host", value: live.hostname || "—" },
    { id: "os", label: "OS", value: live.osLabel || "—" },
    {
      id: "cpu",
      label: "CPU load",
      value: fmtPct(live.cpuPercent),
      progress: live.cpuPercent ?? undefined,
      pct: fmtPct(live.cpuPercent),
      tone: "cyan",
    },
    {
      id: "ram",
      label: "RAM",
      value:
        live.ramUsedBytes != null && live.ramTotalBytes != null
          ? `${formatBytes(live.ramUsedBytes)} / ${formatBytes(live.ramTotalBytes)}`
          : "—",
      progress: live.ramPercent ?? undefined,
      pct: fmtPct(live.ramPercent),
      tone: "blue",
    },
    {
      id: "gpu",
      label: "GPU",
      value: live.gpuName || "—",
      detail: live.gpuPercent == null ? "Geen GPU-telemetrie" : `Utilisatie ${fmtPct(live.gpuPercent)}`,
      progress: live.gpuPercent ?? undefined,
      pct: fmtPct(live.gpuPercent),
      tone: "gold",
    },
    {
      id: "backend",
      label: "Backend",
      value: live.health?.backend || "—",
      badge: live.health?.version || undefined,
    },
    {
      id: "lm",
      label: "LM Studio",
      value: live.health?.lm_studio || "—",
      tone: lmOk ? undefined : "gold",
    },
  ];

  const services = [
    { id: "api", name: "HADES API", icon: "database", online: Boolean(live.health) },
    { id: "lm", name: "LM Studio", icon: "bolt", online: lmOk },
    { id: "native", name: "Native runtime", icon: "bolt", online: Boolean(live.native?.available || live.native?.connected || live.metricsAvailable) },
    { id: "agents", name: "Agents", icon: "users", online: !live.lastError },
  ];

  const body = (
    <div className="mc-page pr-page prp-page" data-page="performance" data-live="performance">
      <MediaWelcome
        title="Performance"
        subtitle="Realtime monitoring, systeemtelemetrie en prestatieanalyse van HADES."
        quote={PR_PERF_QUOTE}
        right={
          <div className="prp-controls">
            <div className="prp-period">
              <button
                type="button"
                className="prp-ctrl-btn"
                aria-expanded={periodOpen}
                onClick={() => setPeriodOpen((v) => !v)}
              >
                <FbIcon name="clock" size={13} />
                <span>{periodLabel}</span>
                <FbIcon name="chevron" size={11} className="prp-period-chevron" />
              </button>
              {periodOpen ? (
                <div className="prp-period-menu" role="listbox">
                  {PR_PERF_PERIODS.map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      className={opt.id === period ? "active" : undefined}
                      role="option"
                      aria-selected={opt.id === period}
                      onClick={() => {
                        setPeriod(opt.id);
                        live.setRange(rangeMap[opt.id]);
                        setPeriodOpen(false);
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <button type="button" className="prp-ctrl-btn" onClick={() => live.refresh()}>
              <FbIcon name="refresh" size={13} />
              <span>Vernieuwen</span>
            </button>
            <button type="button" className="prp-ctrl-btn active" aria-pressed="true">
              <span className={`mc-dot ${live.lastError ? "red" : "green"}`} />
              <span>{live.lastError ? "Sync fout" : "Live polling"}</span>
            </button>
          </div>
        }
      />

      {live.lastError ? (
        <div className="card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Telemetrie laden mislukt.</strong> {live.lastError}
        </div>
      ) : null}

      <div className="prp-tabs" role="tablist" aria-label="Performance secties">
        {PR_PERF_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`perf-tab-${item.id}`}
            className={`prp-tab${tab === item.id ? " active" : ""}`}
            aria-selected={tab === item.id}
            aria-controls={`perf-panel-${item.id}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div
        id={`perf-panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`perf-tab-${tab}`}
        className="prp-tab-panel"
      >
        {tab === "logs" ? (
          <div className="mc-panel prp-panel" style={{ marginBottom: 12, padding: 12 }}>
            <h2>Logs</h2>
            <p className="muted">
              Live logstreaming zit in Settings → Console. Deze tab toont geen mockregels.
            </p>
            <button type="button" className="btn btn-sm btn-outline" onClick={() => onNavigate("settings-console")}>
              Open console
            </button>
          </div>
        ) : null}
        {tab === "modellen" ? (
          <div className="mc-panel prp-panel" style={{ marginBottom: 12, padding: 12 }}>
            <h2>Modellen</h2>
            <p className="muted">Modelcatalogus en latency staan onder LLM → Modellen / Stats.</p>
            <button type="button" className="btn btn-sm btn-outline" onClick={() => onNavigate("models")}>
              Open modellen
            </button>
          </div>
        ) : null}
        {tab === "processen" ? (
          <div className="mc-panel prp-panel" style={{ marginBottom: 12, padding: 12 }}>
            <h2>Processen</h2>
            <p className="muted">
              {live.agents?.length
                ? `${live.agents.length} agent(s) in de laatste snapshot.`
                : "Geen agent-proceslijst in de huidige telemetrie-snapshot."}
            </p>
          </div>
        ) : null}
        {(tab === "overzicht" || tab === "hardware" || tab === "netwerk") && (
      <div className="prp-kpi-row">
        {kpis.map((kpi) => (
          <article key={kpi.id} className={`mc-kpi prp-kpi tone-${kpi.tone}`}>
            <div className="prp-kpi-top">
              <span className={`prp-kpi-ico ${kpi.tone}`}>
                <FbIcon name={kpi.icon} size={13} />
              </span>
              <span className="mc-kpi-label">{kpi.label}</span>
            </div>
            <div className="prp-kpi-mid">
              <div className={`mc-kpi-value prp-kpi-value ${kpi.tone}`}>{kpi.value}</div>
              {kpi.spark.length ? <Sparkline values={kpi.spark} color={kpi.color} /> : null}
            </div>
            <div className="prp-kpi-hint">{kpi.hint}</div>
          </article>
        ))}
      </div>
        )}

      {(tab === "overzicht" || tab === "hardware" || tab === "netwerk") && (
      <div className="prp-charts-grid">
        <section className="mc-panel prp-panel">
          <div className="mc-panel-head">
            <div>
              <h2>CPU &amp; RAM</h2>
            </div>
            <div className="prp-legend">
              {cpuRamSeries.map((s) => (
                <span key={s.id}>
                  <i style={{ background: s.color }} />
                  {s.label}
                </span>
              ))}
            </div>
          </div>
          {cpuRamSeries.some((s) => s.values.length) ? (
            <LineChart series={cpuRamSeries} yLabels={["100%", "50%", "0%"]} />
          ) : (
            <p className="muted" style={{ padding: 12 }}>
              Geen CPU/RAM samples. Native metrics of health polling starten automatisch.
            </p>
          )}
        </section>

        <section className="mc-panel prp-panel">
          <div className="mc-panel-head">
            <div>
              <h2>GPU &amp; VRAM</h2>
            </div>
            <div className="prp-legend">
              {gpuVramSeries.map((s) => (
                <span key={s.id}>
                  <i style={{ background: s.color }} />
                  {s.label}
                </span>
              ))}
            </div>
          </div>
          {gpuVramSeries.some((s) => s.values.length) ? (
            <LineChart series={gpuVramSeries} yLabels={["100%", "50%", "0%"]} />
          ) : (
            <p className="muted" style={{ padding: 12 }}>
              Geen GPU/VRAM telemetrie beschikbaar op deze host.
            </p>
          )}
        </section>

        <section className="mc-panel prp-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Disk I/O</h2>
            </div>
          </div>
          <p className="muted" style={{ padding: 12 }}>
            Disk I/O-reeks is nog niet aangesloten op een live API — geen mockwaarden.
          </p>
        </section>

        <section className="mc-panel prp-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Netwerk</h2>
            </div>
          </div>
          <p className="muted" style={{ padding: 12 }}>
            Netwerk-telemetrie is nog niet aangesloten — geen mockwaarden.
          </p>
        </section>

        <section className="mc-panel prp-panel">
          <div className="mc-panel-head">
            <div>
              <h2>LM latency</h2>
            </div>
          </div>
          <p className="muted" style={{ padding: 12 }}>
            {typeof live.health?.latency_ms === "number"
              ? `Laatste health latency: ${Math.round(live.health.latency_ms)} ms`
              : "Geen latency-sample in health payload."}
          </p>
        </section>

        <section className="mc-panel prp-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Agents / queue</h2>
            </div>
          </div>
          <p className="muted" style={{ padding: 12 }}>
            Actieve agents: {live.agents.length}
            {live.agentsSummary ? ` · summary beschikbaar` : ""}
          </p>
        </section>
      </div>
      )}

      {(tab === "overzicht" || tab === "hardware" || tab === "processen") && (
      <div className="prp-bottom">
        <section className="mc-panel prp-panel prp-proc">
          <div className="mc-panel-head">
            <div>
              <h2>Health checks</h2>
              <p>Live `/health` checks</p>
            </div>
          </div>
          {!healthChecks.length ? (
            <p className="muted" style={{ padding: 12 }}>
              Geen gedetailleerde health checks in payload.
            </p>
          ) : (
            <table className="mc-table prp-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Check</th>
                  <th>Status</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {healthChecks.map((check, index) => (
                  <tr key={check.id}>
                    <td className="prp-rank">{index + 1}</td>
                    <td className="prp-proc-name">{check.label}</td>
                    <td>
                      <span className="prp-status">
                        <span className={`mc-dot ${check.status === "ok" ? "green" : check.status === "warn" ? "gold" : "red"}`} />
                        {check.status}
                      </span>
                    </td>
                    <td>{check.detail || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="mc-panel prp-panel prp-bottle">
          <div className="mc-panel-head">
            <div className="prp-bottle-title">
              <FbIcon name="target" size={14} />
              <h2>Bottleneck analyse</h2>
            </div>
          </div>
          <p className="prp-bottle-head">
            {live.metricsAvailable
              ? "Live resource loads van native/health metrics."
              : "Wacht op native metrics — geen verzonnen bottlenecks."}
          </p>
          <div className="prp-bottle-bars">
            {bottleBars.map((bar) => (
              <div key={bar.id} className="prp-bottle-row">
                <span className="prp-bottle-lab">{bar.label}</span>
                <div className={`prp-bottle-track ${bar.tone}`}>
                  <span style={{ width: `${Math.min(100, bar.value)}%` }} />
                </div>
                <span className="prp-bottle-pct">{bar.value}%</span>
              </div>
            ))}
          </div>
        </section>
      </div>
      )}
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“{PR_PERF_QUOTE}”</p>

      <section className="mc-insp-section">
        <div className="prp-insp-head">
          <h3 className="mc-insp-title">Hardware &amp; Systeem</h3>
        </div>
        <div className="mc-insp-card prp-hw-card">
          {hardwareRows.map((row) => (
            <div className="prp-hw-row" key={row.id}>
              <div className="prp-hw-top">
                <span className="k">{row.label}</span>
                <span className={`v${row.tone === "gold" ? " gold" : ""}`}>{row.value}</span>
              </div>
              {row.progress != null ? (
                <div className="prp-hw-meter">
                  <div className={`mc-progress prp-hw-bar ${row.tone ?? ""}`}>
                    <span style={{ width: `${Math.min(100, row.progress)}%` }} />
                  </div>
                  {row.pct ? <span className="prp-hw-pct">{row.pct}</span> : null}
                </div>
              ) : null}
              {"detail" in row && row.detail ? <div className="prp-hw-detail">{row.detail}</div> : null}
              {"badge" in row && row.badge ? <span className="prp-hw-badge">{row.badge}</span> : null}
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <div className="prp-insp-head">
          <h3 className="mc-insp-title">HADES services</h3>
        </div>
        <div className="mc-insp-card prp-svc-list">
          {services.map((svc) => (
            <div className="prp-svc-row" key={svc.id}>
              <span className="prp-svc-ico">
                <FbIcon name={svc.icon} size={12} />
              </span>
              <span className="prp-svc-name">{svc.name}</span>
              <span className="prp-svc-state">
                <span className={`mc-dot ${svc.online ? "green" : "gray"}`} />
                {svc.online ? "Online" : "Offline / onbekend"}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Systeemstatus</h3>
        <div className="mc-insp-card prp-sys-ok">
          <span className="prp-sys-ico">
            <FbIcon name={overall === "ok" ? "checkcircle" : "flask"} size={22} />
          </span>
          <div>
            <strong>
              {overall === "ok"
                ? "Systemen bereikbaar."
                : overall === "error"
                  ? "Er is een health/telemetrie fout."
                  : "Gedeeltelijke telemetrie."}
            </strong>
            <p>
              {live.health?.detail ||
                (live.metricsAvailable
                  ? "Native metrics actief."
                  : "Native metrics niet beschikbaar — health blijft leidend.")}
            </p>
          </div>
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Snelkoppelingen</h3>
        <div className="prp-shortcut-list">
          {PR_PERF_SHORTCUTS.map((item) => (
            <button
              key={item.id}
              type="button"
              className="prp-shortcut"
              onClick={() => {
                if (item.id === "logs") onNavigate("settings-logs");
                else if (item.id === "diag") onNavigate("dashboard");
              }}
            >
              <span className="prp-shortcut-ico">
                <FbIcon name={item.icon} size={13} />
              </span>
              <span>{item.label}</span>
              <FbIcon name="chevron" size={12} className="prp-shortcut-chevron" />
            </button>
          ))}
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="performance"
      appClassName="mc-app pr-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
