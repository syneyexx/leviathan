"use client";

import { useMemo, useState } from "react";
import { chartPolyline, sparkPath } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import {
  TRAINING_BASE_MODEL,
  TRAINING_CHECKPOINTS,
  TRAINING_DATASET_PREVIEW,
  TRAINING_DATASET_ROWS,
  TRAINING_DATASET_SETTINGS,
  TRAINING_HARDWARE,
  TRAINING_LOG_LINES,
  TRAINING_MONITOR,
  TRAINING_PIXEL_DATASET_PREVIEW_TABS,
  TRAINING_PIXEL_TABS,
  TRAINING_QUEUE,
  TRAINING_RUN_FORM,
  TRAINING_SAFETY_NUMBERS,
  TRAINING_SAFETY_TOGGLES,
  TRAINING_STATUS_CARDS,
  type TrainingDatasetPreviewTab,
  type TrainingPixelTab,
} from "../mocks/training-pixel";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function MetaMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        d="M7 8c3-4 7-4 10 0s-3 8-5 8-2-4-5-8Zm0 8c3 4 7 4 10 0s-3-8-5-8-2 4-5 8Z"
      />
    </svg>
  );
}

function PulseWave() {
  const d = chartPolyline([4, 8, 6, 14, 10, 18, 8, 16, 12, 10, 14, 8], 64, 18);
  return (
    <svg className="trn-stat-pulse" viewBox="0 0 64 18" aria-hidden="true">
      <path d={d} fill="none" stroke="#3ac7ee" strokeWidth="1.6" />
    </svg>
  );
}

