"use client";

import { useMemo, useState, type ReactNode } from "react";
import { FbIcon } from "../../icons";
import {
  RUN_DETAIL_TABS,
  RUN_LOG_LINES,
  RUN_METRICS_POINTS,
  RUN_STATS,
  mockRuns,
  type RunDetailTab,
  type TrainingRunStatus,
} from "../../mocks/model-training";

function statusClass(status: TrainingRunStatus) {
  if (status === "Actief") return "gold";
  if (status === "Voltooid") return "green";
  if (status === "Mislukt") return "warn";
  if (status === "Gepauzeerd") return "cyan";
  return "";
}

function metricsPath(points: number[]) {
  const w = 640;
  const h = 120;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const span = Math.max(max - min, 1);
  return points
    .map((p, i) => {
      const x = (i / Math.max(points.length - 1, 1)) * w;
      const y = 12 + ((max - p) / span) * (h - 28);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function TrainingTabRuns({ tabs }: { tabs?: ReactNode }) {
  const [selectedId, setSelectedId] = useState("run-llama");
  const [query, setQuery] = useState("");
  const [detailTab, setDetailTab] = useState<RunDetailTab>("Overzicht");
  const selected = mockRuns.find((r) => r.id === selectedId) ?? mockRuns[0]!;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return mockRuns;
    return mockRuns.filter(
      (run) =>
        run.name.toLowerCase().includes(q) ||
        run.model.toLowerCase().includes(q) ||
        run.dataset.toLowerCase().includes(q) ||
        run.status.toLowerCase().includes(q),
    );
  }, [query]);

  const line = metricsPath(RUN_METRICS_POINTS);
  const area = `${line} L640,120 L0,120 Z`;

  return (
    <div className="training-runs">
      <div className="page-head">
        <div>
          <h1 className="page-title">Runs</h1>
          <p className="page-sub">Monitor actieve en historische training runs, metrics en artifacts.</p>
        </div>
        <div className="page-actions">
          <label className="training-search">
            <FbIcon name="search" size={14} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Zoek runs, modellen, datasets..."
              aria-label="Zoek runs"
            />
          </label>
          <button type="button" className="btn btn-outline" data-toast="Filter runs (demo)">
            Alle runs
            <FbIcon name="chevron" size={12} />
          </button>
          <button className="btn btn-gold" type="button" data-toast="Nieuwe run (demo)">
            <FbIcon name="plus" size={14} />
            Nieuwe run
          </button>
        </div>
      </div>

      {tabs}

      <div className="training-stat-row training-stat-row-6">
        {RUN_STATS.map((stat) => (
          <div key={stat.label} className="card training-stat">
            <span className="training-stat-label">{stat.label}</span>
            <strong className={`training-stat-value ${stat.tone}`}>{stat.value}</strong>
          </div>
        ))}
      </div>

      <div className="training-runs-grid">
        <section className="card card-pad training-table-card">
          <div className="training-section-head">
            <div>
              <h2 className="section-title">Run Monitor</h2>
              <p className="section-sub">Selecteer een run voor details en metrics.</p>
            </div>
          </div>
          <div className="training-table-wrap">
            <table className="training-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Model</th>
                  <th>Dataset</th>
                  <th>Strategie</th>
                  <th>Voortgang</th>
                  <th>Status</th>
                  <th>ETA</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((run) => (
                  <tr
                    key={run.id}
                    className={run.id === selectedId ? "selected" : undefined}
                    onClick={() => setSelectedId(run.id)}
                  >
                    <td>
                      <strong>{run.name}</strong>
                    </td>
                    <td>{run.model}</td>
                    <td>{run.dataset}</td>
                    <td>{run.strategy}</td>
                    <td>
                      <div className="training-mini-progress">
                        <div className="bar">
                          <span style={{ width: `${run.progress}%` }} />
                        </div>
                        <span>{run.progress}%</span>
                      </div>
                    </td>
                    <td>
                      <span className={`tag ${statusClass(run.status)}`}>{run.status}</span>
                    </td>
                    <td className="mono">{run.eta}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="card card-pad training-run-details">
          <h2 className="section-title">Run details</h2>
          <p className="section-sub">{selected.name}</p>
          <nav className="training-subtabs" aria-label="Run detail weergaven">
            {RUN_DETAIL_TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                className={`training-subtab${detailTab === tab ? " active" : ""}`}
                onClick={() => setDetailTab(tab)}
              >
                {tab}
              </button>
            ))}
          </nav>

          {detailTab === "Overzicht" ? (
            <div className="training-run-panel">
              <div className="kv">
                <span>Status</span>
                <span className={`tag ${statusClass(selected.status)}`}>{selected.status}</span>
              </div>
              <div className="kv">
                <span>Loss</span>
                <span className="mono">{selected.loss}</span>
              </div>
              <div className="kv">
                <span>Throughput</span>
                <span>{selected.throughput}</span>
              </div>
              <div className="kv">
                <span>Score</span>
                <span>{selected.score}</span>
              </div>
              <div className="kv">
                <span>Gestart</span>
                <span>{selected.started}</span>
              </div>
              <div className="training-quality">
                <div className="training-quality-top">
                  <span>Voortgang</span>
                  <strong>{selected.progress}%</strong>
                </div>
                <div className="bar">
                  <span style={{ width: `${selected.progress}%` }} />
                </div>
              </div>
            </div>
          ) : null}

          {detailTab === "Metrics" ? (
            <div className="training-run-panel">
              <div className="kv">
                <span>Train loss</span>
                <span className="mono">{selected.loss}</span>
              </div>
              <div className="kv">
                <span>Piek VRAM</span>
                <span>13.6 GB</span>
              </div>
              <div className="kv">
                <span>Bottleneck</span>
                <span className="orange">VRAM 71%</span>
              </div>
              <div className="kv">
                <span>Tokens/s</span>
                <span>{selected.throughput}</span>
              </div>
            </div>
          ) : null}

          {detailTab === "Parameters" ? (
            <div className="training-run-panel">
              <div className="kv">
                <span>Strategie</span>
                <span>{selected.strategy}</span>
              </div>
              <div className="kv">
                <span>Mode</span>
                <span>QLoRA · r=64 · α=128</span>
              </div>
              <div className="kv">
                <span>LR</span>
                <span className="mono">2e-4</span>
              </div>
              <div className="kv">
                <span>Batch / accum</span>
                <span>4 / 8</span>
              </div>
              <div className="kv">
                <span>Seq length</span>
                <span>4096</span>
              </div>
            </div>
          ) : null}

          {detailTab === "Logboek" ? (
            <div className="training-run-log">
              {RUN_LOG_LINES.map((lineText) => (
                <div key={lineText} className="mono">
                  {lineText}
                </div>
              ))}
            </div>
          ) : null}
        </aside>
      </div>

      <div className="training-bottom-3">
        <section className="card card-pad training-chart-card">
          <div className="chart-head">
            <span>Metrics timeline · loss (geselecteerde run)</span>
            <span>Smoothing: 0.6</span>
          </div>
          <svg className="chart-svg" viewBox="0 0 640 120" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="runLossFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f0b429" stopOpacity="0.22" />
                <stop offset="100%" stopColor="#f0b429" stopOpacity="0" />
              </linearGradient>
            </defs>
            <g stroke="#1a2b3a" strokeWidth="1">
              <line x1="0" y1="20" x2="640" y2="20" />
              <line x1="0" y1="50" x2="640" y2="50" />
              <line x1="0" y1="80" x2="640" y2="80" />
              <line x1="0" y1="110" x2="640" y2="110" />
            </g>
            <path d={area} fill="url(#runLossFill)" />
            <path d={line} fill="none" stroke="#f0b429" strokeWidth="2.2" strokeLinecap="round" />
          </svg>
        </section>

        <section className="card card-pad">
          <h2 className="section-title">Artifacts</h2>
          <p className="section-sub">Output van de geselecteerde run.</p>
          <div className="artifact">
            <FbIcon name="folder" size={14} />
            <div className="artifact-body">
              <div className="artifact-name">Adapter output</div>
              <div className="artifact-path">./outputs/{selected.name.toLowerCase()}</div>
            </div>
            <span className="tag gold">LoRA</span>
          </div>
          <div className="artifact">
            <FbIcon name="file" size={14} />
            <div className="artifact-body">
              <div className="artifact-name">Run config</div>
              <div className="artifact-path">config.json</div>
            </div>
            <span className="tag">JSON</span>
          </div>
          <div className="artifact">
            <FbIcon name="chart" size={14} />
            <div className="artifact-body">
              <div className="artifact-name">Metrics</div>
              <div className="artifact-path">metrics.jsonl</div>
            </div>
            <span className="tag">Log</span>
          </div>
        </section>

        <section className="card card-pad">
          <h2 className="section-title">Events</h2>
          <p className="section-sub">Recente run-gebeurtenissen.</p>
          <div className="training-activity">
            <div className="training-activity-row">
              <span className="training-activity-dot gold" />
              <div className="grow">
                <strong>Checkpoint opgeslagen</strong>
                <div className="muted">stap {selected.progress > 0 ? Math.round(selected.progress * 100) : 0}</div>
              </div>
              <span className="muted">6m</span>
            </div>
            <div className="training-activity-row">
              <span className="training-activity-dot cyan" />
              <div className="grow">
                <strong>Eval sample batch</strong>
                <div className="muted">score pending</div>
              </div>
              <span className="muted">18m</span>
            </div>
            <div className="training-activity-row">
              <span className="training-activity-dot green" />
              <div className="grow">
                <strong>Dataset mount OK</strong>
                <div className="muted">{selected.dataset}</div>
              </div>
              <span className="muted">1u</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

export function TrainingRunsInspector() {
  return (
    <>
      <p className="quote">
        “Measure twice.
        <br />
        Train once.”
      </p>
      <section className="insp-section">
        <h3 className="insp-title">Run Runtime</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Device</span>
            <span className="v">cuda:0</span>
          </div>
          <div className="detail-row">
            <span className="k">Worker</span>
            <span className="v">train-worker-01</span>
          </div>
          <div className="detail-row">
            <span className="k">ATME</span>
            <span className="tag green">Actief</span>
          </div>
          <div className="detail-row">
            <span className="k">Uptime</span>
            <span className="v">0u 28m</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Scheduler</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Policy</span>
            <span className="v">FIFO + priority</span>
          </div>
          <div className="detail-row">
            <span className="k">Max concurrent</span>
            <span className="v">2</span>
          </div>
          <div className="detail-row">
            <span className="k">Next slot</span>
            <span className="v">~42m</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Queue</h3>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Waiting</span>
            <span className="v">1</span>
          </div>
          <div className="detail-row">
            <span className="k">Paused</span>
            <span className="v">0</span>
          </div>
          <div className="detail-row">
            <span className="k">Failed retry</span>
            <span className="v">1</span>
          </div>
        </div>
      </section>
      <section className="insp-section">
        <h3 className="insp-title">Snelle acties</h3>
        <div className="insp-card training-insp-actions">
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Pause run (demo)">
            <FbIcon name="pause" size={13} />
            Pause
          </button>
          <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Resume run (demo)">
            <FbIcon name="play" size={13} />
            Resume
          </button>
          <button className="btn btn-sm btn-danger btn-block" type="button" data-toast="Stop run (demo)">
            <FbIcon name="stop" size={13} />
            Stop
          </button>
        </div>
      </section>
    </>
  );
}
