import { Donut, LineSeries, RingGauge, Spark } from "../../shared";
import { fmtMetric, fmtPctMetric, progressPct, type OverviewModel } from "../viewModels";

function CandidateCard({
  title,
  card,
  pendingLabel,
}: {
  title: string;
  card: OverviewModel["bestTrain"] | OverviewModel["qualified"];
  pendingLabel?: string;
}) {
  const pending = "pending" in card ? card.pending : !card.id;
  return (
    <article className="lv-rl-card">
      <div className="lv-rl-cand-head">
        <h3>{title}</h3>
        {card.sparkPoints.length >= 2 ? (
          <Spark points={card.sparkPoints} color="#34d399" width={72} height={22} />
        ) : null}
      </div>
      {pending ? (
        <p className="lv-rl-card-hint">{pendingLabel || "Not recorded yet"}</p>
      ) : (
        <>
          <div className="lv-rl-card-hint" style={{ color: "rgba(246,241,232,0.9)" }}>
            {card.label}
            {card.id ? ` · ${card.id.slice(0, 10)}…` : ""}
          </div>
          <div className="lv-rl-metric-row">
            <span>
              Sharpe<strong>{fmtMetric(card.metrics.sharpe, 2)}</strong>
            </span>
            <span>
              Max DD<strong>{fmtPctMetric(card.metrics.maxDrawdownPct)}</strong>
            </span>
            <span>
              Win<strong>{fmtMetric(card.metrics.winRate, 3)}</strong>
            </span>
            <span>
              Fitness<strong>{fmtMetric(card.metrics.fitness, 3)}</strong>
            </span>
          </div>
        </>
      )}
    </article>
  );
}

