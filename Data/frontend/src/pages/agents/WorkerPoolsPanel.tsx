import { useMemo, useState } from "react";
import type {
  AgentsDashboardWorkers,
  WorkerFabricDashboard,
  WorkerFabricPool,
  WorkerFabricWorker,
} from "../../types/api";
import { formatPct } from "./helpers";
import { Bar, PanelHead } from "./agentsUi";

type Tab = "Pools" | "Workers" | "Jobs" | "Failures";

function resLabel(classes: string[] | undefined): string {
  if (!classes?.length) return "—";
  const map: Record<string, string> = {
    CPU_LIGHT: "CPU",
    CPU_HEAVY: "CPU",
    IO_HEAVY: "IO",
    MEMORY_HEAVY: "MEM",
    NETWORK_BOUND: "NET",
    MODEL_INFERENCE: "MODEL",
    GPU_SHARED: "GPU",
    GPU_EXCLUSIVE: "GPU",
    DB_SERIAL: "DB",
    BATCH: "BATCH",
    MAINTENANCE_EXCLUSIVE: "EXCL",
  };
  const out: string[] = [];
  for (const c of classes) {
    const lab = map[c] || c;
    if (!out.includes(lab)) out.push(lab);
  }
  return out.join(" / ");
}

function statusTone(status: string | undefined): "ok" | "warn" | "muted" {
  const s = (status || "").toUpperCase();
  if (s === "HEALTHY" || s === "READY") return "ok";
  if (s === "DISABLED" || s === "DEPRECATED" || s === "UNAVAILABLE") return "muted";
  return "warn";
}

function fmtCpu(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v)}%`;
}

function fmtRam(mb: number | null | undefined): string {
  if (mb == null || Number.isNaN(mb)) return "—";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(0)} MB`;
}

function progressLabel(w: WorkerFabricWorker): string {
  if (w.progress_current != null && w.progress_total != null) {
    return `${w.progress_current} / ${w.progress_total}`;
  }
  if (w.progress_percent != null) return `${w.progress_percent}%`;
  return "—";
}

/** Legacy dashboard-only pools (agents dashboard workers.pools) → fabric-like rows. */
function legacyPools(workers: AgentsDashboardWorkers | null): WorkerFabricPool[] {
  return (workers?.pools ?? []).map((p) => ({
    pool_id: p.poolId,
    description: p.description,
    desired: p.desired,
    max_count: p.maxCount,
    instances: p.instances,
    running: p.ready + p.busy,
    ready: p.ready,
    idle: p.ready,
    busy: p.busy,
    draining: p.draining,
    degraded: p.degraded,
    failed: 0,
    starting: 0,
    queued: p.queue ?? 0,
    restarts: 0,
    status:
      p.desired <= 0
        ? "DISABLED"
        : p.ready + p.busy <= 0
          ? "DEGRADED"
          : p.degraded > 0
            ? "DEGRADED"
            : "HEALTHY",
    status_reason: null,
    optional: false,
    resource_classes: p.resourceClasses,
    job_kinds: p.jobKinds,
    entrypoint: p.entrypoint ?? "",
    default_count: p.desired,
    workers: [],
  }));
}

