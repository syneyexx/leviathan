import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tradingHeroes } from "../../assets/tradingAssets";
import { ApiError, api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { Panel, TradingHero } from "./shared";

type LabOverview = Record<string, unknown>;

export function ResearchLabPage() {
  const [overview, setOverview] = useState<LabOverview | null>(null);
  const [trials, setTrials] = useState<Record<string, unknown>[]>([]);
  const [trialCount, setTrialCount] = useState(0);
  const [costPack, setCostPack] = useState<Record<string, unknown> | null>(null);
  const [feedHealth, setFeedHealth] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [ov, tr, cost] = await Promise.all([
        api.marketSimLabOverview(),
        api.marketSimLabTrials({ limit: 40 }),
        api.marketSimLabCostPack({ feeBps: 5, slippageBps: 2, seed: 7 }),
      ]);
      setOverview(ov);
      setTrials(tr.trials || []);
      setTrialCount(Number(tr.count || 0));
      setCostPack(cost.cost_pack);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

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

  const live = (overview?.live_trading as Record<string, unknown> | undefined) || {};
  const truth = (overview?.truth as Record<string, unknown> | undefined) || {};
  const stages = (overview?.curriculum_stages as string[]) || [];
  const roles = (overview?.lab_roles as string[]) || [];
  const outcomes = (overview?.valid_lab_outcomes as string[]) || [];

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
