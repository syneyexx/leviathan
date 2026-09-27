import { Donut, LineSeries, Spark } from "../../shared";
import {
  fmtMetric,
  fmtPctMetric,
  progressPct,
  type CandidateRecord,
  type OverviewModel,
} from "../viewModels";
import { LineageMiniGraph } from "./LineageMiniGraph";

function CandidateCard({
  title,
  icon,
  tone,
  card,
  pendingLabel,
  sparkColor,
}: {
  title: string;
  icon: string;
  tone: "train" | "val" | "qual";
  card: OverviewModel["bestTrain"] | OverviewModel["qualified"];
  pendingLabel?: string;
  sparkColor: string;
}) {
  const pending = "pending" in card ? card.pending : !card.id;
  const shortId = card.id
    ? card.generation != null
      ? `v${card.generation}-${String(card.id).slice(-2)}`
      : String(card.id).slice(0, 10)
    : "Pending";

  return (
    <article className={`lv-rl-cand is-${tone}`}>
      <div className="lv-rl-cand-top">
        <div className="lv-rl-cand-title">
          <span className="lv-rl-cand-ico" aria-hidden="true">
            {icon}
          </span>
          {title}
        </div>
        {card.sparkPoints.length >= 2 ? (
          <Spark points={card.sparkPoints} color={sparkColor} width={68} height={20} />
        ) : null}
      </div>
      <div className="lv-rl-cand-id">{pending ? "Pending" : shortId}</div>
      <div className="lv-rl-cand-sub">
        {pending
          ? pendingLabel || "Not recorded yet"
          : `${card.label}${card.generation != null ? ` · Gen ${card.generation}` : ""}`}
      </div>
      {!pending ? (
        <div className="lv-rl-metric-row">
          <span>
            Sharpe
            <strong>{fmtMetric(card.metrics.sharpe, 2)}</strong>
          </span>
          <span>
            Max DD
            <strong className={card.metrics.maxDrawdownPct != null && card.metrics.maxDrawdownPct < 0 ? "is-bad" : undefined}>
              {fmtPctMetric(card.metrics.maxDrawdownPct)}
            </strong>
          </span>
          <span>
            Win
            <strong>{fmtMetric(card.metrics.winRate, 3)}</strong>
          </span>
        </div>
      ) : (
        <div className="lv-rl-metric-row">
          <span>
            Status<strong>Awaiting holdout</strong>
          </span>
        </div>
      )}
    </article>
  );
}

