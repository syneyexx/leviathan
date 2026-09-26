import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tradingHeroes } from "../../assets/tradingAssets";
import { ApiError, api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { Panel, TradingHero } from "./shared";

type LabOverview = Record<string, unknown>;

function stageLabel(stage: string | undefined): string {
  const s = String(stage || "NOT_RUN").toUpperCase();
  const map: Record<string, string> = {
    TRAIN: "TRAIN LEADER",
    VALIDATING: "VALIDATION RUNNING",
    ROBUSTNESS: "ROBUSTNESS RUNNING",
    SEALED_EVALUATION: "SEALED RUNNING",
    QUALIFIED_STRATEGY_FOUND: "QUALIFIED",
    NO_STRATEGY_QUALIFIED: "NO STRATEGY QUALIFIED",
    PAUSED: "PAUSED",
    CANCELLED: "CANCELLED",
    FAILED: "FAILED",
    CREATED: "NOT RUN",
    QUEUED: "QUEUED",
    RUNNING: "RUNNING",
  };
  return map[s] || s;
}

function fmtNum(v: unknown): string {
  if (v == null) return "UNMEASURED";
  const n = Number(v);
  if (Number.isNaN(n) || !Number.isFinite(n)) return "INVALID";
  return n.toFixed(4);
}

export function ResearchLabPage() {
  const [overview, setOverview] = useState<LabOverview | null>(null);
  const [trials, setTrials] = useState<Record<string, unknown>[]>([]);
  const [trialCount, setTrialCount] = useState(0);
  const [costPack, setCostPack] = useState<Record<string, unknown> | null>(null);
  const [feedHealth, setFeedHealth] = useState<Record<string, unknown> | null>(null);
  const [labs, setLabs] = useState<Record<string, unknown>[]>([]);
  const [selectedLabId, setSelectedLabId] = useState<string | null>(null);
  const [learning, setLearning] = useState<Record<string, unknown> | null>(null);
  const [candidates, setCandidates] = useState<Record<string, unknown>[]>([]);
  const [generations, setGenerations] = useState<Record<string, unknown>[]>([]);
  const [familyProbs, setFamilyProbs] = useState<Record<string, number>>({});
  const [lessons, setLessons] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshLearning = useCallback(async (labId: string) => {
    try {
      const [learn, gens, cands, less] = await Promise.all([
        api.marketSimLabLearning(labId),
        api.marketSimLabGenerations(labId),
        api.marketSimLabCandidates(labId),
        api.marketSimLabLessons(labId),
      ]);
      setLearning(learn.learning || null);
      setGenerations(gens.generation_summaries || []);
      setFamilyProbs(gens.family_probabilities || {});
      setCandidates(cands.candidates || []);
      setLessons(less.lessons || []);
    } catch {
      setLearning(null);
      setGenerations([]);
      setFamilyProbs({});
      setCandidates([]);
      setLessons([]);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [ov, tr, cost, labList] = await Promise.all([
        api.marketSimLabOverview(),
        api.marketSimLabTrials({ limit: 40 }),
        api.marketSimLabCostPack({ feeBps: 5, slippageBps: 2, seed: 7 }),
        api.marketSimLabListRuns(20),
      ]);
      setOverview(ov);
      setTrials(tr.trials || []);
      setTrialCount(Number(tr.count || 0));
      setCostPack(cost.cost_pack);
      setLabs(labList.labs || []);
      const firstId = selectedLabId || String((labList.labs || [])[0]?.lab_id || "");
      if (firstId) {
        setSelectedLabId(firstId);
        await refreshLearning(firstId);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, [refreshLearning, selectedLabId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const probeFeed = async () => {
    setBusy(true);
    try {
      const res = await api.marketSimLabFeedHealth({
        feedId: "paper-probe",
        lastTickTs: new Date(Date.now() - 5000).toISOString(),
        asOf: new Date().toISOString(),
        maxStalenessSeconds: 120,
        provenance: "ui_probe",
      });
      setFeedHealth(res.feed_health);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const runControl = async (action: "start" | "pause" | "resume" | "cancel") => {
    if (!selectedLabId) return;
    setBusy(true);
    try {
      if (action === "start") await api.marketSimLabStartRun(selectedLabId);
      if (action === "pause") await api.marketSimLabPauseRun(selectedLabId);
      if (action === "resume") await api.marketSimLabResumeRun(selectedLabId);
      if (action === "cancel") await api.marketSimLabCancelRun(selectedLabId);
      await refresh();
      await refreshLearning(selectedLabId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const live = (overview?.live_trading as Record<string, unknown> | undefined) || {};
  const truth = (overview?.truth as Record<string, unknown> | undefined) || {};
  const stages = (overview?.curriculum_stages as string[]) || [];
  const roles = (overview?.lab_roles as string[]) || [];
  const outcomes = (overview?.valid_lab_outcomes as string[]) || [];
  const learnerState = (learning?.learner_state as Record<string, unknown> | undefined) || {};
  const objective = (learning?.objective_spec as Record<string, unknown> | undefined) || {};

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <TradingHero title="Research Lab" image={tradingHeroes.strategieen} />
      <div className="lv-tp-wrap">
        {error ? <p className="lv-tp-banner">{error}</p> : null}

        <Panel title="Lab truth">
          <ul className="lv-tp-list">
            <li>
              LIVE_TRADING_AVAILABLE ={" "}
              <strong>{String(live.LIVE_TRADING_AVAILABLE ?? live.live_trading ?? "BLOCKED")}</strong>
            </li>
            <li>A5 = {String(truth.a5 ?? "IMPOSSIBLE")}</li>
            <li>NO_STRATEGY_QUALIFIED is valid PASS: {String(truth.no_strategy_qualified_is_valid_pass ?? true)}</li>
            <li>Paper ≠ live profitability: {String(truth.paper_does_not_prove_live_profitability ?? true)}</li>
            <li>No mock KPIs: {String(truth.no_mock_kpis ?? true)}</li>
            <li>DSL version: {String(overview?.dsl_version ?? "—")}</li>
            <li>Feature pipeline: {String(overview?.feature_pipeline_version ?? "—")}</li>
            <li>Trial ledger count: {String(overview?.trial_ledger_count ?? trialCount)}</li>
          </ul>
          <p>
            <Link to="/trading/marktdata">Market data</Link>
            {" · "}
            <Link to="/trading/strategieen">Strategies</Link>
            {" · "}
            <Link to="/trading/simulatie">Simulation</Link>
            {" · "}
            <Link to="/trading/paper">Paper</Link>
            {" · "}
            <Link to="/trading/broker">Broker (blocked)</Link>
          </p>
        </Panel>

        <Panel title="Learning Run">
          <div className="lv-tp-actions" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
            <select
              value={selectedLabId || ""}
              onChange={(e) => {
                const id = e.target.value || null;
                setSelectedLabId(id);
                if (id) void refreshLearning(id);
              }}
            >
              <option value="">Select lab…</option>
              {labs.map((l) => (
                <option key={String(l.lab_id)} value={String(l.lab_id)}>
                  {String(l.name || l.lab_id)} · {String(l.status)}
                </option>
              ))}
            </select>
            <button type="button" className="lv-btn" disabled={busy || !selectedLabId} onClick={() => void runControl("start")}>
              Start
            </button>
            <button type="button" className="lv-btn" disabled={busy || !selectedLabId} onClick={() => void runControl("pause")}>
              Pause
            </button>
            <button type="button" className="lv-btn" disabled={busy || !selectedLabId} onClick={() => void runControl("resume")}>
              Resume
            </button>
            <button type="button" className="lv-btn" disabled={busy || !selectedLabId} onClick={() => void runControl("cancel")}>
              Cancel
            </button>
          </div>
          {learning ? (
            <ul className="lv-tp-list">
              <li>status: {String(learning.status)}</li>
              <li>stage: {stageLabel(String(learning.stage || ""))}</li>
              <li>
                generation: {String(learning.current_generation)} / {String(learning.generation_budget)}
              </li>
              <li>
                trials: {String(learning.trials_used)} / {String(learning.trial_budget)}
              </li>
              <li>population: {String(learning.population_size)}</li>
              <li>best train: {String(learning.best_train_candidate || "NOT RUN")}</li>
              <li>best validation: {String(learning.best_validation_candidate || "NOT RUN")}</li>
              <li>qualified: {String(learning.qualified_candidate || "NOT RUN")}</li>
              <li>objective hash: {String(learning.objective_hash || "").slice(0, 12) || "—"}</li>
              <li>
                objective: min_trades={String(objective.min_trades ?? "—")} · max_dd=
                {String(objective.max_drawdown_pct ?? "—")}%
              </li>
              <li>job: {String(learning.job_id || "inline / none")}</li>
              <li>split: {String(learning.stage || "—")}</li>
            </ul>
          ) : (
            <p className="lv-tp-muted">
              No learning run bound to the selected lab. Create a lab with enableLearning to attach adaptive DSL search.
            </p>
          )}
        </Panel>

        <Panel title="Learner State">
          {Object.keys(familyProbs).length === 0 ? (
            <p className="lv-tp-muted">Family probabilities appear after the first TRAIN generation.</p>
          ) : (
            <ul className="lv-tp-list">
              {Object.entries(familyProbs).map(([fam, p]) => (
                <li key={fam}>
                  {fam}: {(Number(p) * 100).toFixed(1)}%
                </li>
              ))}
              <li>exploration_rate: {fmtNum(learnerState.exploration_rate)}</li>
              <li>mutation numeric: {fmtNum((learnerState.mutation_rates as Record<string, unknown> | undefined)?.numeric)}</li>
              <li>diversity: {fmtNum(learnerState.diversity_score)}</li>
              <li>generations without improvement: {String(learnerState.generations_without_improvement ?? 0)}</li>
            </ul>
          )}
        </Panel>

        <Panel title="Strategy Evolution (lineage)">
          {candidates.length === 0 ? (
            <p className="lv-tp-muted">No candidates yet.</p>
          ) : (
            <ul className="lv-tp-list">
              {candidates.slice(0, 40).map((c) => {
                const stagesMap = (c.metadata as Record<string, unknown> | undefined)?.stage_results as
                  | Record<string, Record<string, unknown>>
                  | undefined;
                const train = stagesMap?.TRAIN;
                const val = stagesMap?.VAL;
                const sealed = stagesMap?.SEALED;
                const parents = (c.parent_refs as Record<string, unknown>[] | undefined) || [];
                return (
                  <li key={String(c.candidate_id)}>
                    v{String(c.strategy_version)} · gen {String(c.generation)} · {String(c.proposal_method)} ·{" "}
                    {String(c.family)} · status={String(c.status)}
                    {parents.length ? ` · parents=${parents.length}` : ""}
                    {" · return="}
                    {fmtNum((train?.metrics as Record<string, unknown> | undefined)?.total_return_pct)}
                    {" · dd="}
                    {fmtNum((train?.metrics as Record<string, unknown> | undefined)?.max_drawdown_pct)}
                    {" · fitness="}
                    {fmtNum(train?.fitness_score)}
                    {" · val="}
                    {val ? (val.accepted ? "VALIDATION PASSED" : "VALIDATION FAILED") : "NOT RUN"}
                    {" · sealed="}
                    {sealed ? (sealed.accepted ? "SEALED PASSED" : "SEALED FAILED") : "NOT RUN"}
                    {train?.failure_categories
                      ? ` · fail=${JSON.stringify(train.failure_categories)}`
                      : ""}
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel title="Generation summaries">
          {generations.length === 0 ? (
            <p className="lv-tp-muted">No completed generations.</p>
          ) : (
            <ul className="lv-tp-list">
              {generations.map((g) => (
                <li key={String(g.generation)}>
                  gen {String(g.generation)} · best={fmtNum(g.best_train_fitness)} · median=
                  {fmtNum(g.median_train_fitness)} · diversity={fmtNum(g.diversity_score)} · explore=
                  {fmtNum(g.exploration_rate)}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Lessons (AGENT_PROPOSED ≠ proof)">
          {lessons.length === 0 ? (
            <p className="lv-tp-muted">No lessons yet.</p>
          ) : (
            <ul className="lv-tp-list">
              {lessons.map((l) => (
                <li key={String(l.lesson_id)}>
                  [{String(l.trust)}] {String(l.claim)} · confidence={fmtNum(l.confidence)}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Curriculum stages">
          <ol className="lv-tp-list">
            {stages.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
          <p className="lv-tp-muted">Logged and reproducible — sealed is a late stage, not a tuning surface.</p>
        </Panel>

        <Panel title="Lab roles">
          <ul className="lv-tp-list">
            {roles.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p className="lv-tp-muted">Valid outcomes: {outcomes.join(" | ") || "—"}</p>
        </Panel>

        <Panel title="Cost model pack (MEASURED / ASSUMED / UNMEASURED)">
          {costPack ? (
            <ul className="lv-tp-list">
              {(["fee", "spread", "impact", "latency", "funding", "borrow"] as const).map((k) => {
                const row = costPack[k] as Record<string, unknown> | undefined;
                return (
                  <li key={k}>
                    {k}: value={String(row?.value ?? "null")} · status={String(row?.status ?? "—")} ·{" "}
                    {String(row?.provenance ?? "")}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="lv-tp-muted">Loading cost pack…</p>
          )}
        </Panel>

        <Panel title="Feed health probe">
          <button type="button" className="lv-btn" disabled={busy} onClick={() => void probeFeed()}>
            Probe healthy feed
          </button>
          {feedHealth ? (
            <ul className="lv-tp-list">
              <li>status: {String(feedHealth.status)}</li>
              <li>staleness_seconds: {String(feedHealth.staleness_seconds)}</li>
              <li>provenance: {String(feedHealth.provenance)}</li>
            </ul>
          ) : (
            <p className="lv-tp-muted">No probe yet — stale/gap/UNMEASURED feeds block paper orders.</p>
          )}
        </Panel>

        <Panel title={`Trial Ledger (${trialCount})`}>
          {trials.length === 0 ? (
            <p className="lv-tp-muted">No trials recorded yet. Losing trials must remain in the ledger.</p>
          ) : (
            <ul className="lv-tp-list">
              {trials.slice(0, 20).map((t) => (
                <li key={String(t.trial_id || t.trialId)}>
                  {String(t.trial_id || t.trialId)} · {String(t.strategy_id || t.strategyId || "?")} ·{" "}
                  {String(t.status)} · hyp={String(t.hypothesis || "").slice(0, 80)}
                </li>
              ))}
            </ul>
          )}
          <button type="button" className="lv-btn" onClick={() => void refresh()}>
            Refresh
          </button>
        </Panel>

        <Panel title="HPO / regimes honesty">
          <ul className="lv-tp-list">
            <li>HPO methods: {((overview?.hpo_methods as string[]) || []).join(", ") || "—"}</li>
            <li>
              Bayesian TPE:{" "}
              {String(((overview?.hpo_bayesian_tpe as Record<string, unknown>) || {}).status ?? "—")}
            </li>
            <li>
              HMM regimes: {String(((overview?.hmm_regime as Record<string, unknown>) || {}).status ?? "—")}
            </li>
            <li>
              Python strategies:{" "}
              {String(((overview?.python_strategies as Record<string, unknown>) || {}).status ?? "—")}
            </li>
          </ul>
        </Panel>
      </div>
    </AppShell>
  );
}
