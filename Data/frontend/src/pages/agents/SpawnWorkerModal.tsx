import { useState } from "react";
import type { AgentsDashboardPool } from "../../types/api";
import { Modal } from "./agentsUi";

export function SpawnWorkerModal({
  pools,
  initialPoolId,
  supervisorHealth,
  busy,
  onScale,
  onClose,
}: {
  pools: AgentsDashboardPool[];
  initialPoolId?: string;
  supervisorHealth: string | null;
  busy: boolean;
  onScale: (poolId: string, desired: number) => void;
  onClose: () => void;
}) {
  const [poolId, setPoolId] = useState(initialPoolId || pools[0]?.poolId || "");
  const pool = pools.find((p) => p.poolId === poolId);
  const [desired, setDesired] = useState<number>(
    pool ? Math.min(pool.maxCount, pool.desired + 1) : 1,
  );

  function selectPool(id: string) {
    setPoolId(id);
    const next = pools.find((p) => p.poolId === id);
    if (next) setDesired(Math.min(next.maxCount, next.desired + 1));
  }

  const maxCount = pool?.maxCount ?? 0;
  const valid = Boolean(pool) && desired >= 0 && desired <= maxCount && desired !== pool?.desired;

  return (
    <Modal
      title="Spawn / Scale Workers"
      onClose={onClose}
      footer={
        <>
          <span className="lv-ag-field-hint">
            Persists desired count; the supervisor applies it on its next tick. The API never spawns
            processes directly.
          </span>
          <button
            type="button"
            className="lv-ag-btn-gold"
            disabled={busy || !valid}
            onClick={() => onScale(poolId, desired)}
          >
            Apply
          </button>
        </>
      }
    >
      {pools.length === 0 ? (
        <p className="lv-ag-empty">Worker registry unavailable — no pools to scale.</p>
      ) : (
        <div className="lv-ag-editor-grid">
          <label className="lv-ag-field">
            <span>Pool</span>
            <select value={poolId} onChange={(e) => selectPool(e.target.value)}>
              {pools.map((p) => (
                <option key={p.poolId} value={p.poolId}>
                  {p.poolId} · {p.ready + p.busy}/{p.desired} live · max {p.maxCount}
                </option>
              ))}
            </select>
          </label>
          <label className="lv-ag-field">
            <span>Desired workers (0–{maxCount})</span>
            <input
              type="number"
              min={0}
              max={maxCount}
              value={desired}
              onChange={(e) => setDesired(Math.max(0, Number(e.target.value) || 0))}
            />
          </label>
          {pool ? (
            <ul className="lv-ag-kv lv-ag-span-2">
              <li>
                <span>Description</span>
                <em>{pool.description || "—"}</em>
              </li>
              <li>
                <span>Current desired / instances</span>
                <em>
                  {pool.desired} / {pool.instances}
                </em>
              </li>
              <li>
                <span>Ready / busy / draining / degraded</span>
                <em>
                  {pool.ready} / {pool.busy} / {pool.draining} / {pool.degraded}
                </em>
              </li>
              <li>
                <span>Queued jobs</span>
                <em>{pool.queue ?? "—"}</em>
              </li>
              <li>
                <span>Resource classes</span>
                <em>{pool.resourceClasses.join(", ") || "—"}</em>
              </li>
              <li>
                <span>Supervisor</span>
                <em>{supervisorHealth ?? "unknown"}</em>
              </li>
            </ul>
          ) : null}
          {maxCount === 1 ? (
            <p className="lv-ag-field-hint lv-ag-span-2">
              Singleton pool (max_count = 1) — cannot exceed one worker.
            </p>
          ) : null}
        </div>
      )}
    </Modal>
  );
}