export function ResearchLabOverview({
  model,
  candidates,
  hasLearning,
  learningError,
  loading,
}: {
  model: OverviewModel;
  candidates: CandidateRecord[];
  hasLearning: boolean;
  learningError: string | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 56 }} />
        <div className="lv-rl-skel-bar" style={{ height: 110 }} />
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

  const trialPct = progressPct(model.trialsUsed, model.trialBudget) ?? 0;
  const genBudget = Math.max(model.generationBudget || 1, 1);
  const steps = Array.from({ length: Math.min(genBudget, 16) }, (_, i) => i + 1);
  const hasFitness = model.fitnessBest.length >= 2 || model.fitnessMedian.length >= 2;
  const totalCandidates = candidates.length;

  return (
    <div className="lv-rl-overview">
      <section className="lv-rl-card">
        <p className="lv-rl-sec-label">Learning progress</p>
        <div className="lv-rl-progress-panel">
          <div>
            <div className="lv-rl-stepper" aria-label="Generation stepper">
              {steps.map((n, i) => {
                const done = n < model.currentGeneration;
                const active = n === model.currentGeneration || (model.currentGeneration === 0 && n === 1);
                return (
                  <div key={n} className={`lv-rl-step${done ? " is-done" : ""}${active ? " is-active" : ""}`}>
                    {i > 0 ? <span className="lv-rl-step-conn" /> : null}
                    <span className="lv-rl-step-node">{n}</span>
                  </div>
                );
              })}
            </div>
            <div className="lv-rl-gen-caption">
              Generation {model.currentGeneration} of {model.generationBudget || "—"}
              <span>{model.stageLabel}</span>
            </div>
          </div>
          <div className="lv-rl-trials-box">
            <div className="lbl">
              <span>Trials used</span>
              <span>{Math.round(trialPct)}%</span>
            </div>
            <div className="val">
              {model.trialsUsed} / {model.trialBudget || "—"}
            </div>
            <div className="bar">
              <i style={{ width: `${trialPct}%` }} />
            </div>
          </div>
        </div>
      </section>

      <section>
        <p className="lv-rl-sec-label">Key candidates</p>
        <div className="lv-rl-grid-3">
          <CandidateCard
            title="Best train candidate"
            icon="◆"
            tone="train"
            card={model.bestTrain}
            pendingLabel="No train candidate recorded yet"
            sparkColor="#34d399"
          />
          <CandidateCard
            title="Best validation candidate"
            icon="◇"
            tone="val"
            card={model.bestValidation}
            pendingLabel="No validation candidate recorded yet"
            sparkColor="#3b82f6"
          />
          <CandidateCard
            title="Qualified candidate"
            icon="◎"
            tone="qual"
            card={model.qualified}
            pendingLabel="Requires validation on holdout"
            sparkColor="#8b5cf6"
          />
        </div>
      </section>

      <div className="lv-rl-grid-5">
        <article className="lv-rl-tile">
          <div className="lv-rl-tile-ico" aria-hidden="true">
            ⊞
          </div>
          <div>
            <div className="k">Population</div>
            <div className="v">{model.populationSize ?? "—"}</div>
            <div className="h">candidates</div>
          </div>
        </article>
        <article className="lv-rl-tile">
          <div className="lv-rl-tile-ico" aria-hidden="true">
            ✶
          </div>
          <div>
            <div className="k">Mutation rate</div>
            <div className="v">{fmtMetric(model.mutationRate, 2)}</div>
            <div className="h">per generation</div>
          </div>
        </article>
        <article className="lv-rl-tile">
          <div className="lv-rl-tile-ico" aria-hidden="true">
            ◎
          </div>
          <div>
            <div className="k">Diversity</div>
            <div className="v">{fmtMetric(model.diversity, 2)}</div>
            <div className="h">
              {model.diversity == null ? "unmeasured" : model.diversity >= 0.6 ? "(high)" : model.diversity >= 0.3 ? "(moderate)" : "(low)"}
            </div>
          </div>
        </article>
        <article className="lv-rl-tile">
          <div className="lv-rl-tile-ico" aria-hidden="true">
            ▣
          </div>
          <div>
            <div className="k">Trials used</div>
            <div className="v">
              {model.trialsUsed}/{model.trialBudget || "—"}
            </div>
            <div className="h">{Math.round(trialPct)}% of budget</div>
          </div>
        </article>
        <article className="lv-rl-tile">
          <div className="lv-rl-tile-ico" aria-hidden="true">
            ▦
          </div>
          <div>
            <div className="k">Current generation</div>
            <div className="v">
              {model.currentGeneration}/{model.generationBudget || "—"}
            </div>
            <div className="h">
              {model.generationBudget
                ? `${Math.round(progressPct(model.currentGeneration, model.generationBudget) ?? 0)}% complete`
                : "—"}
            </div>
          </div>
        </article>
      </div>

      <div className="lv-rl-charts-3">
        <article className="lv-rl-card">
          <p className="lv-rl-sec-label">Fitness &amp; reward</p>
          {hasFitness ? (
            <>
              <div className="lv-rl-chart-wrap">
                <LineSeries
                  width={420}
                  height={140}
                  series={[
                    ...(model.fitnessBest.length ? [{ values: model.fitnessBest, color: "#f59e0b" }] : []),
                    ...(model.fitnessMedian.length ? [{ values: model.fitnessMedian, color: "#22c9d6" }] : []),
                    ...(model.diversitySeries.length ? [{ values: model.diversitySeries, color: "#8b5cf6" }] : []),
                  ]}
                />
              </div>
              <div className="lv-rl-legend">
                <span>
                  <i style={{ background: "#f59e0b" }} /> Best fitness
                </span>
                <span>
                  <i style={{ background: "#22c9d6" }} /> Average fitness
                </span>
                <span>
                  <i style={{ background: "#8b5cf6" }} /> Diversity
                </span>
              </div>
            </>
          ) : (
            <div className="lv-rl-empty" style={{ padding: 14 }}>
              <strong>No fitness series yet</strong>
              Trends appear after completed generations.
            </div>
          )}
        </article>

        <article className="lv-rl-card">
          <p className="lv-rl-sec-label">Strategy family distribution</p>
          {model.familySlices.length === 0 ? (
            <div className="lv-rl-empty" style={{ padding: 14 }}>
              <strong>No family probabilities yet</strong>
              Appear after the first TRAIN generation.
            </div>
          ) : (
            <div className="lv-rl-donut-row">
              <Donut
                size={118}
                center={totalCandidates > 0 ? String(totalCandidates) : String(model.familySlices.length)}
                slices={model.familySlices.map((s) => ({ value: s.value, color: s.color }))}
              />
              <ul className="lv-rl-fam-list">
                {model.familySlices.map((s) => (
                  <li key={s.label}>
                    <span className="lv-rl-fam-swatch" style={{ background: s.color }} />
                    {s.label}: {(s.value * 100).toFixed(0)}%
                  </li>
                ))}
              </ul>
            </div>
          )}
        </article>

        <article className="lv-rl-card">
          <p className="lv-rl-sec-label">Candidate lineage</p>
          <LineageMiniGraph
            candidates={candidates}
            bestId={model.bestTrain.id}
          />
        </article>
      </div>

      <article className="lv-rl-card">
        <p className="lv-rl-sec-label">Generation summary</p>
        {model.generationRows.length === 0 ? (
          <div className="lv-rl-empty" style={{ padding: 14 }}>
            <strong>No completed generations yet</strong>
          </div>
        ) : (
          <div className="lv-rl-table-wrap">
            <table className="lv-rl-table">
              <thead>
                <tr>
                  <th>Gen</th>
                  <th>Best fitness</th>
                  <th>Avg fitness</th>
                  <th>Diversity</th>
                  <th>Explore</th>
                  <th>Top candidate</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {model.generationRows.map((row) => (
                  <tr
                    key={row.generation}
                    className={row.generation === model.currentGeneration ? "is-current" : undefined}
                  >
                    <td>{row.generation}</td>
                    <td className={row.bestFitness != null && row.bestFitness >= 0 ? "is-good" : undefined}>
                      {fmtMetric(row.bestFitness)}
                    </td>
                    <td>{fmtMetric(row.medianFitness)}</td>
                    <td>{fmtMetric(row.diversity)}</td>
                    <td>{fmtMetric(row.exploration)}</td>
                    <td>
                      {row.topCandidateId
                        ? `v${row.generation}-${row.topCandidateId.slice(-2)}`
                        : "—"}
                    </td>
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
