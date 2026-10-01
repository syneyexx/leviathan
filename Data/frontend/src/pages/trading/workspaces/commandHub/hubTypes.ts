export type HubTone = "green" | "blue" | "purple" | "gold" | "red" | "muted";

export type HubKpiCard = {
  id: string;
  label: string;
  value: string;
  delta: string;
  deltaTone: HubTone;
  tone: HubTone;
  spark: number[];
  sparkKind: "line" | "bars";
  href?: string;
};

export type HubAgentRow = {
  id: string;
  name: string;
  status: string;
  statusTone: HubTone;
  task: string;
  market: string;
  workload: number | null;
};

export type HubMarketPanel = {
  symbol: string;
  price: string;
  change: string;
  changeTone: HubTone;
  spark: number[];
  volatility: string;
  volatilityTone: HubTone;
  liquidity: string;
  funding: string;
  regime: string;
  regimeTone: HubTone;
  measured: boolean;
};

export type HubSourceRow = {
  id: string;
  name: string;
  tag: string;
  online: boolean | null;
};

export type HubSessionRow = {
  id: string;
  name: string;
  strategy: string;
  wallet: string;
  market: string;
  focus: string;
  result: string;
  progress: number | null;
  status: string;
  statusTone: HubTone;
};

export type HubWatchRow = {
  id: string;
  agent: string;
  focus: string;
  hypothesis: string;
  finding: string;
  confidence: number | null;
  last: string;
};

export type HubAttentionRow = {
  id: string;
  time: string;
  type: string;
  message: string;
  priority: "Hoog" | "Medium" | "Laag";
};

export type HubQueueRow = {
  id: string;
  task: string;
  type: string;
  agent: string;
  priority: "Hoog" | "Medium" | "Laag";
  started: string;
  status: string;
  statusTone: HubTone;
};

export type HubCapability = {
  id: string;
  label: string;
  sub: string;
  tone: HubTone;
  active: boolean;
};

export type CommandHubData = {
  loading: boolean;
  error: string | null;
  liveTrading: string;
  capabilities: HubCapability[];
  kpis: HubKpiCard[];
  agents: HubAgentRow[];
  market: HubMarketPanel;
  sources: HubSourceRow[];
  sourcesOnline: number;
  paperSessions: HubSessionRow[];
  researchSessions: HubSessionRow[];
  watching: HubWatchRow[];
  attention: HubAttentionRow[];
  queue: HubQueueRow[];
  refresh: () => Promise<void>;
};
