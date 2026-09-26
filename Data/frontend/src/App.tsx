import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AgentsPage } from "./pages/AgentsPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { BrainPage } from "./pages/BrainPage";
import { ChatPage } from "./pages/ChatPage";
import { CodingPage } from "./pages/CodingPage";
import { CognitionPage } from "./pages/CognitionPage";
import { CommandPage } from "./pages/CommandPage";
import {
  DatasetManagementPixelPage,
  OfflineDatasetsPixelPage,
  TrainingPixelPage,
} from "./pages/pixel";
import { DatasetsPage } from "./pages/DatasetsPage";
import { ModelsPage } from "./pages/ModelsPage";
import { EvidenceVaultPage } from "./pages/EvidenceVaultPage";
import { GeheugenPage } from "./pages/GeheugenPage";
import { KnowledgeLibraryPage } from "./pages/KnowledgeLibraryPage";
import { FacebookPage } from "./pages/media/FacebookPage";
import { InstagramPage } from "./pages/media/InstagramPage";
import { MediaCalendarPage } from "./pages/media/MediaCalendarPage";
import { MediaControlPage } from "./pages/media/MediaControlPage";
import { MediaLibraryPage } from "./pages/media/MediaLibraryPage";
import { MediaPersonasPage } from "./pages/media/MediaPersonasPage";
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
import { McpPage } from "./pages/McpPage";
import { ConsolePage } from "./pages/ConsolePage";
import { WorkflowsPage } from "./pages/WorkflowsPage";
import { ErrorBoundary } from "./components/ErrorBoundary";

const BrokerTradingPage = lazy(() =>
  import("./pages/trading/BrokerTradingPage").then((m) => ({ default: m.BrokerTradingPage })),
);
const MarktdataPage = lazy(() =>
  import("./pages/trading/MarktdataPage").then((m) => ({ default: m.MarktdataPage })),
);
const OnderzoekPage = lazy(() =>
  import("./pages/trading/OnderzoekPage").then((m) => ({ default: m.OnderzoekPage })),
);
const ResearchLabPage = lazy(() =>
  import("./pages/trading/ResearchLabPage").then((m) => ({ default: m.ResearchLabPage })),
);
const PaperTradingPage = lazy(() =>
  import("./pages/trading/PaperTradingPage").then((m) => ({ default: m.PaperTradingPage })),
);
const PortefeuillePage = lazy(() =>
  import("./pages/trading/PortefeuillePage").then((m) => ({ default: m.PortefeuillePage })),
);
const SimulatiePage = lazy(() =>
  import("./pages/trading/SimulatiePage").then((m) => ({ default: m.SimulatiePage })),
);
const StrategieenPage = lazy(() =>
  import("./pages/trading/StrategieenPage").then((m) => ({ default: m.StrategieenPage })),
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
      <Route path="/coding" element={<CodingPage />} />

      <Route path="/models" element={<ModelsPage />} />
      <Route path="/training" element={<TrainingPixelPage />} />
      <Route path="/dataset-management" element={<DatasetManagementPixelPage />} />
      <Route path="/offline-datasets" element={<OfflineDatasetsPixelPage />} />
      <Route path="/agents" element={<AgentsPage />} />
      <Route path="/analytics" element={<AnalyticsPage />} />

      <Route path="/media" element={<MediaControlPage />} />
      <Route path="/media/youtube" element={<YouTubePage />} />
      <Route path="/media/tiktok" element={<TikTokPage />} />
      <Route path="/media/instagram" element={<InstagramPage />} />
      <Route path="/media/facebook" element={<FacebookPage />} />
      <Route path="/media/queue" element={<MediaQueuePage />} />
      <Route path="/media/viral" element={<MediaViralPage />} />
      <Route path="/media/calendar" element={<MediaCalendarPage />} />
      <Route path="/media/analytics" element={<SectionPage title="Media Analytics" />} />
      <Route path="/media/library" element={<MediaLibraryPage />} />
      <Route path="/media/personas" element={<MediaPersonasPage />} />

      <Route path="/trading" element={<Navigate to="/trading/simulatie" replace />} />
      <Route path="/trading/simulatie" element={<TradingSuspense><SimulatiePage /></TradingSuspense>} />
      <Route path="/trading/strategieen" element={<TradingSuspense><StrategieenPage /></TradingSuspense>} />
      <Route path="/trading/marktdata" element={<TradingSuspense><MarktdataPage /></TradingSuspense>} />
      <Route path="/trading/portefeuille" element={<TradingSuspense><PortefeuillePage /></TradingSuspense>} />
      <Route path="/trading/paper" element={<TradingSuspense><PaperTradingPage /></TradingSuspense>} />
      <Route path="/trading/broker" element={<TradingSuspense><BrokerTradingPage /></TradingSuspense>} />
      <Route path="/trading/onderzoek" element={<TradingSuspense><OnderzoekPage /></TradingSuspense>} />
      <Route path="/trading/lab" element={<TradingSuspense><ResearchLabPage /></TradingSuspense>} />

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
