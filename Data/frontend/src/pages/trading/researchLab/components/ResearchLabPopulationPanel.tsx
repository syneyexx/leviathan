import { extractStageResults, fmtMetric, stageMetrics, type CandidateRecord } from "../viewModels";

export function ResearchLabPopulationPanel({
  candidates,
  populationRefs,
  loading,
}: {
  candidates: CandidateRecord[];
  populationRefs: string[];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }

  const byId = new Map(candidates.map((c) => [String(c.candidate_id), c]));
  let rows = populationRefs.length
    ? populationRefs.map((id) => byId.get(id)).filter(Boolean) as CandidateRecord[]
    : candidates;

  // Latest generation preference when no population_refs
  if (!populationRefs.length && candidates.length) {
    const maxGen = Math.max(...candidates.map((c) => Number(c.generation || 0)));
    const latest = candidates.filter((c) => Number(c.generation || 0) === maxGen);
    if (latest.length) rows = latest;
  }

  if (rows.length === 0) {
    return (
      <div className="lv-rl-empty">
        <strong>No population members yet</strong>
        Candidates appear after the learner proposes strategies for evaluation.
      </div>
    );
  }

  return (
    <article className="lv-rl-card">
      <h3>Population {populationRefs.length ? `(refs ${populationRefs.length})` : `(${rows.length})`}</h3>
      <div className="lv-rl-table-wrap" style={{ maxHeight: 520 }}>
        <table className="lv-rl-table">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Gen</th>
              <th>Family</th>
              <th>Method</th>
              <th>Status</th>
              <th>Train fitness</th>
              <th>Sharpe</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const train = stageMetrics(extractStageResults(c).TRAIN);
              return (
                <tr key={String(c.candidate_id)}>
                  <td>{String(c.candidate_id).slice(0, 14)}</td>
                  <td>{String(c.generation ?? "—")}</td>
                  <td>{String(c.family || "—")}</td>
                  <td>{String(c.proposal_method || "—")}</td>
                  <td>{String(c.status || "—")}</td>
                  <td>{fmtMetric(train.fitness)}</td>
                  <td>{fmtMetric(train.sharpe, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </article>
  );
}