export function ResearchLabOverview({
  model,
  hasLearning,
  learningError,
  loading,
}: {
  model: OverviewModel;
  hasLearning: boolean;
  learningError: string | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 48 }} />
        <div className="lv-rl-skel-bar" style={{ height: 100 }} />
        <div className="lv-rl-skel-bar" style={{ height: 140 }} />
      </div>
    );
  }

  if (!hasLearning) {
    return (
      <div className="lv-rl-empty">
        <strong>No learner state available yet</strong>
        {learningError ||
          "Select a run with learning enabled, or create a new research run. Market simulation remains the evaluation environment."}
      </div>
    );
  }

  const trialPct = progressPct(model.trialsUsed, model.trialBudget);
  const genPct = progressPct(model.currentGeneration, model.generationBudget);
  const hasFitness = model.fitnessBest.length >= 2 || model.fitnessMedian.length >= 2;

  const steps = Array.from({ length: Math.max(model.generationBudget, 1) }, (_, i) => i + 1).slice(
    0,
    Math.min(model.generationBudget || 1, 16),
  );

  return (
    <div className="lv-rl-overview">
      <div className="lv-rl-card">
        <h3>Learning progress</h3>
        <div className="lv-rl-gauge-row">
          <div style={{ flex: 1, minWidth: 180 }}>
            <div className="lv-rl-trials-label">
              <span>
                Generation {model.currentGeneration} / {model.generationBudget || "—"}
              </span>
              <span>{model.stageLabel}</span>
            </div>
            <div className="lv-rl-stepper" aria-label="Generation stepper">
              {steps.map((n, i) => {
                const done = n < model.currentGeneration;
                const active = n === model.currentGeneration;
                return (
                  <div key={n} style={{ display: "contents" }}>
                    <div className={`lv-rl-step${done ? " is-done" : ""}${active ? " is-active" : ""}`}>
                      <span className="lv-rl-step-dot" />
                      <span>G{n}</span>
                    </div>
                    {i < steps.length - 1 ? <span className="lv-rl-step-bar" /> : null}
                  </div>
                );
              })}
            </div>
          </div>
          <RingGauge
            value={trialPct ?? 0}
            label="Trials used"
            display={
              model.trialBudget > 0 ? `${model.trialsUsed}/${model.trialBudget}` : String(model.trialsUsed)
            }
            color="#22c9d6"
          />
          {genPct != null ? (
            <RingGauge value={genPct} label="Gen budget" display={`${Math.round(genPct)}%`} color="#d4af37" />
          ) : null}
        </div>
      </div>

      <div className="lv-rl-grid-3">
        <CandidateCard title="Best train candidate" card={model.bestTrain} pendingLabel="No train candidate recorded yet" />
        <CandidateCard
          title="Best validation candidate"
          card={model.bestValidation}
          pendingLabel="No validation candidate recorded yet"
        />
        <CandidateCard title="Qualified candidate" card={model.qualified} pendingLabel="Pending — no qualified candidate yet" />
      </div>

      <div className="lv-rl-grid-4">
        <article className="lv-rl-card">
          <h3>Population</h3>
          <div className="lv-rl-card-value">{model.populationSize ?? "—"}</div>
        </article>
        <article className="lv-rl-card">
          <h3>Mutation rate</h3>
          <div className="lv-rl-card-value">{fmtMetric(model.mutationRate, 2)}</div>
        </article>
        <article className="lv-rl-card">
          <h3>Diversity</h3>
          <div className="lv-rl-card-value">{fmtMetric(model.diversity, 2)}</div>
          <div className="lv-rl-card-hint">
            {model.diversity == null ? "Unmeasured" : model.diversity >= 0.6 ? "High" : model.diversity >= 0.3 ? "Moderate" : "Low"}
          </div>
        </article>
        <article className="lv-rl-card">
          <h3>Current generation</h3>
          <div className="lv-rl-card-value">
            {model.currentGeneration}/{model.generationBudget || "—"}
          </div>
        </article>
      </div>

      <div className="lv-rl-grid-2">
        <article className="lv-rl-card">
          <h3>Fitness &amp; reward</h3>
          {hasFitness ? (
            <>
              <div className="lv-rl-chart-wrap">
                <LineSeries
                  width={480}
                  height={150}
                  series={[
                    ...(model.fitnessBest.length
                      ? [{ values: model.fitnessBest, color: "#34d399" }]
                      : []),
                    ...(model.fitnessMedian.length
                      ? [{ values: model.fitnessMedian, color: "#22c9d6" }]
                      : []),
                    ...(model.diversitySeries.length
                      ? [{ values: model.diversitySeries, color: "#818cf8" }]
                      : []),
                  ]}
                />
              </div>
              <div className="lv-rl-legend">
                <span>
                  <i style={{ background: "#34d399" }} /> Best fitness
                </span>
                <span>
                  <i style={{ background: "#22c9d6" }} /> Median fitness
                </span>
                <span>
                  <i style={{ background: "#818cf8" }} /> Diversity
                </span>
              </div>
            </>
          ) : (
            <div className="lv-rl-empty" style={{ padding: 16 }}>
              <strong>No fitness series yet</strong>
              Trends appear after completed generations.
            </div>
          )}
        </article>

        <article className="lv-rl-card">
          <h3>Strategy family distribution</h3>
          {model.familySlices.length === 0 ? (
            <div className="lv-rl-empty" style={{ padding: 16 }}>
              <strong>No family probabilities yet</strong>
              Appear after the first TRAIN generation.
            </div>
          ) : (
            <div className="lv-rl-donut-row">
              <Donut
                size={120}
                center={`${model.familySlices.length}`}
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
          )}
        </article>
      </div>

      <article className="lv-rl-card">
        <h3>Generation summary</h3>
        {model.generationRows.length === 0 ? (
          <div className="lv-rl-empty" style={{ padding: 16 }}>
            <strong>No completed generations yet</strong>
          </div>
        ) : (
          <div className="lv-rl-table-wrap">
            <table className="lv-rl-table">
              <thead>
                <tr>
                  <th>Gen</th>
                  <th>Best fitness</th>
                  <th>Median</th>
                  <th>Diversity</th>
                  <th>Explore</th>
                  <th>Top candidate</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {model.generationRows.map((row) => (
                  <tr key={row.generation}>
                    <td>{row.generation}</td>
                    <td>{fmtMetric(row.bestFitness)}</td>
                    <td>{fmtMetric(row.medianFitness)}</td>
                    <td>{fmtMetric(row.diversity)}</td>
                    <td>{fmtMetric(row.exploration)}</td>
                    <td>{row.topCandidateId ? `${row.topCandidateId.slice(0, 12)}…` : "—"}</td>
                    <td>{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </div>
  );
}
