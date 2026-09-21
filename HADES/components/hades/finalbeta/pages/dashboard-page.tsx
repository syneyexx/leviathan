"use client";

import { useEffect, useMemo, useState } from "react";
import { DashboardReferenceIcon } from "../dashboard-reference-icon";
import {
  MetricRange,
  agentStateLabel,
  agentVisualState,
  chartPolyline,
  donutSegments,
  formatBytes,
  formatUptime,
  shortModelName,
  sparkArea,
  sparkPath,
} from "../hooks/dashboard-live-utils";
import { useDashboardLive } from "../hooks/use-dashboard-live";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

/** Placeholder until dedicated coding-model selection exists. */
const MOCK_CODE_MODEL = "—";

function pad(n: number) {
  return String(n).padStart(2, "0");
}

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

function PanelTitle({ icon, title, sub, tone = "gold" }: { icon: string; title: string; sub?: string; tone?: "gold" | "white" }) {
  return (
    <div className="dash-panel-titleline">
      <DashboardReferenceIcon name={icon} size={18} className={`dash-title-icon ${tone}`} />
      <div>
        <h2 className="dash-panel-title">{title}</h2>
        {sub ? <div className="dash-panel-sub">{sub}</div> : null}
      </div>
    </div>
  );
}

function pct(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

function relativeAgo(iso?: string | null): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "—";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (mins < 1) return "nu";
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}u`;
  return `${Math.round(hours / 24)}d`;
}

export function DashboardPage({ onNavigate }: Props) {
  const live = useDashboardLive();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 15_000);
    return () => window.clearInterval(id);
  }, []);

  const systemOnline = live.health?.backend === "ok";
  const overall = live.health?.overall || (systemOnline ? "ok" : "error");
  const statusLabel = !live.health ? (live.loading ? "Laden…" : "Offline") : overall === "ok" ? "Online" : overall === "warn" ? "Degraded" : "Probleem";
  const statusHint = !live.health
    ? live.lastError || "Backend onbereikbaar"
    : live.health.lm_studio === "connected"
      ? "LM Studio verbonden"
      : "LM Studio offline · lokale fallback";

  const runningAgents = live.agentsSummary?.running ?? live.agents.filter((a) => a.status === "running" || a.status === "busy").length;
  const totalAgents = live.agentsSummary?.total ?? live.agents.length;
  const chatModel = shortModelName(live.health?.active_model || live.agentsSummary?.active_model);
  const latency = live.health?.latency_ms;
  const chatHint =
    live.health?.lm_studio === "connected"
      ? latency != null
        ? `Ready · ${Math.round(latency)}ms`
        : "Ready"
      : live.health
        ? "Niet verbonden"
        : "—";

  const gpuValue = live.gpuPercent != null ? pct(live.gpuPercent, 0) : live.vramPercent != null ? pct(live.vramPercent, 0) : "—";
  const gpuHint =
    live.vramUsedBytes != null || live.vramTotalBytes != null
      ? `${formatBytes(live.vramUsedBytes)} / ${formatBytes(live.vramTotalBytes)}`
      : live.gpuName || (live.metricsAvailable ? "Geen GPU-data" : "Metrics laden…");

  const rangeHistory = live.rangeHistory;
  const cpuSeries = rangeHistory.map((s) => s.cpu);
  const ramSeries = rangeHistory.map((s) => s.ram);
  const gpuSeries = rangeHistory.map((s) => s.gpu);
  const vramSeries = rangeHistory.map((s) => s.vram);

  const sparks = [
    { label: "CPU", val: pct(live.cpuPercent, 0), color: "#1aa4ff", series: cpuSeries },
    {
      label: "RAM",
      val: live.ramUsedBytes != null ? `${formatBytes(live.ramUsedBytes)} / ${formatBytes(live.ramTotalBytes)}` : pct(live.ramPercent, 0),
      color: "#9b5cff",
      series: ramSeries,
    },
    { label: "GPU", val: pct(live.gpuPercent, 0), color: "#20e38d", series: gpuSeries },
    {
      label: "VRAM",
      val: live.vramUsedBytes != null ? `${formatBytes(live.vramUsedBytes)} / ${formatBytes(live.vramTotalBytes)}` : pct(live.vramPercent, 0),
      color: "#f0b429",
      series: vramSeries,
    },
  ];

  const activityRows = useMemo(() => {
    const fromAgents = live.agents
      .filter((agent) => agent.status === "running" || agent.status === "busy" || agent.current_task)
      .slice(0, 8)
      .map((agent) => {
        const task = agent.current_task;
        return {
          key: agent.id,
          name: agent.name,
          action: task?.step_title || task?.task_title || agent.status_label || agent.status || "actief",
          sub: task?.task_title || agent.role || agent.type || "",
          tag: (agent.status || "RUNNING").toUpperCase(),
          time: relativeAgo(task?.started_at || agent.last_activity_at),
          icon: "agents",
        };
      });
    if (fromAgents.length) return fromAgents;
    return (live.activity || []).slice(0, 8).map((row, index) => ({
      key: `${row.at || index}-${row.agent_id || "a"}`,
      name: row.agent_id || "Agent",
      action: row.message || row.level || "event",
      sub: row.task_id || row.source || "",
      tag: (row.level || "INFO").toUpperCase(),
      time: relativeAgo(row.at),
      icon: "activity",
    }));
  }, [live.activity, live.agents]);

  const resultRows = useMemo(() => {
    const rows: Array<{ key: string; title: string; sub: string; ago: string; icon: string; tone: string }> = [];
    for (const agent of live.agents) {
      for (const run of agent.recent_runs || []) {
        if ((run.status || "").toLowerCase() !== "completed" && (run.status || "").toLowerCase() !== "success") continue;
        rows.push({
          key: `${agent.id}-${run.id}`,
          title: run.title || agent.name,
          sub: agent.name,
          ago: relativeAgo(run.finished_at || run.updated_at),
          icon: "coderesult",
          tone: "blue",
        });
      }
      if (agent.last_task?.finished_at) {
        rows.push({
          key: `${agent.id}-last`,
          title: agent.last_task.task_title || agent.name,
          sub: agent.role || "Agent",
          ago: relativeAgo(agent.last_task.finished_at),
          icon: "check",
          tone: "green",
        });
      }
    }
    rows.sort((a, b) => a.ago.localeCompare(b.ago));
    return rows.slice(0, 6);
  }, [live.agents]);

  const donutTotal = live.donut.reduce((sum, slice) => sum + slice.count, 0);
  const donutSegs = donutSegments(live.donut);

  const idleAgents = live.agents.filter((a) => (a.status || "idle") === "idle").length;
  const errorAgents = live.agentsSummary?.errors ?? live.agents.filter((a) => a.status === "error" || a.health === "error").length;
  const modeLabel = live.health?.lm_studio === "connected" ? "Local" : live.native?.connected ? "Native" : "Local";
  const modelReady = Boolean(live.health?.active_model) && live.health?.lm_studio === "connected";

  const body = (
    <>
      <div className="dash-welcome">
        <div className="dash-welcome-copy">
          <h1>Welkom terug</h1>
          <p>
            {systemOnline
              ? "HADES is operationeel. Live metrics en agents zijn aangesloten."
              : live.loading
                ? "Dashboardgegevens worden geladen…"
                : "Backend offline — lokale shell blijft beschikbaar."}
          </p>
        </div>
        <div className="dash-welcome-mid">
          “Discipline creates freedom.
          <br />
          Intelligence multiplies it.”
        </div>
        <div className="dash-clock">
          <div className="dash-clock-copy">
            <div className="date">
              {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
            </div>
            <div className="time">
              {pad(now.getHours())}:{pad(now.getMinutes())}
            </div>
          </div>
          <DashboardReferenceIcon name="sun" size={28} className="dash-sun" />
        </div>
      </div>

      <div className="dash-status">
        <div className="card dash-stat">
          <div className={`dash-stat-ico${overall === "ok" ? " ok" : ""}`}><DashboardReferenceIcon name="status" size={24} /></div>
          <div>
            <span className="dash-stat-label">System Status</span>
            <span className="dash-stat-value">{statusLabel}</span>
            <span className="dash-stat-hint">{statusHint}</span>
          </div>
        </div>
        <div className="card dash-stat">
          <div className="dash-stat-ico"><DashboardReferenceIcon name="agents" size={24} /></div>
          <div>
            <span className="dash-stat-label">Actieve Agents</span>
            <span className="dash-stat-value">{totalAgents ? `${runningAgents} / ${totalAgents}` : "—"}</span>
            <span className="dash-stat-hint">{runningAgents ? "Agents in uitvoering" : "Geen actieve runs"}</span>
          </div>
        </div>
        <div className="card dash-stat">
          <div className="dash-stat-ico"><DashboardReferenceIcon name="runtime" size={24} /></div>
          <div>
            <span className="dash-stat-label">Actieve chatmodel</span>
            <span className="dash-stat-value" title={live.health?.active_model || undefined}>{chatModel}</span>
            <span className="dash-stat-hint">{chatHint}</span>
          </div>
        </div>
        <div className="card dash-stat">
          <div className="dash-stat-ico ring-gold"><DashboardReferenceIcon name="check" size={22} /></div>
          <div>
            <span className="dash-stat-label">Actieve code model</span>
            <span className="dash-stat-value">{MOCK_CODE_MODEL}</span>
            <span className="dash-stat-hint">Mock · selectie volgt later</span>
          </div>
        </div>
        <div className="card dash-stat">
          <div className="dash-stat-ico ring"><DashboardReferenceIcon name="gpu" size={22} /></div>
          <div>
            <span className="dash-stat-label">GPU / VRAM</span>
            <span className="dash-stat-value">{gpuValue}</span>
            <span className="dash-stat-hint">{gpuHint}</span>
          </div>
        </div>
        <div className="card dash-stat">
          <div className="dash-stat-ico"><DashboardReferenceIcon name="clock" size={24} /></div>
          <div>
            <span className="dash-stat-label">Uptime</span>
            <span className="dash-stat-value">{formatUptime(live.uptimeMs)}</span>
            <span className="dash-stat-hint">{live.metricsAvailable ? "Host uptime" : "Wachten op metrics"}</span>
          </div>
        </div>
      </div>

      <div className="dash-mid">
        <section className="card dash-panel">
          <div className="dash-panel-head">
            <PanelTitle icon="power" title="Systeemgebruik" sub="Live resource monitoring" tone="white" />
            <div className="dash-seg">
              {(["1m", "5m", "1h", "24h"] as MetricRange[]).map((r) => (
                <button key={r} type="button" className={live.range === r ? "active" : undefined} onClick={() => live.setRange(r)}>
                  {r}
                </button>
              ))}
            </div>
          </div>
          <div className="spark-grid">
            {sparks.map((spark) => (
              <div className="spark" key={spark.label}>
                <div className="spark-top">
                  <span>{spark.label}</span>
                  <span className="spark-val">{spark.val}</span>
                </div>
                <svg viewBox="0 0 120 36" preserveAspectRatio="none" aria-hidden="true">
                  <path d={sparkArea(spark.series)} fill={spark.color} fillOpacity={0.16} />
                  <path d={sparkPath(spark.series)} fill="none" stroke={spark.color} strokeWidth="1.8" />
                </svg>
              </div>
            ))}
          </div>
        </section>

        <section className="card dash-panel">
          <div className="dash-panel-head">
            <PanelTitle icon="activity" title="Activiteit" sub="Actieve processen en workflows" tone="white" />
            <button type="button" className="dash-mini-btn" data-fb-page="tasks">Alles bekijken</button>
          </div>
          {activityRows.length ? activityRows.map((row) => (
            <div className="activity-row" key={row.key}>
              <div className="activity-ico"><DashboardReferenceIcon name={row.icon} size={16} /></div>
              <div className="activity-body">
                <div className="activity-name">{row.name} <span>— {row.action}</span></div>
                <div className="activity-sub">{row.sub || "—"}</div>
              </div>
              <div className="activity-meta">
                <span className={`tag ${row.tag.includes("WAIT") || row.tag.includes("ERROR") ? "warn" : "green"}`}>{row.tag}</span>
                <div className="activity-time">{row.time}</div>
              </div>
            </div>
          )) : (
            <div className="activity-row">
              <div className="activity-body">
                <div className="activity-name">Geen actieve workflows</div>
                <div className="activity-sub">Agents en runs verschijnen hier live.</div>
              </div>
            </div>
          )}
        </section>

        <section className="card dash-panel">
          <div className="dash-panel-head">
            <PanelTitle icon="results" title="Recente resultaten" sub="Laatste succesvolle taken" tone="white" />
            <button type="button" className="dash-mini-btn" data-fb-page="tasks">Alles bekijken</button>
          </div>
          {resultRows.length ? resultRows.map((row) => (
            <div className="result-row" key={row.key}>
              <span className={`result-icon ${row.tone}`}><DashboardReferenceIcon name={row.icon} size={16} /></span>
              <span className="result-copy"><strong>{row.title}</strong><small>{row.sub}</small></span>
              <span className="ago">{row.ago}</span>
            </div>
          )) : (
            <div className="result-row">
              <span className="result-copy"><strong>Nog geen resultaten</strong><small>Voltooide agent-runs verschijnen hier.</small></span>
            </div>
          )}
        </section>
      </div>

      <div className="dash-bottom">
        <section className="card dash-panel">
          <div className="dash-panel-head">
            <PanelTitle icon="performance" title="Systeemprestaties" sub={`Live · venster ${live.range}`} />
            <div className="perf-legend">
              <span><i style={{ background: "#1aa4ff" }} />CPU</span>
              <span><i style={{ background: "#9b5cff" }} />RAM</span>
              <span><i style={{ background: "#20e38d" }} />GPU</span>
              <span><i style={{ background: "#f0b429" }} />VRAM</span>
            </div>
          </div>
          <div className="perf-chart">
            <svg viewBox="0 0 640 168" width="100%" height="168" preserveAspectRatio="none" aria-hidden="true">
              <g stroke="#123142" strokeWidth="1">
                {[28, 56, 84, 112, 140].map((y) => <line key={y} x1="0" y1={y} x2="640" y2={y} />)}
                {[80, 160, 240, 320, 400, 480, 560].map((x) => <line key={x} x1={x} y1="0" x2={x} y2="168" />)}
              </g>
              <path d={chartPolyline(cpuSeries)} fill="none" stroke="#1aa4ff" strokeWidth="2" />
              <path d={chartPolyline(ramSeries)} fill="none" stroke="#9b5cff" strokeWidth="2" />
              <path d={chartPolyline(gpuSeries)} fill="none" stroke="#20e38d" strokeWidth="2" />
              <path d={chartPolyline(vramSeries)} fill="none" stroke="#f0b429" strokeWidth="2" />
            </svg>
          </div>
        </section>

        <section className="card dash-panel">
          <div className="dash-panel-head">
            <PanelTitle icon="distribution" title="Taakverdeling" sub="Framework-rollen & agenttypen" />
          </div>
          <div className="donut-wrap">
            <div className="donut">
              <svg viewBox="0 0 36 36">
                <circle cx="18" cy="18" r="14" fill="none" stroke="#223544" strokeWidth="4" />
                {donutSegs.map((seg, index) => (
                  <circle
                    key={`${seg.color}-${index}`}
                    cx="18"
                    cy="18"
                    r="14"
                    fill="none"
                    stroke={seg.color}
                    strokeWidth="4"
                    strokeDasharray={seg.dash}
                    strokeDashoffset={seg.offset}
                    transform="rotate(-90 18 18)"
                  />
                ))}
              </svg>
              <div className="donut-center"><strong>{donutTotal}</strong><span>Agents</span></div>
            </div>
            <div className="donut-legend">
              {live.donut.map((slice) => (
                <div key={slice.label}>
                  <span><i className="swatch" style={{ background: slice.color }} />{slice.label}</span>
                  <span>{donutTotal ? `${Math.round((slice.count / donutTotal) * 100)}%` : "—"}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>

      <section className="card agents-strip">
        <div className="agents-strip-head">
          <PanelTitle icon="warning" title="Actieve agents" sub={`${totalAgents} geregistreerd · live status`} />
          <button type="button" className="dash-mini-btn" data-fb-page="agents">Agents beheren</button>
        </div>
        <div className="agents-row agents-row-wrap">
          {live.agents.length ? live.agents.map((agent) => {
            const state = agentVisualState(agent.status, agent.health);
            return (
              <button
                key={agent.id}
                type="button"
                className="agent-chip"
                data-fb-page="agents"
                title={agent.current_task?.task_title || agent.description || agent.role}
              >
                <span className={`agent-icon ${state}`}><DashboardReferenceIcon name="agents" size={17} /></span>
                <div className="agent-chip-copy">
                  <div className="agent-chip-name">{agent.name}</div>
                  <div className="agent-chip-sub">{agent.role || agent.type || "Agent"}</div>
                  <div className={`agent-state ${state}`}><span className="dot" />{agentStateLabel(state)}</div>
                </div>
              </button>
            );
          }) : (
            <div className="agent-chip">
              <div className="agent-chip-copy">
                <div className="agent-chip-name">Geen agents geladen</div>
                <div className="agent-chip-sub">Open Agents om te vernieuwen</div>
              </div>
            </div>
          )}
        </div>
      </section>
    </>
  );

  const inspector = (
    <>
      <p className="quote dashboard-sovereign-quote">
        “Sovereign AI. Local power.
        <br />
        Infinite possibilities.”
      </p>

      <section className="insp-section">
        <div className="insp-head">
          <h3 className="insp-title">HADES Core</h3>
          <span className="tag">v{live.health?.version || "—"}</span>
        </div>
        <div className="insp-card">
          <div className="detail-row"><span className="k">Status</span><span className={`v${systemOnline ? " green" : ""}`}>{statusLabel}</span></div>
          <div className="detail-row"><span className="k">Mode</span><span className="v">{modeLabel}</span></div>
          <div className="detail-row"><span className="k">Host</span><span className="v">{live.hostname || "—"}</span></div>
          <div className="detail-row"><span className="k">OS</span><span className="v">{live.osLabel || "—"}</span></div>
          <div className="detail-row"><span className="k">Uptime</span><span className="v">{formatUptime(live.uptimeMs)}</span></div>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Model Runtime</h3>
        <div className="insp-card" style={{ marginTop: 8 }}>
          <div className="detail-row"><span className="k">Actief model</span><span className="v" title={live.health?.active_model || undefined}>{chatModel}</span></div>
          <div className="detail-row"><span className="k">Provider</span><span className="v">{live.agentsSummary?.provider || "LM Studio"}</span></div>
          <div className="detail-row"><span className="k">Modellen</span><span className="v">{live.health?.models ?? "—"}</span></div>
          <div className="detail-row"><span className="k">Status</span><span className={`v${modelReady ? " green" : ""}`}>{modelReady ? "● Ready" : live.health?.lm_studio === "connected" ? "● Geen model" : "● Offline"}</span></div>
          <div className="detail-row"><span className="k">Latency</span><span className="v">{latency != null ? `${Math.round(latency)}ms` : "—"}</span></div>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Agents</h3>
        <div className="insp-card" style={{ marginTop: 8 }}>
          <div className="detail-row"><span className="k">✦ Totaal</span><span className="v">{totalAgents || 0}</span></div>
          <div className="detail-row"><span className="k"><i className="mini-state active" />Actief</span><span className="v">{runningAgents}</span></div>
          <div className="detail-row"><span className="k"><i className="mini-state idle" />Idle</span><span className="v">{idleAgents}</span></div>
          <div className="detail-row"><span className="k"><i className="mini-state error" />Error</span><span className={`v${errorAgents ? " red" : ""}`}>{errorAgents}</span></div>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Snelle acties</h3>
        <div className="dash-quick" style={{ marginTop: 8 }}>
          {(
            [
              ["tasks", "Nieuwe taak", "plus"],
              ["model-training", "Model trainen", "training"],
              ["research", "Research starten", "magnify"],
              ["coding", "Code analyseren", "coding"],
              ["media", "Media genereren", "media"],
              ["trading", "Trading strategie", "trading"],
            ] as const
          ).map(([id, label, icon]) => (
            <button key={id} type="button" className="btn btn-outline" data-fb-page={id} onClick={() => onNavigate(id)}>
              <DashboardReferenceIcon name={icon} size={15} />
              {label}
            </button>
          ))}
        </div>
      </section>
    </>
  );

  const footer = (
    <footer className="dash-footer">
      <span>HADES FINALBETA v{live.health?.version || "—"}&nbsp;&nbsp;|&nbsp;&nbsp;Local AI Platform</span>
      <span className="motto">Build a smarter tomorrow. <b>━━</b></span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="dashboard"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="dash-app"
      mainClassName="dash-main"
      footer={footer}
    />
  );
}
