import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { startEditorContentRuntime } from "./editorContentRuntime";
import { ToastProvider } from "./state/ToastContext";
import "./styles/tokens.css";
import "./styles/leviathan.css";
import "./styles/sidebar-reference.css";
import "./styles/chat.css";
import "./styles/pages.css";
import "./styles/analytics.css";
import "./styles/trading.css";
import "./styles/trading-pages.css";
import "./styles/training.css";
import "./styles/coding.css";
import "./styles/media-platform.css";
import "./styles/media-pages.css";
import "./styles/media-control.css";
import "./styles/media-research-pages.css";
import "./styles/agents.css";
import "./styles/media-instagram.css";
import "./styles/media-facebook.css";
import "./styles/brain-pages.css";
import "./styles/brain-fidelity.css";
import "./styles/brain-fidelity-layout.css";
import "./styles/pixel-pages.css";
import "./styles/plugin-runtime-pages.css";
import "./styles/onderzoek-kennis.css";
import "./styles/research-dashboard.css";
import "./styles/datasets-dashboard.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("LEVIATHAN frontend root element #root was not found.");
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <ToastProvider>
          <App />
        </ToastProvider>
      </ErrorBoundary>
    </BrowserRouter>
  </StrictMode>,
);

// Apply saved visual-editor content in normal Leviathan runs (no editor UI).
startEditorContentRuntime();
