import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type {
  HardwareSnapshot,
  PreflightResult,
  TrainingCapabilities,
  TrainingCheckpoint,
  TrainingJob,
  TrainingLogs,
  TrainingMetric,
  TrainingPlan,
} from "../types/api";

type Tab = "datasets" | "prepare" | "train" | "runs" | "evaluate" | "checkpoints" | "exports";

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

export function TrainingPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<Tab>("train");
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

  // Train form
  const [name, setName] = useState("training-run");
  const [method, setMethod] = useState("fixture");
  const [baseModel, setBaseModel] = useState("unspecified");
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [datasetPath, setDatasetPath] = useState("");
  const [epochs, setEpochs] = useState("1");
  const [batchSize, setBatchSize] = useState("1");
  const [learningRate, setLearningRate] = useState("0.0002");
  const [maxSeq, setMaxSeq] = useState("512");
  const [precision, setPrecision] = useState("fp32");
  const [fixtureSteps, setFixtureSteps] = useState("5");

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
    }),
    [name, method, baseModel, datasetVersionId, datasetPath, epochs, batchSize, learningRate, maxSeq, precision, fixtureSteps],
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
    }, "Preflight complete");
  }

  async function onCreate(start: boolean) {
    if (preflight?.verdict === "BLOCKED") {
      toast("Preflight blocked — fix issues before starting");
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
      setTab("runs");
    }, start ? "Job created and started" : "Job created");
  }

  const methodDisabledReason = useMemo(() => {
    if (!capabilities) return capsError ?? "Capabilities not loaded";
    if (method === "fixture" && !capabilities.canRunFixture) return "Fixture runner unavailable";
    if (method === "lora" && !capabilities.canRunLora) {
      return `LoRA unavailable — missing: ${capabilities.missingForLora.join(", ") || "deps"}`;
    }
    if (method === "qlora" && !capabilities.canRunQlora) return "QLoRA unavailable on this host";
    if (method === "dpo" && !capabilities.canRunDpo) return "DPO unavailable on this host";
    return null;
  }, [capabilities, capsError, method]);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Training Mode"
      searchPlaceholder="Search training runs…"
      pageClass="lv-app--training"
      layout="wide"
    >
      <main className="lv-main">
        <header className="lv-models-header">
          <div>
            <div className="lv-models-kicker">Improve the mind</div>
            <h1 className="lv-models-title">Training</h1>
            <p className="lv-muted">Live jobs, real metrics, honest hardware — no fake progress.</p>
          </div>
          <div className="lv-models-header-actions">
            <button className="lv-btn" type="button" disabled={busy} onClick={() => void loadCaps()}>
              Refresh hardware
            </button>
            <button className="lv-btn" type="button" disabled={busy} onClick={() => void loadJobs()}>
              Refresh jobs
            </button>
          </div>
        </header>

        {error ? (
          <div className="lv-models-banner is-error" role="alert">
            <strong>Training API error</strong>
            <span>{error}</span>
          </div>
        ) : null}

        <div className="lv-models-status-row">
          <div className="lv-models-status-card">
            <span>Capabilities</span>
            <strong>
              {capabilities
                ? capabilities.ready
                  ? "Ready"
                  : "Partial"
                : capsError
                  ? "Unavailable"
                  : "…"}
            </strong>
          </div>
          <div className="lv-models-status-card">
            <span>CUDA</span>
            <strong>
              {hardware ? (hardware.cudaAvailable ? "Available" : "None") : hwError ? "—" : "…"}
            </strong>
          </div>
          <div className="lv-models-status-card">
            <span>GPUs</span>
            <strong>{hardware ? hardware.gpus.length : "—"}</strong>
          </div>
          <div className="lv-models-status-card">
            <span>Active jobs</span>
            <strong>{jobs.filter((j) => ACTIVE.has(j.status)).length}</strong>
          </div>
        </div>

        {(capsError || hwError) && (
          <div className="lv-models-banner is-warn" role="status">
            <strong>Environment note</strong>
            <span>{[capsError, hwError].filter(Boolean).join(" · ")}</span>
          </div>
        )}

        <div className="lv-tabs" role="tablist">
          {(
            [
              ["datasets", "Datasets"],
              ["prepare", "Prepare"],
              ["train", "Train"],
              ["runs", "Runs"],
              ["evaluate", "Evaluate"],
              ["checkpoints", "Checkpoints"],
              ["exports", "Exports"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              className={`lv-tab${tab === id ? " is-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "datasets" ? (
          <section className="lv-panel">
            <p>
              Training consumes dataset versions from the Datasets control plane. Prepare data there, then
              paste a <code>dataset_version_id</code> into Train.
            </p>
            <Link className="lv-btn lv-btn-gold" to="/datasets">
              Open Datasets
            </Link>
          </section>
        ) : null}

        {tab === "prepare" ? (
          <section className="lv-panel">
            <h2>Prepare note</h2>
            <p className="lv-muted">
              Validate, dedupe, split, and export happen on the Datasets page. This tab does not invent
              preparation progress — configure a dataset version, then return here to train.
            </p>
            <Link className="lv-btn" to="/datasets">
              Go to Prepare on Datasets
            </Link>
            {capabilities ? (
              <div style={{ marginTop: "1rem" }}>
                <h3>Package availability</h3>
                <ul>
                  {capabilities.packages.map((p) => (
                    <li key={p.name}>
                      {p.name}: {p.available ? `ok${p.version ? ` (${p.version})` : ""}` : "missing"}
                      {p.importError ? ` — ${p.importError}` : ""}
                    </li>
                  ))}
                </ul>
                {capabilities.notes.length > 0 ? (
                  <p className="lv-muted">{capabilities.notes.join(" · ")}</p>
                ) : null}
              </div>
            ) : null}
            {hardware ? (
              <div style={{ marginTop: "1rem" }}>
                <h3>Hardware</h3>
                <div className="lv-meta-grid">
                  <div className="lv-meta-item">
                    <span>CPU</span>
                    <strong>{dash(hardware.cpuModel)}</strong>
                  </div>
                  <div className="lv-meta-item">
                    <span>RAM free</span>
                    <strong>{formatBytes(hardware.ramAvailableBytes)}</strong>
                  </div>
                  <div className="lv-meta-item">
                    <span>Disk free</span>
                    <strong>{formatBytes(hardware.diskFreeBytes)}</strong>
                  </div>
                </div>
                {hardware.gpus.length === 0 ? (
                  <p className="lv-muted">No GPUs measured on this host.</p>
                ) : (
                  <ul>
                    {hardware.gpus.map((g) => (
                      <li key={g.index}>
                        [{g.index}] {g.name} — VRAM {formatBytes(g.totalVramBytes)}
                      </li>
                    ))}
                  </ul>
                )}
                {hardware.notes.length > 0 ? (
                  <p className="lv-muted">{hardware.notes.join(" · ")}</p>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}

        {tab === "train" ? (
          <section className="lv-panel" aria-label="Create training job">
            <div className="lv-form-grid">
              <div className="lv-form-field">
                <label htmlFor="tr-name">Job name</label>
                <input id="tr-name" className="lv-input" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-method">Method</label>
                <select id="tr-method" className="lv-input" value={method} onChange={(e) => setMethod(e.target.value)}>
                  <option value="fixture">fixture</option>
                  <option value="sft">sft</option>
                  <option value="lora">lora</option>
                  <option value="qlora">qlora</option>
                  <option value="dpo">dpo</option>
                </select>
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-base">Base model ref</label>
                <input
                  id="tr-base"
                  className="lv-input"
                  value={baseModel}
                  onChange={(e) => setBaseModel(e.target.value)}
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-dsv">Dataset version id</label>
                <input
                  id="tr-dsv"
                  className="lv-input"
                  value={datasetVersionId}
                  onChange={(e) => setDatasetVersionId(e.target.value)}
                  placeholder="optional"
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-dsp">Dataset path</label>
                <input
                  id="tr-dsp"
                  className="lv-input"
                  value={datasetPath}
                  onChange={(e) => setDatasetPath(e.target.value)}
                  placeholder="optional local path"
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-epochs">Epochs</label>
                <input id="tr-epochs" className="lv-input" value={epochs} onChange={(e) => setEpochs(e.target.value)} />
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-bs">Batch size</label>
                <input id="tr-bs" className="lv-input" value={batchSize} onChange={(e) => setBatchSize(e.target.value)} />
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-lr">Learning rate</label>
                <input
                  id="tr-lr"
                  className="lv-input"
                  value={learningRate}
                  onChange={(e) => setLearningRate(e.target.value)}
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-seq">Max seq length</label>
                <input id="tr-seq" className="lv-input" value={maxSeq} onChange={(e) => setMaxSeq(e.target.value)} />
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-prec">Precision</label>
                <select
                  id="tr-prec"
                  className="lv-input"
                  value={precision}
                  onChange={(e) => setPrecision(e.target.value)}
                >
                  <option value="fp32">fp32</option>
                  <option value="fp16">fp16</option>
                  <option value="bf16">bf16</option>
                </select>
              </div>
              <div className="lv-form-field">
                <label htmlFor="tr-fix">Fixture steps</label>
                <input
                  id="tr-fix"
                  className="lv-input"
                  value={fixtureSteps}
                  onChange={(e) => setFixtureSteps(e.target.value)}
                  disabled={method !== "fixture"}
                  title={method !== "fixture" ? "Only used for fixture method" : undefined}
                />
              </div>
            </div>

            {methodDisabledReason ? (
              <p className="lv-muted">Selected method note: {methodDisabledReason}</p>
            ) : null}

            <div className="lv-form-actions" style={{ marginTop: "1rem" }}>
              <button className="lv-btn" type="button" disabled={busy} onClick={() => void onPreflight()}>
                Run preflight
              </button>
              <button
                className="lv-btn"
                type="button"
                disabled={busy || Boolean(methodDisabledReason && method !== "fixture" && method !== "sft")}
                title={methodDisabledReason ?? undefined}
                onClick={() => void onCreate(false)}
              >
                Create job
              </button>
              <button
                className="lv-btn lv-btn-gold"
                type="button"
                disabled={
                  busy ||
                  preflight?.verdict === "BLOCKED" ||
                  Boolean(methodDisabledReason && method !== "fixture" && method !== "sft")
                }
                title={
                  preflight?.verdict === "BLOCKED"
                    ? "Blocked by preflight"
                    : (methodDisabledReason ?? undefined)
                }
                onClick={() => void onCreate(true)}
              >
                Create &amp; start
              </button>
            </div>

            {preflight ? (
              <div style={{ marginTop: "1rem" }}>
                <h3>Preflight — {preflight.verdict}</h3>
                {preflight.issues.length === 0 ? (
                  <p className="lv-muted">No issues reported.</p>
                ) : (
                  <ul>
                    {preflight.issues.map((issue) => (
                      <li key={`${issue.code}-${issue.message}`}>
                        [{issue.severity}] {issue.code}: {issue.message}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <p className="lv-muted">Run preflight before starting production jobs.</p>
            )}

            {plan ? (
              <div style={{ marginTop: "1rem" }}>
                <h3>Plan — {plan.strategy}</h3>
                <p className="lv-muted">{plan.reason}</p>
                {plan.warnings.length > 0 ? <p className="lv-muted">{plan.warnings.join(" · ")}</p> : null}
              </div>
            ) : null}
          </section>
        ) : null}

        {tab === "runs" ? (
          <section className="lv-panel" aria-label="Training runs">
            {jobs.length === 0 ? (
              <div className="lv-models-empty">
                <h2>NO TRAINING JOBS</h2>
                <p>Create a job from the Train tab. Nothing is simulated here.</p>
                <button className="lv-btn lv-btn-gold" type="button" onClick={() => setTab("train")}>
                  Open Train
                </button>
              </div>
            ) : (
              <>
                <div className="lv-models-table-wrap">
                  <table className="lv-models-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Method</th>
                        <th>Status</th>
                        <th>Progress</th>
                        <th>Updated</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {jobs.map((job) => (
                        <tr
                          key={job.jobId}
                          className={job.jobId === selectedJobId ? "is-selected" : undefined}
                          onClick={() => setSelectedJobId(job.jobId)}
                        >
                          <td>
                            <strong>{job.name}</strong>
                            <div className="lv-muted">{job.jobId}</div>
                          </td>
                          <td>{job.method}</td>
                          <td>{job.status}</td>
                          <td>{job.progress == null ? "—" : `${Math.round(job.progress * 100)}%`}</td>
                          <td>{job.updatedAt}</td>
                          <td>
                            <div className="lv-row-actions">
                              {job.status === "queued" ? (
                                <button
                                  className="lv-btn"
                                  type="button"
                                  disabled={busy}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void withBusy(async () => {
                                      await api.startTrainingJob(job.jobId);
                                      await loadJobs();
                                    }, "Started");
                                  }}
                                >
                                  Start
                                </button>
                              ) : null}
                              {ACTIVE.has(job.status) ? (
                                <button
                                  className="lv-btn"
                                  type="button"
                                  disabled={busy}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void withBusy(async () => {
                                      await api.cancelTrainingJob(job.jobId);
                                      await loadJobs();
                                    }, "Cancel requested");
                                  }}
                                >
                                  Cancel
                                </button>
                              ) : null}
                              {RESUMABLE.has(job.status) ? (
                                <button
                                  className="lv-btn"
                                  type="button"
                                  disabled={busy}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void withBusy(async () => {
                                      await api.resumeTrainingJob(job.jobId);
                                      await loadJobs();
                                    }, "Resume requested");
                                  }}
                                >
                                  Resume
                                </button>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {selectedJob ? (
                  <div style={{ marginTop: "1rem" }}>
                    <h3>
                      {selectedJob.name} — {selectedJob.status}
                    </h3>
                    {selectedJob.error ? <p className="lv-muted">Error: {selectedJob.error}</p> : null}
                    <h4>Metrics</h4>
                    {metrics.length === 0 ? (
                      <p className="lv-muted">No metrics recorded yet.</p>
                    ) : (
                      <div className="lv-models-table-wrap">
                        <table className="lv-models-table">
                          <thead>
                            <tr>
                              <th>Step</th>
                              <th>Epoch</th>
                              <th>Name</th>
                              <th>Value</th>
                              <th>At</th>
                            </tr>
                          </thead>
                          <tbody>
                            {metrics.slice(-40).map((m, i) => (
                              <tr key={`${m.metricName}-${m.step}-${m.recordedAt}-${i}`}>
                                <td>{dash(m.step)}</td>
                                <td>{dash(m.epoch)}</td>
                                <td>{m.metricName}</td>
                                <td>{m.metricValue}</td>
                                <td>{m.recordedAt}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <h4>Logs</h4>
                    {logs?.text ? (
                      <pre className="lv-code-block" style={{ maxHeight: 240, overflow: "auto" }}>
                        {logs.text}
                      </pre>
                    ) : (
                      <p className="lv-muted">No log text yet{logs?.logPath ? ` (path: ${logs.logPath})` : ""}.</p>
                    )}
                  </div>
                ) : null}
              </>
            )}
          </section>
        ) : null}

        {tab === "evaluate" ? (
          <section className="lv-panel">
            {!selectedJob ? (
              <p className="lv-muted">Select a job on Runs first.</p>
            ) : (
              <>
                <p className="lv-muted">
                  Evaluate <strong>{selectedJob.name}</strong> ({selectedJob.status})
                </p>
                <button
                  className="lv-btn lv-btn-gold"
                  type="button"
                  disabled={busy || ACTIVE.has(selectedJob.status)}
                  title={ACTIVE.has(selectedJob.status) ? "Wait for the job to finish" : undefined}
                  onClick={() =>
                    void withBusy(async () => {
                      const res = await api.evaluateTrainingJob(selectedJob.jobId);
                      setEvaluation(res.evaluation);
                    }, "Evaluation complete")
                  }
                >
                  Run evaluate
                </button>
                {evaluation ? (
                  <pre className="lv-code-block" style={{ marginTop: "1rem", maxHeight: 320, overflow: "auto" }}>
                    {JSON.stringify(evaluation, null, 2)}
                  </pre>
                ) : (
                  <p className="lv-muted">No evaluation result loaded.</p>
                )}
              </>
            )}
          </section>
        ) : null}

        {tab === "checkpoints" ? (
          <section className="lv-panel">
            {!selectedJobId ? (
              <p className="lv-muted">Select a job on Runs first.</p>
            ) : checkpoints.length === 0 ? (
              <div className="lv-models-empty">
                <h2>NO CHECKPOINTS</h2>
                <p>Checkpoints appear when the trainer writes them for this job.</p>
              </div>
            ) : (
              <div className="lv-models-table-wrap">
                <table className="lv-models-table">
                  <thead>
                    <tr>
                      <th>Step</th>
                      <th>Epoch</th>
                      <th>Path</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checkpoints.map((c) => (
                      <tr key={c.checkpointId}>
                        <td>{dash(c.step)}</td>
                        <td>{dash(c.epoch)}</td>
                        <td>{c.path}</td>
                        <td>{c.createdAt}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ) : null}

        {tab === "exports" ? (
          <section className="lv-panel">
            {!selectedJob ? (
              <p className="lv-muted">Select a job on Runs first.</p>
            ) : (
              <>
                <button
                  className="lv-btn lv-btn-gold"
                  type="button"
                  disabled={busy || selectedJob.status !== "completed"}
                  title={
                    selectedJob.status !== "completed"
                      ? "Export is available after a completed job"
                      : undefined
                  }
                  onClick={() =>
                    void withBusy(async () => {
                      const res = await api.exportTrainingJob(selectedJob.jobId);
                      setExportResult(res.export);
                    }, "Export complete")
                  }
                >
                  Export artifact
                </button>
                {exportResult ? (
                  <pre className="lv-code-block" style={{ marginTop: "1rem", maxHeight: 320, overflow: "auto" }}>
                    {JSON.stringify(exportResult, null, 2)}
                  </pre>
                ) : (
                  <p className="lv-muted">No export result yet.</p>
                )}
              </>
            )}
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
