"use client";

import { useCallback, useEffect, useState } from "react";
import { FinalBetaShell } from "./shell/finalbeta-shell";
import { finalBetaHash, luxHashToFinalBetaRedirect, readFinalBetaPageFromHash, resolveFinalBetaPageId } from "./routes";
import type { FinalBetaPageId, FinalBetaPageRender } from "./types";
import {
  DatasetManagementPage,
  DatasetsPage,
  EvidencePage,
  FacebookPage,
  InstagramPage,
  KnowledgePage,
  McpPage,
  MediaPage,
  MediaAnalyticsPage,
  MediaCalendarPage,
  MediaQueuePage,
  MediaViralPage,
  ModelTrainingPage,
  OfflineDatasetsPage,
  PerformancePage,
  ResearchPage,
  TiktokPage,
  ToolsPage,
  TradingBrokerPage,
  TradingMarketdataPage,
  TradingPage,
  TradingPaperPage,
  TradingPortfolioPage,
  TradingStrategiesPage,
  WorkflowsPage,
  YoutubePage,
} from "./pages";
import { AgentsPage } from "./pages/agents-page";
import { ModelsPage } from "./pages/models-page";
import { DashboardPage } from "./pages/dashboard-page";
import { CodingPage } from "./pages/coding-page";
import { BrainPage } from "./pages/brain-page";
import { ChatPage } from "./pages/chat-page";
import { TasksPage } from "./pages/tasks-page";
import { MemoryPage } from "./pages/memory-page";
import { LlmStatsPage } from "./pages/llm-stats-page";
import { SettingsConsolePage } from "./pages/settings-console-page";
import { FinalBetaSettingsPage } from "./pages/finalbeta-settings-page";
import { LoginPage } from "./pages/login-page";
import {
  MediaLibraryPage,
  MediaPersonasPage,
  SettingsBackupsPage,
  SettingsBenchmarksPage,
  SettingsLlmStudioPage,
  SettingsLogsPage,
  SettingsPythonPage,
  TradingSimulationPage,
} from "./pages/nav-stubs";
import "@/components/hades/styles/finalbeta/index.css";

type LiveSettingsTab = "algemeen" | "interface" | "ai" | "privacy" | "opslag" | "updates";

const SETTINGS_LIVE: Partial<Record<FinalBetaPageId, LiveSettingsTab>> = {
  "settings-general": "algemeen",
  "settings-interface": "interface",
  "settings-llm-behavior": "ai",
  "settings-security": "privacy",
  "settings-storage": "opslag",
};

type ShellPageId = Exclude<
  FinalBetaPageId,
  | "dashboard"
  | "chat"
  | "coding"
  | "brain"
  | "tasks"
  | "memory"
  | "llm-stats"
  | "media"
  | "youtube"
  | "tiktok"
  | "instagram"
  | "facebook"
  | "media-queue"
  | "media-viral"
  | "media-analytics"
  | "media-calendar"
  | "trading"
  | "trading-strategies"
  | "trading-marketdata"
  | "trading-portfolio"
  | "trading-paper"
  | "trading-broker"
  | "evidence"
  | "files"
  | "datasets"
  | "dataset-management"
  | "offline-datasets"
  | "knowledge"
  | "research"
  | "performance"
  | "tools"
  | "mcp"
  | "workflows"
  | "settings-console"
  | "login"
  | "mission-control"
  | "settings"
  | "system"
  | "settings-general"
  | "settings-interface"
  | "settings-llm-behavior"
  | "settings-security"
  | "settings-storage"
  | "model-training"
  | "models"
  | "agents"
>;

const pageRenderers: Record<ShellPageId, () => FinalBetaPageRender> = {
  "media-library": MediaLibraryPage,
  "media-personas": MediaPersonasPage,
  "trading-simulation": TradingSimulationPage,
  "settings-llm-studio": SettingsLlmStudioPage,
  "settings-benchmarks": SettingsBenchmarksPage,
  "settings-python": SettingsPythonPage,
  "settings-logs": SettingsLogsPage,
  "settings-backups": SettingsBackupsPage,
};

