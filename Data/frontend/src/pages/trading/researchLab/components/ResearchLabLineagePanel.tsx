import { extractStageResults, fmtMetric, stageMetrics, type CandidateRecord } from "../viewModels";

export function ResearchLabLineagePanel({
  candidates,
  loading,
}: {
  candidates: CandidateRecord[];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }
  if (candidates.length === 0) {
    return (
      <div className="lv-rl-empty">
        <strong>No lineage available yet</strong>
        Parent/child links appear when candidates carry parent_refs from mutation or crossover.
      </div>
    );
  }

  const sorted = [...candidates].sort(
    (a, b) => Number(a.generation || 0) - Number(b.generation || 0),
  );

  return (
    <article className="lv-rl-card">
      <h3>Candidate lineage</h3>
      <div className="lv-rl-lineage">
        {sorted.slice(0, 60).map((c) => {
          const parents = (Array.isArray(c.parent_refs) ? c.parent_refs : []) as Record<
            string,
            unknown
          >[];
          const train = stageMetrics(extractStageResults(c).TRAIN);
          return (
            <div key={String(c.candidate_id)} className="lv-rl-lineage-node">
              <div>
                <strong>v{String(c.strategy_version ?? "?")}</strong>
                {" · gen "}
                {String(c.generation)}
                {" · "}
                {String(c.proposal_method)}
                {" · "}
                {String(c.family || "—")}
                {" · "}
                {String(c.status)}
                {" · fitness="}
                {fmtMetric(train.fitness)}
              </div>
              <div className="parents">
                id={String(c.candidate_id)}
                {parents.length
                  ? ` · parents=${parents
                      .map((p) => String(p.candidate_id || p.strategy_version || JSON.stringify(p)))
                      .join(", ")}`
                  : " · no parents (seed / exploration)"}
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}
