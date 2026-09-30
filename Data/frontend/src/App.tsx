import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AgentsPage } from "./pages/AgentsPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { BrainPage } from "./pages/BrainPage";
import { ChatPage } from "./pages/ChatPage";
import { CodingPage } from "./pages/CodingPage";
import { CognitionPage } from "./pages/CognitionPage";
import { CommandPage } from "./pages/CommandPage";
import { OfflineDatasetsPixelPage } from "./pages/pixel";
import { DatasetManagementPage } from "./pages/DatasetManagementPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { ModelsPage } from "./pages/ModelsPage";
import { TrainingPage } from "./pages/TrainingPage";
import { EvaluationsPage } from "./pages/EvaluationsPage";
import { EvidenceVaultPage } from "./pages/EvidenceVaultPage";
import { GeheugenPage } from "./pages/GeheugenPage";
import { KnowledgeLibraryPage } from "./pages/KnowledgeLibraryPage";
import { PromptsPage } from "./pages/PromptsPage";
import { FacebookPage } from "./pages/media/FacebookPage";
import { InstagramPage } from "./pages/media/InstagramPage";
import { MediaCalendarPage } from "./pages/media/MediaCalendarPage";
import { MediaControlPage } from "./pages/media/MediaControlPage";
import { MediaDistributionPage } from "./pages/media/MediaDistributionPage";
import { MediaEditPage } from "./pages/media/MediaEditPage";
import { MediaGeneratePage } from "./pages/media/MediaGeneratePage";
import { MediaLibraryPage } from "./pages/media/MediaLibraryPage";
import { MediaPersonasPage } from "./pages/media/MediaPersonasPage";
import { MediaPlanningPage } from "./pages/media/MediaPlanningPage";
import { MediaQueuePage } from "./pages/media/MediaQueuePage";
import { MediaViralPage } from "./pages/media/MediaViralPage";
import { TikTokPage } from "./pages/media/TikTokPage";
import { YouTubePage } from "./pages/media/YouTubePage";
import { ResearchPage } from "./pages/ResearchPage";
import { PerformancePage } from "./pages/PerformancePage";
import { SectionPage } from "./pages/SectionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TasksPage } from "./pages/TasksPage";
import { ToolsPage } from "./pages/ToolsPage";
import { ModulesPage } from "./pages/ModulesPage";
import { SkillsPage } from "./pages/plugin-runtime/SkillsPage";
import { McpPage } from "./pages/McpPage";
import { ConsolePage } from "./pages/ConsolePage";
import { WorkflowsPage } from "./pages/WorkflowsPage";
import { ErrorBoundary } from "./components/ErrorBoundary";

const CommandHubPage = lazy(() =>
  import("./pages/trading/workspaces/CommandHubPage").then((m) => ({ default: m.CommandHubPage })),
);
const StrategyLabWorkspacePage = lazy(() =>
  import("./pages/trading/workspaces/StrategyLabWorkspacePage").then((m) => ({
    default: m.StrategyLabWorkspacePage,
  })),
);
const TradingDeskPage = lazy(() =>
  import("./pages/trading/workspaces/TradingDeskPage").then((m) => ({ default: m.TradingDeskPage })),
);
const MarketDataWorkspacePage = lazy(() =>
  import("./pages/trading/workspaces/MarketDataWorkspacePage").then((m) => ({
    default: m.MarketDataWorkspacePage,
  })),
);

