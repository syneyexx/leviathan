/**
 * Legacy Dataset Management mock module.
 * Production UI constants live in `pages/datasets/datasetManagementConstants.ts`.
 * This file re-exports production constants and keeps TEST-ONLY table fixtures
 * for older pixel/demo paths — do not import screenshot KPI numbers into V2.
 */

export type {
  DatasetMgmtStatus,
  DatasetSampleTab,
  DatasetSidebarAction,
} from "../pages/datasets/datasetManagementConstants";

export {
  DM_CATEGORY_FILTERS,
  DM_FOOTER_ACTIONS,
  DM_PAGE_COPY,
  DM_QUICK_ACTIONS,
  DM_SAMPLE_TABS,
  DM_SIDEBAR_ACTIONS,
  DM_SOURCE_FILTERS,
  DM_SPLIT_FILTERS,
  DM_STATUS_FILTERS,
  DM_TYPE_FILTERS,
} from "../pages/datasets/datasetManagementConstants";

/** @deprecated Screenshot/demo table rows — visual fixture owns Screen 1 data. */
export type DatasetMgmtRow = {
  id: string;
  name: string;
  type: string;
  typeTone: "cyan" | "gold" | "green" | "purple" | "blue";
  source: string;
  sourceIcon: string;
  split: string;
  size: string;
  tokens: string;
  status: import("../pages/datasets/datasetManagementConstants").DatasetMgmtStatus;
  tags: string[];
  updated: string;
};

/** @deprecated */
export type DatasetMgmtDetail = {
  id: string;
  name: string;
  description: string;
  source: string;
  type: string;
  splits: string;
  location: string;
  version: string;
  language: string;
  license: string;
  taskType: string;
  created: string;
  updated: string;
};

/** @deprecated */
export type DatasetImportJob = {
  id: string;
  task: string;
  dataset: string;
  status: "Klaar" | "Bezig" | "Wachtrij";
  progress: number;
  started: string;
  duration: string;
};

/** @deprecated — use overview API / visual fixture */
export const DM_STATS = [] as const;
/** @deprecated */
export const DM_ACTIONS = [] as const;
/** @deprecated */
export const DM_TAG_OPTIONS = ["nl", "wiki", "kennis", "code", "instruct", "medisch", "chat", "legal", "eu", "news"];
/** @deprecated */
export const DM_TABLE_ROWS: DatasetMgmtRow[] = [];
/** @deprecated */
export const DM_DATASET_DETAILS: Record<string, DatasetMgmtDetail> = {};
/** @deprecated */
export const DM_SAMPLE_JSON = "{}";
/** @deprecated */
export const DM_IMPORT_JOBS: DatasetImportJob[] = [];
/** @deprecated */
export const DM_STORAGE_HEALTH = {
  used: "—",
  total: "—",
  pct: 0,
  dedupeSaved: "—",
  integrity: "—",
  lastCheck: "—",
};
/** @deprecated */
export const DM_TAG_CLOUD = [] as const;
/** @deprecated */
export const DM_TABLE_META = { total: 0, page: 1, pageSize: 8, pageCount: 0 };