/**
 * Isolated FINALBETA shell with HOOFDMENU + per-section SUBMENU navigation.
 * Mounted only when ui_style === "finalbeta". Starts on Login; Chat uses live HADES APIs.
 */
export function FinalBetaApp() {
  const [page, setPage] = useState<FinalBetaPageId>(() => readFinalBetaPageFromHash());

  useEffect(() => {
    const sync = () => {
      const hash = window.location.hash || "";
      if (hash.startsWith("#/coding-agent")) {
        const q = hash.includes("?") ? hash.slice(hash.indexOf("?")) : "";
        const params = new URLSearchParams(q.startsWith("?") ? q.slice(1) : q);
        const job = params.get("codingJob");
        const next = job ? `#/fb/coding?codingJob=${encodeURIComponent(job)}` : "#/fb/coding";
        if (window.location.hash !== next) window.location.hash = next.slice(1);
        return;
      }
      const luxTarget = luxHashToFinalBetaRedirect(hash);
      if (luxTarget) {
        const next = finalBetaHash(luxTarget);
        if (window.location.hash !== next) window.location.hash = next;
        return;
      }
      if (!hash.startsWith("#/fb/")) return;
      setPage(readFinalBetaPageFromHash());
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const navigate = useCallback((next: FinalBetaPageId) => {
    const resolved = resolveFinalBetaPageId(next);
    const hash = finalBetaHash(resolved);
    if (window.location.hash !== hash) {
      window.location.hash = hash;
    } else {
      setPage(resolved);
    }
  }, []);

  useEffect(() => {
    // Explicit Lux → FINALBETA redirects only (F-21); no dual page-state machine.
    const luxTarget = luxHashToFinalBetaRedirect(window.location.hash);
    if (luxTarget) {
      window.location.hash = finalBetaHash(luxTarget);
      return;
    }
    if (!window.location.hash.startsWith("#/fb/")) {
      window.location.hash = finalBetaHash(readFinalBetaPageFromHash());
    }
  }, []);

  if (page === "login") {
    return (
      <div className="fb-root login-page" data-finalbeta="pixel-reference">
        <LoginPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "dashboard") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <DashboardPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "chat") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <ChatPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "coding") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <CodingPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "models") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <ModelsPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "agents") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <AgentsPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "tasks") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <TasksPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "memory") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <MemoryPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "brain") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <BrainPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "evidence") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <EvidencePage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "datasets") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <DatasetsPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "dataset-management") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <DatasetManagementPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "offline-datasets") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <OfflineDatasetsPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "knowledge") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <KnowledgePage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "research") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <ResearchPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "llm-stats") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <LlmStatsPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "model-training") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <ModelTrainingPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "performance") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <PerformancePage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "tools") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <ToolsPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "mcp") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <McpPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "workflows") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <WorkflowsPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "settings-console") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <SettingsConsolePage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "media") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <MediaPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "youtube") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <YoutubePage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "tiktok") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <TiktokPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "instagram") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <InstagramPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "facebook") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <FacebookPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "media-queue") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <MediaQueuePage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "media-viral") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <MediaViralPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "media-analytics") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <MediaAnalyticsPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "media-calendar") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <MediaCalendarPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "trading") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <TradingPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "trading-marketdata") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <TradingMarketdataPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "trading-strategies") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <TradingStrategiesPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "trading-portfolio") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <TradingPortfolioPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "trading-paper") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <TradingPaperPage onNavigate={navigate} />
      </div>
    );
  }

  if (page === "trading-broker") {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <TradingBrokerPage onNavigate={navigate} />
      </div>
    );
  }

  const liveSettingsTab = SETTINGS_LIVE[page];
  if (liveSettingsTab) {
    return (
      <div className="fb-root" data-finalbeta="pixel-reference">
        <FinalBetaSettingsPage onNavigate={navigate} pageId={page} initialTab={liveSettingsTab} />
      </div>
    );
  }

  const render = pageRenderers[page as ShellPageId]();

  return (
    <div className="fb-root" data-finalbeta="pixel-reference">
      <FinalBetaShell page={page} body={render.body} inspector={render.inspector} onNavigate={navigate} />
    </div>
  );
}
