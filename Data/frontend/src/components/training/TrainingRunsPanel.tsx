import { useMemo, useState } from "react";
import {
  ACTIVE_TRAINING_STATUSES,
  RESUMABLE_TRAINING_STATUSES,
  TRAINING_STATUS_LABELS,
  trainingStatusTone,
} from "../../training/constants";
import { visualNowMs, type TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import type { TrainingJob } from "../../types/api";
import { Badge, Button, Panel, ProgressBar } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

type RunFilter = "all" | "active" | "queued" | "completed" | "failed";

function RunsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  );
}

function formatDuration(startedAt?: string | null, finishedAt?: string | null): string {
  if (!startedAt) return "—";
  const start = Date.parse(startedAt);
  if (Number.isNaN(start)) return "—";
  const end = finishedAt ? Date.parse(finishedAt) : visualNowMs();
  if (Number.isNaN(end) || end < start) return "—";
  const sec = Math.floor((end - start) / 1000);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}u ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function datasetLabel(ws: TrainingWorkspace, versionId?: string | null): string {
  if (!versionId) return "—";
  const ver = ws.datasetVersions.find((v) => v.versionId === versionId);
  if (ver) return ver.versionLabel || ver.versionId;
  const ds = ws.datasets.find((d) => d.datasetId === versionId);
  return ds?.displayName || ds?.name || versionId.slice(0, 8);
}

function gpuLabel(config: Record<string, unknown> | undefined): string {
  const ids = config?.selected_stable_device_ids;
  if (Array.isArray(ids) && ids.length) {
    const id = String(ids[0]);
    if (id.includes("gpu-0")) return "GPU 0";
    if (id.includes("gpu-1")) return "GPU 1";
    return id;
  }
  const strategy = config?.device_strategy;
  return strategy ? String(strategy) : "auto";
}

function matchesFilter(job: TrainingJob, filter: RunFilter): boolean {
  if (filter === "all") return true;
  if (filter === "queued") return job.status === "queued" || job.status === "preflight";
  if (filter === "completed") return job.status === "completed";
  if (filter === "failed") return job.status === "failed";
  if (filter === "active") {
    return ACTIVE_TRAINING_STATUSES.has(job.status) && job.status !== "queued" && job.status !== "preflight";
  }
  return true;
}

export function TrainingRunsPanel({ ws }: Props) {
  const [filter, setFilter] = useState<RunFilter>("all");

  const counts = useMemo(() => {
    let active = 0;
    let queued = 0;
    let completed = 0;
    let failed = 0;
    for (const job of ws.jobs) {
      if (job.status === "queued" || job.status === "preflight") queued += 1;
      else if (ACTIVE_TRAINING_STATUSES.has(job.status)) active += 1;
      else if (job.status === "completed") completed += 1;
      else if (job.status === "failed") failed += 1;
    }
    return { all: ws.jobs.length, active, queued, completed, failed };
  }, [ws.jobs]);

  const filtered = useMemo(
    () => ws.jobs.filter((j) => matchesFilter(j, filter)),
    [ws.jobs, filter],
  );

  const tabs: Array<{ id: RunFilter; label: string; count: number }> = [
    { id: "all", label: "Alle", count: counts.all },
    { id: "active", label: "Actief", count: counts.active },
    { id: "queued", label: "In wachtrij", count: counts.queued },
    { id: "completed", label: "Voltooid", count: counts.completed },
    { id: "failed", label: "Mislukt", count: counts.failed },
  ];

  return (
    <Panel title="Training Runs" icon={<RunsIcon />} className="lv-v2-training-runs">
      <div className="lv-v2-training-runs__tabs" role="tablist" aria-label="Filter runs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={filter === tab.id}
            className={`lv-v2-training-runs__tab${filter === tab.id ? " is-active" : ""}`}
            onClick={() => setFilter(tab.id)}
          >
            {tab.label} ({tab.count})
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="lv-v2-muted">{ws.loading ? "Runs laden…" : "Geen runs in deze filter."}</p>
      ) : (
        <div className="lv-v2-training-runs__table-wrap">
          <table className="lv-v2-training-runs__table">
            <thead>
              <tr>
                <th>Naam</th>
                <th>Model</th>
                <th>Dataset</th>
                <th>Epochs</th>
                <th>Status</th>
                <th>Voortgang</th>
                <th>GPU</th>
                <th>Looptijd</th>
                <th>Acties</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((job) => {
                const selected = ws.selectedJobId === job.jobId;
                const progress =
                  job.progress == null
                    ? null
                    : Math.max(0, Math.min(100, job.progress * (job.progress <= 1 ? 100 : 1)));
                const canCancel = ACTIVE_TRAINING_STATUSES.has(job.status);
                const canResume = RESUMABLE_TRAINING_STATUSES.has(job.status);
                const canStart = job.status === "queued";
                const canExport = job.status === "completed";
                const canEvaluate = job.status === "completed" || job.status === "interrupted";
                const epochs = job.config?.epochs;
                return (
                  <tr
                    key={job.jobId}
                    className={selected ? "is-selected" : undefined}
                    onClick={() => ws.selectJob(job.jobId)}
                  >
                    <td>{job.name}</td>
                    <td title={job.baseModelRef}>{job.baseModelRef}</td>
                    <td>{datasetLabel(ws, job.datasetVersionId)}</td>
                    <td>{epochs != null ? String(epochs) : "—"}</td>
                    <td>
                      <Badge tone={trainingStatusTone(job.status)}>
                        {TRAINING_STATUS_LABELS[job.status] || job.status}
                      </Badge>
                    </td>
                    <td>
                      <div className="lv-v2-training-runs__progress">
                        <ProgressBar value={progress} />
                        <span>{progress == null ? "—" : `${Math.round(progress)}%`}</span>
                      </div>
                    </td>
                    <td>{gpuLabel(job.config)}</td>
                    <td>{formatDuration(job.startedAt, job.finishedAt)}</td>
                    <td>
                      <div className="lv-v2-training-runs__actions" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label="Bekijk metrics"
                          onClick={() => ws.selectJob(job.jobId)}
                        >
                          ↗
                        </Button>
                        {canStart ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={ws.busy}
                            onClick={() => void ws.startJob(job.jobId)}
                          >
                            Start
                          </Button>
                        ) : null}
                        {canResume && !canStart ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={ws.busy}
                            onClick={() => void ws.resumeJob(job.jobId)}
                          >
                            Hervat
                          </Button>
                        ) : null}
                        {canCancel ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={ws.busy}
                            aria-label="Stop training"
                            onClick={() => void ws.cancelJob(job.jobId)}
                          >
                            Stop
                          </Button>
                        ) : null}
                        {canEvaluate ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={ws.busy}
                            onClick={() => void ws.evaluateJob(job.jobId)}
                          >
                            Eval
                          </Button>
                        ) : null}
                        {canExport ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={ws.busy}
                            onClick={() => void ws.exportJob(job.jobId)}
                          >
                            Export
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
