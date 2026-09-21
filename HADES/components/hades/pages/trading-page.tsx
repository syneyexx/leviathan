import { lazy, Suspense, useState } from "react";
import { PageHeader, StatusBadge } from "@/components/hades/ui";
import { PaperDeskTab } from "./trading-lab/paper-desk-tab";

const OverviewTab = lazy(() => import("./trading-lab/overview-tab").then((module) => ({ default: module.OverviewTab })));
const MarketDataTab = lazy(() => import("./trading-lab/market-data-tab").then((module) => ({ default: module.MarketDataTab })));
const SimulatorTab = lazy(() => import("./trading-lab/simulator-tab").then((module) => ({ default: module.SimulatorTab })));
const StrategyLabTab = lazy(() => import("./trading-lab/strategy-lab-tab").then((module) => ({ default: module.StrategyLabTab })));
const ExperimentsTab = lazy(() => import("./trading-lab/experiments-tab").then((module) => ({ default: module.ExperimentsTab })));
const ValidationTab = lazy(() => import("./trading-lab/validation-tab").then((module) => ({ default: module.ValidationTab })));
const AgentTeamTab = lazy(() => import("./trading-lab/agents-tab").then((module) => ({ default: module.AgentTeamTab })));
const PortfolioRiskTab = lazy(() => import("./trading-lab/portfolio-risk-tab").then((module) => ({ default: module.PortfolioRiskTab })));
const OrdersTab = lazy(() => import("./trading-lab/orders-tab").then((module) => ({ default: module.OrdersTab })));
const KnowledgeTab = lazy(() => import("./trading-lab/knowledge-tab").then((module) => ({ default: module.KnowledgeTab })));
const LearningTab = lazy(() => import("./trading-lab/learning-tab").then((module) => ({ default: module.LearningTab })));
const SettingsTab = lazy(() => import("./trading-lab/settings-tab").then((module) => ({ default: module.SettingsTab })));

const TABS = [
  ["overview", "Overzicht"],
  ["market-data", "Marktdata"],
  ["simulator", "Simulator"],
  ["strategy-lab", "Strategy Lab"],
  ["experiments", "Experimenten"],
  ["validation", "Validatie"],
  ["agents", "Agentteam"],
  ["portfolio", "Portefeuille & risico"],
  ["orders", "Orders & uitvoering"],
  ["knowledge", "Kennis"],
  ["learning", "Leren"],
  ["paper-desk", "Paper desk (legacy)"],
  ["settings", "Instellingen"],
] as const;

type TabId = (typeof TABS)[number][0];

export function TradingPage() {
  const [tab, setTab] = useState<TabId>("overview");
  const [runId, setRunId] = useState("");
  const [strategyId, setStrategyId] = useState("");

  const openRun = (id: string) => {
    setRunId(id);
    setTab("simulator");
  };

  return (
    <div className="page page-trading">
      <PageHeader
        title="Trading Lab"
        description="Lokale onderzoeks-, simulatie- en paperomgeving: marktdata beheren, strategieën onderbouwen, simuleren op één virtuele klok en onafhankelijk laten evalueren."
        actions={<StatusBadge tone="warning">SIMULATIE / PAPER — geen echt geld</StatusBadge>}
      />

      <div className="lab-tabs" role="tablist" aria-label="Trading Lab">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`lab-tab${tab === id ? " is-active" : ""}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <Suspense fallback={<div className="lab-empty"><strong>Laden…</strong><span>Het tabblad wordt opgehaald.</span></div>}>
        {tab === "overview" ? <OverviewTab onOpenRun={openRun} /> : null}
        {tab === "market-data" ? <MarketDataTab /> : null}
        {tab === "simulator" ? <SimulatorTab runId={runId} onSelectRun={setRunId} /> : null}
        {tab === "strategy-lab" ? <StrategyLabTab strategyId={strategyId} onSelectStrategy={setStrategyId} /> : null}
        {tab === "experiments" ? <ExperimentsTab /> : null}
        {tab === "validation" ? <ValidationTab strategyId={strategyId} /> : null}
        {tab === "agents" ? <AgentTeamTab strategyId={strategyId} /> : null}
        {tab === "portfolio" ? <PortfolioRiskTab runId={runId} onSelectRun={setRunId} /> : null}
        {tab === "orders" ? <OrdersTab runId={runId} onSelectRun={setRunId} /> : null}
        {tab === "knowledge" ? <KnowledgeTab /> : null}
        {tab === "learning" ? <LearningTab /> : null}
        {tab === "paper-desk" ? <PaperDeskTab /> : null}
        {tab === "settings" ? <SettingsTab /> : null}
      </Suspense>
    </div>
  );
}
