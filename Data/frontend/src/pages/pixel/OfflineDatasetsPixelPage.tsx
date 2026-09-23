import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { formatElapsed, isActiveJobStatus } from "../../lib/jobStatus";
import { OFFLINE_PAGE_COPY } from "../../mocks/offline-datasets";
import { useAppToast } from "../../state/useAppToast";
import type { DatasetJob, DatasetRecord } from "../../types/api";
import { PxIcon, PxKpi } from "./pixel-shared";

type OfflineStatus = "ready" | "indexing" | "queued" | "failed" | "unknown";

type OfflineRow = {
  id: string;
  datasetId: string;
  versionId: string | null;
  name: string;
  source: string;
  size: string;
  status: OfflineStatus;
  statusLabel: string;
  progress?: number;
  localPath: string;
  checksum: string;
  lastSynced: string;
  chunkCount: number | null;
  documentCount: number | null;
  indexId: string | null;
  sourceMissing: boolean;
};

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = ["JAN.", "FEB.", "MRT.", "APR.", "MEI", "JUN.", "JUL.", "AUG.", "SEP.", "OKT.", "NOV.", "DEC."];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function statusTone(status: OfflineStatus) {
  if (status === "ready") return "green";
  if (status === "indexing") return "cyan";
  if (status === "queued") return "gold";
  if (status === "failed") return "red";
  return "orange";
}

function mapBrainToOffline(status: string | undefined): OfflineStatus {
  const s = String(status || "").toLowerCase();
  if (s === "learned" || s === "ready") return "ready";
  if (s === "indexing" || s === "running") return "indexing";
  if (s === "queued" || s === "pending") return "queued";
  if (s === "failed" || s === "error") return "failed";
  return "unknown";
}

