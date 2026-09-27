import { Link } from "react-router-dom";
import { tradingHeroes } from "../../../assets/tradingAssets";
import { AppShell } from "../../../layouts/AppShell";
import { TradingHero } from "../shared";
import { QualificationTruthStrip } from "../QualificationTruthStrip";
import { asRecord } from "./viewModels";
import { useResearchLab } from "./hooks/useResearchLab";
import { ResearchRunListRail } from "./components/ResearchRunListRail";
import { ResearchLabTabBar } from "./components/ResearchLabTabBar";
import { ResearchLabOverview } from "./components/ResearchLabOverview";
import { ResearchLabGenerationsPanel } from "./components/ResearchLabGenerationsPanel";
import { ResearchLabPopulationPanel } from "./components/ResearchLabPopulationPanel";
import { ResearchLabLineagePanel } from "./components/ResearchLabLineagePanel";
import { ResearchLabValidationPanel } from "./components/ResearchLabValidationPanel";
import { ResearchLabAnalyticsPanel } from "./components/ResearchLabAnalyticsPanel";
import { ResearchLabLogsPanel } from "./components/ResearchLabLogsPanel";
import { ResearchRunDetailPanel } from "./components/ResearchRunDetailPanel";
import { ResearchLabCreateModal } from "./components/ResearchLabCreateModal";
import { ResearchLabStatusFooter } from "./components/ResearchLabStatusFooter";
import "../../../styles/trading-research-lab.css";