function TrnLineChart({
  series,
  width = 320,
  height = 56,
  strokes = ["#3ac7ee", "#eab94f"],
}: {
  series: number[][];
  width?: number;
  height?: number;
  strokes?: string[];
}) {
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Grafiek">
      <line x1="0" y1={height - 1} x2={width} y2={height - 1} stroke="rgba(58,199,238,0.15)" />
      {series.map((values, i) => (
        <path
          key={i}
          d={chartPolyline(values, width, height - 4)}
          fill="none"
          stroke={strokes[i] ?? strokes[0]}
          strokeWidth="1.8"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

export function ModelTrainingPage({ onNavigate }: Props) {
  const [tab, setTab] = useState<TrainingPixelTab>("General");
  const [dsPreviewTab, setDsPreviewTab] = useState<TrainingDatasetPreviewTab>("Voorbeeld");
  const [toggles, setToggles] = useState(() =>
    Object.fromEntries(TRAINING_SAFETY_TOGGLES.map((t) => [t.id, t.on])) as Record<string, boolean>,
  );

  const lossChart = useMemo(
    () => [TRAINING_MONITOR.lossSeries.train, TRAINING_MONITOR.lossSeries.val],
    [],
  );
  const lrChart = useMemo(() => [TRAINING_MONITOR.lrSeries], []);

  const body = (
    <div className="trn-page">
      <header className="trn-hero">
        <div className="trn-hero-copy">
          <h1>MODEL TRAINING</h1>
          <p className="trn-hero-tag">ADAPT. ALIGN. TRANSCEND.</p>
        </div>
        <blockquote className="trn-hero-quote">
          Transform data into intelligence.
          <cite>— LEVIATHAN</cite>
        </blockquote>
      </header>

      <div className="trn-toolbar">
        <nav className="trn-tabs" aria-label="Training secties">
          {TRAINING_PIXEL_TABS.map((item) => (
            <button
              key={item}
              type="button"
              className={`trn-tab${tab === item ? " active" : ""}`}
              onClick={() => setTab(item)}
              data-toast={item === "General" ? undefined : `${item} (demo)`}
            >
              {item}
            </button>
          ))}
        </nav>
        <button type="button" className="trn-quick" data-toast="Snelle acties menu">
          Snelle acties
          <FbIcon name="chevron" size={14} />
        </button>
      </div>

      <div className="trn-stats">
        {TRAINING_STATUS_CARDS.map((card) => (
          <article key={card.id} className="trn-stat">
            <div className="trn-stat-top">
              <div>
                <div className="trn-stat-label">{card.label}</div>
                <div
                  className={`trn-stat-value${card.tone === "gold" ? " gold" : ""}${card.tone === "cyan" ? " cyan" : ""}${card.tone === "green" ? " green" : ""}`}
                >
                  {card.value}
                </div>
              </div>
              {card.icon === "meta" ? (
                <span className="trn-stat-ico" style={{ color: "#eab94f" }}>
                  <MetaMark />
                </span>
              ) : card.icon ? (
                <span className="trn-stat-ico">
                  <FbIcon name={card.icon === "pulse" ? "line" : card.icon} size={16} />
                </span>
              ) : null}
            </div>
            <div className={`trn-stat-hint${card.id === "queue" ? " warn" : ""}`}>{card.hint}</div>
            {card.spark ? (
              <svg className="trn-stat-spark" viewBox="0 0 72 28" aria-hidden="true">
                <path d={sparkPath(card.spark, 72, 28)} fill="none" stroke="#3ac7ee" strokeWidth="1.6" />
              </svg>
            ) : null}
            {card.icon === "pulse" ? <PulseWave /> : null}
          </article>
        ))}
      </div>

      <div className="trn-work">
        <div className="trn-col">
          <section className="trn-panel">
            <div className="trn-panel-head">
              <h2 className="trn-panel-title">Training run</h2>
            </div>
            <div className="trn-panel-body">
              <div className="trn-form-grid">
                <label className="trn-field">
                  <span>Run naam</span>
                  <input className="trn-input" readOnly value={TRAINING_RUN_FORM.name} />
                </label>
                <label className="trn-field">
                  <span>Project</span>
                  <select className="trn-select" defaultValue={TRAINING_RUN_FORM.project}>
                    <option>{TRAINING_RUN_FORM.project}</option>
                  </select>
                </label>
                <label className="trn-field span-2">
                  <span>Uitvoer directory</span>
                  <div className="trn-input-dir">
                    <input className="trn-input" readOnly value={TRAINING_RUN_FORM.outputDir} />
                    <button type="button" className="trn-icon-btn" aria-label="Map openen" data-toast="Map openen (demo)">
                      <FbIcon name="folder" size={14} />
                    </button>
                  </div>
                </label>
                <label className="trn-field span-2">
                  <span>Beschrijving</span>
                  <textarea className="trn-textarea" readOnly value={TRAINING_RUN_FORM.description} />
                </label>
                <div className="trn-field span-2">
                  <span>Tags</span>
                  <div className="trn-tags">
                    {TRAINING_RUN_FORM.tags.map((tag) => (
                      <span key={tag} className="trn-tag">{tag}</span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="trn-panel">
            <div className="trn-panel-head">
              <h2 className="trn-panel-title">Dataset(s)</h2>
              <div className="trn-panel-actions">
                <button type="button" className="trn-link-btn" data-toast="Dataset bibliotheek">
                  Dataset bibliotheek
                </button>
              </div>
            </div>
            <div className="trn-panel-body">
              <div className="trn-table-wrap">
                <table className="trn-table">
                  <thead>
                    <tr>
                      <th aria-label="Selectie" />
                      <th>Dataset</th>
                      <th>Split</th>
                      <th>Voorbeelden</th>
                      <th>Tokens</th>
                    </tr>
                  </thead>
                  <tbody>
                    {TRAINING_DATASET_ROWS.map((row) => (
                      <tr key={row.id}>
                        <td>
                          <input type="checkbox" checked={row.selected} readOnly aria-label={`Selecteer ${row.name}`} />
                        </td>
                        <td className="name">{row.name}</td>
                        <td>{row.split}</td>
                        <td>{row.examples}</td>
                        <td>{row.tokens}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="trn-ds-foot">
                <label className="trn-field">
                  <span>Validatie set ({TRAINING_DATASET_SETTINGS.validationPct}%)</span>
                  <input type="range" min={0} max={20} value={TRAINING_DATASET_SETTINGS.validationPct} readOnly />
                </label>
                <label className="trn-field">
                  <span>Format template</span>
                  <select className="trn-select" defaultValue={TRAINING_DATASET_SETTINGS.formatTemplate}>
                    <option>{TRAINING_DATASET_SETTINGS.formatTemplate}</option>
                  </select>
                </label>
              </div>
              <div className="trn-mini-tabs" role="tablist" aria-label="Dataset preview">
                {TRAINING_PIXEL_DATASET_PREVIEW_TABS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    role="tab"
                    className={`trn-mini-tab${dsPreviewTab === item ? " active" : ""}`}
                    aria-selected={dsPreviewTab === item}
                    onClick={() => setDsPreviewTab(item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
              {dsPreviewTab === "Voorbeeld" ? (
                <pre className="trn-code">{TRAINING_DATASET_PREVIEW}</pre>
              ) : (
                <p className="trn-stat-hint" style={{ marginTop: 8 }}>
                  {dsPreviewTab === "Statistieken"
                    ? "Gem. tokens/voorbeeld: 342 · max seq: 4,096 · duplicaten: 0.02%"
                    : "Token histogram: piek rond 180–420 tokens; lange staart tot 8k."}
                </p>
              )}
            </div>
          </section>
        </div>

        <div className="trn-col">
          <section className="trn-panel">
            <div className="trn-panel-head">
              <h2 className="trn-panel-title">Base model</h2>
            </div>
            <div className="trn-panel-body trn-model-grid">
              <div className="trn-form-grid">
                <label className="trn-field span-2">
                  <span>Model</span>
                  <select className="trn-select" defaultValue={TRAINING_BASE_MODEL.model}>
                    <option>{TRAINING_BASE_MODEL.model}</option>
                  </select>
                </label>
                <label className="trn-field">
                  <span>Provider</span>
                  <input className="trn-input" readOnly value={TRAINING_BASE_MODEL.provider} />
                </label>
                <label className="trn-field">
                  <span>Parameters</span>
                  <input className="trn-input" readOnly value={TRAINING_BASE_MODEL.parameters} />
                </label>
                <label className="trn-field">
                  <span>Context lengte</span>
                  <input className="trn-input" readOnly value={TRAINING_BASE_MODEL.context} />
                </label>
                <label className="trn-field">
                  <span>Quantisatie</span>
                  <input className="trn-input" readOnly value={TRAINING_BASE_MODEL.quant} />
                </label>
              </div>
              <aside className="trn-model-info">
                <div className="trn-model-emblem" aria-hidden="true">
                  <FbIcon name="trident" size={26} />
                </div>
                <strong style={{ fontSize: 10, color: "#eab94f" }}>Model info</strong>
                <dl>
                  <dt>Architectuur</dt>
                  <dd>{TRAINING_BASE_MODEL.info.architecture}</dd>
                  <dt>Licentie</dt>
                  <dd>{TRAINING_BASE_MODEL.info.license}</dd>
                  <dt>Familie</dt>
                  <dd>{TRAINING_BASE_MODEL.info.family}</dd>
                </dl>
                <p style={{ margin: 0, fontSize: 9, color: "#718a96", lineHeight: 1.35 }}>{TRAINING_BASE_MODEL.info.notes}</p>
              </aside>
            </div>
          </section>

          <section className="trn-panel">
            <div className="trn-panel-head">
              <h2 className="trn-panel-title">Hardware &amp; runtime</h2>
            </div>
            <div className="trn-panel-body trn-model-grid">
              <div className="trn-form-grid">
                <label className="trn-field span-2">
                  <span>Compute device</span>
                  <select className="trn-select" defaultValue={TRAINING_HARDWARE.device}>
                    <option>{TRAINING_HARDWARE.device}</option>
                  </select>
                </label>
                <label className="trn-field">
                  <span>VRAM per GPU</span>
                  <input className="trn-input" readOnly value={TRAINING_HARDWARE.vramPerGpu} />
                </label>
                <label className="trn-field">
                  <span>Aantal GPUs</span>
                  <input className="trn-input" readOnly value={TRAINING_HARDWARE.gpuCount} />
                </label>
                <label className="trn-field">
                  <span>Batch size</span>
                  <input className="trn-input" readOnly value={TRAINING_HARDWARE.batchSize} />
                </label>
                <label className="trn-field">
                  <span>Grad accum</span>
                  <input className="trn-input" readOnly value={TRAINING_HARDWARE.gradAccum} />
                </label>
              </div>
              <div className="trn-usage">
                <strong style={{ fontSize: 10, color: "#eab94f", letterSpacing: "0.06em" }}>HUIDIG GEBRUIK</strong>
                {TRAINING_HARDWARE.usage.map((row) => (
                  <div key={row.label} className="trn-usage-row">
                    <span>{row.label}</span>
                    <span>{row.value}</span>
                    <div className="trn-bar">
                      <span style={{ width: `${row.pct}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="trn-panel">
            <div className="trn-panel-head">
              <h2 className="trn-panel-title">Veiligheid &amp; controles</h2>
            </div>
            <div className="trn-panel-body trn-safety-grid">
              <div>
                {TRAINING_SAFETY_TOGGLES.map((item) => (
                  <div key={item.id} className="trn-toggle-row">
                    <div>
                      <b>{item.label}</b>
                      <span>{item.description}</span>
                    </div>
                    <button
                      type="button"
                      className={`trn-switch${toggles[item.id] ? " on" : ""}`}
                      role="switch"
                      aria-checked={toggles[item.id]}
                      aria-label={item.label}
                      onClick={() => setToggles((prev) => ({ ...prev, [item.id]: !prev[item.id] }))}
                    />
                  </div>
                ))}
              </div>
              <div className="trn-form-grid">
                <label className="trn-field">
                  <span>Checkpoint interval</span>
                  <input className="trn-input" readOnly value={TRAINING_SAFETY_NUMBERS.checkpointInterval} />
                </label>
                <label className="trn-field">
                  <span>Maximale epochs</span>
                  <input className="trn-input" readOnly value={TRAINING_SAFETY_NUMBERS.maxEpochs} />
                </label>
                <label className="trn-field">
                  <span>Early stopping patience</span>
                  <input className="trn-input" readOnly value={TRAINING_SAFETY_NUMBERS.earlyStoppingPatience} />
                </label>
                <label className="trn-field">
                  <span>Max. training tijd (u)</span>
                  <input className="trn-input" readOnly value={TRAINING_SAFETY_NUMBERS.maxTrainingHours} />
                </label>
              </div>
            </div>
          </section>

          <section className="trn-panel">
            <div className="trn-panel-head">
              <h2 className="trn-panel-title">Checkpoints ({TRAINING_CHECKPOINTS.length})</h2>
            </div>
            <div className="trn-panel-body">
              <div className="trn-table-wrap" style={{ maxHeight: 100 }}>
                <table className="trn-table trn-ckpt-table">
                  <thead>
                    <tr>
                      <th>Naam</th>
                      <th>Stap</th>
                      <th>Grootte</th>
                      <th>Tijd</th>
                    </tr>
                  </thead>
                  <tbody>
                    {TRAINING_CHECKPOINTS.map((ck) => (
                      <tr key={ck.name}>
                        <td className="name">{ck.name}</td>
                        <td>{ck.step}</td>
                        <td>{ck.size}</td>
                        <td>{ck.when}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </div>
      </div>

      <div className="trn-bottom">
        <section className="trn-panel">
          <div className="trn-panel-head">
            <h2 className="trn-panel-title">Training logs</h2>
            <span className="trn-live">
              <span className="trn-live-dot" aria-hidden="true" />
              Live
            </span>
          </div>
          <div className="trn-panel-body trn-logs" role="log" aria-live="polite">
            {TRAINING_LOG_LINES.map((line) => (
              <div key={`${line.time}-${line.message}`} className="trn-log-line">
                <span className="trn-log-time">{line.time}</span>
                <span className={`trn-log-level ${line.level.toLowerCase()}`}>{line.level}</span>
                <span>{line.message}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = (
    <div className="trn-insp">
      <section className="trn-insp-panel">
        <div className="trn-insp-head">
          <h3 className="trn-insp-title">Training monitor</h3>
          {TRAINING_MONITOR.live ? (
            <span className="trn-live">
              <span className="trn-live-dot" aria-hidden="true" />
              Live
            </span>
          ) : null}
        </div>

        <div className="trn-prog-block">
          <div className="trn-prog-label">
            <span>Epoch</span>
            <strong>
              {TRAINING_MONITOR.epoch.current} / {TRAINING_MONITOR.epoch.total} ({TRAINING_MONITOR.epoch.pct}%)
            </strong>
          </div>
          <div className="trn-prog-track">
            <span style={{ width: `${TRAINING_MONITOR.epoch.pct}%` }} />
          </div>
        </div>
        <div className="trn-prog-block">
          <div className="trn-prog-label">
            <span>Stappen</span>
            <strong>
              {TRAINING_MONITOR.steps.current.toLocaleString("nl-NL")} /{" "}
              {TRAINING_MONITOR.steps.total.toLocaleString("nl-NL")} ({TRAINING_MONITOR.steps.pct}%)
            </strong>
          </div>
          <div className="trn-prog-track">
            <span style={{ width: `${TRAINING_MONITOR.steps.pct}%` }} />
          </div>
        </div>

        <dl className="trn-time-row">
          <div>
            <dt>Verstreken tijd</dt>
            <dd>{TRAINING_MONITOR.elapsed}</dd>
          </div>
          <div>
            <dt>Geschatte resterende tijd</dt>
            <dd>{TRAINING_MONITOR.eta}</dd>
          </div>
        </dl>

        <div className="trn-chart">
          <div className="trn-chart-title">Training &amp; validatie loss</div>
          <TrnLineChart series={lossChart} />
        </div>
        <div className="trn-chart">
          <div className="trn-chart-title">Learning rate</div>
          <TrnLineChart series={lrChart} strokes={["#3ac7ee"]} />
        </div>

        <div className="trn-stat-grid">
          {TRAINING_MONITOR.stats.map((stat) => (
            <div key={stat.label} className="trn-stat-mini">
              <div className="k">{stat.label}</div>
              <div className="v">{stat.value}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="trn-insp-panel">
        <div className="trn-insp-head">
          <h3 className="trn-insp-title">Training wachtrij ({TRAINING_QUEUE.length})</h3>
        </div>
        <div className="trn-table-wrap" style={{ maxHeight: 200 }}>
          <table className="trn-table trn-queue-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Naam</th>
                <th>Status</th>
                <th>Voortgang</th>
                <th>Prioriteit</th>
              </tr>
            </thead>
            <tbody>
              {TRAINING_QUEUE.map((row) => (
                <tr key={row.rank}>
                  <td>{row.rank}</td>
                  <td>
                    <div className="name">{row.name}</div>
                    <div className="trn-stat-hint">{row.model} · {row.dataset}</div>
                  </td>
                  <td>
                    <span
                      className={`trn-status-pill${row.status === "Valideren" ? " val" : ""}${row.status === "In wachtrij" ? " wait" : ""}`}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td>
                    <div className="trn-queue-bar">
                      <span style={{ width: `${row.progress}%` }} />
                    </div>
                  </td>
                  <td>
                    <span className={`trn-pri ${row.priority.toLowerCase()}`}>{row.priority}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="trn-insp-panel trn-controls">
        <h3 className="trn-insp-title">Run controls</h3>
        <button type="button" className="trn-btn start" data-toast="Training gestart (demo)">
          <FbIcon name="play" size={16} />
          Start Training
        </button>
        <button type="button" className="trn-btn stop" data-toast="Training gestopt (demo)">
          <FbIcon name="stop" size={16} />
          Stop Training
        </button>
        <div className="trn-btn-row">
          <button type="button" className="trn-btn outline" data-toast="Validatie config">
            Validatie config
          </button>
          <button type="button" className="trn-btn outline" data-toast="Preset opgeslagen">
            Opslaan als preset
          </button>
          <button type="button" className="trn-btn outline" data-toast="Run gedupliceerd">
            Duplicate run
          </button>
        </div>
      </section>
    </div>
  );

  return (
    <FinalBetaShell
      page="model-training"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="trn-app"
      mainClassName="trn-main"
    />
  );
}
