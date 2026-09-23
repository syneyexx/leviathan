import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { formatElapsed, isActiveJobStatus } from "../../lib/jobStatus";
import { OFFLINE_PAGE_COPY } from "../../mocks/offline-datasets";
import { useAppToast } from "../../state/useAppToast";
import type { DatasetIndex, DatasetJob, DatasetRecord, DatasetVersion } from "../../types/api";
import { PxIcon, PxKpi } from "./pixel-shared";

type OfflineStatus = "ready" | "indexing" | "queued" | "failed" | "raw" | "unknown";

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
  indexId: string | null;
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

function mapIndexStatus(status: string | undefined): OfflineStatus {
  const s = String(status || "").toLowerCase();
  if (s === "ready") return "ready";
  if (s === "indexing" || s === "running") return "indexing";
  if (s === "pending" || s === "queued") return "queued";
  if (s === "failed" || s === "error") return "failed";
  return "unknown";
}

export function OfflineDatasetsPixelPage() {
  const toast = useAppToast();
  const [now, setNow] = useState(() => new Date());
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [indexes, setIndexes] = useState<DatasetIndex[]>([]);
  const [jobs, setJobs] = useState<DatasetJob[]>([]);
  const [sources, setSources] = useState<Array<Record<string, unknown>>>([]);
  const [roots, setRoots] = useState<Array<{ id: string; path: string }>>([]);
  const [versionsByDataset, setVersionsByDataset] = useState<Record<string, DatasetVersion[]>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("Alle statussen");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preflight, setPreflight] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [ds, idx, jobRes, discovered] = await Promise.all([
        api.listDatasets(200),
        api.listOfflineBrainIndexes(200),
        api.listDatasetJobs(undefined, 100),
        api.discoverOfflineDatasets(500).catch(() => ({ roots: [], sources: [], count: 0 })),
      ]);
      setDatasets(ds.datasets);
      setIndexes(idx.indexes);
      setJobs(jobRes.jobs);
      setSources(discovered.sources);
      setRoots(discovered.roots);
      const versionEntries = await Promise.all(
        ds.datasets.slice(0, 40).map(async (d) => {
          try {
            const detail = await api.getDataset(d.datasetId);
            return [d.datasetId, detail.versions] as const;
          } catch {
            return [d.datasetId, [] as DatasetVersion[]] as const;
          }
        }),
      );
      setVersionsByDataset(Object.fromEntries(versionEntries));
      if (!selectedId && ds.datasets[0]) setSelectedId(ds.datasets[0].datasetId);
    } catch (err) {
      setLoadError(errMsg(err, "Offline datasets laden mislukt"));
    }
  }, [selectedId]);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(id);
  }, [load]);

  const indexByVersion = useMemo(() => {
    const map = new Map<string, DatasetIndex>();
    for (const idx of indexes) {
      const prev = map.get(idx.versionId);
      if (!prev || (idx.updatedAt || "") > (prev.updatedAt || "")) map.set(idx.versionId, idx);
    }
    return map;
  }, [indexes]);

  const rows: OfflineRow[] = useMemo(() => {
    return datasets.map((ds) => {
      const versions = versionsByDataset[ds.datasetId] ?? [];
      const version =
        versions.find((v) => v.status === "ready") ??
        versions[0] ??
        null;
      const idx = version ? indexByVersion.get(version.versionId) : undefined;
      const activeJob = jobs.find(
        (j) => j.datasetId === ds.datasetId && isActiveJobStatus(j.status),
      );
      let status: OfflineStatus = "raw";
      let statusLabel = "Bron aanwezig";
      if (activeJob) {
        status = activeJob.status === "queued" ? "queued" : "indexing";
        statusLabel = `${activeJob.jobType} · ${activeJob.status}`;
      } else if (idx) {
        status = mapIndexStatus(idx.status);
        statusLabel =
          status === "ready"
            ? "Brain-index klaar"
            : status === "failed"
              ? "Index mislukt"
              : idx.status;
      } else if (version?.status === "ready") {
        status = "raw";
        statusLabel = "Nog niet geïndexeerd";
      }
      return {
        id: ds.datasetId,
        datasetId: ds.datasetId,
        versionId: version?.versionId ?? null,
        name: ds.name,
        source: ds.sourceType || "local",
        size: formatBytes(version?.byteSize ?? ds.byteSize),
        status,
        statusLabel,
        progress: activeJob?.progress != null ? Math.round(Number(activeJob.progress) * 100) : undefined,
        localPath: version?.storagePath || ds.rawPath || "—",
        checksum: version?.contentHash || ds.contentHash || "—",
        lastSynced: idx?.updatedAt || version?.updatedAt || ds.updatedAt,
        chunkCount: idx?.chunkCount ?? null,
        indexId: idx?.indexId ?? null,
      };
    });
  }, [datasets, versionsByDataset, indexByVersion, jobs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (statusFilter === "Offline klaar" && row.status !== "ready") return false;
      if (statusFilter === "Converting" && row.status !== "indexing") return false;
      if (statusFilter === "Queued" && row.status !== "queued") return false;
      if (statusFilter === "Sync required" && row.status === "ready") return false;
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
    const active = jobs.filter((j) => isActiveJobStatus(j.status)).length;
    const discovered = sources.length;
    const bytes = datasets.reduce((sum, d) => sum + (d.byteSize || 0), 0);
    return [
      { id: "datasets", label: "Datasets", value: String(rows.length), hint: `${ready} geïndexeerd`, icon: "database", tone: "gold" as const },
      { id: "storage", label: "Corpus bytes", value: formatBytes(bytes), hint: "dataset registry", icon: "save", tone: "cyan" as const },
      { id: "jobs", label: "Actieve jobs", value: String(active), hint: "import/index", icon: "bolt", tone: "cyan" as const },
      { id: "discovered", label: "Ontdekte bronnen", value: String(discovered), hint: "allowed roots", icon: "folder", tone: "green" as const },
    ];
  }, [rows, jobs, sources.length, datasets]);

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

  async function onImportSource(path: string) {
    await withBusy(async () => {
      await api.importDatasetLocal({ path, materialize: true });
    }, "Lokale import in wachtrij");
  }

  async function onPreflight() {
    if (!selected?.datasetId || !selected.versionId) {
      toast("Selecteer een datasetversie");
      return;
    }
    await withBusy(async () => {
      const res = await api.offlineBrainPreflight({
        datasetId: selected.datasetId,
        versionId: selected.versionId!,
        offlineOnly: true,
      });
      setPreflight(res.preflight);
      if (!res.preflight.ok) toast("Preflight geblokkeerd");
    }, "Offline preflight klaar");
  }

  async function onIndexToBrain() {
    if (!selected?.datasetId || !selected.versionId) {
      toast("Selecteer een datasetversie");
      return;
    }
    await withBusy(async () => {
      await api.enqueueOfflineBrainIndex({
        datasetId: selected.datasetId,
        versionId: selected.versionId!,
        sourceFingerprint: selected.checksum !== "—" ? selected.checksum : null,
      });
    }, "Brain-index job gestart");
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
      searchPlaceholder="Zoek lokale bronnen, indexes..."
      systemItems={["OFFLINE", `${rows.length} DATASETS`, `${sources.length} SOURCES`]}
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
                Dataset Management
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
                <button type="button" disabled={busy || !selected?.versionId} onClick={() => void onPreflight()}>
                  <PxIcon name="shield" />
                  <span>Offline preflight</span>
                </button>
                <button type="button" className="is-gold" disabled={busy || !selected?.versionId} onClick={() => void onIndexToBrain()}>
                  <PxIcon name="database" />
                  <span>Index naar Brain</span>
                </button>
                <button type="button" disabled={busy || !selected} onClick={() => void onCancelActive()}>
                  <PxIcon name="stop" />
                  <span>Annuleer job</span>
                </button>
              </div>
              {preflight ? (
                <div style={{ marginTop: 12, fontSize: 10 }}>
                  <strong>Preflight</strong>
                  <p>ok={String(preflight.ok)}</p>
                  {Array.isArray(preflight.blockers) && preflight.blockers.length > 0 ? (
                    <p style={{ color: "var(--lv-danger, #c44)" }}>{(preflight.blockers as string[]).join("; ")}</p>
                  ) : null}
                  {Array.isArray(preflight.warnings) && preflight.warnings.length > 0 ? (
                    <p>{(preflight.warnings as string[]).join("; ")}</p>
                  ) : null}
                </div>
              ) : null}
              <h3 className="lv-px-panel-title" style={{ marginTop: 16 }}>
                Allowed roots
              </h3>
              <ul style={{ fontSize: 10, color: "var(--lv-text-muted)", paddingLeft: 14 }}>
                {roots.map((r) => (
                  <li key={r.id}>
                    <code>{r.id}</code>: {r.path}
                  </li>
                ))}
                {roots.length === 0 ? <li>Geen roots gerapporteerd</li> : null}
              </ul>
            </aside>

            <section className="lv-px-panel">
              <div className="lv-px-panel-head">
                <h2 className="lv-px-panel-title">Lokale / brain-indexed datasets</h2>
                <span style={{ fontSize: 9, color: "var(--lv-text-muted)" }}>
                  {filtered.length} zichtbaar · {rows.length} totaal
                </span>
              </div>
              <div className="lv-px-filters">
                <label className="lv-px-search">
                  <PxIcon name="search" />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Zoek..." aria-label="Zoek offline datasets" />
                </label>
                <select className="lv-px-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  {["Alle statussen", "Offline klaar", "Converting", "Queued", "Sync required"].map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
              <div className="lv-px-table-wrap">
                <table className="lv-px-table">
                  <thead>
                    <tr>
                      <th>Naam</th>
                      <th>Bron</th>
                      <th>Grootte</th>
                      <th>Chunks</th>
                      <th>Status</th>
                      <th>Checksum</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.length === 0 ? (
                      <tr>
                        <td colSpan={7}>Geen datasets. Importeer via Dataset Management of ontdekte bronnen.</td>
                      </tr>
                    ) : (
                      filtered.map((row) => (
                        <tr
                          key={row.id}
                          className={selectedId === row.id ? "is-selected" : ""}
                          onClick={() => setSelectedId(row.id)}
                        >
                          <td>{row.name}</td>
                          <td>{row.source}</td>
                          <td>{row.size}</td>
                          <td>{row.chunkCount ?? "—"}</td>
                          <td>
                            <span className={`lv-px-badge is-${statusTone(row.status)}`}>{row.statusLabel}</span>
                            {row.progress != null ? ` ${row.progress}%` : ""}
                          </td>
                          <td title={row.checksum}>{row.checksum.slice(0, 12)}</td>
                          <td>{formatElapsed(row.lastSynced)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <aside className="lv-px-panel">
              <h2 className="lv-px-panel-title">Detail</h2>
              {selected ? (
                <dl style={{ fontSize: 11, display: "grid", gap: 6 }}>
                  <div>
                    <dt>ID</dt>
                    <dd>
                      <code>{selected.datasetId}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Version</dt>
                    <dd>
                      <code>{selected.versionId ?? "—"}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Index</dt>
                    <dd>
                      <code>{selected.indexId ?? "—"}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Pad</dt>
                    <dd style={{ wordBreak: "break-all" }}>{selected.localPath}</dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd>{selected.statusLabel}</dd>
                  </div>
                </dl>
              ) : (
                <p style={{ fontSize: 11, color: "var(--lv-text-muted)" }}>Selecteer een rij.</p>
              )}

              <h3 className="lv-px-panel-title" style={{ marginTop: 16 }}>
                Jobs
              </h3>
              <ul style={{ fontSize: 10, paddingLeft: 14 }}>
                {jobs
                  .filter((j) => !selected || j.datasetId === selected.datasetId)
                  .slice(0, 8)
                  .map((j) => (
                    <li key={j.jobId}>
                      {j.jobType} · {j.status}
                      {j.progress != null ? ` · ${Math.round(Number(j.progress) * 100)}%` : ""}
                      {j.error ? ` · ${j.error}` : ""}
                    </li>
                  ))}
                {jobs.length === 0 ? <li>Geen jobs</li> : null}
              </ul>

              <h3 className="lv-px-panel-title" style={{ marginTop: 16 }}>
                Ontdekte bronnen
              </h3>
              <ul style={{ fontSize: 10, paddingLeft: 14, maxHeight: 180, overflow: "auto" }}>
                {sources.slice(0, 30).map((s) => {
                  const path = String(s.path ?? "");
                  return (
                    <li key={path}>
                      {String(s.relativePath ?? path)} · {formatBytes(Number(s.sizeBytes) || 0)}
                      <button
                        type="button"
                        className="lv-px-link"
                        style={{ marginLeft: 6 }}
                        disabled={busy || !path}
                        onClick={() => void onImportSource(path)}
                      >
                        Import
                      </button>
                    </li>
                  );
                })}
                {sources.length === 0 ? <li>Geen bestanden onder allowed roots</li> : null}
              </ul>
            </aside>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
