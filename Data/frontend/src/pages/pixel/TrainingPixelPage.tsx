import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import {
  TRAINING_DATASET_PREVIEW,
  TRAINING_PIXEL_DATASET_PREVIEW_TABS,
  TRAINING_PIXEL_TABS,
  TRAINING_SAFETY_TOGGLES,
  type TrainingPixelTab,
} from "../../mocks/training-pixel";
import { useAppToast } from "../../state/useAppToast";
import type {
  HardwareSnapshot,
  PreflightResult,
  TrainingCapabilities,
  TrainingCheckpoint,
  TrainingJob,
  TrainingLogs,
  TrainingMetric,
  TrainingPlan,
} from "../../types/api";
import { chartPolyline, PxHero, PxIcon, PxKpi, PxSwitch } from "./pixel-shared";

const ACTIVE = new Set(["queued", "preflight", "running", "evaluating", "exporting", "cancelling"]);
const RESUMABLE = new Set(["interrupted", "queued"]);

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function metricSeries(metrics: TrainingMetric[], names: string[]): number[] {
  const wanted = new Set(names.map((n) => n.toLowerCase()));
  const points = metrics
    .filter((m) => wanted.has(m.metricName.toLowerCase()))
    .sort((a, b) => (a.step ?? 0) - (b.step ?? 0) || a.recordedAt.localeCompare(b.recordedAt));
  return points.map((m) => m.metricValue);
}

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
  const hasData = series.some((s) => s.length > 1);
  if (!hasData) {
    return (
      <p style={{ fontSize: 9, color: "var(--lv-text-muted)", margin: "4px 0" }}>Nog geen metrieken.</p>
    );
  }
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
  const [dsPreviewTab, setDsPreviewTab] =
    useState<(typeof TRAINING_PIXEL_DATASET_PREVIEW_TABS)[number]>("Voorbeeld");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [capabilities, setCapabilities] = useState<TrainingCapabilities | null>(null);
  const [hardware, setHardware] = useState<HardwareSnapshot | null>(null);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [hwError, setHwError] = useState<string | null>(null);

  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<TrainingMetric[]>([]);
  const [logs, setLogs] = useState<TrainingLogs | null>(null);
  const [checkpoints, setCheckpoints] = useState<TrainingCheckpoint[]>([]);
  const [evaluation, setEvaluation] = useState<Record<string, unknown> | null>(null);
  const [exportResult, setExportResult] = useState<Record<string, unknown> | null>(null);

  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [plan, setPlan] = useState<TrainingPlan | null>(null);

  const [searchParams] = useSearchParams();
  const [name, setName] = useState("training-run");
  const [method, setMethod] = useState("fixture");
  const [baseModel, setBaseModel] = useState("unspecified");
  const [datasetVersionId, setDatasetVersionId] = useState(() => searchParams.get("datasetVersionId") ?? "");
  const [datasetPath, setDatasetPath] = useState("");
  const [epochs, setEpochs] = useState("1");
  const [batchSize, setBatchSize] = useState("1");
  const [learningRate, setLearningRate] = useState("0.0002");
  const [maxSeq, setMaxSeq] = useState("512");
  const [precision, setPrecision] = useState("fp32");
  const [fixtureSteps, setFixtureSteps] = useState("5");
  const [saveSteps, setSaveSteps] = useState("500");
  const [gradientCheckpointing, setGradientCheckpointing] = useState(false);
  const [loadIn4bit, setLoadIn4bit] = useState(false);

  const selectedJob = useMemo(
    () => jobs.find((j) => j.jobId === selectedJobId) ?? null,
    [jobs, selectedJobId],
  );

  const payload = useMemo(
    () => ({
      name: name.trim() || "training-run",
      method,
      base_model_ref: baseModel.trim() || "unspecified",
      dataset_version_id: datasetVersionId.trim() || null,
      dataset_path: datasetPath.trim() || null,
      epochs: Number(epochs) || 1,
      train_batch_size: Number(batchSize) || 1,
      learning_rate: Number(learningRate) || 2e-4,
      max_seq_length: Number(maxSeq) || 512,
      precision,
      fixture_steps: Number(fixtureSteps) || 5,
      save_steps: Number(saveSteps) || 500,
      gradient_checkpointing: gradientCheckpointing,
      load_in_4bit: loadIn4bit,
    }),
    [
      name,
      method,
      baseModel,
      datasetVersionId,
      datasetPath,
      epochs,
      batchSize,
      learningRate,
      maxSeq,
      precision,
      fixtureSteps,
      saveSteps,
      gradientCheckpointing,
      loadIn4bit,
    ],
  );

  const loadCaps = useCallback(async () => {
    setCapsError(null);
    setHwError(null);
    try {
      const res = await api.trainingCapabilities();
      setCapabilities(res.capabilities);
    } catch (err) {
      setCapabilities(null);
      setCapsError(errMsg(err, "Training capabilities unavailable"));
    }
    try {
      const res = await api.trainingHardware();
      setHardware(res.hardware);
    } catch (err) {
      setHardware(null);
      setHwError(errMsg(err, "Hardware probe unavailable"));
    }
  }, []);

  const loadJobs = useCallback(async () => {
    setError(null);
    try {
      const res = await api.listTrainingJobs();
      setJobs(res.jobs);
      if (res.jobs.length === 0) {
        setSelectedJobId(null);
      } else if (!selectedJobId || !res.jobs.some((j) => j.jobId === selectedJobId)) {
        setSelectedJobId(res.jobs[0].jobId);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load training jobs"));
      setJobs([]);
    }
  }, [selectedJobId]);

  useEffect(() => {
    void loadCaps();
    void loadJobs();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedJobId) {
      setMetrics([]);
      setLogs(null);
      setCheckpoints([]);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const [m, l, c, jobRes] = await Promise.all([
          api.listTrainingMetrics(selectedJobId),
          api.getTrainingLogs(selectedJobId),
          api.listTrainingCheckpoints(selectedJobId),
          api.getTrainingJob(selectedJobId),
        ]);
        if (cancelled) return;
        setMetrics(m.metrics);
        setLogs(l);
        setCheckpoints(c.checkpoints);
        setJobs((prev) => {
          const others = prev.filter((j) => j.jobId !== selectedJobId);
          return [jobRes.job, ...others].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
        });
      } catch {
        /* keep last good snapshot */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [selectedJobId]);

  async function withBusy(fn: () => Promise<void>, ok?: string) {
    setBusy(true);
    try {
      await fn();
      if (ok) toast(ok);
    } catch (err) {
      toast(errMsg(err, "Action failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onPreflight() {
    await withBusy(async () => {
      const [pf, pl] = await Promise.all([
        api.trainingPreflight(payload),
        api.trainingPlan(payload),
      ]);
      setPreflight(pf.preflight);
      setPlan(pl.plan);
    }, "Preflight voltooid");
  }

  async function onCreate(start: boolean) {
    if (preflight?.verdict === "BLOCKED") {
      toast("Preflight geblokkeerd — los problemen op");
      return;
    }
    await withBusy(async () => {
      if (!preflight) {
        const pf = await api.trainingPreflight(payload);
        setPreflight(pf.preflight);
        if (pf.preflight.verdict === "BLOCKED") {
          throw new ApiError(400, "Preflight blocked — cannot start");
        }
      }
      const res = await api.createTrainingJob({ ...payload, auto_start: start });
      setSelectedJobId(res.job.jobId);
      await loadJobs();
      setTab("Training");
    }, start ? "Job aangemaakt en gestart" : "Job aangemaakt");
  }

  const methodDisabledReason = useMemo(() => {
    if (!capabilities) return capsError ?? "Capabilities niet geladen";
    if (method === "fixture" && !capabilities.canRunFixture) return "Fixture runner niet beschikbaar";
    if (method === "lora" && !capabilities.canRunLora) {
      return `LoRA niet beschikbaar — mist: ${capabilities.missingForLora.join(", ") || "deps"}`;
    }
    if (method === "qlora" && !capabilities.canRunQlora) return "QLoRA niet beschikbaar";
    if (method === "dpo" && !capabilities.canRunDpo) return "DPO niet beschikbaar";
    return null;
  }, [capabilities, capsError, method]);

  const methodBlocked = Boolean(
    methodDisabledReason && method !== "fixture" && method !== "sft",
  );

  const trainActions = (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
      <button type="button" className="lv-px-btn" disabled={busy} onClick={() => void onPreflight()}>
        Preflight
      </button>
      <button
        type="button"
        className="lv-px-btn"
        disabled={busy || methodBlocked}
        onClick={() => void onCreate(false)}
      >
        Job aanmaken
      </button>
      <button
        type="button"
        className="lv-px-btn is-gold"
        disabled={busy || methodBlocked || preflight?.verdict === "BLOCKED"}
        onClick={() => void onCreate(true)}
      >
        <PxIcon name="play" /> Start training
      </button>
    </div>
  );

  const activeCount = jobs.filter((j) => ACTIVE.has(j.status)).length;
  const queuedCount = jobs.filter((j) => j.status === "queued").length;

  const lossChart = useMemo(
    () => [
      metricSeries(metrics, ["loss", "train_loss", "training_loss"]),
      metricSeries(metrics, ["val_loss", "eval_loss", "validation_loss"]),
    ],
    [metrics],
  );
  const lrChart = useMemo(
    () => [metricSeries(metrics, ["lr", "learning_rate", "learning rate"])],
    [metrics],
  );

  const progressPct = selectedJob?.progress != null ? Math.round(selectedJob.progress * 100) : 0;
  const isLive = selectedJob ? ACTIVE.has(selectedJob.status) : false;

  const statusCards = useMemo(() => {
    const gpu = hardware?.gpus[0];
    const vramHint = gpu
      ? `${gpu.name} · ${formatBytes(gpu.totalVramBytes)}`
      : hardware?.cudaAvailable
        ? "CUDA · geen GPU-details"
        : "Geen CUDA";
    return [
      {
        id: "active",
        label: "Actieve runs",
        value: String(activeCount),
        hint: `${queuedCount} in wachtrij`,
        tone: "cyan" as const,
        icon: "pulse",
      },
      {
        id: "queue",
        label: "Wachtrij",
        value: String(queuedCount),
        hint: `${jobs.length} jobs totaal`,
        icon: "list",
      },
      {
        id: "model",
        label: "Basismodel",
        value: (selectedJob?.baseModelRef ?? baseModel).slice(0, 28),
        hint: selectedJob?.method ?? method,
        tone: "gold" as const,
        icon: "meta",
      },
      {
        id: "datasets",
        label: "Dataset",
        value: datasetVersionId.trim() ? "Versie gekoppeld" : "—",
        hint: datasetVersionId.trim() || datasetPath.trim() || "Geen pad",
        icon: "database",
      },
      {
        id: "vram",
        label: "Hardware",
        value: gpu?.name?.slice(0, 16) ?? (hardware?.cudaAvailable ? "CUDA" : "CPU"),
        hint: vramHint,
        icon: "bolt",
      },
      {
        id: "checkpoints",
        label: "Checkpoints",
        value: String(checkpoints.length),
        hint: selectedJob ? selectedJob.name : "Selecteer run",
        icon: "save",
      },
      {
        id: "health",
        label: "Training health",
        value: capabilities?.ready ? "Gereed" : capabilities ? "Gedeeltelijk" : "Onbekend",
        hint: capsError ?? (capabilities?.notes[0] ?? "Live API"),
        tone: capabilities?.ready ? ("green" as const) : ("default" as const),
        icon: "shield",
      },
    ];
  }, [
    activeCount,
    queuedCount,
    jobs.length,
    selectedJob,
    baseModel,
    method,
    datasetVersionId,
    datasetPath,
    hardware,
    checkpoints.length,
    capabilities,
    capsError,
  ]);

  const systemItems = useMemo(() => {
    const gpuPct =
      hardware?.gpus.length && hardware.gpus[0].totalVramBytes
        ? "GPU"
        : hardware?.cudaAvailable
          ? "CUDA"
          : "CPU";
    return ["TRAINING", gpuPct, `${activeCount} ACTIVE`, "LIVE API"];
  }, [hardware, activeCount]);

  const logLines = useMemo(() => {
    if (!logs?.text) return [];
    return logs.text.split("\n").filter(Boolean).slice(-24);
  }, [logs]);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Model Training"
      searchPlaceholder="Zoek runs, datasets, checkpoints..."
      systemItems={systemItems}
      layout="wide"
      pageClass="lv-app--pixel-llm"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-stack">
          <PxHero
            title="MODEL TRAINING"
            subtitle="ADAPT. ALIGN. TRANSCEND."
            quote="Echte jobs, echte metrieken — geen gesimuleerde voortgang."
            extra={
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="button" className="lv-px-btn" disabled={busy} onClick={() => void loadCaps()}>
                  Hardware verversen
                </button>
                <button type="button" className="lv-px-btn" disabled={busy} onClick={() => void loadJobs()}>
                  Jobs verversen
                </button>
                <Link to="/dataset-management" className="lv-px-btn is-gold">
                  Datasets
                </Link>
                <Link to="/offline-datasets" className="lv-px-btn">
                  Offline
                </Link>
                <Link to="/analytics" className="lv-px-btn">
                  Stats
                </Link>
              </div>
            }
          />

          {error ? (
            <div className="lv-px-panel" role="alert" style={{ borderColor: "var(--lv-red, #c44)" }}>
              <strong>Training API</strong>
              <span style={{ marginLeft: 8 }}>{error}</span>
            </div>
          ) : null}
          {(capsError || hwError) && (
            <p style={{ fontSize: 10, color: "var(--lv-gold-pale)" }}>
              {[capsError, hwError].filter(Boolean).join(" · ")}
            </p>
          )}

          <div className="lv-px-filters" style={{ justifyContent: "space-between" }}>
            <nav className="lv-px-tabs" aria-label="Training secties">
              {TRAINING_PIXEL_TABS.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`lv-px-tab${tab === item ? " is-active" : ""}`}
                  onClick={() => setTab(item)}
                >
                  {item}
                </button>
              ))}
            </nav>
          </div>

          <div className="lv-px-kpi-row is-6">
            {statusCards.map((card) => (
              <PxKpi
                key={card.id}
                label={card.label}
                value={card.value}
                hint={card.hint}
                hintTone={
                  card.tone === "cyan"
                    ? "cyan"
                    : card.tone === "gold"
                      ? "gold"
                      : card.tone === "green"
                        ? "green"
                        : "muted"
                }
                icon={card.icon}
              />
            ))}
          </div>

          <div className="lv-px-trn-grid">
            <div className="lv-px-stack">
              {(tab === "General" || tab === "Training") && (
                <section className="lv-px-panel">
                  <h2 className="lv-px-panel-title">Run configuratie</h2>
                  <div className="lv-px-form-grid" style={{ marginTop: 8 }}>
                    <div className="lv-px-field">
                      <label htmlFor="trn-name">Run naam</label>
                      <input
                        id="trn-name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <div className="lv-px-field">
                      <label htmlFor="trn-method">Methode</label>
                      <select
                        id="trn-method"
                        value={method}
                        onChange={(e) => setMethod(e.target.value)}
                        disabled={busy}
                      >
                        <option value="fixture">fixture</option>
                        <option value="sft">sft</option>
                        <option value="lora" disabled={capabilities ? !capabilities.canRunLora : false}>
                          lora
                        </option>
                        <option value="qlora" disabled={capabilities ? !capabilities.canRunQlora : false}>
                          qlora
                        </option>
                        <option value="dpo" disabled={capabilities ? !capabilities.canRunDpo : false}>
                          dpo
                        </option>
                      </select>
                    </div>
                    <div className="lv-px-field">
                      <label htmlFor="trn-epochs">Epochs</label>
                      <input
                        id="trn-epochs"
                        value={epochs}
                        onChange={(e) => setEpochs(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <div className="lv-px-field">
                      <label htmlFor="trn-bs">Batch</label>
                      <input
                        id="trn-bs"
                        value={batchSize}
                        onChange={(e) => setBatchSize(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <div className="lv-px-field">
                      <label htmlFor="trn-lr">Learning rate</label>
                      <input
                        id="trn-lr"
                        value={learningRate}
                        onChange={(e) => setLearningRate(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <div className="lv-px-field">
                      <label htmlFor="trn-seq">Max seq</label>
                      <input
                        id="trn-seq"
                        value={maxSeq}
                        onChange={(e) => setMaxSeq(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <div className="lv-px-field">
                      <label htmlFor="trn-prec">Precisie</label>
                      <select
                        id="trn-prec"
                        value={precision}
                        onChange={(e) => setPrecision(e.target.value)}
                        disabled={busy}
                      >
                        <option value="fp32">fp32</option>
                        <option value="fp16">fp16</option>
                        <option value="bf16">bf16</option>
                      </select>
                    </div>
                    <div className="lv-px-field">
                      <label htmlFor="trn-fix">Fixture steps</label>
                      <input
                        id="trn-fix"
                        value={fixtureSteps}
                        onChange={(e) => setFixtureSteps(e.target.value)}
                        disabled={busy || method !== "fixture"}
                      />
                    </div>
                  </div>
                  {methodDisabledReason ? (
                    <p style={{ fontSize: 9, color: "var(--lv-text-muted)", marginTop: 8 }}>{methodDisabledReason}</p>
                  ) : null}
                  {(tab === "Training" || tab === "General") && trainActions}
                </section>
              )}

              {(tab === "General" || tab === "Model") && (
                <section className="lv-px-panel">
                  <h2 className="lv-px-panel-title">Basismodel</h2>
                  <div className="lv-px-field is-full" style={{ marginTop: 8 }}>
                    <label htmlFor="trn-base">Model ref</label>
                    <input
                      id="trn-base"
                      value={baseModel}
                      onChange={(e) => setBaseModel(e.target.value)}
                      disabled={busy}
                    />
                  </div>
                  <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                    <dt>Methode</dt>
                    <dd>{method}</dd>
                    <dt>Plan</dt>
                    <dd>{plan?.strategy ?? "—"}</dd>
                    <dt>Batch effectief</dt>
                    <dd>{plan ? plan.effectiveBatchSize : "—"}</dd>
                    <dt>4-bit</dt>
                    <dd>{plan ? (plan.loadIn4bit ? "ja" : "nee") : "—"}</dd>
                  </dl>
                </section>
              )}

              {(tab === "General" || tab === "Dataset") && (
                <section className="lv-px-panel">
                  <h2 className="lv-px-panel-title">Datasets</h2>
                  <div className="lv-px-form-grid" style={{ marginTop: 8 }}>
                    <div className="lv-px-field is-full">
                      <label htmlFor="trn-dsv">Dataset version id</label>
                      <input
                        id="trn-dsv"
                        value={datasetVersionId}
                        onChange={(e) => setDatasetVersionId(e.target.value)}
                        placeholder="optioneel"
                        disabled={busy}
                      />
                    </div>
                    <div className="lv-px-field is-full">
                      <label htmlFor="trn-dsp">Dataset pad</label>
                      <input
                        id="trn-dsp"
                        value={datasetPath}
                        onChange={(e) => setDatasetPath(e.target.value)}
                        placeholder="optioneel lokaal pad"
                        disabled={busy}
                      />
                    </div>
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
                  {dsPreviewTab === "Voorbeeld" ? (
                    <pre className="lv-px-code" style={{ marginTop: 8 }}>
                      {TRAINING_DATASET_PREVIEW}
                    </pre>
                  ) : (
                    <p style={{ fontSize: 9, color: "var(--lv-text-muted)", marginTop: 8 }}>
                      {dsPreviewTab === "Statistieken"
                        ? "Statistieken komen van de gekozen datasetversie op Datasets."
                        : "Token distributie vereist dataset-analyse op Datasets."}
                    </p>
                  )}
                  <p style={{ fontSize: 9, color: "var(--lv-text-muted)", marginTop: 8 }}>
                    Voorbereiding en validatie gebeuren op de Datasets-pagina.
                  </p>
                </section>
              )}

              {(tab === "General" || tab === "Advanced") && (
                <section className="lv-px-panel">
                  <h2 className="lv-px-panel-title">Veiligheid &amp; limieten</h2>
                  {TRAINING_SAFETY_TOGGLES.map((toggle) => (
                    <div key={toggle.id} className="lv-px-toggle-row">
                      <div>
                        <strong>{toggle.label}</strong>
                        <span>{toggle.description}</span>
                      </div>
                    </div>
                  ))}
                  <div className="lv-px-toggle-row">
                    <div>
                      <strong>Gradient checkpointing</strong>
                      <span>Minder VRAM, langzamere stappen</span>
                    </div>
                    <PxSwitch
                      label="Gradient checkpointing"
                      on={gradientCheckpointing}
                      onToggle={() => setGradientCheckpointing((v) => !v)}
                    />
                  </div>
                  <div className="lv-px-toggle-row">
                    <div>
                      <strong>Load in 4-bit</strong>
                      <span>Voor QLoRA wanneer ondersteund</span>
                    </div>
                    <PxSwitch label="Load in 4-bit" on={loadIn4bit} onToggle={() => setLoadIn4bit((v) => !v)} />
                  </div>
                  <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                    <dt>Checkpoint interval</dt>
                    <dd>
                      <input
                        value={saveSteps}
                        onChange={(e) => setSaveSteps(e.target.value)}
                        disabled={busy}
                        aria-label="Checkpoint interval"
                      />
                    </dd>
                    <dt>Max epochs</dt>
                    <dd>{epochs}</dd>
                  </dl>
                </section>
              )}

              {(tab === "Training" || tab === "Advanced") && preflight && (
                <section className="lv-px-panel">
                  <h2 className="lv-px-panel-title">Preflight — {preflight.verdict}</h2>
                  {preflight.issues.length === 0 ? (
                    <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Geen issues.</p>
                  ) : (
                    <ul style={{ fontSize: 10, margin: "8px 0", paddingLeft: 16 }}>
                      {preflight.issues.map((issue) => (
                        <li key={`${issue.code}-${issue.message}`}>
                          [{issue.severity}] {issue.code}: {issue.message}
                        </li>
                      ))}
                    </ul>
                  )}
                  {plan ? (
                    <p style={{ fontSize: 10, marginTop: 8 }}>
                      Plan: {plan.strategy} — {plan.reason}
                    </p>
                  ) : null}
                </section>
              )}

              {tab === "Advanced" && capabilities && (
                <section className="lv-px-panel">
                  <h2 className="lv-px-panel-title">Packages</h2>
                  <ul style={{ fontSize: 10, margin: "8px 0", paddingLeft: 16 }}>
                    {capabilities.packages.map((p) => (
                      <li key={p.name}>
                        {p.name}: {p.available ? "ok" : "missing"}
                        {p.importError ? ` — ${p.importError}` : ""}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {tab === "Advanced" && selectedJob ? (
                <section className="lv-px-panel">
                  <h2 className="lv-px-panel-title">Evaluatie &amp; export</h2>
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>
                    {selectedJob.name} · {selectedJob.status}
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                    <button
                      type="button"
                      className="lv-px-btn is-gold"
                      disabled={busy || ACTIVE.has(selectedJob.status)}
                      onClick={() =>
                        void withBusy(async () => {
                          const res = await api.evaluateTrainingJob(selectedJob.jobId);
                          setEvaluation(res.evaluation);
                        }, "Evaluatie voltooid")
                      }
                    >
                      Evalueer run
                    </button>
                    <button
                      type="button"
                      className="lv-px-btn"
                      disabled={busy || selectedJob.status !== "completed"}
                      onClick={() =>
                        void withBusy(async () => {
                          const res = await api.exportTrainingJob(selectedJob.jobId);
                          setExportResult(res.export);
                        }, "Export voltooid")
                      }
                    >
                      Exporteer artifact
                    </button>
                  </div>
                  {evaluation ? (
                    <pre className="lv-px-code" style={{ marginTop: 8, maxHeight: 200, overflow: "auto" }}>
                      {JSON.stringify(evaluation, null, 2)}
                    </pre>
                  ) : null}
                  {exportResult ? (
                    <pre className="lv-px-code" style={{ marginTop: 8, maxHeight: 200, overflow: "auto" }}>
                      {JSON.stringify(exportResult, null, 2)}
                    </pre>
                  ) : null}
                </section>
              ) : null}
            </div>

            <aside className="lv-px-stack">
              <section className="lv-px-panel">
                <div className="lv-px-panel-head">
                  <h2 className="lv-px-panel-title">Live monitor</h2>
                  {isLive ? <span className="lv-px-pill is-green">Live</span> : null}
                </div>
                {selectedJob ? (
                  <>
                    <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>
                      {selectedJob.name} · {selectedJob.status} · {progressPct}%
                    </p>
                    <div className="lv-px-progress" style={{ margin: "8px 0" }}>
                      <i style={{ width: `${progressPct}%` }} />
                    </div>
                    <p style={{ fontSize: 10, margin: "8px 0 4px", color: "var(--lv-gold-pale)" }}>Loss</p>
                    <LineChart series={lossChart} />
                    <p style={{ fontSize: 10, margin: "8px 0 4px", color: "var(--lv-gold-pale)" }}>Learning rate</p>
                    <LineChart series={lrChart} strokes={["var(--lv-gold-bright)"]} />
                  </>
                ) : (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Selecteer een run in de wachtrij.</p>
                )}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Hardware</h2>
                {hardware ? (
                  <>
                    <p style={{ fontSize: 10, marginTop: 6 }}>{dash(hardware.cpuModel)}</p>
                    <dl className="lv-px-meta-grid" style={{ marginTop: 8 }}>
                      <dt>RAM vrij</dt>
                      <dd>{formatBytes(hardware.ramAvailableBytes)}</dd>
                      <dt>Disk vrij</dt>
                      <dd>{formatBytes(hardware.diskFreeBytes)}</dd>
                      <dt>CUDA</dt>
                      <dd>{hardware.cudaAvailable ? "ja" : "nee"}</dd>
                    </dl>
                    {hardware.gpus.length === 0 ? (
                      <p style={{ fontSize: 9, color: "var(--lv-text-muted)" }}>Geen GPU gemeten.</p>
                    ) : (
                      hardware.gpus.map((g) => (
                        <div key={g.index} style={{ marginTop: 8, fontSize: 9 }}>
                          [{g.index}] {g.name} — {formatBytes(g.totalVramBytes)}
                        </div>
                      ))
                    )}
                  </>
                ) : (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>{hwError ?? "Hardware laden…"}</p>
                )}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Log</h2>
                <div className="lv-px-log">
                  {logLines.length === 0 ? (
                    <div className="lv-px-log-line">Geen logregels{logs?.logPath ? ` (${logs.logPath})` : ""}.</div>
                  ) : (
                    logLines.map((line, i) => (
                      <div
                        key={i}
                        className={`lv-px-log-line${/warn/i.test(line) ? " is-warning" : ""}`}
                      >
                        {line}
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Checkpoints</h2>
                {checkpoints.length === 0 ? (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Geen checkpoints voor deze job.</p>
                ) : (
                  checkpoints.map((ck) => (
                    <div key={ck.checkpointId} className="lv-px-queue-item">
                      <strong>stap {dash(ck.step)}</strong>
                      <div className="lv-px-queue-meta">
                        <span>{ck.path}</span>
                        <span>{ck.createdAt}</span>
                      </div>
                    </div>
                  ))
                )}
              </section>

              <section className="lv-px-panel">
                <h2 className="lv-px-panel-title">Wachtrij</h2>
                {jobs.length === 0 ? (
                  <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Geen training jobs.</p>
                ) : (
                  <div className="lv-px-table-wrap">
                    <table className="lv-px-table">
                      <thead>
                        <tr>
                          <th>Run</th>
                          <th>Status</th>
                          <th>%</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {jobs.map((row) => (
                          <tr
                            key={row.jobId}
                            className={row.jobId === selectedJobId ? "is-selected" : undefined}
                            onClick={() => setSelectedJobId(row.jobId)}
                            style={{ cursor: "pointer" }}
                          >
                            <td>
                              <strong>{row.name}</strong>
                              <div style={{ fontSize: 8, color: "var(--lv-text-muted)" }}>{row.method}</div>
                            </td>
                            <td>{row.status}</td>
                            <td>{row.progress == null ? "—" : `${Math.round(row.progress * 100)}`}</td>
                            <td onClick={(e) => e.stopPropagation()}>
                              {row.status === "queued" ? (
                                <button
                                  type="button"
                                  className="lv-px-btn"
                                  disabled={busy}
                                  onClick={() =>
                                    void withBusy(async () => {
                                      await api.startTrainingJob(row.jobId);
                                      await loadJobs();
                                    }, "Gestart")
                                  }
                                >
                                  Start
                                </button>
                              ) : null}
                              {ACTIVE.has(row.status) ? (
                                <button
                                  type="button"
                                  className="lv-px-btn"
                                  disabled={busy}
                                  onClick={() =>
                                    void withBusy(async () => {
                                      await api.cancelTrainingJob(row.jobId);
                                      await loadJobs();
                                    }, "Annuleren aangevraagd")
                                  }
                                >
                                  Stop
                                </button>
                              ) : null}
                              {RESUMABLE.has(row.status) ? (
                                <button
                                  type="button"
                                  className="lv-px-btn"
                                  disabled={busy}
                                  onClick={() =>
                                    void withBusy(async () => {
                                      await api.resumeTrainingJob(row.jobId);
                                      await loadJobs();
                                    }, "Hervatten aangevraagd")
                                  }
                                >
                                  Hervat
                                </button>
                              ) : null}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {jobs.length > 0 ? trainActions : null}
              </section>
            </aside>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
