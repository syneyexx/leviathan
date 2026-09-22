import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { startEditorContentRuntime } from "./editorContentRuntime";
import { ToastProvider } from "./state/ToastContext";
import "./styles/tokens.css";
import "./styles/leviathan.css";
import "./styles/chat.css";
import "./styles/pages.css";
import "./styles/analytics.css";
import "./styles/trading.css";
import "./styles/training.css";
import "./styles/coding.css";
import "./styles/media-platform.css";
import "./styles/media-pages.css";
import "./styles/media-control.css";
import "./styles/agents.css";
import "./styles/media-instagram.css";
import "./styles/media-facebook.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("LEVIATHAN frontend root element #root was not found.");
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <App />
      </ToastProvider>
    </BrowserRouter>
  </StrictMode>,
);

// Apply saved visual-editor content in normal Leviathan runs (no editor UI).
startEditorContentRuntime();
