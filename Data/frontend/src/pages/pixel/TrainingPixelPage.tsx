import { useMemo, useState } from "react";
import { AppShell } from "../../layouts/AppShell";
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
  type TrainingPixelTab,
} from "../../mocks/training-pixel";
import { useAppToast } from "../../state/useAppToast";
import { chartPolyline, PxHero, PxIcon, PxKpi, PxSwitch } from "./pixel-shared";

function LineChart({
  series,
  width = 320,
  height = 56,
  strokes = ["var(--lv-cyan)", "var(--lv-gold-bright)"],
}: {
  series: number[][];
  width?: number;
  height?: number;
  strokes?: string[];
}) {
  return (
    <div className="lv-px-chart">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Grafiek">
        <line x1="0" y1={height - 1} x2={width} y2={height - 1} stroke="rgba(34,201,214,0.15)" />
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
    </div>
  );
}

export function TrainingPixelPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<TrainingPixelTab>("General");
  const [dsPreviewTab, setDsPreviewTab] = useState<(typeof TRAINING_PIXEL_DATASET_PREVIEW_TABS)[number]>("Voorbeeld");
  const [toggles, setToggles] = useState(() =>
    Object.fromEntries(TRAINING_SAFETY_TOGGLES.map((t) => [t.id, t.on])) as Record<string, boolean>,
  );

  const lossChart = useMemo(
    () => [TRAINING_MONITOR.lossSeries.train, TRAINING_MONITOR.lossSeries.val],
    [],
  );
  const lrChart = useMemo(() => [TRAINING_MONITOR.lrSeries], []);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Model Training"
      searchPlaceholder="Zoek runs, datasets, checkpoints..."
      systemItems={["TRAINING", "GPU 87%", "3 RUNS", "SYNC"]}
      layout="wide"
      pageClass="lv-app--pixel-llm"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-stack">
          <PxHero
            title="MODEL TRAINING"
            subtitle="ADAPT. ALIGN. TRANSCEND."
            quote="Transform data into intelligence."
          />

          <div className="lv-px-filters" style={{ justifyContent: "space-between" }}>
            <nav className="lv-px-tabs" aria-label="Training secties">
              {TRAINING_PIXEL_TABS.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`lv-px-tab${tab === item ? " is-active" : ""}`}
                  onClick={() => {
                    setTab(item);
                    if (item !== "General") toast(`${item} (demo)`);
                  }}
                >
                  {item}
                </button>
              ))}
            </nav>
            <button type="button" className="lv-px-btn is-gold" onClick={() => toast("Snelle acties menu")}>
              Snelle acties
            </button>
          </div>

          <div className="lv-px-kpi-row is-6">
            {TRAINING_STATUS_CARDS.map((card) => (
              <PxKpi
                key={card.id}
                label={card.label}
                value={card.value}
                hint={card.hint}
                hintTone={card.tone === "cyan" ? "cyan" : card.tone === "gold" ? "gold" : card.tone === "green" ? "green" : "muted"}
                icon={card.icon}
                spark={card.spark}
              />
            ))}
          </div>

          <div className="lv-px-trn-grid">
            <div className="lv-px-stack">
              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Run configuratie</h2>
                <div className="lv-px-form-grid" style={{ marginTop: 8 }}>
                  <div className="lv-px-field">
                    <label htmlFor="trn-name">Run naam</label>
                    <input id="trn-name" defaultValue={TRAINING_RUN_FORM.name} readOnly />
                  </div>
                  <div className="lv-px-field">
                    <label htmlFor="trn-project">Project</label>
                    <input id="trn-project" defaultValue={TRAINING_RUN_FORM.project} readOnly />
                  </div>
                  <div className="lv-px-field is-full">
                    <label htmlFor="trn-out">Output map</label>
                    <input id="trn-out" defaultValue={TRAINING_RUN_FORM.outputDir} readOnly />
                  </div>
                  <div className="lv-px-field is-full">
                    <label htmlFor="trn-desc">Beschrijving</label>
                    <textarea id="trn-desc" rows={3} defaultValue={TRAINING_RUN_FORM.description} readOnly />
                  </div>
                </div>
                <div className="lv-px-pills" style={{ marginTop: 8 }}>
                  {TRAINING_RUN_FORM.tags.map((tag) => (
                    <span key={tag} className="lv-px-pill is-cyan">{tag}</span>
                  ))}
                </div>
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Basismodel</h2>
                <p style={{ margin: "8px 0", fontSize: 11, color: "var(--lv-text-bright)" }}>
                  {TRAINING_BASE_MODEL.model} · {TRAINING_BASE_MODEL.provider}
                </p>
                <dl className="lv-px-meta-grid">
                  <dt>Parameters</dt>
                  <dd>{TRAINING_BASE_MODEL.parameters}</dd>
                  <dt>Context</dt>
                  <dd>{TRAINING_BASE_MODEL.context}</dd>
                  <dt>Quant</dt>
                  <dd>{TRAINING_BASE_MODEL.quant}</dd>
                  <dt>Architectuur</dt>
                  <dd>{TRAINING_BASE_MODEL.info.architecture}</dd>
                </dl>
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Datasets</h2>
                <div className="lv-px-table-wrap" style={{ marginTop: 8 }}>
                  <table className="lv-px-table">
                    <thead>
                      <tr>
                        <th />
                        <th>Naam</th>
                        <th>Split</th>
                        <th>Voorbeelden</th>
                        <th>Tokens</th>
                      </tr>
                    </thead>
                    <tbody>
                      {TRAINING_DATASET_ROWS.map((row) => (
                        <tr key={row.id}>
                          <td>
                            <input type="checkbox" readOnly checked={row.selected} aria-label={row.name} />
                          </td>
                          <td><strong>{row.name}</strong></td>
                          <td>{row.split}</td>
                          <td>{row.examples}</td>
                          <td>{row.tokens}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="lv-px-tabs" style={{ marginTop: 8 }}>
                  {TRAINING_PIXEL_DATASET_PREVIEW_TABS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      className={`lv-px-tab${dsPreviewTab === t ? " is-active" : ""}`}
                      onClick={() => setDsPreviewTab(t)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                <pre className="lv-px-code" style={{ marginTop: 8 }}>{TRAINING_DATASET_PREVIEW}</pre>
                <p style={{ fontSize: 9, color: "var(--lv-text-muted)", marginTop: 6 }}>
                  Validatie {TRAINING_DATASET_SETTINGS.validationPct}% · Template {TRAINING_DATASET_SETTINGS.formatTemplate}
                </p>
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Veiligheid &amp; limieten</h2>
                {TRAINING_SAFETY_TOGGLES.map((toggle) => (
                  <div key={toggle.id} className="lv-px-toggle-row">
                    <div>
                      <strong>{toggle.label}</strong>
                      <span>{toggle.description}</span>
                    </div>
                    <PxSwitch
                      label={toggle.label}
                      on={!!toggles[toggle.id]}
                      onToggle={() => {
                        setToggles((prev) => ({ ...prev, [toggle.id]: !prev[toggle.id] }));
                        toast(toggle.label);
                      }}
                    />
                  </div>
                ))}
                <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                  <dt>Checkpoint interval</dt>
                  <dd>{TRAINING_SAFETY_NUMBERS.checkpointInterval}</dd>
                  <dt>Max epochs</dt>
                  <dd>{TRAINING_SAFETY_NUMBERS.maxEpochs}</dd>
                  <dt>Early stopping</dt>
                  <dd>{TRAINING_SAFETY_NUMBERS.earlyStoppingPatience}</dd>
                  <dt>Max uren</dt>
                  <dd>{TRAINING_SAFETY_NUMBERS.maxTrainingHours}</dd>
                </dl>
              </section>
            </div>

            <aside className="lv-px-stack">
              <section className="lv-px-panel">
                <div className="lv-px-panel-head">
                  <h2 className="lv-px-panel-title">Live monitor</h2>
                  {TRAINING_MONITOR.live ? <span className="lv-px-pill is-green">Live</span> : null}
                </div>
                <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>
                  Epoch {TRAINING_MONITOR.epoch.current}/{TRAINING_MONITOR.epoch.total} · Stap{" "}
                  {TRAINING_MONITOR.steps.current.toLocaleString()}/{TRAINING_MONITOR.steps.total.toLocaleString()}
                </p>
                <div className="lv-px-progress" style={{ margin: "8px 0" }}>
                  <i style={{ width: `${TRAINING_MONITOR.steps.pct}%` }} />
                </div>
                <p style={{ fontSize: 9, color: "var(--lv-text-muted)" }}>
                  Verstreken {TRAINING_MONITOR.elapsed} · ETA {TRAINING_MONITOR.eta}
                </p>
                <p style={{ fontSize: 10, margin: "8px 0 4px", color: "var(--lv-gold-pale)" }}>Loss</p>
                <LineChart series={lossChart} />
                <p style={{ fontSize: 10, margin: "8px 0 4px", color: "var(--lv-gold-pale)" }}>Learning rate</p>
                <LineChart series={lrChart} strokes={["var(--lv-gold-bright)"]} />
                <div className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                  {TRAINING_MONITOR.stats.map((s) => (
                    <div key={s.label}>
                      <dt>{s.label}</dt>
                      <dd>{s.value}</dd>
                    </div>
                  ))}
                </div>
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Hardware</h2>
                <p style={{ fontSize: 10, marginTop: 6 }}>{TRAINING_HARDWARE.device}</p>
                {TRAINING_HARDWARE.usage.map((u) => (
                  <div key={u.label} style={{ marginTop: 8 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9 }}>
                      <span>{u.label}</span>
                      <span>{u.value}</span>
                    </div>
                    <div className="lv-px-progress is-thin">
                      <i style={{ width: `${u.pct}%` }} />
                    </div>
                  </div>
                ))}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Log</h2>
                <div className="lv-px-log">
                  {TRAINING_LOG_LINES.map((line, i) => (
                    <div
                      key={i}
                      className={`lv-px-log-line${line.level === "WARNING" ? " is-warning" : ""}`}
                    >
                      [{line.time}] {line.level}: {line.message}
                    </div>
                  ))}
                </div>
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Checkpoints</h2>
                {TRAINING_CHECKPOINTS.map((ck) => (
                  <div key={ck.name} className="lv-px-queue-item">
                    <strong>{ck.name}</strong>
                    <div className="lv-px-queue-meta">
                      <span>Stap {ck.step}</span>
                      <span>{ck.size}</span>
                      <span>{ck.when}</span>
                    </div>
                  </div>
                ))}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Wachtrij</h2>
                <div className="lv-px-table-wrap">
                  <table className="lv-px-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Run</th>
                        <th>Status</th>
                        <th>%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {TRAINING_QUEUE.map((row) => (
                        <tr key={row.rank}>
                          <td>{row.rank}</td>
                          <td>
                            <strong>{row.name}</strong>
                            <div style={{ fontSize: 8, color: "var(--lv-text-muted)" }}>{row.dataset}</div>
                          </td>
                          <td>{row.status}</td>
                          <td>{row.progress}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button type="button" className="lv-px-btn is-gold" style={{ marginTop: 8, width: "100%" }} onClick={() => toast("Training starten")}>
                  <PxIcon name="play" /> Start training
                </button>
              </section>
            </aside>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
