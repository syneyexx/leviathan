import { Navigate, Route, Routes } from "react-router-dom";
import { AgentsPage } from "./pages/AgentsPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { BrainPage } from "./pages/BrainPage";
import { ChatPage } from "./pages/ChatPage";
import { CodingPage } from "./pages/CodingPage";
import { CognitionPage } from "./pages/CognitionPage";
import { CommandPage } from "./pages/CommandPage";
import { DatasetsPage } from "./pages/DatasetsPage";
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
import { ModelsPage } from "./pages/ModelsPage";
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
import { TrainingPage } from "./pages/TrainingPage";
import { WorkflowsPage } from "./pages/WorkflowsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CommandPage />} />
      <Route path="/status" element={<Navigate to="/tasks" replace />} />
      <Route path="/tasks" element={<TasksPage />} />
      <Route path="/chat" element={<ChatPage />} />
      <Route path="/coding" element={<CodingPage />} />

      <Route path="/models" element={<ModelsPage />} />
      <Route path="/training" element={<TrainingPage />} />
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
      <Route path="/knowledge" element={<SectionPage title="Knowledge Library" />} />
      <Route path="/evidence" element={<EvidenceVaultPage />} />
      <Route path="/datasets" element={<DatasetsPage />} />

      <Route path="/performance" element={<SectionPage title="Performance" />} />
      <Route path="/tools" element={<ToolsPage />} />
      <Route path="/mcp" element={<McpPage />} />
      <Route path="/workflows" element={<WorkflowsPage />} />
      <Route path="/console" element={<SectionPage title="Console" />} />

      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/settings/llm-gedrag" element={<SectionPage title="LLM Gedrag" />} />
      <Route path="/settings/llm-studio" element={<SectionPage title="LLM Studio" />} />
      <Route path="/settings/rechten" element={<SectionPage title="Rechten & Security" />} />
      <Route path="/settings/benchmarks" element={<SectionPage title="Model Benchmarks" />} />
      <Route path="/settings/mediacenter" element={<SectionPage title="Mediacenter" />} />
      <Route path="/settings/opslag" element={<SectionPage title="Opslag" />} />
      <Route path="/settings/python" element={<SectionPage title="Python & Runtime" />} />
      <Route path="/settings/console" element={<SectionPage title="Console" />} />
      <Route path="/settings/logs" element={<SectionPage title="Logs" />} />

      <Route path="/chat.html" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
