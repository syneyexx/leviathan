import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
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

export function StatusPage() {
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
        const message = err instanceof ApiError ? err.message : "Failed to load operator status";
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

  return (
    <AppShell activeMode="explore" searchPlaceholder="Operator status">
      <main className="lv-main">
        <section className="lv-panel lv-card" style={{ marginBottom: "1rem" }}>
          <div className="lv-card-head">
            <div className="lv-section-label">Operator Status</div>
            <span className="lv-online-count">
              {health?.ok ? "Control plane reachable" : "Waiting for health"}
            </span>
          </div>
          {state.error ? <p className="lv-muted">{state.error}</p> : null}
          {health ? (
            <div className="lv-world-stats">
              <div className="lv-world-stat">
                <span>Version</span>
                <strong>{health.version}</strong>
              </div>
              <div className="lv-world-stat">
                <span>LLM</span>
                <strong>{health.llm.available ? health.llm.model ?? "Ready" : "Offline"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Agents flag</span>
                <strong>{health.agents?.enabled ? "ON" : "OFF"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Approvals pending</span>
                <strong>{health.approvals?.pending ?? 0}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Capabilities</span>
                <strong>{health.capabilities?.registered ?? "—"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Chaos</span>
                <strong>{health.chaos?.plan.enabled ? "ON" : "OFF"}</strong>
              </div>
            </div>
          ) : null}
        </section>

        <section className="lv-grid-2">
          <article className="lv-panel lv-card">
            <div className="lv-section-label">Master gates</div>
            <p>
              <strong>{state.master?.status ?? "…"}</strong>
              {state.master ? ` · phases ${state.master.phase_span}` : null}
            </p>
            <ul className="lv-agent-list">
              {(state.master?.checks ?? []).map((check) => (
                <li key={check.check_id} className="lv-agent-row" style={{ cursor: "default" }}>
                  <span>
                    <strong>{check.name}</strong>
                    <small>
                      {check.status} — {check.detail}
                    </small>
                  </span>
                </li>
              ))}
            </ul>
            <p className="lv-muted">Local readiness ≠ production certification.</p>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Release gates</div>
            <p>
              <strong>{state.release?.ready ? "READY" : "NOT READY"}</strong>
            </p>
            <ul className="lv-agent-list">
              {(state.release?.checks ?? []).map((check) => (
                <li key={check.gate_id} className="lv-agent-row" style={{ cursor: "default" }}>
                  <span>
                    <strong>{check.name}</strong>
                    <small>
                      {check.passed ? "pass" : "fail"} · {check.severity} — {check.detail}
                    </small>
                  </span>
                </li>
              ))}
            </ul>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Security posture</div>
            <p>
              <strong>
                {state.security
                  ? `${state.security.summary.passed}/${state.security.summary.total} passed`
                  : "…"}
              </strong>
            </p>
            <ul className="lv-agent-list">
              {(state.security?.findings ?? []).map((finding) => (
                <li key={finding.finding_id} className="lv-agent-row" style={{ cursor: "default" }}>
                  <span>
                    <strong>{finding.title}</strong>
                    <small>
                      {finding.passed ? "pass" : "fail"} · {finding.severity} — {finding.detail}
                    </small>
                  </span>
                </li>
              ))}
            </ul>
            <p className="lv-muted">Posture checks only — not a penetration test.</p>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Neuro layer</div>
            <div className="lv-world-stats">
              <div className="lv-world-stat">
                <span>Neuro</span>
                <strong>{neuro?.enabled ? "ON" : "OFF"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Residual</span>
                <strong>
                  {state.residual?.supports_residuals
                    ? state.residual.kind ?? "supported"
                    : state.residual?.kind ?? neuro?.residual_kind ?? "unsupported"}
                </strong>
              </div>
              <div className="lv-world-stat">
                <span>Cortex / tiers</span>
                <strong>
                  {neuro?.cortex ? "cortex" : "—"}/{neuro?.memory_tiers ? "tiers" : "—"}
                </strong>
              </div>
              <div className="lv-world-stat">
                <span>Module manager</span>
                <strong>{health?.module_manager?.enabled ? "ON" : "OFF"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Recipes</span>
                <strong>{state.recipes.length || health?.training_recipes?.registered || 0}</strong>
              </div>
            </div>
            <p className="lv-muted">
              Neural signal ≠ authority. Residual unsupported is not success.
            </p>
            <button type="button" className="lv-button-primary" onClick={() => void runSoak()}>
              Run mini soak
            </button>
            {state.soak ? (
              <p className="lv-muted">
                Soak {state.soak.passed}/{state.soak.passed + state.soak.failed} steps ok ·{" "}
                {Math.round(state.soak.duration_ms)}ms (not a production SLO)
              </p>
            ) : null}
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Knowledge / RAG</div>
            <div className="lv-world-stats">
              <div className="lv-world-stat">
                <span>Documents</span>
                <strong>{health?.knowledge?.documents ?? "—"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Embeddings</span>
                <strong>
                  {health?.knowledge?.embedding_available
                    ? health.knowledge.embedding_provider ?? "ready"
                    : health?.knowledge?.embedding_provider ?? "unavailable"}
                </strong>
              </div>
              <div className="lv-world-stat">
                <span>RAG V3</span>
                <strong>{health?.knowledge?.rag_v3 ? "ON" : "OFF"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Deep recall</span>
                <strong>{health?.knowledge?.deep_recall ? "ON" : "OFF"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Why library</span>
                <strong>{health?.knowledge?.why_library ? "ON" : "OFF"}</strong>
              </div>
              <div className="lv-world-stat">
                <span>Reranker</span>
                <strong>{health?.knowledge?.reranker_available ? "ready" : "unavailable"}</strong>
              </div>
            </div>
            <p className="lv-muted">
              Unavailable embeddings/reranker/deep-recall are reported honestly — never fabricated.
            </p>
          </article>
        </section>
      </main>
    </AppShell>
  );
}
