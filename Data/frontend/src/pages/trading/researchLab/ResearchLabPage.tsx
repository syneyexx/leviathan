import { tradingHeroes } from "../../../assets/tradingAssets";
import { AppShell } from "../../../layouts/AppShell";
import { TradingHero } from "../shared";
import { asRecord } from "./viewModels";
import { useResearchLab } from "./hooks/useResearchLab";
import { ResearchRunListRail } from "./components/ResearchRunListRail";
import { ResearchLabTabBar } from "./components/ResearchLabTabBar";
import { ResearchLabOverview } from "./components/ResearchLabOverview";
import { ResearchLabHypothesesPanel } from "./components/ResearchLabHypothesesPanel";
import { ResearchLabPerceptionPanel } from "./components/ResearchLabPerceptionPanel";
import { ResearchLabGenerationsPanel } from "./components/ResearchLabGenerationsPanel";
import { ResearchLabPopulationPanel } from "./components/ResearchLabPopulationPanel";
import { ResearchLabLineagePanel } from "./components/ResearchLabLineagePanel";
import { ResearchLabValidationPanel } from "./components/ResearchLabValidationPanel";
import { ResearchLabLessonsPanel } from "./components/ResearchLabLessonsPanel";
import { ResearchLabPaperPanel } from "./components/ResearchLabPaperPanel";
import { ResearchLabAnalyticsPanel } from "./components/ResearchLabAnalyticsPanel";
import { ResearchLabLogsPanel } from "./components/ResearchLabLogsPanel";
import { ResearchRunDetailPanel } from "./components/ResearchRunDetailPanel";
import { ResearchLabCreateModal } from "./components/ResearchLabCreateModal";
import { ResearchLabStatusFooter } from "./components/ResearchLabStatusFooter";
import "../../../styles/trading-research-lab.css";

export function ResearchLabPage({ embedded = false }: { embedded?: boolean } = {}) {
  const {
    state,
    overviewModel,
    phases,
    events,
    runCounts,
    qualification,
    refresh,
    selectLab,
    setTab,
    runControl,
    openCreate,
    closeCreate,
    patchCreateDraft,
    submitCreate,
  } = useResearchLab();

  const learnerState = asRecord(state.learning?.learner_state) || {};
  const populationRefs = Array.isArray(learnerState.population_refs)
    ? (learnerState.population_refs as unknown[]).map(String)
    : [];

  const centerBusy = state.learningLoading && !state.learning;
  const apiHealthy = state.error == null;

  const body = (
    <>
      <main className="lv-main lv-tp-main lv-rl-page">
        <TradingHero
          title="RESEARCH LAB"
          image={tradingHeroes.strategieen}
          imageOnly={false}
          kicker="DISCOVER. EVOLVE. VALIDATE."
          quote="Autonomous strategy research and learning for systematic trading."
          rails={["IDEAS", "HYPOTHESES", "EXPERIMENTS", "EVOLUTION", "ALPHA"]}
        />

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

        <div className="lv-rl-layout">
          <ResearchRunListRail
            labs={state.labs}
            selectedLabId={state.selectedLabId}
            loading={state.loading}
            onSelect={selectLab}
            onCreate={() => void openCreate()}
          />

          <section className="lv-rl-center" aria-label="Research Lab workspace">
            <ResearchLabTabBar
              tab={state.tab}
              onChange={setTab}
              disabled={!state.selectedLabId && state.labs.length === 0}
            />
            <div className="lv-rl-center-scroll">
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
                      candidates={state.candidates}
                      lab={state.selectedLab}
                      qualification={qualification}
                      hasLearning={state.learning != null}
                      learningError={state.learningError}
                      loading={centerBusy}
                    />
                  ) : null}
                  {state.tab === "hypotheses" ? (
                    <ResearchLabHypothesesPanel
                      hypotheses={state.hypotheses}
                      loading={centerBusy && state.hypotheses.length === 0}
                      strategyFamilies={state.strategyFamilies}
                    />
                  ) : null}
                  {state.tab === "perception" ? (
                    <ResearchLabPerceptionPanel
                      perception={state.perception}
                      status={state.perceptionStatus}
                      loading={centerBusy && state.perception == null}
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
                  {state.tab === "lessons" ? (
                    <ResearchLabLessonsPanel lessons={state.lessons} loading={centerBusy} />
                  ) : null}
                  {state.tab === "paper" ? (
                    <ResearchLabPaperPanel lab={state.selectedLab} learning={state.learning} />
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
            </div>
          </section>

          <ResearchRunDetailPanel
            lab={state.selectedLab}
            learning={state.learning}
            phases={phases}
            busyAction={state.busyAction}
            onControl={(a) => void runControl(a)}
            onClose={state.selectedLabId ? () => selectLab(null) : undefined}
          />
        </div>

        <ResearchLabStatusFooter
          counts={runCounts}
          refreshing={state.refreshing}
          apiHealthy={apiHealthy}
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
        </>
  );

  if (embedded) return body;
  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      {body}
    </AppShell>
  );
}
