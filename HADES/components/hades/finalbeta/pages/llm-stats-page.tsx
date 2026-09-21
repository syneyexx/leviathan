/** FINALBETA LLM Stats — live models/gateway/agents/tasks + dashboard telemetrie. */
"use client";

import { useMemo, useState } from "react";
import { useHadesLlmStats } from "@/components/hades/features/stats/hooks/useHadesLlmStats";
import { chartPolyline, donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };
type StatsPeriod = "24h" | "7d" | "30d";

const STATS_PERIODS: Array<{ id: StatsPeriod; label: string }> = [
  { id: "24h", label: "Laatste 24 uur" },
  { id: "7d", label: "Laatste 7 dagen" },
  { id: "30d", label: "Laatste 30 dagen" },
];

const PERF_LEGEND = [
  { id: "cpu", label: "CPU", color: "#38bdf8" },
  { id: "ram", label: "RAM", color: "#22c55e" },
  { id: "gpu", label: "GPU", color: "#eab94f" },
  { id: "vram", label: "VRAM", color: "#a78bfa" },
];

const CHART_W = 640;
const CHART_H = 168;

function padSeries(values: number[], min = 2): number[] {
  if (values.length >= min) return values;
  if (!values.length) return [0, 0];
  return [...values, values[values.length - 1]!];
}

