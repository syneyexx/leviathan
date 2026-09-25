/**
 * T10 / G57 — Frontend action matrix for Trading Center.
 * Every operator action maps to a real control-plane API method (no dead buttons).
 */

export type TradingActionId =
  | "sim.status"
  | "sim.data.list"
  | "sim.data.scan"
  | "sim.strategies.list"
  | "sim.runs.list"
  | "sim.runs.create"
  | "sim.runs.start"
  | "sim.runs.pause"
  | "sim.runs.step"
  | "sim.runs.stop"
  | "sim.runs.live"
  | "sim.run_builder"
  | "sim.demos.run"
  | "paper.sessions.list"
  | "paper.sessions.create"
  | "paper.sessions.get"
  | "paper.orders.place"
  | "paper.kill_switch"
  | "paper.forward.start"
  | "paper.forward.tick"
  | "paper.forward.pause"
  | "paper.forward.resume"
  | "risk.status"
  | "risk.reset"
  | "audit.verify"
  | "security.posture"
  | "shadow.start"
  | "shadow.decide"
  | "shadow.outcome"
  | "training.export"
  | "live.status"
  | "capabilities";

export type TradingAction = {
  id: TradingActionId;
  page: "simulatie" | "paper" | "portefeuille" | "broker" | "marktdata" | "strategieen" | "onderzoek" | "shared";
  label: string;
  apiMethod: string;
  path: string;
  method: "GET" | "POST" | "DELETE";
  mutates: boolean;
};