export function OfflineDatasetsPixelPage() {
  const toast = useAppToast();
  const [now, setNow] = useState(() => new Date());
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [jobs, setJobs] = useState<DatasetJob[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("Alle statussen");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dataRoot, setDataRoot] = useState<string | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [learned, jobRes, discovery] = await Promise.all([
        api.listLearnedDatasets(200),
        api.listDatasetJobs(undefined, 100),
        api.discoverOfflineDatasets(1).catch(() => ({ dataRoot: undefined, roots: [], sources: [], count: 0 })),
      ]);
      // Include in-progress learn jobs so operators can watch Brain ingestion.
      const learningJobs = jobRes.jobs.filter(
        (j) =>
          j.jobType === "index" &&
          isActiveJobStatus(j.status) &&
          (j.config as Record<string, unknown> | undefined)?.learnToBrain !== false,
      );
      const byId = new Map(learned.datasets.map((d) => [d.datasetId, d]));
      for (const job of learningJobs) {
        if (!job.datasetId || byId.has(job.datasetId)) continue;
        try {
          const detail = await api.getDataset(job.datasetId);
          byId.set(job.datasetId, {
            ...detail.dataset,
            brainStatus: job.status === "queued" ? "queued" : "indexing",
            learned: false,
            brain: {
              brainStatus: job.status === "queued" ? "queued" : "indexing",
              learned: false,
              jobId: job.jobId,
              progress: job.progress ?? null,
              phase: job.phase ?? null,
              label: job.status === "queued" ? "In wachtrij" : "Bezig met leren",
            },
          });
        } catch {
          /* skip unavailable */
        }
      }
      const merged = [...byId.values()];
      setDatasets(merged);
      setJobs(jobRes.jobs);
      setDataRoot(discovery.dataRoot ?? null);
      if (!selectedId && merged[0]) setSelectedId(merged[0].datasetId);
    } catch (err) {
      setLoadError(errMsg(err, "Geleerde datasets laden mislukt"));
    }
  }, [selectedId]);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(id);
  }, [load]);

  const rows: OfflineRow[] = useMemo(() => {
    return datasets.map((ds) => {
      const brain = ds.brain;
      const idx = (ds.indexes ?? [])[0];
      const activeJob = jobs.find(
        (j) => j.datasetId === ds.datasetId && j.jobType === "index" && isActiveJobStatus(j.status),
      );
      let status: OfflineStatus = mapBrainToOffline(ds.brainStatus ?? brain?.brainStatus);
      let statusLabel = brain?.label || "Geleerd in Brain";
      if (activeJob) {
        status = activeJob.status === "queued" ? "queued" : "indexing";
        statusLabel = `${activeJob.phase || activeJob.jobType} · ${activeJob.status}`;
      } else if (ds.sourceMissing || brain?.sourceMissing) {
        statusLabel = status === "ready" ? "Geleerd (bron ontbreekt)" : statusLabel;
      }
      return {
        id: ds.datasetId,
        datasetId: ds.datasetId,
        versionId: brain?.versionId ?? idx?.versionId ?? null,
        name: ds.name,
        source: ds.sourceType || "local",
        size: formatBytes(ds.byteSize),
        status,
        statusLabel,
        progress:
          activeJob?.progress != null
            ? Math.round(Number(activeJob.progress) * 100)
            : brain?.progress != null
              ? Math.round(Number(brain.progress) * 100)
              : undefined,
        localPath: ds.rawPath || ds.originalUri || "—",
        checksum: ds.contentHash || "—",
        lastSynced: brain?.updatedAt || idx?.updatedAt || ds.updatedAt,
        chunkCount: brain?.chunkCount ?? idx?.chunkCount ?? null,
        documentCount:
          brain?.documentCount != null
            ? Number(brain.documentCount)
            : idx?.provenance && typeof idx.provenance.documentCount === "number"
              ? idx.provenance.documentCount
              : null,
        indexId: brain?.indexId ?? idx?.indexId ?? null,
        sourceMissing: Boolean(ds.sourceMissing || brain?.sourceMissing),
      };
    });
  }, [datasets, jobs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (statusFilter === "Geleerd" && row.status !== "ready") return false;
      if (statusFilter === "Bezig" && row.status !== "indexing") return false;
      if (statusFilter === "Wachtrij" && row.status !== "queued") return false;
      if (statusFilter === "Bron ontbreekt" && !row.sourceMissing) return false;
      if (!q) return true;
      return (
        row.name.toLowerCase().includes(q) ||
        row.source.toLowerCase().includes(q) ||
        row.localPath.toLowerCase().includes(q)
      );
    });
  }, [rows, query, statusFilter]);

  const selected = filtered.find((r) => r.id === selectedId) ?? rows.find((r) => r.id === selectedId) ?? null;

  const stats = useMemo(() => {
    const ready = rows.filter((r) => r.status === "ready").length;
    const active = jobs.filter((j) => j.jobType === "index" && isActiveJobStatus(j.status)).length;
    const chunks = rows.reduce((sum, r) => sum + (r.chunkCount || 0), 0);
    return [
      {
        id: "learned",
        label: "Geleerd in Brain",
        value: String(ready),
        hint: `${rows.length} zichtbaar`,
        icon: "database",
        tone: "gold" as const,
      },
      {
        id: "chunks",
        label: "Chunks",
        value: chunks ? String(chunks) : "—",
        hint: chunks ? "uit READY indexes" : "geen chunktelling",
        icon: "file",
        tone: "cyan" as const,
      },
      {
        id: "jobs",
        label: "Actieve leerjobs",
        value: String(active),
        hint: "index → Brain",
        icon: "bolt",
        tone: "cyan" as const,
      },
      {
        id: "root",
        label: "Data root",
        value: dataRoot ? "gezet" : "—",
        hint: dataRoot || "via LEVIATHAN_DATA_ROOT",
        icon: "folder",
        tone: "green" as const,
      },
    ];
  }, [rows, jobs, dataRoot]);

  async function withBusy(fn: () => Promise<void>, ok?: string) {
    setBusy(true);
    try {
      await fn();
      if (ok) toast(ok);
      await load();
    } catch (err) {
      toast(errMsg(err, "Actie mislukt"));
    } finally {
      setBusy(false);
    }
  }

  async function onRelearn() {
    if (!selected?.datasetId) {
      toast("Selecteer een dataset");
      return;
    }
    await withBusy(async () => {
      await api.learnDataset(selected.datasetId, {
        versionId: selected.versionId,
        rebuild: true,
        offlineOnly: true,
      });
    }, "Opnieuw leren gestart");
  }

  async function onCancelActive() {
    const active = jobs.find(
      (j) => j.datasetId === selected?.datasetId && isActiveJobStatus(j.status),
    );
    if (!active) {
      toast("Geen actieve job");
      return;
    }
    await withBusy(async () => {
      await api.cancelDatasetJob(active.jobId);
    }, "Cancel aangevraagd");
  }

  const clock = `${DAYS[now.getDay()]} ${pad(now.getDate())} ${MONTHS[now.getMonth()]} ${now.getFullYear()} · ${pad(now.getHours())}:${pad(now.getMinutes())}`;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Offline Datasets"
      searchPlaceholder="Zoek geleerde datasets..."
      systemItems={["BRAIN", `${rows.filter((r) => r.status === "ready").length} GELEERD`, dataRoot ? "ROOT" : "—"]}
      layout="wide"
      pageClass="lv-app--pixel-datasets"
    >
      <main className="lv-main lv-px-main">
        <div className="lv-px-stack">
          <header className="lv-px-hero" style={{ padding: "18px 20px" }}>
            <div>
              <h1 className="lv-px-hero-title">{OFFLINE_PAGE_COPY.title}</h1>
              <p className="lv-px-hero-sub">{OFFLINE_PAGE_COPY.subtitle}</p>
              <p style={{ fontSize: 10, color: "var(--lv-text-muted)", marginTop: 8 }}>{clock}</p>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="lv-px-btn" disabled={busy} onClick={() => void load()}>
                Refresh
              </button>
              <Link className="lv-px-btn is-gold" to="/dataset-management">
                Dataset Library
              </Link>
            </div>
          </header>

          {loadError ? (
            <div className="lv-px-panel">
              <p>{loadError}</p>
              <button type="button" className="lv-px-btn is-gold" onClick={() => void load()}>
                Opnieuw
              </button>
            </div>
          ) : null}

          <div className="lv-px-kpi-row is-4">
            {stats.map((stat) => (
              <PxKpi key={stat.id} label={stat.label} value={stat.value} hint={stat.hint} icon={stat.icon} hintTone={stat.tone} />
            ))}
          </div>

          <div className="lv-px-workspace">
            <aside className="lv-px-panel">
              <h2 className="lv-px-panel-title">Acties</h2>
              <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>
                Geselecteerd: {selected ? selected.name : "geen"}
              </p>
              <div className="lv-px-action-list" style={{ marginTop: 8 }}>
                <button type="button" className="is-gold" disabled={busy || !selected} onClick={() => void onRelearn()}>
                  <PxIcon name="refresh" />
                  <span>Opnieuw leren</span>
                </button>
                <button type="button" disabled={busy || !selected} onClick={() => void onCancelActive()}>
                  <PxIcon name="stop" />
                  <span>Annuleer job</span>
                </button>
              </div>
              <p style={{ fontSize: 10, color: "var(--lv-text-muted)", marginTop: 12 }}>
                Alleen datasets met een geverifieerde READY Brain-index horen hier. Fysieke bronnen staan in Dataset
                Library.
              </p>
              {dataRoot ? (
                <p style={{ fontSize: 10, marginTop: 8 }}>
                  <strong>Data root</strong>
                  <br />
                  <code>{dataRoot}</code>
                </p>
              ) : null}
            </aside>

            <section className="lv-px-panel">
              <div className="lv-px-panel-head">
                <h2 className="lv-px-panel-title">Brain-geïmporteerde datasets</h2>
                <span style={{ fontSize: 9, color: "var(--lv-text-muted)" }}>
                  {filtered.length} zichtbaar · {rows.length} totaal
                </span>
              </div>
              <div className="lv-px-filters">
                <label className="lv-px-search">
                  <PxIcon name="search" />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Zoek..." aria-label="Zoek geleerde datasets" />
                </label>
                <select className="lv-px-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  {["Alle statussen", "Geleerd", "Bezig", "Wachtrij", "Bron ontbreekt"].map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
              {filtered.length === 0 ? (
                <p style={{ fontSize: 11, color: "var(--lv-text-muted)", marginTop: 12 }}>
                  Nog geen datasets geleerd. Open Dataset Library en kies &quot;Kennis leren&quot;.
                </p>
              ) : (
                <table className="lv-px-table" style={{ marginTop: 8 }}>
                  <thead>
                    <tr>
                      <th>Dataset</th>
                      <th>Bron</th>
                      <th>Status</th>
                      <th>Chunks</th>
                      <th>Grootte</th>
                      <th>Laatst</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((row) => (
                      <tr
                        key={row.id}
                        className={selectedId === row.id ? "is-selected" : undefined}
                        onClick={() => setSelectedId(row.id)}
                        style={{ cursor: "pointer" }}
                      >
                        <td>{row.name}</td>
                        <td>{row.source}</td>
                        <td>
                          <span className={`lv-px-pill is-${statusTone(row.status)}`}>
                            {row.statusLabel}
                            {row.progress != null ? ` ${row.progress}%` : ""}
                          </span>
                        </td>
                        <td>{row.chunkCount ?? "—"}</td>
                        <td>{row.size}</td>
                        <td>{row.lastSynced ? formatElapsed(row.lastSynced) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <aside className="lv-px-panel">
              <h2 className="lv-px-panel-title">Detail</h2>
              {selected ? (
                <dl className="lv-px-meta" style={{ fontSize: 10 }}>
                  <dt>Naam</dt>
                  <dd>{selected.name}</dd>
                  <dt>Brain status</dt>
                  <dd>{selected.statusLabel}</dd>
                  <dt>Index</dt>
                  <dd>{selected.indexId || "—"}</dd>
                  <dt>Chunks</dt>
                  <dd>{selected.chunkCount ?? "—"}</dd>
                  <dt>Documenten</dt>
                  <dd>{selected.documentCount ?? "—"}</dd>
                  <dt>Pad</dt>
                  <dd>
                    <code>{selected.localPath}</code>
                  </dd>
                  <dt>Checksum</dt>
                  <dd>
                    <code>{selected.checksum}</code>
                  </dd>
                  <dt>Bronstatus</dt>
                  <dd>{selected.sourceMissing ? "Source missing" : "Aanwezig of niet van toepassing"}</dd>
                </dl>
              ) : (
                <p style={{ fontSize: 10, color: "var(--lv-text-muted)" }}>Selecteer een geleerde dataset</p>
              )}
            </aside>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
