import { api, ApiError } from "../../api/client";

export type ServingWorker = {
  worker_id?: string;
  workerId?: string;
  provider_id?: string;
  providerId?: string;
  model_id?: string;
  modelId?: string;
  backend_kind?: string;
  backendKind?: string;
  endpoint?: string | null;
  state?: string;
  pid?: number | null;
  health_score?: number | null;
  healthScore?: number | null;
  last_error?: string | null;
  lastError?: string | null;
  started_at?: string | null;
  startedAt?: string | null;
};

function field<T>(worker: ServingWorker, snake: keyof ServingWorker, camel: keyof ServingWorker): T | null {
  const value = worker[camel] ?? worker[snake];
  return (value ?? null) as T | null;
}

export function ModelServingPanel({
  workers,
  onRefresh,
  busy = false,
}: {
  workers: ServingWorker[];
  onRefresh: () => Promise<void>;
  busy?: boolean;
}) {
  async function reconcile() {
    try {
      await api.reconcileServingWorkers();
      await onRefresh();
    } catch (err) {
      // Parent surfaces toast via refresh errors; keep panel honest.
      throw err instanceof ApiError ? err : new Error("Reconcile failed");
    }
  }

  return (
    <article className="lv-panel lv-card">
      <div className="lv-card-head">
        <div className="lv-section-label">Serving workers</div>
        <div className="lv-row-actions">
          <button className="lv-link" type="button" disabled={busy} onClick={() => void onRefresh()}>
            Refresh
          </button>
          <button className="lv-btn" type="button" disabled={busy} onClick={() => void reconcile()}>
            Reconcile
          </button>
        </div>
      </div>
      {workers.length === 0 ? (
        <p className="lv-muted">No managed serving workers. Load a managed llama.cpp / vLLM model to start one.</p>
      ) : (
        <table className="lv-models-table">
          <thead>
            <tr>
              <th>Worker</th>
              <th>Model</th>
              <th>Backend</th>
              <th>State</th>
              <th>Endpoint</th>
              <th>PID</th>
              <th>Started</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {workers.map((w) => {
              const id = field<string>(w, "worker_id", "workerId") ?? "—";
              return (
                <tr key={id}>
                  <td>{id}</td>
                  <td>{field<string>(w, "model_id", "modelId") ?? "—"}</td>
                  <td>{field<string>(w, "backend_kind", "backendKind") ?? "—"}</td>
                  <td>{w.state ?? "—"}</td>
                  <td>{w.endpoint ?? "—"}</td>
                  <td>{field<number>(w, "pid", "pid") ?? "—"}</td>
                  <td>{field<string>(w, "started_at", "startedAt") ?? "—"}</td>
                  <td>{field<string>(w, "last_error", "lastError") ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </article>
  );
}
