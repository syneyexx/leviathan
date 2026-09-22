import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type {
  DatasetJob,
  DatasetPreviewRow,
  DatasetRecord,
  DatasetVersion,
  HfDatasetFile,
} from "../types/api";

type Tab = "datasets" | "import" | "prepare" | "jobs";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function DatasetsPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<Tab>("datasets");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [preview, setPreview] = useState<DatasetPreviewRow[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<DatasetJob[]>([]);

  // Import form state
  const [createName, setCreateName] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [localName, setLocalName] = useState("");
  const [hfRepo, setHfRepo] = useState("");
  const [hfRevision, setHfRevision] = useState("main");
  const [hfToken, setHfToken] = useState("");
  const [hfFiles, setHfFiles] = useState<HfDatasetFile[]>([]);
  const [hfFilename, setHfFilename] = useState("");
  const [hfListError, setHfListError] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);

  // Prepare / split
  const [trainRatio, setTrainRatio] = useState("0.8");
  const [valRatio, setValRatio] = useState("0.1");
  const [testRatio, setTestRatio] = useState("0.1");

  const selected = datasets.find((d) => d.datasetId === selectedId) ?? null;
  const selectedVersion = versions.find((v) => v.versionId === selectedVersionId) ?? null;

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listDatasets();
      setDatasets(res.datasets);
      if (res.datasets.length === 0) {
        setSelectedId(null);
      } else if (!selectedId || !res.datasets.some((d) => d.datasetId === selectedId)) {
        setSelectedId(res.datasets[0].datasetId);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load datasets"));
      setDatasets([]);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  const loadJobs = useCallback(async () => {
    try {
      const res = await api.listDatasetJobs(selectedId ?? undefined);
      setJobs(res.jobs);
    } catch (err) {
      toast(errMsg(err, "Failed to load dataset jobs"));
    }
  }, [selectedId, toast]);

  useEffect(() => {
    void loadDatasets();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial load

  useEffect(() => {
    if (!selectedId) {
      setVersions([]);
      setSelectedVersionId(null);
      setPreview([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await api.getDataset(selectedId);
        if (cancelled) return;
        setVersions(detail.versions);
        const ready = detail.versions.find((v) => v.status === "ready") ?? detail.versions[0];
        setSelectedVersionId(ready?.versionId ?? null);
      } catch (err) {
        if (!cancelled) toast(errMsg(err, "Failed to load dataset detail"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, toast]);

  useEffect(() => {
    if (!selectedVersionId) {
      setPreview([]);
      setPreviewError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setPreviewError(null);
      try {
        const res = await api.previewDatasetVersion(selectedVersionId, 20);
        if (cancelled) return;
        setPreview(res.rows);
      } catch (err) {
        if (!cancelled) {
          setPreview([]);
          setPreviewError(errMsg(err, "Preview unavailable"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedVersionId]);

  useEffect(() => {
    void loadJobs();
    const id = window.setInterval(() => {
      void loadJobs();
    }, 4000);
    return () => window.clearInterval(id);
  }, [loadJobs]);

  async function withBusy(fn: () => Promise<void>, okMsg?: string) {
    setBusy(true);
    try {
      await fn();
      if (okMsg) toast(okMsg);
    } catch (err) {
      toast(errMsg(err, "Action failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onCreate() {
    if (!createName.trim()) {
      toast("Name is required");
      return;
    }
    await withBusy(async () => {
      await api.createDataset({ name: createName.trim(), description: createDesc });
      setCreateName("");
      setCreateDesc("");
      await loadDatasets();
      setTab("datasets");
    }, "Dataset created");
  }

  async function onUpload() {
    if (!uploadFile) {
      toast("Choose a file first");
      return;
    }
    await withBusy(async () => {
      const form = new FormData();
      form.append("file", uploadFile);
      if (createName.trim()) form.append("name", createName.trim());
      if (createDesc) form.append("description", createDesc);
      form.append("materialize", "true");
      await api.uploadDataset(form);
      setUploadFile(null);
      await loadDatasets();
      await loadJobs();
      setTab("jobs");
    }, "Upload queued");
  }

  async function onImportLocal() {
    if (!localPath.trim()) {
      toast("Local path is required");
      return;
    }
    await withBusy(async () => {
      await api.importDatasetLocal({
        path: localPath.trim(),
        name: localName.trim() || undefined,
        materialize: true,
      });
      await loadJobs();
      setTab("jobs");
    }, "Local import queued");
  }

  async function onListHf() {
    if (!hfRepo.trim()) {
      toast("Repository id is required");
      return;
    }
    setBusy(true);
    setHfListError(null);
    setHfFiles([]);
    try {
      const res = await api.listHuggingFaceDatasetFiles({
        repositoryId: hfRepo.trim(),
        revision: hfRevision.trim() || "main",
        token: hfToken.trim() || null,
      });
      setHfFiles(res.files);
      if (res.files.length === 0) {
        setHfListError("No files returned for this repository.");
      } else {
        const first = res.files[0];
        setHfFilename(String(first.path ?? first.filename ?? ""));
      }
    } catch (err) {
      setHfListError(errMsg(err, "HuggingFace list failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onImportHf() {
    if (!hfRepo.trim() || !hfFilename.trim()) {
      toast("Repository and filename are required");
      return;
    }
    await withBusy(async () => {
      await api.importDatasetHuggingFace({
        repositoryId: hfRepo.trim(),
        filename: hfFilename.trim(),
        revision: hfRevision.trim() || "main",
        token: hfToken.trim() || null,
        materialize: true,
      });
      await loadJobs();
      setTab("jobs");
    }, "HuggingFace import queued");
  }

  async function runVersionAction(
    action: () => Promise<{ job: DatasetJob }>,
    label: string,
  ) {
    if (!selectedId || !selectedVersionId) {
      toast("Select a dataset version first");
      return;
    }
    await withBusy(async () => {
      await action();
      await loadJobs();
      setTab("jobs");
    }, `${label} queued`);
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Datasets Mode"
      searchPlaceholder="Search datasets…"
      pageClass="lv-app--datasets"
      layout="wide"
    >
      <main className="lv-main">
        <header className="lv-models-header">
          <div>
            <div className="lv-models-kicker">Corpus control</div>
            <h1 className="lv-models-title">Datasets</h1>
            <p className="lv-muted">Real imports, versions, and jobs — no demo corpora.</p>
          </div>
          <div className="lv-models-header-actions">
            <button className="lv-btn" type="button" disabled={busy || loading} onClick={() => void loadDatasets()}>
              Refresh
            </button>
            <Link className="lv-btn" to="/training">
              Open Training
            </Link>
          </div>
        </header>
        {error ? (
          <div className="lv-models-banner is-error" role="alert">
            <strong>Datasets unavailable</strong>
            <span>{error}</span>
            <button className="lv-btn" type="button" onClick={() => void loadDatasets()}>
              Retry
            </button>
          </div>
        ) : null}

        <div className="lv-tabs" role="tablist">
          {(
            [
              ["datasets", "My Datasets"],
              ["import", "Import"],
              ["prepare", "Prepare"],
              ["jobs", "Jobs"],
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
          <section className="lv-panel" aria-label="Dataset list">
            {loading ? (
              <div className="lv-models-banner" role="status">
                Loading datasets…
              </div>
            ) : null}
            {!loading && datasets.length === 0 ? (
              <div className="lv-models-empty">
                <h2>NO DATASETS</h2>
                <p>Upload a file, import a local path, or pull from HuggingFace.</p>
                <div className="lv-models-empty-actions">
                  <button className="lv-btn lv-btn-gold" type="button" onClick={() => setTab("import")}>
                    Import data
                  </button>
                </div>
              </div>
            ) : (
              <div className="lv-models-table-wrap">
                <table className="lv-models-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Source</th>
                      <th>Status</th>
                      <th>Rows</th>
                      <th>Size</th>
                      <th>Updated</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {datasets.map((ds) => (
                      <tr
                        key={ds.datasetId}
                        className={ds.datasetId === selectedId ? "is-selected" : undefined}
                        onClick={() => setSelectedId(ds.datasetId)}
                      >
                        <td>
                          <strong>{ds.name}</strong>
                          <div className="lv-muted">{ds.description || ds.datasetId}</div>
                        </td>
                        <td>{ds.sourceType}</td>
                        <td>{ds.status}</td>
                        <td>{dash(ds.rowCount)}</td>
                        <td>{formatBytes(ds.byteSize)}</td>
                        <td>{ds.updatedAt}</td>
                        <td>
                          <button
                            className="lv-btn lv-btn-danger"
                            type="button"
                            disabled={busy}
                            onClick={(e) => {
                              e.stopPropagation();
                              void withBusy(async () => {
                                await api.deleteDataset(ds.datasetId);
                                await loadDatasets();
                              }, "Dataset deleted");
                            }}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {selected ? (
              <div className="lv-panel" style={{ marginTop: "1rem" }}>
                <div className="lv-card-head">
                  <div>
                    <div className="lv-section-label">Selected</div>
                    <h2>{selected.name}</h2>
                    <p className="lv-muted">
                      {selected.status} · {selected.sourceType} · {dash(selected.detectedFormat)}
                    </p>
                  </div>
                  <div className="lv-row-actions">
                    <button
                      className="lv-btn"
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void withBusy(async () => {
                          await api.materializeDataset(selected.datasetId);
                          await loadJobs();
                          setTab("jobs");
                        }, "Materialize queued")
                      }
                    >
                      Materialize
                    </button>
                    <button className="lv-btn" type="button" onClick={() => setTab("prepare")}>
                      Prepare
                    </button>
                  </div>
                </div>

                <h3>Versions</h3>
                {versions.length === 0 ? (
                  <p className="lv-muted">No versions yet. Import or materialize to create one.</p>
                ) : (
                  <div className="lv-models-table-wrap">
                    <table className="lv-models-table">
                      <thead>
                        <tr>
                          <th>Label</th>
                          <th>Kind</th>
                          <th>Status</th>
                          <th>Rows</th>
                          <th>Updated</th>
                        </tr>
                      </thead>
                      <tbody>
                        {versions.map((v) => (
                          <tr
                            key={v.versionId}
                            className={v.versionId === selectedVersionId ? "is-selected" : undefined}
                            onClick={() => setSelectedVersionId(v.versionId)}
                          >
                            <td>{v.versionLabel}</td>
                            <td>{v.kind}</td>
                            <td>{v.status}</td>
                            <td>{dash(v.rowCount)}</td>
                            <td>{v.updatedAt}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <h3>Preview</h3>
                {previewError ? (
                  <p className="lv-muted">{previewError}</p>
                ) : preview.length === 0 ? (
                  <p className="lv-muted">
                    {selectedVersion
                      ? "No preview rows for this version."
                      : "Select a version to preview."}
                  </p>
                ) : (
                  <pre className="lv-code-block" style={{ maxHeight: 280, overflow: "auto" }}>
                    {JSON.stringify(preview, null, 2)}
                  </pre>
                )}
              </div>
            ) : null}
          </section>
        ) : null}

        {tab === "import" ? (
          <section className="lv-panel" aria-label="Import datasets">
            <div className="lv-form-grid">
              <div className="lv-form-field">
                <label htmlFor="ds-create-name">Create empty dataset — name</label>
                <input
                  id="ds-create-name"
                  className="lv-input"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  placeholder="my-corpus"
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="ds-create-desc">Description</label>
                <input
                  id="ds-create-desc"
                  className="lv-input"
                  value={createDesc}
                  onChange={(e) => setCreateDesc(e.target.value)}
                />
              </div>
              <div className="lv-form-actions full">
                <button className="lv-btn" type="button" disabled={busy} onClick={() => void onCreate()}>
                  Create dataset
                </button>
              </div>
            </div>

            <hr />

            <h3>Upload file</h3>
            <p className="lv-muted">
              Allowed: .jsonl .ndjson .json .csv .tsv .txt .md — max 512 MiB. Larger corpora use local/HF
              paths.
            </p>
            <div className="lv-form-grid">
              <div className="lv-form-field full">
                <label htmlFor="ds-upload">File</label>
                <input
                  id="ds-upload"
                  type="file"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <div className="lv-form-actions full">
                <button
                  className="lv-btn lv-btn-gold"
                  type="button"
                  disabled={busy || !uploadFile}
                  onClick={() => void onUpload()}
                >
                  Upload &amp; queue import
                </button>
              </div>
            </div>

            <hr />

            <h3>Import local path</h3>
            <div className="lv-form-grid">
              <div className="lv-form-field full">
                <label htmlFor="ds-local-path">Absolute path on server</label>
                <input
                  id="ds-local-path"
                  className="lv-input"
                  value={localPath}
                  onChange={(e) => setLocalPath(e.target.value)}
                  placeholder="/data/corpus.jsonl"
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="ds-local-name">Optional name</label>
                <input
                  id="ds-local-name"
                  className="lv-input"
                  value={localName}
                  onChange={(e) => setLocalName(e.target.value)}
                />
              </div>
              <div className="lv-form-actions full">
                <button className="lv-btn" type="button" disabled={busy} onClick={() => void onImportLocal()}>
                  Import local
                </button>
                <button
                  className="lv-btn"
                  type="button"
                  disabled={busy || !localPath.trim()}
                  onClick={() =>
                    void withBusy(async () => {
                      const res = await api.inspectDatasetPath(localPath.trim());
                      toast(`Format: ${String(res.inspection.format ?? "unknown")}`);
                    })
                  }
                >
                  Inspect path
                </button>
              </div>
            </div>

            <hr />

            <h3>HuggingFace import</h3>
            <div className="lv-form-grid">
              <div className="lv-form-field">
                <label htmlFor="ds-hf-repo">Repository id</label>
                <input
                  id="ds-hf-repo"
                  className="lv-input"
                  value={hfRepo}
                  onChange={(e) => setHfRepo(e.target.value)}
                  placeholder="org/dataset"
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="ds-hf-rev">Revision</label>
                <input
                  id="ds-hf-rev"
                  className="lv-input"
                  value={hfRevision}
                  onChange={(e) => setHfRevision(e.target.value)}
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="ds-hf-token">Token (optional)</label>
                <input
                  id="ds-hf-token"
                  className="lv-input"
                  type="password"
                  value={hfToken}
                  onChange={(e) => setHfToken(e.target.value)}
                  autoComplete="off"
                />
              </div>
              <div className="lv-form-actions full">
                <button className="lv-btn" type="button" disabled={busy} onClick={() => void onListHf()}>
                  List files
                </button>
              </div>
              {hfListError ? <p className="lv-muted full">{hfListError}</p> : null}
              {hfFiles.length > 0 ? (
                <div className="lv-form-field full">
                  <label htmlFor="ds-hf-file">Filename</label>
                  <select
                    id="ds-hf-file"
                    className="lv-input"
                    value={hfFilename}
                    onChange={(e) => setHfFilename(e.target.value)}
                  >
                    {hfFiles.map((f) => {
                      const name = String(f.path ?? f.filename ?? "");
                      return (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      );
                    })}
                  </select>
                </div>
              ) : (
                <div className="lv-form-field full">
                  <label htmlFor="ds-hf-file-manual">Filename</label>
                  <input
                    id="ds-hf-file-manual"
                    className="lv-input"
                    value={hfFilename}
                    onChange={(e) => setHfFilename(e.target.value)}
                    placeholder="data/train.jsonl"
                  />
                </div>
              )}
              <div className="lv-form-actions full">
                <button
                  className="lv-btn lv-btn-gold"
                  type="button"
                  disabled={busy || !hfRepo.trim() || !hfFilename.trim()}
                  onClick={() => void onImportHf()}
                >
                  Import from HuggingFace
                </button>
              </div>
            </div>
          </section>
        ) : null}

        {tab === "prepare" ? (
          <section className="lv-panel" aria-label="Prepare dataset">
            {!selected || !selectedVersion ? (
              <div className="lv-models-empty">
                <h2>NO VERSION SELECTED</h2>
                <p>Choose a dataset and version under My Datasets first.</p>
                <button className="lv-btn" type="button" onClick={() => setTab("datasets")}>
                  Back to datasets
                </button>
              </div>
            ) : (
              <>
                <p className="lv-muted">
                  Working on <strong>{selected.name}</strong> / {selectedVersion.versionLabel} (
                  {selectedVersion.status})
                </p>
                <div className="lv-row-actions" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
                  <button
                    className="lv-btn"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void runVersionAction(
                        () => api.validateDatasetVersion(selected.datasetId, selectedVersion.versionId),
                        "Validate",
                      )
                    }
                  >
                    Validate
                  </button>
                  <button
                    className="lv-btn"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void runVersionAction(
                        () => api.dedupeDatasetVersion(selected.datasetId, selectedVersion.versionId),
                        "Dedupe",
                      )
                    }
                  >
                    Dedupe
                  </button>
                  <button
                    className="lv-btn"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void runVersionAction(
                        () =>
                          api.tokenizeStatsDatasetVersion(selected.datasetId, selectedVersion.versionId),
                        "Tokenize stats",
                      )
                    }
                  >
                    Tokenize stats
                  </button>
                  <button
                    className="lv-btn"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void runVersionAction(
                        () => api.exportDatasetVersion(selected.datasetId, selectedVersion.versionId),
                        "Export",
                      )
                    }
                  >
                    Export
                  </button>
                  <button
                    className="lv-btn"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void runVersionAction(
                        () => api.indexDatasetVersion(selected.datasetId, selectedVersion.versionId),
                        "Index",
                      )
                    }
                  >
                    Index into knowledge
                  </button>
                  <button
                    className="lv-btn"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void withBusy(async () => {
                        const res = await api.scanDatasetPii(selectedVersion.versionId);
                        toast(
                          `PII scan: ${JSON.stringify(res.pii).slice(0, 120)}${
                            JSON.stringify(res.pii).length > 120 ? "…" : ""
                          }`,
                        );
                      })
                    }
                  >
                    Scan PII
                  </button>
                </div>

                <h3>Split</h3>
                <div className="lv-form-grid">
                  <div className="lv-form-field">
                    <label htmlFor="split-train">Train ratio</label>
                    <input
                      id="split-train"
                      className="lv-input"
                      value={trainRatio}
                      onChange={(e) => setTrainRatio(e.target.value)}
                    />
                  </div>
                  <div className="lv-form-field">
                    <label htmlFor="split-val">Val ratio</label>
                    <input
                      id="split-val"
                      className="lv-input"
                      value={valRatio}
                      onChange={(e) => setValRatio(e.target.value)}
                    />
                  </div>
                  <div className="lv-form-field">
                    <label htmlFor="split-test">Test ratio</label>
                    <input
                      id="split-test"
                      className="lv-input"
                      value={testRatio}
                      onChange={(e) => setTestRatio(e.target.value)}
                    />
                  </div>
                  <div className="lv-form-actions full">
                    <button
                      className="lv-btn lv-btn-gold"
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void runVersionAction(
                          () =>
                            api.splitDatasetVersion(selected.datasetId, selectedVersion.versionId, {
                              trainRatio: Number(trainRatio),
                              valRatio: Number(valRatio),
                              testRatio: Number(testRatio),
                            }),
                          "Split",
                        )
                      }
                    >
                      Queue split
                    </button>
                  </div>
                </div>
                <p className="lv-muted">
                  Actions enqueue durable jobs. Watch progress under the Jobs tab — nothing is fabricated.
                </p>
              </>
            )}
          </section>
        ) : null}

        {tab === "jobs" ? (
          <section className="lv-panel" aria-label="Dataset jobs">
            <div className="lv-row-actions" style={{ marginBottom: "1rem" }}>
              <button
                className="lv-btn lv-btn-gold"
                type="button"
                disabled={busy}
                onClick={() =>
                  void withBusy(async () => {
                    const res = await api.processDatasetJobs();
                    toast(`Processed ${res.processed.length} job(s)`);
                    await loadJobs();
                  })
                }
              >
                Process queue
              </button>
              <button
                className="lv-btn"
                type="button"
                disabled={busy}
                onClick={() =>
                  void withBusy(async () => {
                    const res = await api.reconcileDatasetJobs();
                    toast(`Reconciled ${res.updated.length} job(s)`);
                    await loadJobs();
                  })
                }
              >
                Reconcile
              </button>
              <button className="lv-btn" type="button" disabled={busy} onClick={() => void loadJobs()}>
                Refresh jobs
              </button>
            </div>
            {jobs.length === 0 ? (
              <div className="lv-models-empty">
                <h2>NO JOBS</h2>
                <p>Import, validate, split, or export actions will appear here when queued.</p>
              </div>
            ) : (
              <div className="lv-models-table-wrap">
                <table className="lv-models-table">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Phase</th>
                      <th>Progress</th>
                      <th>Dataset</th>
                      <th>Error</th>
                      <th>Updated</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr key={job.jobId}>
                        <td>{job.jobType}</td>
                        <td>{job.status}</td>
                        <td>{dash(job.phase)}</td>
                        <td>
                          {job.progress == null ? "—" : `${Math.round(job.progress * 100)}%`}
                        </td>
                        <td>{dash(job.datasetId)}</td>
                        <td>{dash(job.error)}</td>
                        <td>{job.updatedAt}</td>
                        <td>
                          {job.status === "queued" || job.status === "running" ? (
                            <button
                              className="lv-btn"
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                void withBusy(async () => {
                                  await api.cancelDatasetJob(job.jobId);
                                  await loadJobs();
                                }, "Cancel requested")
                              }
                            >
                              Cancel
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
