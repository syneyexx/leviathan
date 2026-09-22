import { Navigate, Route, Routes } from "react-router-dom";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { BrainPage } from "./pages/BrainPage";
import { ChatPage } from "./pages/ChatPage";
import { CodingPage } from "./pages/CodingPage";
import { CommandPage } from "./pages/CommandPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { MediaManagementPage } from "./pages/MediaManagementPage";
import { ModelsPage } from "./pages/ModelsPage";
import { ResearchPage } from "./pages/ResearchPage";
import { SectionPage } from "./pages/SectionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TasksPage } from "./pages/TasksPage";
import { ToolsPage } from "./pages/ToolsPage";
import { TradingCenterPage } from "./pages/TradingCenterPage";
import { TrainingPage } from "./pages/TrainingPage";

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
      <Route path="/agents" element={<SectionPage title="Agents" />} />
      <Route path="/analytics" element={<AnalyticsPage />} />

      <Route path="/media" element={<MediaManagementPage />} />
      <Route path="/media/youtube" element={<SectionPage title="Youtube" />} />
      <Route path="/media/tiktok" element={<SectionPage title="Tiktok" />} />
      <Route path="/media/instagram" element={<SectionPage title="Instagram" />} />
      <Route path="/media/facebook" element={<SectionPage title="Facebook" />} />
      <Route path="/media/queue" element={<SectionPage title="Algemene publicatiewachtrij" />} />
      <Route path="/media/viral" element={<SectionPage title="Viral radar" />} />
      <Route path="/media/calendar" element={<SectionPage title="Calender" />} />
      <Route path="/media/analytics" element={<SectionPage title="Media Analytics" />} />
      <Route path="/media/library" element={<SectionPage title="Bibliotheek" />} />
      <Route path="/media/personas" element={<SectionPage title="Personas" />} />

      <Route path="/trading" element={<TradingCenterPage />} />
      <Route path="/trading/strategieen" element={<SectionPage title="Strategieen" />} />
      <Route path="/trading/marktdata" element={<SectionPage title="Marktdata" />} />
      <Route path="/trading/portefeuille" element={<SectionPage title="Portefeuille" />} />
      <Route path="/trading/paper" element={<SectionPage title="PAPER trading" />} />
      <Route path="/trading/broker" element={<SectionPage title="BROKER trading" />} />

      <Route path="/research" element={<ResearchPage />} />
      <Route path="/brain" element={<BrainPage />} />
      <Route path="/memory" element={<SectionPage title="Geheugen" />} />
      <Route path="/knowledge" element={<SectionPage title="Knowledge Library" />} />
      <Route path="/evidence" element={<SectionPage title="Evidence Vault" />} />
      <Route path="/datasets" element={<DatasetsPage />} />

      <Route path="/performance" element={<SectionPage title="Performance" />} />
      <Route path="/tools" element={<ToolsPage />} />
      <Route path="/mcp" element={<SectionPage title="MCP" />} />
      <Route path="/workflows" element={<SectionPage title="Workflows" />} />
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
