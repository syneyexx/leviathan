import { fmtMetric, type GenerationRecord } from "../viewModels";

export function ResearchLabGenerationsPanel({
  generations,
  loading,
}: {
  generations: GenerationRecord[];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }
  if (generations.length === 0) {
    return (
      <div className="lv-rl-empty">
        <strong>No completed generations yet</strong>
        Generation summaries appear as the learner finishes TRAIN cycles on market simulation.
      </div>
    );
  }
  const rows = [...generations].sort(
    (a, b) => Number(a.generation || 0) - Number(b.generation || 0),
  );
  return (
    <article className="lv-rl-card">
      <h3>Generations</h3>
      <div className="lv-rl-table-wrap" style={{ maxHeight: 520 }}>
        <table className="lv-rl-table">
          <thead>
            <tr>
              <th>Gen</th>
              <th>Best train fitness</th>
              <th>Median fitness</th>
              <th>Diversity</th>
              <th>Exploration</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={String(g.generation)}>
                <td>{String(g.generation)}</td>
                <td>{fmtMetric(g.best_train_fitness)}</td>
                <td>{fmtMetric(g.median_train_fitness)}</td>
                <td>{fmtMetric(g.diversity_score)}</td>
                <td>{fmtMetric(g.exploration_rate)}</td>
                <td>{String(g.status || "recorded")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}
