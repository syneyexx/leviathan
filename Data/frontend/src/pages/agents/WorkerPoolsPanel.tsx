import { useMemo } from "react";
import type { AgentsDashboardWorkers } from "../../types/api";
import { formatPct } from "./helpers";
import { Bar, PanelHead } from "./agentsUi";

export function WorkerPoolsPanel({
  workers,
  busy,
  onScale,
  onManage,
}: {
  workers: AgentsDashboardWorkers | null;
  busy: boolean;
  onScale: (poolId: string, desired: number) => void;
  onManage: (poolId?: string) => void;
}) {
  const pools = useMemo(
    () =>
      [...(workers?.pools ?? [])].sort(
        (a, b) =>
          b.ready + b.busy - (a.ready + a.busy) || b.desired - a.desired || a.poolId.localeCompare(b.poolId),
      ),
    [workers],
  );

  return (
    <section className="lv-ag-panel lv-ag-pools">
      <PanelHead
        title="Worker Pools"
        subtitle={
          workers?.available
            ? `supervisor ${workers.supervisorHealth ?? "unknown"}${workers.degradedReason ? ` · ${workers.degradedReason}` : ""}`
            : undefined
        }
        right={
          <button type="button" className="lv-ag-link" onClick={() => onManage()} disabled={!workers?.available}>
            Manage →
          </button>
        }
      />
      {!workers ? (
        <p className="lv-ag-empty">Loading worker registry…</p>
      ) : !workers.available ? (
        <p className="lv-ag-empty">Worker registry unavailable — no pool data.</p>
      ) : (
        <div className="lv-ag-table-wrap">
          <table className="lv-ag-table is-dense">
            <thead>
              <tr>
                <th>Pool</th>
                <th className="is-num" title="Ready + busy / desired">Workers</th>
                <th className="is-num" title="Queued jobs routed to this pool">Queue</th>
                <th className="is-num" title="Ready / busy">R / B</th>
                <th>Utilization</th>
                <th className="is-num" title="Catalog max_count">Cap</th>
                <th className="is-num">Scale</th>
              </tr>
            </thead>
            <tbody>
              {pools.map((p) => {
                const live = p.ready + p.busy;
                return (
                  <tr key={p.poolId} title={p.description}>
                    <td>
                      <span className="lv-ag-cell-agent">
                        <i className={`lv-ag-dot is-${p.degraded > 0 ? "warn" : live > 0 ? "ok" : "muted"}`} />
                        <span className="lv-ag-cell-name">{p.poolId}</span>
                      </span>
                    </td>
                    <td className="is-num">
                      {live} / {p.desired}
                    </td>
                    <td className={`is-num${p.queue ? " is-warn" : ""}`}>{p.queue ?? "—"}</td>
                    <td className="is-num is-muted">
                      {p.ready} / {p.busy}
                    </td>
                    <td>
                      <span className="lv-ag-util">
                        <Bar ratio={p.utilization} tone={p.utilization != null && p.utilization < 0.5 ? "warn" : "ok"} />
                        <em>{formatPct(p.utilization, 0)}</em>
                      </span>
                    </td>
                    <td className="is-num">{p.maxCount}</td>
                    <td className="is-num">
                      <span className="lv-ag-stepper">
                        <button
                          type="button"
                          disabled={busy || p.desired <= 0}
                          onClick={() => onScale(p.poolId, p.desired - 1)}
                          aria-label={`Scale ${p.poolId} down`}
                        >
                          −
                        </button>
                        <button
                          type="button"
                          disabled={busy || p.desired >= p.maxCount}
                          onClick={() => onScale(p.poolId, p.desired + 1)}
                          aria-label={`Scale ${p.poolId} up`}
                        >
                          +
                        </button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
