import { Navigate, Route, Routes } from "react-router-dom";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { BrainPage } from "./pages/BrainPage";
import { ChatPage } from "./pages/ChatPage";
import { CommandPage } from "./pages/CommandPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { MediaManagementPage } from "./pages/MediaManagementPage";
import { ModelsPage } from "./pages/ModelsPage";
import { ResearchPage } from "./pages/ResearchPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StatusPage } from "./pages/StatusPage";
import { ToolsPage } from "./pages/ToolsPage";
import { TradingCenterPage } from "./pages/TradingCenterPage";
import { TrainingPage } from "./pages/TrainingPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CommandPage />} />
      <Route path="/status" element={<StatusPage />} />
      <Route path="/chat" element={<ChatPage />} />
      <Route path="/research" element={<ResearchPage />} />
      <Route path="/media" element={<MediaManagementPage />} />
      <Route path="/datasets" element={<DatasetsPage />} />
      <Route path="/brain" element={<BrainPage />} />
      <Route path="/models" element={<ModelsPage />} />
      <Route path="/training" element={<TrainingPage />} />
      <Route path="/tools" element={<ToolsPage />} />
      <Route path="/analytics" element={<AnalyticsPage />} />
      <Route path="/trading" element={<TradingCenterPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/chat.html" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
