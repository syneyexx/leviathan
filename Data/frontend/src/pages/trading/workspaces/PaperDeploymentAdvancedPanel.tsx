import { useCallback, useEffect, useState } from "react";
import { api } from "../../../api/client";

/**
 * WAVE 3 — progressive disclosure for paper deployment advanced ops
 * (shadow-observe / promote) that existed in the API client but had weak UI.
 * Drift review requires measured baseline/observed metrics — not invented here.
 */
export function PaperDeploymentAdvancedPanel() {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [targetLevel, setTargetLevel] = useState("A3");

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const { deployments } = await api.listPaperDeployments({ limit: 20 });
      setRows((deployments as unknown as Record<string, unknown>[]) || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load deployments");
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runShadow(id: string) {
    setBusy(`shadow:${id}`);
    setNotice(null);
    setError(null);
    try {
      await api.shadowObserveDeployment(id, {});
      setNotice(`Shadow observe recorded for ${id.slice(0, 10)}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "shadow failed");
    } finally {
      setBusy(null);
    }
  }

  async function runPromote(id: string) {
    setBusy(`promote:${id}`);
    setNotice(null);
    setError(null);
    try {
      await api.promotePaperDeployment(id, { targetLevel });
      setNotice(`Promote → ${targetLevel} requested for ${id.slice(0, 10)} (paper track only)`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "promote failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="lv-tc-wallets" aria-label="Paper deployment advanced">
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
        <h3>Advanced · Shadow / Promote</h3>
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <label className="lv-tc-context__label" style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
            Target
            <select
              className="lv-tc-context__select"
              value={targetLevel}
              onChange={(e) => setTargetLevel(e.target.value)}
            >
              <option value="A2">A2</option>
              <option value="A3">A3</option>
              <option value="A4">A4</option>
            </select>
          </label>
          <button type="button" className="lv-tc-btn" onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
      </header>
      <p className="is-muted" style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
        Shadow observe and promote use COMPLETE paper-deployment APIs. Drift review requires measured
        baseline/observed metrics (not invented in UI). Live money remains BLOCKED.
      </p>
      {notice ? <p style={{ color: "#86efac", fontSize: "0.8rem" }}>{notice}</p> : null}
      {error ? <p style={{ color: "#f87171", fontSize: "0.8rem" }}>{error}</p> : null}
      {!rows.length ? (
        <p className="is-muted">No paper deployments yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Deployment</th>
              <th>Mode</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => {
              const id = String(d.deployment_id || d.id || "");
              return (
                <tr key={id}>
                  <td>{id.slice(0, 14) || "—"}</td>
                  <td>{String(d.mode || "—")}</td>
                  <td>{String(d.status || "—")}</td>
                  <td style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="lv-tc-btn"
                      disabled={!!busy}
                      onClick={() => void runShadow(id)}
                    >
                      Shadow
                    </button>
                    <button
                      type="button"
                      className="lv-tc-btn"
                      disabled={!!busy}
                      onClick={() => void runPromote(id)}
                    >
                      Promote
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
