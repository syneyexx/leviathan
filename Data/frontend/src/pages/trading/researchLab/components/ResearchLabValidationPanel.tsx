import {
  extractStageResults,
  fmtMetric,
  stageMetrics,
  type CandidateRecord,
  type LearningRecord,
} from "../viewModels";

export function ResearchLabValidationPanel({
  candidates,
  learning,
  loading,
}: {
  candidates: CandidateRecord[];
  learning: LearningRecord | null;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }

  const withVal = candidates.filter((c) => {
    const s = extractStageResults(c);
    return s.VAL || s.ROBUSTNESS || s.SEALED;
  });

  if (withVal.length === 0) {
    return (
      <div className="lv-rl-empty">
        <strong>No validation results recorded yet</strong>
        Validation / robustness / sealed outcomes appear after those curriculum phases run on market simulation.
        {learning?.best_validation_candidate
          ? ` Best validation candidate id: ${String(learning.best_validation_candidate)}`
          : ""}
        {learning?.qualified_candidate
          ? ` · Qualified: ${String(learning.qualified_candidate)}`
          : " · No qualified candidate yet."}
      </div>
    );
  }

  return (
    <article className="lv-rl-card">
      <h3>Validation &amp; holdout</h3>
      <p className="lv-rl-card-hint" style={{ marginBottom: 10 }}>
        Qualified candidate: {learning?.qualified_candidate ? String(learning.qualified_candidate) : "none"} ·
        Best validation:{" "}
        {learning?.best_validation_candidate ? String(learning.best_validation_candidate) : "none"}
      </p>
      <div className="lv-rl-table-wrap" style={{ maxHeight: 520 }}>
        <table className="lv-rl-table">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Family</th>
              <th>VAL</th>
              <th>Robustness</th>
              <th>Sealed</th>
              <th>VAL fitness</th>
            </tr>
          </thead>
          <tbody>
            {withVal.map((c) => {
              const stages = extractStageResults(c);
              const val = stageMetrics(stages.VAL);
              const rob = stageMetrics(stages.ROBUSTNESS);
              const sealed = stageMetrics(stages.SEALED);
              const label = (m: ReturnType<typeof stageMetrics>, raw?: Record<string, unknown>) => {
                if (!raw) return "NOT RUN";
                if (m.accepted === true) return "PASSED";
                if (m.accepted === false) return "FAILED";
                return "RECORDED";
              };
              return (
                <tr key={String(c.candidate_id)}>
                  <td>{String(c.candidate_id).slice(0, 12)}</td>
                  <td>{String(c.family || "—")}</td>
                  <td>{label(val, stages.VAL)}</td>
                  <td>{label(rob, stages.ROBUSTNESS)}</td>
                  <td>{label(sealed, stages.SEALED)}</td>
                  <td>{fmtMetric(val.fitness)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </article>
  );
}
