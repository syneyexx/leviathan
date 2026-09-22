import type { ReactNode } from "react";

/** FINALBETA page ids — dedicated namespace, independent of Lux PageId. */
export type FinalBetaPageId =
  | "login"
  | "dashboard"
  | "chat"
  | "coding"
  | "tasks"
  | "models"
  | "model-training"
  | "agents"
  | "llm-stats"
  | "dataset-management"
  | "offline-datasets"
  | "datasets"
  | "media"
  | "youtube"
  | "tiktok"
  | "instagram"
  | "facebook"
  | "media-queue"
  | "media-viral"
  | "media-calendar"
  | "media-analytics"
  | "media-library"
  | "media-personas"
  | "trading-simulation"
  | "trading-strategies"
  | "trading-marketdata"
  | "trading-portfolio"
  | "trading-paper"
  | "trading-broker"
  | "research"
  | "brain"
  | "memory"
  | "knowledge"
  | "evidence"
  | "files"
  | "performance"
  | "tools"
  | "mcp"
  | "workflows"
  | "settings-general"
  | "settings-interface"
  | "settings-llm-behavior"
  | "settings-llm-studio"
  | "settings-security"
  | "settings-benchmarks"
  | "settings-storage"
  | "settings-python"
  | "settings-console"
  | "settings-logs"
  | "settings-backups"
  /** @deprecated Redirects to tasks — Mission Control is merged into Taken. */
  | "mission-control"
  /** TradingCenter Overzicht (commandocentrum). */
  | "trading"
  /** @deprecated Redirects to settings-general. */
  | "settings"
  /** @deprecated Redirects to settings-console. */
  | "system";

/** Top HOOFDMENU sections — each owns its own SUBMENU. */
export type FinalBetaHoofdmenuId =
  | "hades-ai"
  | "llm"
  | "media-control"
  | "trading-center"
  | "onderzoek"
  | "plugin-runtime"
  | "settings";

/** @deprecated Use FinalBetaHoofdmenuId — kept for transitional imports. */
export type FinalBetaTopGroup = FinalBetaHoofdmenuId;

export type FinalBetaSubmenuItem = {
  id: FinalBetaPageId;
  label: string;
  icon: string;
  desc?: string;
};

export type FinalBetaHoofdmenuSection = {
  id: FinalBetaHoofdmenuId;
  label: string;
  /** Page opened when the HOOFDMENU item itself is clicked. */
  home: FinalBetaPageId;
  submenu: FinalBetaSubmenuItem[];
};

export type FinalBetaPageRender = {
  body: ReactNode;
  inspector: ReactNode;
};

export type FinalBetaNavigate = (page: FinalBetaPageId) => void;
