import { useState } from "react";
import { marketSimLabApi } from "../../../../api/domains/marketSimLab";
import { extractStageResults, fmtMetric, stageMetrics, type CandidateRecord } from "../viewModels";

export function ResearchLabPopulationPanel({
  labId,
  candidates,
  populationRefs,
  loading,
}: {
  labId?: string | null;
  candidates: CandidateRecord[];
  populationRefs: string[];
  loading?: boolean;
}) {
  const [explainId, setExplainId] = useState<string | null>(null);
  const [explainBody, setExplainBody] = useState<Record<string, unknown> | null>(null);
  const [explainError, setExplainError] = useState<string | null>(null);
  const [explainBusy, setExplainBusy] = useState(false);

  async function openExplain(candidateId: string) {
    if (!labId) {
      setExplainError("No lab run selected");
      setExplainId(candidateId);
      return;
    }
    setExplainId(candidateId);
    setExplainBusy(true);
    setExplainError(null);
    setExplainBody(null);
    try {
      const body = await marketSimLabApi.marketSimLabExplainCandidate(labId, candidateId);
      setExplainBody(body);
    } catch (err) {
      setExplainError(err instanceof Error ? err.message : "Explain failed");
    } finally {
      setExplainBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }

  const byId = new Map(candidates.map((c) => [String(c.candidate_id), c]));
  let rows = populationRefs.length
    ? (populationRefs.map((id) => byId.get(id)).filter(Boolean) as CandidateRecord[])
    : candidates;

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
              <th>Explain</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const train = stageMetrics(extractStageResults(c).TRAIN);
              const id = String(c.candidate_id);
              return (
                <tr key={id}>
                  <td>{id.slice(0, 14)}</td>
                  <td>{String(c.generation ?? "—")}</td>
                  <td>{String(c.family || "—")}</td>
                  <td>{String(c.proposal_method || "—")}</td>
                  <td>{String(c.status || "—")}</td>
                  <td>{fmtMetric(train.fitness)}</td>
                  <td>{fmtMetric(train.sharpe, 2)}</td>
                  <td>
                    <button type="button" className="lv-rl-btn ghost" onClick={() => void openExplain(id)}>
                      Explain
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {explainId ? (
        <div className="lv-tc-explain" role="dialog" aria-label="Candidate explainability">
          <div className="lv-tc-explain__panel">
            <header>
              <h3>Explain · {explainId.slice(0, 18)}</h3>
              <button type="button" className="lv-tc-btn" onClick={() => setExplainId(null)}>
                Close
              </button>
            </header>
            <p className="is-muted" style={{ color: "#94a3b8", fontSize: "0.78rem" }}>
              Backend explainability evidence — not a promotion decision.
            </p>
            {explainBusy ? <p>Loading…</p> : null}
            {explainError ? <p style={{ color: "#f87171" }}>{explainError}</p> : null}
            {explainBody ? <pre>{JSON.stringify(explainBody, null, 2)}</pre> : null}
          </div>
        </div>
      ) : null}
    </article>
  );
}
