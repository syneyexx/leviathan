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
  DatasetsHubPixelPage,
  KnowledgeLibraryPixelPage,
  ModelsPixelPage,
  OfflineDatasetsPixelPage,
  TrainingPixelPage,
} from "./pages/pixel";
import { EvidenceVaultPage } from "./pages/EvidenceVaultPage";
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
import { ResearchMockPage } from "./pages/ResearchMockPage";
import { SectionPage } from "./pages/SectionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TasksPage } from "./pages/TasksPage";
import { ToolsPage } from "./pages/ToolsPage";
import { McpPage } from "./pages/McpPage";
import { BrokerTradingPage } from "./pages/trading/BrokerTradingPage";
import { MarktdataPage } from "./pages/trading/MarktdataPage";
import { PaperTradingPage } from "./pages/trading/PaperTradingPage";
import { PortefeuillePage } from "./pages/trading/PortefeuillePage";
import { SimulatiePage } from "./pages/trading/SimulatiePage";
import { StrategieenPage } from "./pages/trading/StrategieenPage";
import { WorkflowsPage } from "./pages/WorkflowsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CommandPage />} />
      <Route path="/status" element={<Navigate to="/tasks" replace />} />
      <Route path="/tasks" element={<TasksPage />} />
      <Route path="/chat" element={<ChatPage />} />
      <Route path="/coding" element={<CodingPage />} />

      <Route path="/models" element={<ModelsPixelPage />} />
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
      <Route path="/trading/simulatie" element={<SimulatiePage />} />
      <Route path="/trading/strategieen" element={<StrategieenPage />} />
      <Route path="/trading/marktdata" element={<MarktdataPage />} />
      <Route path="/trading/portefeuille" element={<PortefeuillePage />} />
      <Route path="/trading/paper" element={<PaperTradingPage />} />
      <Route path="/trading/broker" element={<BrokerTradingPage />} />

      <Route path="/research" element={<ResearchMockPage />} />
      <Route path="/brain" element={<BrainPage />} />
      <Route path="/cognition" element={<CognitionPage />} />
      <Route path="/memory" element={<SectionPage title="Geheugen" />} />
      <Route path="/knowledge" element={<KnowledgeLibraryPixelPage />} />
      <Route path="/evidence" element={<EvidenceVaultPage />} />
      <Route path="/datasets" element={<DatasetsHubPixelPage />} />

      <Route path="/performance" element={<SectionPage title="Performance" />} />
      <Route path="/tools" element={<ToolsPage />} />
      <Route path="/mcp" element={<McpPage />} />
      <Route path="/workflows" element={<WorkflowsPage />} />
      <Route path="/console" element={<SectionPage title="Console" />} />

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