export function LlmStatsPage({ onNavigate }: Props) {
  const [period, setPeriod] = useState<StatsPeriod>("24h");
  const [periodOpen, setPeriodOpen] = useState(false);
  const live = useHadesLlmStats();

  const periodLabel = STATS_PERIODS.find((p) => p.id === period)?.label ?? "Laatste 24 uur";
  const donut = useMemo(() => donutSegments([...live.taskSlices]), [live.taskSlices]);
  const taskTotal = live.taskSlices.reduce((s, x) => s + x.count, 0);

  const cpuPath = chartPolyline(padSeries(live.perfSeries.cpu), CHART_W, CHART_H);
  const ramPath = chartPolyline(padSeries(live.perfSeries.ram), CHART_W, CHART_H);
  const gpuPath = chartPolyline(padSeries(live.perfSeries.gpu), CHART_W, CHART_H);
  const vramPath = chartPolyline(padSeries(live.perfSeries.vram), CHART_W, CHART_H);

  const modelSummary = [
    { id: "active", label: "Actief model", value: live.activeModel || "—" },
    {
      id: "count",
      label: "Ontdekte modellen",
      value: live.loading ? "…" : String(live.modelRows.length),
    },
    {
      id: "queue",
      label: "Gateway queue",
      value: live.gateway?.queue_depth != null ? String(live.gateway.queue_depth) : "—",
    },
    {
      id: "active-calls",
      label: "Actieve calls",
      value: live.gateway?.active_count != null ? String(live.gateway.active_count) : "—",
    },
  ];

  const body = (
    <div className="mc-page stats-page" data-live="llm-stats">
      <MediaWelcome
        title="Statistieken"
        subtitle="Live prestaties, gebruik en trends van het HADES platform."
        quote="Data today. A smarter tomorrow."
        right={
          <div className="stats-period">
            <button
              type="button"
              className="stats-period-btn"
              aria-expanded={periodOpen}
              onClick={() => setPeriodOpen((v) => !v)}
            >
              <FbIcon name="calendar" size={14} />
              <span>{periodLabel}</span>
              <FbIcon name="chevron" size={12} className="stats-period-chevron" />
            </button>
            {periodOpen ? (
              <div className="stats-period-menu" role="listbox">
                {STATS_PERIODS.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className={opt.id === period ? "active" : undefined}
                    role="option"
                    aria-selected={opt.id === period}
                    onClick={() => {
                      setPeriod(opt.id);
                      setPeriodOpen(false);
                      void live.refresh();
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        }
      />

      {live.error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12 }}>
          <strong>Stats laden mislukt.</strong> {live.error}{" "}
          <button type="button" className="mc-link-btn" onClick={() => void live.refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="stats-kpi-row">
        {live.kpis.map((kpi) => (
          <article key={kpi.id} className="mc-kpi stats-kpi">
            <div className="stats-kpi-top">
              <span className={`stats-kpi-ico ${kpi.tone}`}>
                <FbIcon name={kpi.icon as "database"} size={14} />
              </span>
              <span className="mc-kpi-label">{kpi.label}</span>
            </div>
            <div className="mc-kpi-value">{live.loading && kpi.value === "—" ? "…" : kpi.value}</div>
            {"progress" in kpi && typeof kpi.progress === "number" ? (
              <div className="mc-progress stats-progress">
                <span style={{ width: `${Math.max(0, Math.min(100, kpi.progress))}%` }} />
              </div>
            ) : null}
          </article>
        ))}
      </div>

      <div className="stats-mid">
        <section className="mc-panel stats-perf">
          <div className="mc-panel-head">
            <div>
              <h2>Systeemprestaties</h2>
              <p>CPU · RAM · GPU · VRAM (live telemetrie)</p>
            </div>
            <div className="stats-legend">
              {PERF_LEGEND.map((item) => (
                <span key={item.id}>
                  <i style={{ background: item.color }} />
                  {item.label}
                </span>
              ))}
            </div>
          </div>
          {live.perfSeries.cpu.length ? (
            <div className="stats-chart">
              <div className="stats-chart-y" aria-hidden="true">
                <span>100%</span>
                <span>75%</span>
                <span>50%</span>
                <span>25%</span>
                <span>0%</span>
              </div>
              <div className="stats-chart-plot">
                <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" aria-hidden="true">
                  {[0.25, 0.5, 0.75].map((t) => (
                    <line
                      key={t}
                      x1="0"
                      x2={CHART_W}
                      y1={CHART_H * t}
                      y2={CHART_H * t}
                      stroke="rgba(90,140,180,0.18)"
                      strokeWidth="1"
                    />
                  ))}
                  <path d={cpuPath} fill="none" stroke="#38bdf8" strokeWidth="2" />
                  <path d={ramPath} fill="none" stroke="#22c55e" strokeWidth="2" />
                  <path d={gpuPath} fill="none" stroke="#eab94f" strokeWidth="2" />
                  <path d={vramPath} fill="none" stroke="#a78bfa" strokeWidth="2" />
                </svg>
                <div className="stats-chart-x" aria-hidden="true">
                  <span>−</span>
                  <span />
                  <span />
                  <span>nu</span>
                </div>
              </div>
            </div>
          ) : (
            <p className="muted" style={{ padding: "12px 16px" }}>
              Nog geen telemetrie — wacht op health/native samples.
            </p>
          )}
        </section>

        <section className="mc-panel stats-activity">
          <div className="mc-panel-head">
            <div>
              <h2>Gateway status</h2>
              <p>Model gateway runtime</p>
            </div>
          </div>
          <div className="stats-activity-grid">
            <div className="stats-activity-card">
              <div className="stats-activity-label">Actief model</div>
              <div className="stats-activity-value">{live.activeModel || "—"}</div>
            </div>
            <div className="stats-activity-card">
              <div className="stats-activity-label">Queue depth</div>
              <div className="stats-activity-value">
                {live.gateway?.queue_depth != null ? String(live.gateway.queue_depth) : "—"}
              </div>
            </div>
            <div className="stats-activity-card">
              <div className="stats-activity-label">Actieve calls</div>
              <div className="stats-activity-value">
                {live.gateway?.active_count != null ? String(live.gateway.active_count) : "—"}
              </div>
            </div>
            <div className="stats-activity-card">
              <div className="stats-activity-label">LM Studio</div>
              <div className="stats-activity-value">
                {live.health?.lm_studio === "connected" ? "Online" : "Offline"}
              </div>
            </div>
          </div>
        </section>
      </div>

      <div className="stats-models-agents">
        <section className="mc-panel stats-models">
          <div className="mc-panel-head">
            <div>
              <h2>Model statistieken</h2>
              <p>Ontdekte modellen via LM Studio / gateway</p>
            </div>
          </div>
          <div className="stats-model-summary">
            {modelSummary.map((item) => (
              <div key={item.id}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
          <div className="stats-table-wrap">
            <div className="stats-table-title">Actieve modellen</div>
            {live.loading && !live.modelRows.length ? (
              <p className="muted" style={{ padding: 12 }}>
                Modellen laden…
              </p>
            ) : !live.modelRows.length ? (
              <p className="muted" style={{ padding: 12 }}>
                Nog geen modellen ontdekt. Start LM Studio of controleer de verbinding.
              </p>
            ) : (
              <table className="mc-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Requests</th>
                    <th>Latency</th>
                    <th>Succes</th>
                  </tr>
                </thead>
                <tbody>
                  {live.modelRows.map((model) => (
                    <tr key={model.id}>
                      <td>
                        <span className="stats-model-name">
                          <span className="stats-model-ico">
                            <FbIcon name="database" size={12} />
                          </span>
                          {model.name}
                        </span>
                      </td>
                      <td>
                        <span className={`mc-pill ${model.status === "Actief" ? "green" : "blue"}`}>
                          {model.status}
                        </span>
                      </td>
                      <td>{model.requests}</td>
                      <td>{model.latency}</td>
                      <td>
                        <span className="stats-success mid">—</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <section className="mc-panel stats-agents">
          <div className="mc-panel-head">
            <div>
              <h2>Agent status</h2>
              <p>Live agent registry</p>
            </div>
          </div>
          {!live.agentRows.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Agents laden…" : "Nog geen agents geregistreerd."}
            </p>
          ) : (
            <table className="mc-table stats-agents-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Health</th>
                  <th>Enabled</th>
                </tr>
              </thead>
              <tbody>
                {live.agentRows.map((agent, index) => (
                  <tr key={agent.id}>
                    <td className="stats-rank">{index + 1}</td>
                    <td>
                      <span className="stats-agent-name">
                        <span className="stats-agent-ico">
                          <FbIcon name="users" size={12} />
                        </span>
                        {agent.name}
                      </span>
                    </td>
                    <td>{agent.status}</td>
                    <td>{agent.health}</td>
                    <td className={agent.enabled ? "stats-success hi" : ""}>
                      {agent.enabled ? "ja" : "nee"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <div className="stats-bottom">
        <section className="mc-panel stats-donut-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Taakverdeling</h2>
              <p>Status van Work Runtime taken</p>
            </div>
          </div>
          <div className="stats-donut-wrap">
            <div className="stats-donut">
              <svg viewBox="0 0 42 42">
                <circle cx="21" cy="21" r="14" fill="none" stroke="#223544" strokeWidth="5" />
                {donut.map((seg, index) => (
                  <circle
                    key={`${seg.color}-${index}`}
                    cx="21"
                    cy="21"
                    r="14"
                    fill="none"
                    stroke={seg.color}
                    strokeWidth="5"
                    strokeDasharray={seg.dash}
                    strokeDashoffset={seg.offset}
                    transform="rotate(-90 21 21)"
                  />
                ))}
              </svg>
              <div className="stats-donut-center">
                <strong>{taskTotal}</strong>
                <span>taken</span>
              </div>
            </div>
            <ul className="stats-donut-legend">
              {live.taskSlices.map((slice) => (
                <li key={slice.label}>
                  <i style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <b>{taskTotal ? `${Math.round((slice.count / taskTotal) * 100)}%` : "0%"}</b>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="mc-panel stats-events">
          <div className="mc-panel-head">
            <div>
              <h2>Runtime</h2>
              <p>Health snapshot</p>
            </div>
            <button type="button" className="mc-link-btn" onClick={() => void live.refresh()}>
              Vernieuwen
            </button>
          </div>
          <table className="mc-table stats-events-table">
            <thead>
              <tr>
                <th>Sleutel</th>
                <th>Waarde</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Backend</td>
                <td>{live.health?.status || "—"}</td>
              </tr>
              <tr>
                <td>LM Studio</td>
                <td>{live.health?.lm_studio || "—"}</td>
              </tr>
              <tr>
                <td>Actief model</td>
                <td>{live.activeModel || "—"}</td>
              </tr>
              <tr>
                <td>Periodefilter</td>
                <td>{periodLabel} (telemetrie-venster volgt beschikbare samples)</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Data today. A smarter tomorrow.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Stats Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">models · gateway · agents · tasks · health</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className={`v ${live.error ? "gold" : "green"}`}>
              {live.loading ? "Laden…" : live.error ? "Fout" : "Live"}
            </span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Modellen</span>
            <span className="v">{live.modelRows.length}</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Agents</span>
            <span className="v">{live.agentRows.length}</span>
          </div>
        </div>
      </section>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Quick Actions</h3>
        <div className="stats-quick-grid">
          <button type="button" className="stats-quick-btn" onClick={() => void live.refresh()}>
            <FbIcon name="bolt" size={16} />
            <span>Vernieuwen</span>
          </button>
          <button type="button" className="stats-quick-btn" data-fb-page="models">
            <FbIcon name="database" size={16} />
            <span>Modellen</span>
          </button>
          <button type="button" className="stats-quick-btn" data-fb-page="agents">
            <FbIcon name="users" size={16} />
            <span>Agents</span>
          </button>
          <button type="button" className="stats-quick-btn" data-fb-page="performance">
            <FbIcon name="chart" size={16} />
            <span>Performance</span>
          </button>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="llm-stats"
      appClassName="mc-app stats-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
