export type Measurement = "MEASURED" | "UNMEASURED" | "EMPTY" | "AGENT_ESTIMATE";

export type Measured<T = string | number | null> = {
  value: T | null;
  measurement: Measurement;
  note?: string | null;
};

export type ResearchAction = {
  enabled: boolean;
  reason: string;
};

export type ResearchCommandSnapshot = {
  session: {
    bound: boolean;
    sessionId: string | null;
    state: string;
    mode: string;
    safety: string;
    name: string | null;
    orchestraId: string | null;
    startedAt: string | null;
    pausedAt: string | null;
    uptime: Measured<number>;
    universe: string[];
    portfolioId: string | null;
    labId: string | null;
    asOf: string | null;
    autonomy: string | null;
    readiness: { state?: string; reason?: string } | null;
  };
  team: {
    name: string | null;
    orchestraId?: string | null;
    members: Array<{
      agentId: string | null;
      name: string | null;
      role: string | null;
      kind: string | null;
      enabled: boolean;
      health?: string | null;
      state: string;
      activity: string | null;
      activityMeasurement: Measurement;
      telemetry: "UNMEASURED";
    }>;
    telemetry: "UNMEASURED";
  };
  portfolio: {
    bound: boolean;
    portfolioId: string | null;
    name: string | null;
    status: string | null;
    mode: string | null;
    currency: string | null;
    killSwitch: boolean | null;
    equity: Measured;
    cash: Measured;
    allocated: Measured;
    openRisk: Measured;
    buyingPower: Measured;
    leverage: Measured;
    dailyPnl: Measured;
    sessionPnl: Measured;
    unrealizedPnl: Measured;
    realizedPnl: Measured;
    allocations: { cash: Measured; positions: Measured; risk: Measured };
    openCount: number;
    marks: string;
  };
  watching: {
    watchlist: WatchRow[];
    opportunities: Array<{
      symbol: string | null;
      direction: string;
      why: string | null;
      whySource: string | null;
      asOf: string | null;
      decisionId: string | null;
    }>;
    highVolatility: { rows: WatchRow[]; note: string };
    news: NewsRow[];
    signals: SignalRow[];
    signalsAreDataNotAuthority: boolean;
  };
  publicEvents: Array<{
    id: string | null;
    at: string | null;
    kind: string;
    stage: string | null;
    role: string | null;
    summary: string;
    source: string;
  }>;
  decisions: Array<{
    decisionId: string;
    orchestraId?: string;
    agentId?: string;
    role?: string;
    stage: string;
    asOf?: string;
    payload: Record<string, unknown>;
    createdAt?: string;
    mandateFingerprint?: string;
  }>;
  signals: SignalRow[];
  feeds: FeedRow[];
  thesis: {
    present: boolean;
    source: string | null;
    decisionId?: string | null;
    primary: string | null;
    instruments: string[];
    direction?: string | null;
    horizon: Measured;
    expectedEdge: Measured;
    invalidation: Measured;
    catalysts: Measured;
    confidence: Measured;
    measuredValidation: Measured;
    asOf?: string | null;
  };
  intent: {
    present: boolean;
    authority: string;
    stage?: string;
    liveTrading: "BLOCKED";
    paperOnly: boolean;
    instrument: string | null;
    direction: string | null;
    size: Measured;
    maxRisk: Measured;
    stop: Measured;
    target: Measured;
    rationale: string | null;
    sizingRationale: Measured;
    riskAllowed?: boolean | null;
    status?: string | null;
  };
  positions: {
    open: PositionRow[];
    closed: PositionRow[];
    unrealizedPnl: Measured;
    realizedPnl: Measured;
    openCount: number;
  };
  strategyEvolution: {
    bound: boolean;
    labId: string | null;
    name: string | null;
    status: string | null;
    rows: EvolutionRow[];
    currentGeneration: Measured<number>;
    hypothesis: string | null;
    bestValidation: Measured;
    canStart: boolean;
    owner: string;
    paperPnl?: Measured;
  };
  guardrails: {
    paperTradingOnly: boolean;
    liveTrading: "BLOCKED";
    riskGuard: string;
    maxSymbolExposurePct: Measured;
    maxGrossExposurePct: Measured;
    perTradeRiskPct: Measured;
    maxOrdersPerDay: Measured;
    maxDrawdownPct: Measured;
    dailyLossLimitPct: Measured;
    killSwitch: string;
    cannotEnableLive: boolean | null;
    mandateFingerprint?: string | null;
  };
  missions: Array<{ missionId?: string; status?: string; title?: string }>;
  catalogs: {
    orchestras: Array<{ orchestraId: string; name: string; autonomyLevel?: string }>;
    portfolios: Array<{ portfolioId: string; name: string; status?: string; mode?: string; killSwitch?: boolean }>;
    labs: Array<{ labId: string; name: string; status?: string; strategyId?: string }>;
  };
  selection: {
    orchestraId: string | null;
    portfolioId: string | null;
    labId: string | null;
    sessionId: string | null;
    asOf: string | null;
  };
  actions: {
    start: ResearchAction;
    pause: ResearchAction;
    flatten: ResearchAction;
    evolve: ResearchAction;
    reviewEvidence: ResearchAction;
    openPaper: ResearchAction;
    launchMission: ResearchAction;
    killSwitch: ResearchAction;
  };
  runtime: {
    worker: string;
    paperEngine: string;
    model?: string | null;
    modelAvailable?: boolean | null;
    externalized?: boolean;
    feedsEnabled?: number;
    feeds?: number;
    liveTrading: "BLOCKED";
  };
  truth: {
    liveTrading: "BLOCKED";
    paperOnly: boolean;
    signalsAreDataNotAuthority: boolean;
    publicReasoningOnly: boolean;
    privateChainOfThought: "NOT_EXPOSED";
    readModel: boolean;
    riskAuthority: string | null;
    asOf: string | null;
    errors: string[];
    owners: Record<string, string>;
  };
};

export type WatchRow = {
  symbol: string;
  last: Measured;
  change24h: Measured;
  change7d: Measured;
  spark: number[];
  volatility: Measured;
  why: string | null;
  whySource: string | null;
};

export type NewsRow = {
  itemId: string;
  title: string;
  source?: string;
  publishedAt?: string | null;
  availableAt?: string;
  licenseState?: string;
};

export type SignalRow = {
  signalId: string;
  direction: string;
  eventType: string;
  instruments: string[];
  magnitude: number;
  confidence: number;
  horizon: string;
  rationale: string;
  asOf: string;
  modelId?: string | null;
};

export type FeedRow = {
  feedId: string;
  name: string;
  url: string;
  kind: string;
  enabled: boolean;
  declaredLatencySeconds: number;
  licenseState: string;
  lastStatus?: string | null;
  lastError?: string | null;
};

export type PositionRow = {
  positionId: string | null;
  symbol: string | null;
  side: string | null;
  size: Measured;
  entry: Measured;
  mark: Measured;
  pnl: Measured;
  pnlPct: Measured;
  state: string;
  paper: boolean;
  at?: string | null;
};

export type EvolutionRow = {
  generation: number | null;
  variant: string | null;
  strategyVersion: number | null;
  status: string;
  validationScore: Measured;
  trainFitness?: Measured;
  paperPnl: Measured;
};
