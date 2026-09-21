import { Navigate, Route, Routes } from "react-router-dom";
import { AgentsPage } from "./pages/AgentsPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { BrainPage } from "./pages/BrainPage";
import { ChatPage } from "./pages/ChatPage";
import { CodingPage } from "./pages/CodingPage";
import { CommandPage } from "./pages/CommandPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { FacebookPage } from "./pages/media/FacebookPage";
import { InstagramPage } from "./pages/media/InstagramPage";
import { MediaControlPage } from "./pages/media/MediaControlPage";
import { TikTokPage } from "./pages/media/TikTokPage";
import { YouTubePage } from "./pages/media/YouTubePage";
import { ModelsPage } from "./pages/ModelsPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { ResearchPage } from "./pages/ResearchPage";
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
      <Route path="/research" element={<ResearchPage />} />
      <Route path="/media" element={<MediaControlPage />} />
      <Route path="/media/youtube" element={<YouTubePage />} />
      <Route path="/media/tiktok" element={<TikTokPage />} />
      <Route path="/media/instagram" element={<InstagramPage />} />
      <Route path="/media/facebook" element={<FacebookPage />} />
      <Route path="/datasets" element={<DatasetsPage />} />
      <Route path="/brain" element={<BrainPage />} />
      <Route path="/memory" element={<PlaceholderPage title="Geheugen" modeLabel="Memory Mode" />} />
      <Route path="/knowledge" element={<PlaceholderPage title="Knowledge Library" modeLabel="Knowledge Mode" />} />
      <Route path="/evidence" element={<PlaceholderPage title="Evidence Vault" modeLabel="Evidence Mode" />} />
      <Route path="/models" element={<ModelsPage />} />
      <Route path="/training" element={<TrainingPage />} />
      <Route path="/agents" element={<AgentsPage />} />
      <Route path="/tools" element={<ToolsPage />} />
      <Route path="/performance" element={<PlaceholderPage title="Performance" modeLabel="Runtime Mode" />} />
      <Route path="/mcp" element={<PlaceholderPage title="MCP" modeLabel="Runtime Mode" />} />
      <Route path="/workflows" element={<PlaceholderPage title="Workflows" modeLabel="Runtime Mode" />} />
      <Route path="/console" element={<PlaceholderPage title="Console" modeLabel="Runtime Mode" />} />
      <Route path="/analytics" element={<AnalyticsPage />} />
      <Route path="/trading" element={<TradingCenterPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/chat.html" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