export function ResearchLabPage() {
  const {
    state,
    overviewModel,
    phases,
    events,
    runCounts,
    live,
    truth,
    qualification,
    refresh,
    selectLab,
    setTab,
    runControl,
    openCreate,
    closeCreate,
    patchCreateDraft,
    submitCreate,
    probeFeed,
  } = useResearchLab();

  const hasQualificationMeta =
    state.overview != null &&
    (qualification != null ||
      state.overview.qualificationState != null ||
      state.overview.qualified != null ||
      state.overview.pitState != null ||
      state.overview.sealedState != null);

  const liveBlocked =
    (qualification?.liveBlocked as boolean | undefined) ??
    String(live.LIVE_TRADING_AVAILABLE ?? live.live_trading ?? "BLOCKED").toUpperCase() === "BLOCKED";

  const learnerState = asRecord(state.learning?.learner_state) || {};
  const populationRefs = Array.isArray(learnerState.population_refs)
    ? (learnerState.population_refs as unknown[]).map(String)
    : [];

  const centerBusy = state.learningLoading && !state.learning;

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <main className="lv-main lv-tp-main lv-rl-page">
        <TradingHero
          title="Research Lab"
          image={tradingHeroes.strategieen}
          imageOnly={false}
          kicker="DISCOVER. EVOLVE. VALIDATE."
          quote="Autonomous strategy research and learning for systematic trading — evaluated on market simulation."
          rails={["IDEAS", "MODELS", "BACKTESTS"]}
        />

        <header className="lv-rl-head">
          <div className="lv-rl-head-copy">
            <h1>RESEARCH LAB</h1>
            <p className="lv-rl-kicker">Discover · Evolve · Validate</p>
            <p className="lv-rl-sub">
              Orchestrates adaptive DSL search above market simulation. Paper ≠ live profitability. No mock KPIs.
              A5 live trading remains blocked.
            </p>
          </div>
          <p className="lv-rl-links">
            <Link to="/trading/marktdata">Market data</Link>
            {" · "}
            <Link to="/trading/strategieen">Strategies</Link>
            {" · "}
            <Link to="/trading/simulatie">Simulation</Link>
            {" · "}
            <Link to="/trading/paper">Paper</Link>
          </p>
        </header>

        {state.error ? (
          <div className="lv-rl-banner" role="alert">
            <span>{state.error}</span>
            <button type="button" onClick={() => void refresh()}>
              Retry
            </button>
          </div>
        ) : null}

        {state.actionError ? (
          <div className="lv-rl-banner" role="alert">
            <span>{state.actionError}</span>
            <button type="button" onClick={() => void refresh({ quiet: true })}>
              Dismiss / refresh
            </button>
          </div>
        ) : null}

        {hasQualificationMeta ? (
          <QualificationTruthStrip
            qualificationState={
              (qualification?.qualificationState as string | undefined) ||
              (state.overview?.qualificationState as string | undefined) ||
              null
            }
            qualified={
              (qualification?.qualified as boolean | null | undefined) ??
              (state.overview?.qualified as boolean | null | undefined) ??
              null
            }
            blockers={
              (qualification?.blockers as string[] | undefined) ||
              (state.overview?.blockers as string[] | undefined) ||
              []
            }
            pitState={
              (qualification?.pitState as string | undefined) ||
              (state.overview?.pitState as string | undefined) ||
              null
            }
            sealedState={
              (qualification?.sealedState as string | undefined) ||
              (state.overview?.sealedState as string | undefined) ||
              null
            }
            liveBlocked={liveBlocked}
          />
        ) : null}

        <ResearchLabTabBar
          tab={state.tab}
          onChange={setTab}
          disabled={!state.selectedLabId && state.labs.length === 0}
        />

        <div className="lv-rl-layout">
          <ResearchRunListRail
            labs={state.labs}
            selectedLabId={state.selectedLabId}
            loading={state.loading}
            onSelect={selectLab}
            onCreate={() => void openCreate()}
          />

          <section className="lv-rl-center" aria-label="Research Lab workspace">
            {!state.selectedLabId && !state.loading ? (
              <div className="lv-rl-empty">
                <strong>
                  {state.labs.length === 0
                    ? "No research runs"
                    : state.tab === "overview"
                      ? "No run selected"
                      : `${state.tab[0]!.toUpperCase()}${state.tab.slice(1)} unavailable`}
                </strong>
                {state.labs.length === 0
                  ? "Create a research run to begin learning on market simulation."
                  : `Choose a run from the left rail to inspect ${state.tab}.`}
              </div>
            ) : (
              <>
                {state.tab === "overview" ? (
                  <ResearchLabOverview
                    model={overviewModel}
                    hasLearning={state.learning != null}
                    learningError={state.learningError}
                    loading={centerBusy}
                  />
                ) : null}
                {state.tab === "generations" ? (
                  <ResearchLabGenerationsPanel generations={state.generations} loading={centerBusy} />
                ) : null}
                {state.tab === "population" ? (
                  <ResearchLabPopulationPanel
                    candidates={state.candidates}
                    populationRefs={populationRefs}
                    loading={centerBusy}
                  />
                ) : null}
                {state.tab === "lineage" ? (
                  <ResearchLabLineagePanel candidates={state.candidates} loading={centerBusy} />
                ) : null}
                {state.tab === "validation" ? (
                  <ResearchLabValidationPanel
                    candidates={state.candidates}
                    learning={state.learning}
                    loading={centerBusy}
                  />
                ) : null}
                {state.tab === "analytics" ? (
                  <ResearchLabAnalyticsPanel
                    model={overviewModel}
                    overview={state.overview}
                    costPack={state.costPack}
                    lessons={state.lessons}
                    hasLearning={state.learning != null}
                  />
                ) : null}
                {state.tab === "logs" ? (
                  <ResearchLabLogsPanel
                    events={events}
                    runTrials={state.runTrials}
                    loading={centerBusy}
                  />
                ) : null}
              </>
            )}

            {/* Compact lab truth strip — always visible under workspace */}
            {state.overview ? (
              <article className="lv-rl-card" style={{ marginTop: "auto" }}>
                <h3>Lab truth</h3>
                <ul className="lv-rl-fam-list">
                  <li>
                    LIVE_TRADING_AVAILABLE ={" "}
                    <strong>{String(live.LIVE_TRADING_AVAILABLE ?? live.live_trading ?? "BLOCKED")}</strong>
                  </li>
                  <li>A5 = {String(truth.a5 ?? "IMPOSSIBLE")}</li>
                  <li>
                    NO_STRATEGY_QUALIFIED is valid PASS:{" "}
                    {String(truth.no_strategy_qualified_is_valid_pass ?? true)}
                  </li>
                  <li>
                    Paper ≠ live profitability:{" "}
                    {String(truth.paper_does_not_prove_live_profitability ?? true)}
                  </li>
                  <li>Trial ledger (global): {String(state.overview.trial_ledger_count ?? state.trialCount)}</li>
                </ul>
              </article>
            ) : null}
          </section>

          <ResearchRunDetailPanel
            lab={state.selectedLab}
            learning={state.learning}
            phases={phases}
            busyAction={state.busyAction}
            onControl={(a) => void runControl(a)}
            onProbeFeed={() => void probeFeed()}
            feedHealth={state.feedHealth}
          />
        </div>

        <ResearchLabStatusFooter
          counts={runCounts}
          refreshing={state.refreshing}
          liveBlocked={liveBlocked}
        />
      </main>

      {state.createOpen ? (
        <ResearchLabCreateModal
          draft={state.createDraft}
          strategies={state.strategies}
          sources={state.sources}
          catalogError={state.catalogError}
          busy={state.busyAction === "create"}
          onPatch={patchCreateDraft}
          onClose={closeCreate}
          onSubmit={() => void submitCreate()}
        />
      ) : null}
    </AppShell>
  );
}
