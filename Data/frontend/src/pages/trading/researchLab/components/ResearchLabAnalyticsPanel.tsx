import { Donut, LineSeries } from "../../shared";
import { fmtMetric, type OverviewModel } from "../viewModels";
import type { LabRunRecord } from "../viewModels";

export function ResearchLabAnalyticsPanel({
  model,
  overview,
  costPack,
  lessons,
  hasLearning,
}: {
  model: OverviewModel;
  overview: Record<string, unknown> | null;
  costPack: Record<string, unknown> | null;
  lessons: LabRunRecord[];
  hasLearning: boolean;
}) {
  if (!hasLearning && !costPack && lessons.length === 0) {
    return (
      <div className="lv-rl-empty">
        <strong>No analytics available yet</strong>
        Aggregates appear from generation summaries, learner state, and lab overview truth.
      </div>
    );
  }

  const hasSeries = model.fitnessBest.length >= 2;
  const hpo = ((overview?.hpo_methods as string[]) || []).join(", ") || "—";
  const bayesian = String(
    ((overview?.hpo_bayesian_tpe as Record<string, unknown>) || {}).status ?? "—",
  );
  const hmm = String(((overview?.hmm_regime as Record<string, unknown>) || {}).status ?? "—");

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div className="lv-rl-grid-2">
        <article className="lv-rl-card">
          <h3>Fitness evolution</h3>
          {hasSeries ? (
            <div className="lv-rl-chart-wrap">
              <LineSeries
                width={480}
                height={150}
                series={[
                  { values: model.fitnessBest, color: "#34d399" },
                  ...(model.fitnessMedian.length
                    ? [{ values: model.fitnessMedian, color: "#22c9d6" }]
                    : []),
                ]}
              />
            </div>
          ) : (
            <div className="lv-rl-empty" style={{ padding: 16 }}>
              <strong>No trend data yet</strong>
            </div>
          )}
        </article>
        <article className="lv-rl-card">
          <h3>Family mix</h3>
          {model.familySlices.length ? (
            <div className="lv-rl-donut-row">
              <Donut
                size={110}
                slices={model.familySlices.map((s) => ({ value: s.value, color: s.color }))}
              />
              <ul className="lv-rl-fam-list">
                {model.familySlices.map((s) => (
                  <li key={s.label}>
                    <span className="lv-rl-fam-swatch" style={{ background: s.color }} />
                    {s.label}: {(s.value * 100).toFixed(1)}%
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="lv-rl-empty" style={{ padding: 16 }}>
              <strong>No family distribution yet</strong>
            </div>
          )}
        </article>
      </div>

      <div className="lv-rl-grid-4">
        <article className="lv-rl-card">
          <h3>Mutation</h3>
          <div className="lv-rl-card-value">{fmtMetric(model.mutationRate, 2)}</div>
        </article>
        <article className="lv-rl-card">
          <h3>Diversity</h3>
          <div className="lv-rl-card-value">{fmtMetric(model.diversity, 2)}</div>
        </article>
        <article className="lv-rl-card">
          <h3>Exploration</h3>
          <div className="lv-rl-card-value">{fmtMetric(model.explorationRate, 2)}</div>
        </article>
        <article className="lv-rl-card">
          <h3>Trials</h3>
          <div className="lv-rl-card-value">
            {model.trialsUsed}/{model.trialBudget || "—"}
          </div>
        </article>
      </div>

      <article className="lv-rl-card">
        <h3>HPO / regimes honesty</h3>
        <ul className="lv-rl-fam-list">
          <li>HPO methods: {hpo}</li>
          <li>Bayesian TPE: {bayesian}</li>
          <li>HMM regimes: {hmm}</li>
          <li>
            DSL version: {String(overview?.dsl_version ?? "—")} · Feature pipeline:{" "}
            {String(overview?.feature_pipeline_version ?? "—")}
          </li>
        </ul>
      </article>

      {costPack ? (
        <article className="lv-rl-card">
          <h3>Cost model pack</h3>
          <ul className="lv-rl-fam-list">
            {(["fee", "spread", "impact", "latency", "funding", "borrow"] as const).map((k) => {
              const row = costPack[k] as Record<string, unknown> | undefined;
              return (
                <li key={k}>
                  {k}: value={String(row?.value ?? "null")} · status={String(row?.status ?? "—")}
                </li>
              );
            })}
          </ul>
        </article>
      ) : null}

      <article className="lv-rl-card">
        <h3>Lessons (AGENT_PROPOSED ≠ proof)</h3>
        {lessons.length === 0 ? (
          <p className="lv-rl-card-hint">No lessons yet.</p>
        ) : (
          <ul className="lv-rl-fam-list">
            {lessons.map((l) => (
              <li key={String(l.lesson_id)}>
                [{String(l.trust)}] {String(l.claim)} · confidence={fmtMetric(l.confidence)}
              </li>
            ))}
          </ul>
        )}
      </article>
    </div>
  );
}
