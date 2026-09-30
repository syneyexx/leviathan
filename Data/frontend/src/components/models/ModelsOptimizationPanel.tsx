import type { ModelOptimizationCandidate } from "../../types/api";
import type { ModelsWorkspace, OptimizationGoals } from "../../hooks/useModelsWorkspace";
import { Button, Panel } from "../ui";

type Props = {
  ws: ModelsWorkspace;
  onManageProfiles: () => void;
};

const GOALS: Array<{ id: keyof OptimizationGoals; label: string }> = [
  { id: "maxTokensPerSec", label: "Maximale tokens/sec" },
  { id: "keepDisplayResponsive", label: "Display GPU responsief houden" },
  { id: "maximizeModelSize", label: "Model zo groot mogelijk laden" },
  { id: "stableNoOom", label: "Stabiele configuratie (geen OOM)" },
];

function BoltIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z" />
    </svg>
  );
}

function statusGlyph(candidate: ModelOptimizationCandidate, bestIndex: number | null): string {
  if (candidate.index === bestIndex && candidate.status === "BEST") return "✓ (Beste)";
  if (candidate.status === "PASS" || candidate.status === "BEST") return "✓";
  if (candidate.status === "OOM") return "✗ OOM";
  if (candidate.status === "LOAD_FAILED" || candidate.status === "HEADROOM_VIOLATION" || candidate.status === "UNSTABLE") {
    return "✗";
  }
  if (candidate.status === "CANCELLED") return "—";
  return "…";
}

export function ModelsOptimizationPanel({ ws, onManageProfiles }: Props) {
  const run = ws.optimization;
  const candidates = run?.candidates ?? [];
  const disabled = !ws.selectedId;

  return (
    <Panel title="Optimalisatie" icon={<BoltIcon />} className="lv-v2-models-optimization">
      <p className="lv-v2-muted lv-v2-models-optimization__desc">
        Laat Leviathan automatisch de beste configuratie vinden voor dit model op jouw hardware.
      </p>

      <div className="lv-v2-models-optimization__grid">
        <div className="lv-v2-models-optimization__goals">
          <h4>Optimalisatie doelen</h4>
          <ul>
            {GOALS.map((goal) => (
              <li key={goal.id}>
                <label className="lv-v2-models-checkbox">
                  <input
                    type="checkbox"
                    checked={ws.optimizationGoals[goal.id]}
                    onChange={(e) => ws.setOptimizationGoal(goal.id, e.target.checked)}
                  />
                  {goal.label}
                </label>
              </li>
            ))}
          </ul>
          <div className="lv-v2-models-optimization__actions">
            <Button
              variant="primary"
              size="sm"
              disabled={disabled || ws.optimizing}
              loading={ws.optimizing}
              onClick={() => void ws.startOptimize()}
            >
              Automatisch optimaliseren
            </Button>
            <Button variant="secondary" size="sm" onClick={onManageProfiles}>
              Profielen beheren
            </Button>
          </div>
        </div>

        <div className="lv-v2-models-optimization__results">
          <h4>Geteste profielen</h4>
          {candidates.length === 0 ? (
            <p className="lv-v2-muted">
              {ws.optimizing ? "Optimalisatie loopt…" : "Nog geen profielen getest voor dit model."}
            </p>
          ) : (
            <table className="lv-v2-models-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Context</th>
                  <th>GPU Offload</th>
                  <th>GPU0</th>
                  <th>GPU1</th>
                  <th>Tok/s (gen)</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((candidate) => {
                  const isBest = run?.bestIndex === candidate.index;
                  return (
                    <tr
                      key={candidate.index}
                      className={isBest ? "is-best" : undefined}
                      onClick={() => ws.applyCandidate(candidate)}
                      role="button"
                      tabIndex={0}
                    >
                      <td>{candidate.index}</td>
                      <td>{candidate.context ?? "—"}</td>
                      <td>{candidate.gpuOffload != null ? `${Math.round(candidate.gpuOffload * 100)}%` : "—"}</td>
                      <td>{candidate.gpu0 != null ? `${(candidate.gpu0).toFixed(1)} GB` : "—"}</td>
                      <td>{candidate.gpu1 != null ? `${(candidate.gpu1).toFixed(1)} GB` : "—"}</td>
                      <td>{candidate.generationTps != null ? candidate.generationTps.toFixed(1) : "—"}</td>
                      <td>{statusGlyph(candidate, run?.bestIndex ?? null)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {ws.optimizing ? (
            <Button variant="ghost" size="sm" onClick={() => void ws.cancelOptimize()}>
              Annuleren
            </Button>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