function TradingSuspense({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary fallbackTitle="Trading page failed">
      <Suspense fallback={<div className="lv-tp-wrap"><p className="lv-tp-muted">Loading trading surface…</p></div>}>
        {children}
      </Suspense>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CommandPage />} />
      <Route path="/status" element={<Navigate to="/tasks" replace />} />
      <Route path="/tasks" element={<TasksPage />} />
      <Route path="/chat" element={<ChatPage />} />
      <Route path="/prompts" element={<PromptsPage />} />
      <Route path="/evaluations" element={<EvaluationsPage />} />
      <Route path="/coding" element={<CodingPage />} />

      <Route path="/models" element={<ModelsPage />} />
      <Route path="/training" element={<TrainingPage />} />
      <Route path="/dataset-management" element={<DatasetManagementPage />} />
      <Route path="/offline-datasets" element={<OfflineDatasetsPixelPage />} />
      <Route path="/agents" element={<AgentsPage />} />
      <Route path="/analytics" element={<AnalyticsPage />} />

      <Route path="/media" element={<MediaControlPage />} />
      <Route path="/media/library" element={<MediaLibraryPage />} />
      <Route path="/media/genereren" element={<MediaGeneratePage />} />
      <Route path="/media/bewerken" element={<MediaEditPage />} />
      <Route path="/media/planning" element={<MediaPlanningPage />} />
      <Route path="/media/distributie" element={<MediaDistributionPage />} />
      <Route path="/media/youtube" element={<YouTubePage />} />
      <Route path="/media/tiktok" element={<TikTokPage />} />
      <Route path="/media/instagram" element={<InstagramPage />} />
      <Route path="/media/facebook" element={<FacebookPage />} />
      <Route path="/media/queue" element={<MediaQueuePage />} />
      <Route path="/media/viral" element={<MediaViralPage />} />
      <Route path="/media/calendar" element={<MediaCalendarPage />} />
      <Route path="/media/analytics" element={<SectionPage title="Media Analytics" />} />
      <Route path="/media/personas" element={<MediaPersonasPage />} />

      <Route path="/trading" element={<Navigate to="/trading/command-hub" replace />} />
      <Route
        path="/trading/command-hub"
        element={
          <TradingSuspense>
            <CommandHubPage />
          </TradingSuspense>
        }
      />
      <Route
        path="/trading/strategy-lab"
        element={
          <TradingSuspense>
            <StrategyLabWorkspacePage />
          </TradingSuspense>
        }
      />
      <Route
        path="/trading/trading-desk"
        element={
          <TradingSuspense>
            <TradingDeskPage />
          </TradingSuspense>
        }
      />
      <Route
        path="/trading/market-data"
        element={
          <TradingSuspense>
            <MarketDataWorkspacePage />
          </TradingSuspense>
        }
      />
      {/* Legacy Trading Center routes → four native workspaces (WAVE 5+) */}
      <Route path="/trading/simulatie" element={<Navigate to="/trading/strategy-lab" replace />} />
      <Route path="/trading/strategieen" element={<Navigate to="/trading/strategy-lab" replace />} />
      <Route path="/trading/lab" element={<Navigate to="/trading/strategy-lab" replace />} />
      <Route path="/trading/marktdata" element={<Navigate to="/trading/market-data" replace />} />
      <Route path="/trading/portefeuille" element={<Navigate to="/trading/trading-desk" replace />} />
      <Route path="/trading/paper" element={<Navigate to="/trading/trading-desk" replace />} />
      <Route path="/trading/broker" element={<Navigate to="/trading/trading-desk" replace />} />
      <Route path="/trading/onderzoek" element={<Navigate to="/trading/command-hub" replace />} />
      <Route path="/trading/control-room" element={<Navigate to="/trading/command-hub" replace />} />

      <Route path="/research" element={<ResearchPage />} />
      <Route path="/brain" element={<BrainPage />} />
      <Route path="/cognition" element={<CognitionPage />} />
      <Route path="/memory" element={<GeheugenPage />} />
      <Route path="/knowledge" element={<KnowledgeLibraryPage />} />
      <Route path="/evidence" element={<EvidenceVaultPage />} />
      <Route path="/datasets" element={<DatasetsPage />} />

      <Route path="/performance" element={<PerformancePage />} />
      <Route path="/tools" element={<ToolsPage />} />
      <Route path="/modules" element={<ModulesPage />} />
      <Route path="/skills" element={<SkillsPage />} />
      <Route path="/mcp" element={<McpPage />} />
      <Route path="/workflows" element={<WorkflowsPage />} />
      <Route path="/console" element={<ConsolePage />} />

      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/settings/llm-gedrag" element={<Navigate to="/settings?section=llm_gedrag" replace />} />
      <Route path="/settings/llm-studio" element={<Navigate to="/settings?section=llm_studio" replace />} />
      <Route path="/settings/rechten" element={<Navigate to="/settings?section=rechten" replace />} />
      <Route path="/settings/benchmarks" element={<Navigate to="/settings?section=benchmarks" replace />} />
      <Route path="/settings/mediacenter" element={<Navigate to="/settings?section=mediacenter" replace />} />
      <Route path="/settings/opslag" element={<Navigate to="/settings?section=opslag" replace />} />
      <Route path="/settings/python" element={<Navigate to="/settings?section=python" replace />} />
      <Route path="/settings/console" element={<Navigate to="/settings?section=console" replace />} />
      <Route path="/settings/logs" element={<Navigate to="/settings?section=logs" replace />} />

      <Route path="/chat.html" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