/** Complete matrix — kept in sync with api.client market-sim surface (G57/G59). */
export const TRADING_ACTION_MATRIX: TradingAction[] = [
  { id: "sim.status", page: "shared", label: "Market sim status", apiMethod: "marketSimStatus", path: "/api/market-sim/status", method: "GET", mutates: false },
  { id: "sim.data.list", page: "marktdata", label: "List market data", apiMethod: "listMarketData", path: "/api/market-sim/data", method: "GET", mutates: false },
  { id: "sim.data.scan", page: "marktdata", label: "Scan / seed data", apiMethod: "scanMarketData", path: "/api/market-sim/data/scan", method: "POST", mutates: true },
  { id: "sim.strategies.list", page: "strategieen", label: "List strategies", apiMethod: "listMarketStrategies", path: "/api/market-sim/strategies", method: "GET", mutates: false },
  { id: "sim.runs.list", page: "simulatie", label: "List runs", apiMethod: "listMarketSimRuns", path: "/api/market-sim/runs", method: "GET", mutates: false },
  { id: "sim.runs.create", page: "simulatie", label: "Create run", apiMethod: "createMarketSimRun", path: "/api/market-sim/runs", method: "POST", mutates: true },
  { id: "sim.runs.start", page: "simulatie", label: "Start run", apiMethod: "startMarketSimRun", path: "/api/market-sim/runs/{id}/start", method: "POST", mutates: true },
  { id: "sim.runs.pause", page: "simulatie", label: "Pause run", apiMethod: "pauseMarketSimRun", path: "/api/market-sim/runs/{id}/pause", method: "POST", mutates: true },
  { id: "sim.runs.step", page: "simulatie", label: "Step run", apiMethod: "stepMarketSimRun", path: "/api/market-sim/runs/{id}/step", method: "POST", mutates: true },
  { id: "sim.runs.stop", page: "simulatie", label: "Stop run", apiMethod: "stopMarketSimRun", path: "/api/market-sim/runs/{id}/stop", method: "POST", mutates: true },
  { id: "sim.runs.live", page: "simulatie", label: "Live state", apiMethod: "getMarketSimLive", path: "/api/market-sim/runs/{id}/live", method: "GET", mutates: false },
  { id: "sim.run_builder", page: "simulatie", label: "Run builder options", apiMethod: "marketSimRunBuilder", path: "/api/market-sim/run-builder", method: "GET", mutates: false },
  { id: "sim.demos.run", page: "simulatie", label: "Run demo", apiMethod: "runMarketDemo", path: "/api/market-sim/demos/run", method: "POST", mutates: true },
  { id: "paper.sessions.list", page: "paper", label: "List paper sessions", apiMethod: "listPaperSessions", path: "/api/market-sim/paper/sessions", method: "GET", mutates: false },
  { id: "paper.sessions.create", page: "paper", label: "Start paper session", apiMethod: "createPaperSession", path: "/api/market-sim/paper/sessions", method: "POST", mutates: true },
  { id: "paper.sessions.get", page: "paper", label: "Get paper session", apiMethod: "getPaperSession", path: "/api/market-sim/paper/sessions/{id}", method: "GET", mutates: false },
  { id: "paper.orders.place", page: "paper", label: "Place paper order", apiMethod: "placePaperOrder", path: "/api/market-sim/paper/sessions/{id}/orders", method: "POST", mutates: true },
  { id: "paper.kill_switch", page: "paper", label: "Paper kill switch", apiMethod: "paperKillSwitch", path: "/api/market-sim/paper/sessions/{id}/kill-switch", method: "POST", mutates: true },
  { id: "paper.forward.start", page: "paper", label: "Start paper forward", apiMethod: "startPaperForward", path: "/api/market-sim/paper/sessions/{id}/forward", method: "POST", mutates: true },
  { id: "paper.forward.tick", page: "paper", label: "Tick paper forward", apiMethod: "paperForwardTick", path: "/api/market-sim/paper/forward/{id}/tick", method: "POST", mutates: true },
  { id: "paper.forward.pause", page: "paper", label: "Pause paper forward", apiMethod: "paperForwardPause", path: "/api/market-sim/paper/forward/{id}/pause", method: "POST", mutates: true },
  { id: "paper.forward.resume", page: "paper", label: "Resume paper forward", apiMethod: "paperForwardResume", path: "/api/market-sim/paper/forward/{id}/resume", method: "POST", mutates: true },
  { id: "risk.status", page: "shared", label: "Risk engine status", apiMethod: "marketSimRiskStatus", path: "/api/market-sim/risk", method: "GET", mutates: false },
  { id: "risk.reset", page: "shared", label: "Human risk reset", apiMethod: "marketSimRiskReset", path: "/api/market-sim/risk/reset", method: "POST", mutates: true },
  { id: "audit.verify", page: "shared", label: "Verify audit chain", apiMethod: "marketSimAuditVerify", path: "/api/market-sim/audit/verify", method: "GET", mutates: false },
  { id: "security.posture", page: "broker", label: "Security posture", apiMethod: "marketSimSecurityPosture", path: "/api/market-sim/security-posture", method: "GET", mutates: false },
  { id: "shadow.start", page: "paper", label: "Start shadow live", apiMethod: "startShadowLive", path: "/api/market-sim/shadow/sessions", method: "POST", mutates: true },
  { id: "shadow.decide", page: "paper", label: "Shadow decide", apiMethod: "shadowLiveDecide", path: "/api/market-sim/shadow/sessions/{id}/decide", method: "POST", mutates: true },
  { id: "shadow.outcome", page: "paper", label: "Shadow outcome", apiMethod: "shadowLiveAttachOutcome", path: "/api/market-sim/shadow/sessions/{id}/outcomes/{id}", method: "POST", mutates: true },
  { id: "training.export", page: "shared", label: "Training bridge export", apiMethod: "exportTradingTrainingBridge", path: "/api/market-sim/training-bridge/export", method: "POST", mutates: true },
  { id: "live.status", page: "broker", label: "Live trading status", apiMethod: "marketSimLiveTradingStatus", path: "/api/market-sim/live-trading", method: "GET", mutates: false },
  { id: "capabilities", page: "shared", label: "Capabilities", apiMethod: "marketSimCapabilities", path: "/api/market-sim/capabilities", method: "GET", mutates: false },
];

export function actionIds(): TradingActionId[] {
  return TRADING_ACTION_MATRIX.map((a) => a.id);
}
