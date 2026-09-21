import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { SubMenu } from "../components/SubMenu";
import type {
  HealthResponse,
  MasterGateReport,
  NeuroResidualStatus,
  ReleaseGateReport,
  SecurityAuditReport,
  SoakReport,
  TrainingRecipe,
} from "../types/api";

type LoadState = {
  health: HealthResponse | null;
  release: ReleaseGateReport | null;
  security: SecurityAuditReport | null;
  master: MasterGateReport | null;
  residual: NeuroResidualStatus | null;
  recipes: TrainingRecipe[];
  soak: SoakReport | null;
  error: string | null;
};

/**
 * Taken — merged Mission Control + tasks operator surface.
 * Replaces the separate Mission Control entry with one Hades AI submenu page.
 */
export function TasksPage() {
  const [state, setState] = useState<LoadState>({
    health: null,
    release: null,
    security: null,
    master: null,
    residual: null,
    recipes: [],
    soak: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [health, release, security, master, residual, recipes] = await Promise.all([
          api.health(),
          api.releaseGates(),
          api.securityAudit(),
          api.masterGates(),
          api.neuroResidual(),
          api.listTrainingRecipes(),
        ]);
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          health,
          release: release.report,
          security: security.report,
          master: master.report,
          residual,
          recipes: recipes.recipes,
          error: null,
        }));
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Failed to load tasks status";
        setState((prev) => ({ ...prev, error: message }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function runSoak() {
    try {
      const result = await api.neuroSoak(3);
      setState((prev) => ({ ...prev, soak: result.report, error: null }));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Neuro soak failed";
      setState((prev) => ({ ...prev, error: message }));
    }
  }

  const health = state.health;
  const neuro = health?.neuro;
  const pendingApprovals = health?.approvals?.pending ?? 0;

  return (
    <AppShell activeMode="explore" searchPlaceholder="Zoek taken, jobs, approvals...">
      <main className="lv-main">
        <SubMenu />

        <section className="lv-panel lv-card" style={{ marginBottom: "1rem" }}>
          <div className="lv-card-head">
            <div className="lv-section-label">Taken</div>
            <span className="lv-online-count">
              {health?.ok ? "Control plane reachable" : "Waiting for health"}
            </span>
          </div>
          <p className="lv-muted" style={{ marginTop: 0 }}>
            Mission Control en Taken zijn samengevoegd tot één operator-overzicht.
          </p>
          {state.error ? <p className="lv-muted">{state.error}</p> : null}
          {health ? (
            <div className="lv-world-stats">
              <div className="lv-world-stat">
                <span>Version</span>
                <strong>{health.version}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Pending approvals</span>
                <strong>{pendingApprovals}</strong>
              </div>
              <div className="lv-world-stat">
                <span>LLM</span>
                <strong>{health.llm.available ? health.llm.model ?? "Ready" : "Offline"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Agents</span>
                <strong>{health.agents?.enabled ? "Enabled" : "Flagged off"}</strong>
              </div>
            </div>
          ) : null}
        </section>

        <div className="lv-grid-2">
          <section className="lv-panel lv-card">
            <div className="lv-section-label">Master gates</div>
            {state.master ? (
              <pre className="lv-muted" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                {JSON.stringify(state.master, null, 2)}
              </pre>
            ) : (
              <p className="lv-muted">Loading…</p>
            )}
          </section>
          <section className="lv-panel lv-card">
            <div className="lv-section-label">Release gates</div>
            {state.release ? (
              <pre className="lv-muted" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                {JSON.stringify(state.release, null, 2)}
              </pre>
            ) : (
              <p className="lv-muted">Loading…</p>
            )}
          </section>
          <section className="lv-panel lv-card">
            <div className="lv-section-label">Security posture</div>
            {state.security ? (
              <pre className="lv-muted" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                {JSON.stringify(state.security, null, 2)}
              </pre>
            ) : (
              <p className="lv-muted">Loading…</p>
            )}
          </section>
          <section className="lv-panel lv-card">
            <div className="lv-section-label">Neuro layer</div>
            {neuro || state.residual ? (
              <pre className="lv-muted" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                {JSON.stringify({ neuro, residual: state.residual, soak: state.soak }, null, 2)}
              </pre>
            ) : (
              <p className="lv-muted">Loading…</p>
            )}
            <button className="lv-button-primary" type="button" style={{ marginTop: 12, padding: "8px 14px" }} onClick={() => void runSoak()}>
              Run neuro soak
            </button>
          </section>
        </div>
      </main>
    </AppShell>
  );
}