export function WorkerPoolsPanel({
  workers,
  fabric,
  busy,
  onScale,
  onManage,
  onInspectWorker,
  onInspectPool,
}: {
  workers: AgentsDashboardWorkers | null;
  fabric: WorkerFabricDashboard | null;
  busy: boolean;
  onScale: (poolId: string, desired: number) => void;
  onManage: (poolId?: string) => void;
  onInspectWorker?: (workerId: string) => void;
  onInspectPool?: (poolId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("Pools");
  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);
  const [selectedPoolId, setSelectedPoolId] = useState<string | null>(null);

  const summary = fabric?.summary;
  const pools = useMemo(() => {
    if (fabric?.pools?.length) {
      return [...fabric.pools].sort(
        (a, b) =>
          (b.desired > 0 ? 1 : 0) - (a.desired > 0 ? 1 : 0) ||
          b.busy - a.busy ||
          a.pool_id.localeCompare(b.pool_id),
      );
    }
    return legacyPools(workers);
  }, [fabric, workers]);

  const fabricWorkers = useMemo(() => {
    const list = fabric?.workers ?? [];
    return [...list].sort(
      (a, b) =>
        String(a.pool_id).localeCompare(String(b.pool_id)) || (a.slot ?? 0) - (b.slot ?? 0),
    );
  }, [fabric]);

  const available = Boolean(fabric || workers?.available);
  const liveLabel = summary
    ? `${summary.running_workers} Running · ${summary.busy_workers} Busy · ${summary.idle_workers} Idle · ${summary.queue_depth} Queued`
    : workers?.available
      ? `${workers.active ?? 0} active · ${workers.instances ?? 0} registered`
      : "registry unavailable";

  const selectedWorker =
    selectedWorkerId != null ? fabricWorkers.find((w) => w.worker_id === selectedWorkerId) : null;
  const selectedPool =
    selectedPoolId != null ? pools.find((p) => p.pool_id === selectedPoolId) : null;

  return (
    <section className="lv-ag-panel lv-ag-pools lv-ag-fabric">
      <PanelHead
        title="Worker Fabric"
        subtitle={available ? `LIVE · ${liveLabel}` : undefined}
        right={
          <span className="lv-ag-fabric-live" aria-live="polite">
            {summary?.fabric_status ?? workers?.supervisorHealth ?? "—"}
          </span>
        }
      />

      {!available && !workers && !fabric ? (
        <p className="lv-ag-empty">Loading worker registry…</p>
      ) : !available ? (
        <p className="lv-ag-empty">Worker registry unavailable — no pool data.</p>
      ) : (
        <>
          {summary ? (
            <div className="lv-ag-fabric-kpis" aria-label="Worker fabric summary">
              <span>
                <em>{summary.pools_total}</em> pools
              </span>
              <span>
                <em>{summary.pools_enabled}</em> enabled
              </span>
              <span>
                <em>{summary.desired_workers}</em> desired
              </span>
              <span>
                <em>{summary.running_workers}</em> running
              </span>
              <span>
                <em>{summary.busy_workers}</em> busy
              </span>
              <span>
                <em>{summary.queue_depth}</em> queued
              </span>
              <span className={summary.degraded_pools ? "is-warn" : undefined}>
                <em>{summary.degraded_pools}</em> degraded
              </span>
            </div>
          ) : null}

          <div className="lv-ag-tabs" role="tablist" aria-label="Worker fabric views">
            {(["Pools", "Workers", "Jobs", "Failures"] as Tab[]).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                className={`lv-ag-tab${tab === t ? " is-active" : ""}`}
                onClick={() => setTab(t)}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "Pools" ? (
            <div className="lv-ag-table-wrap">
              <table className="lv-ag-table is-dense">
                <thead>
                  <tr>
                    <th>Pool</th>
                    <th>Purpose</th>
                    <th className="is-num">Desired</th>
                    <th className="is-num">Running</th>
                    <th className="is-num">Busy</th>
                    <th className="is-num">Queue</th>
                    <th>Resources</th>
                    <th>Status</th>
                    <th className="is-num">Max</th>
                    <th className="is-num">Scale</th>
                  </tr>
                </thead>
                <tbody>
                  {pools.map((p) => (
                    <tr
                      key={p.pool_id}
                      title={p.status_reason || p.description}
                      className="is-clickable"
                      onClick={() => {
                        setSelectedPoolId(p.pool_id);
                        onInspectPool?.(p.pool_id);
                      }}
                    >
                      <td>
                        <span className="lv-ag-cell-agent">
                          <i className={`lv-ag-dot is-${statusTone(p.status)}`} />
                          <span className="lv-ag-cell-name">{p.pool_id}</span>
                        </span>
                      </td>
                      <td className="is-muted is-clip">{p.description || "—"}</td>
                      <td className="is-num">{p.desired}</td>
                      <td className="is-num">{p.running ?? p.ready + p.busy}</td>
                      <td className="is-num">{p.busy}</td>
                      <td className={`is-num${p.queued ? " is-warn" : ""}`}>
                        {p.queued ?? "—"}
                      </td>
                      <td className="is-muted">{resLabel(p.resource_classes)}</td>
                      <td>
                        <span className={`lv-ag-pill is-${statusTone(p.status)}`}>
                          {p.status}
                        </span>
                      </td>
                      <td className="is-num">{p.max_count}</td>
                      <td className="is-num" onClick={(e) => e.stopPropagation()}>
                        <span className="lv-ag-stepper">
                          <button
                            type="button"
                            disabled={busy || p.desired <= 0}
                            onClick={() => onScale(p.pool_id, p.desired - 1)}
                            aria-label={`Scale ${p.pool_id} down`}
                          >
                            −
                          </button>
                          <button
                            type="button"
                            disabled={busy || p.desired >= p.max_count}
                            onClick={() => onScale(p.pool_id, p.desired + 1)}
                            aria-label={`Scale ${p.pool_id} up`}
                          >
                            +
                          </button>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {tab === "Workers" ? (
            <div className="lv-ag-table-wrap">
              {fabricWorkers.length === 0 ? (
                <p className="lv-ag-empty">No registered workers yet — supervisor may still be starting.</p>
              ) : (
                <table className="lv-ag-table is-dense">
                  <thead>
                    <tr>
                      <th>Worker</th>
                      <th className="is-num">PID</th>
                      <th>Pool</th>
                      <th>State</th>
                      <th>Current Work</th>
                      <th>Progress</th>
                      <th className="is-num">CPU</th>
                      <th className="is-num">RAM</th>
                      <th className="is-num">Restarts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fabricWorkers.map((w) => (
                      <tr
                        key={w.worker_id}
                        className="is-clickable"
                        onClick={() => {
                          setSelectedWorkerId(w.worker_id);
                          onInspectWorker?.(w.worker_id);
                          onManage(w.pool_id);
                        }}
                      >
                        <td>
                          <span className="lv-ag-cell-name">
                            {w.display_name || `${w.pool_id}-${w.slot}`}
                          </span>
                        </td>
                        <td className="is-num">{w.pid ?? "—"}</td>
                        <td>{w.pool_id}</td>
                        <td>
                          <span
                            className={`lv-ag-pill is-${
                              w.state === "BUSY"
                                ? "ok"
                                : w.state === "READY"
                                  ? "muted"
                                  : "warn"
                            }`}
                          >
                            {w.state}
                          </span>
                        </td>
                        <td className="is-clip">{w.current_work || "—"}</td>
                        <td className="is-muted">{progressLabel(w)}</td>
                        <td className="is-num">{fmtCpu(w.cpu_percent)}</td>
                        <td className="is-num">{fmtRam(w.rss_mb)}</td>
                        <td className="is-num">{w.restart_count ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ) : null}

          {tab === "Jobs" ? (
            <div className="lv-ag-table-wrap">
              {(fabric?.queued_jobs ?? []).length === 0 &&
              fabricWorkers.every((w) => !w.current_job) ? (
                <p className="lv-ag-empty">No active or queued fabric jobs.</p>
              ) : (
                <table className="lv-ag-table is-dense">
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Capability</th>
                      <th>Pool</th>
                      <th>State</th>
                      <th>Progress</th>
                      <th>Elapsed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fabricWorkers
                      .filter((w) => w.current_job)
                      .map((w) => {
                        const j = w.current_job!;
                        return (
                          <tr key={`run-${j.job_id}`}>
                            <td className="is-clip">{j.human_title || j.job_id}</td>
                            <td className="is-muted">{j.capability_id}</td>
                            <td>{w.pool_id}</td>
                            <td>{j.state}</td>
                            <td>
                              {j.progress_current != null && j.progress_total != null
                                ? `${j.progress_current}/${j.progress_total}`
                                : j.progress_percent != null
                                  ? `${j.progress_percent}%`
                                  : "—"}
                            </td>
                            <td>{j.elapsed_display || "—"}</td>
                          </tr>
                        );
                      })}
                    {(fabric?.queued_jobs ?? []).map((j) => (
                      <tr key={`q-${j.job_id}`}>
                        <td className="is-clip">{j.human_title || j.job_id}</td>
                        <td className="is-muted">{j.capability_id}</td>
                        <td>{j.worker_pool || "—"}</td>
                        <td>{j.state}</td>
                        <td>—</td>
                        <td>—</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ) : null}

          {tab === "Failures" ? (
            <div className="lv-ag-table-wrap">
              {(fabric?.failures ?? []).length === 0 ? (
                <p className="lv-ag-empty">No recent failed jobs.</p>
              ) : (
                <table className="lv-ag-table is-dense">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Job</th>
                      <th>Pool</th>
                      <th>Capability</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(fabric?.failures ?? []).map((f) => (
                      <tr key={f.job_id}>
                        <td className="is-muted">{f.finished_at || "—"}</td>
                        <td className="is-clip">{f.human_title || f.job_id}</td>
                        <td>{f.worker_pool || "—"}</td>
                        <td className="is-muted">{f.capability_id}</td>
                        <td className="is-warn">{f.error_code || "FAILED"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ) : null}

          {selectedWorker ? (
            <aside className="lv-ag-fabric-inspect" aria-label="Worker inspector">
              <header>
                <strong>{selectedWorker.display_name || selectedWorker.worker_id}</strong>
                <button type="button" className="lv-ag-link" onClick={() => setSelectedWorkerId(null)}>
                  Close
                </button>
              </header>
              <dl>
                <div>
                  <dt>Pool</dt>
                  <dd>{selectedWorker.pool_id}</dd>
                </div>
                <div>
                  <dt>PID</dt>
                  <dd>{selectedWorker.pid ?? "—"}</dd>
                </div>
                <div>
                  <dt>State</dt>
                  <dd>{selectedWorker.state}</dd>
                </div>
                <div>
                  <dt>Current work</dt>
                  <dd>{selectedWorker.current_work || "—"}</dd>
                </div>
                <div>
                  <dt>Job</dt>
                  <dd>{selectedWorker.current_job_id || "—"}</dd>
                </div>
                <div>
                  <dt>CPU / RAM</dt>
                  <dd>
                    {fmtCpu(selectedWorker.cpu_percent)} / {fmtRam(selectedWorker.rss_mb)}
                  </dd>
                </div>
                <div>
                  <dt>GPU / VRAM</dt>
                  <dd>
                    {selectedWorker.gpu_percent != null ? `${selectedWorker.gpu_percent}%` : "—"} /{" "}
                    {fmtRam(selectedWorker.vram_mb)}
                  </dd>
                </div>
                <div>
                  <dt>Heartbeat age</dt>
                  <dd>
                    {selectedWorker.heartbeat_age_seconds != null
                      ? `${Math.round(selectedWorker.heartbeat_age_seconds)}s`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Restarts</dt>
                  <dd>{selectedWorker.restart_count ?? 0}</dd>
                </div>
                <div>
                  <dt>Degraded</dt>
                  <dd>{selectedWorker.degraded_reason || "—"}</dd>
                </div>
              </dl>
            </aside>
          ) : null}

          {selectedPool && !selectedWorker ? (
            <aside className="lv-ag-fabric-inspect" aria-label="Pool inspector">
              <header>
                <strong>{selectedPool.pool_id}</strong>
                <button type="button" className="lv-ag-link" onClick={() => setSelectedPoolId(null)}>
                  Close
                </button>
              </header>
              <dl>
                <div>
                  <dt>Purpose</dt>
                  <dd>{selectedPool.description || "—"}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>
                    {selectedPool.status}
                    {selectedPool.status_reason ? ` — ${selectedPool.status_reason}` : ""}
                  </dd>
                </div>
                <div>
                  <dt>Desired / Max</dt>
                  <dd>
                    {selectedPool.desired} / {selectedPool.max_count}
                  </dd>
                </div>
                <div>
                  <dt>Running / Busy / Idle</dt>
                  <dd>
                    {selectedPool.running ?? "—"} / {selectedPool.busy} / {selectedPool.idle ?? selectedPool.ready}
                  </dd>
                </div>
                <div>
                  <dt>Queue</dt>
                  <dd>{selectedPool.queued ?? 0}</dd>
                </div>
                <div>
                  <dt>Resources</dt>
                  <dd>{resLabel(selectedPool.resource_classes)}</dd>
                </div>
                <div>
                  <dt>Job kinds</dt>
                  <dd>{(selectedPool.job_kinds || []).join(", ") || "—"}</dd>
                </div>
              </dl>
              <div className="lv-ag-fabric-inspect-actions">
                <button
                  type="button"
                  className="lv-ag-btn-ghost is-xs"
                  disabled={busy || selectedPool.desired >= selectedPool.max_count}
                  onClick={() => onScale(selectedPool.pool_id, selectedPool.desired + 1)}
                >
                  Scale +
                </button>
                <button
                  type="button"
                  className="lv-ag-btn-ghost is-xs"
                  disabled={busy || selectedPool.desired <= 0}
                  onClick={() => onScale(selectedPool.pool_id, selectedPool.desired - 1)}
                >
                  Scale −
                </button>
                <button
                  type="button"
                  className="lv-ag-link"
                  onClick={() => onManage(selectedPool.pool_id)}
                >
                  Manage →
                </button>
              </div>
            </aside>
          ) : null}

          {!fabric && workers?.available ? (
            <p className="lv-ag-hint is-muted">
              Utilization {formatPct(pools[0]?.desired ? (pools[0].busy + pools[0].ready) / Math.max(1, pools[0].desired) : null, 0)}{" "}
              · open Workers tab after fabric dashboard loads for PID / progress detail.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
