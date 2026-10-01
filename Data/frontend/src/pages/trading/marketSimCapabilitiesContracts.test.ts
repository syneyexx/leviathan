import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const typesPath = resolve(__dirname, "../../types/api.ts");
const clientPath = resolve(__dirname, "../../api/client.ts");
const liveHookPath = resolve(__dirname, "liveAgents/useLiveAgentsData.ts");
const livePagePath = resolve(__dirname, "liveAgents/LiveAgentsPage.tsx");
const controlDrawerPath = resolve(__dirname, "agentOverview/AgentOverviewDrawers.tsx");
const controlModelPath = resolve(__dirname, "controlRoom/viewModel.ts");

describe("Trading Center typed capability contracts", () => {
  const types = readFileSync(typesPath, "utf8");
  const client = readFileSync(clientPath, "utf8");
  const live = readFileSync(liveHookPath, "utf8");
  const livePage = readFileSync(livePagePath, "utf8");
  const controlDrawer = readFileSync(controlDrawerPath, "utf8");
  const controlRoomModel = readFileSync(controlModelPath, "utf8");

  it("declares MarketSimCapabilities and granularity types", () => {
    expect(types).toContain("export type MarketSimCapabilities");
    expect(types).toContain("export type MarketSimFamilyCapability");
    expect(types).toContain("export type MarketSimExecutionGranularity");
    expect(types).toContain("export type MarketSimModeCapabilityRow");
    expect(types).toContain("export type MarketSimPaperDeployment");
    expect(types).toContain("HISTORICAL_SIM_AVAILABLE");
    expect(types).toContain("LIVE_TRADING_AVAILABLE");
    expect(types).toContain("ohlcv_is_not_orderbook");
    expect(types).toContain("mode_matrix");
    expect(types).toContain("mode_matrix_machine_derived");
  });

  it("types marketSimCapabilities client method", () => {
    expect(client).toContain("marketSimCapabilities(): Promise<MarketSimCapabilities>");
    expect(client).toContain('"/api/market-sim/capabilities"');
  });

  it("Live Agents consumes paper deployments without fabricating Sharpe", () => {
    expect(live).toContain("listPaperDeployments");
    expect(livePage).toContain("PAPER");
    expect(live).not.toMatch(/sharpe\s*[:=]\s*1\.[0-9]/i);
    expect(live).not.toContain("institutional ready");
    expect(livePage).not.toContain("institutional ready");
  });

  it("Control Room drawer treats live trading as blocked by default", () => {
    expect(controlDrawer).toContain("marketSimInstitutionalControlRoom");
    expect(controlDrawer).not.toContain("setInterval");
    expect(controlRoomModel).toContain("LIVE_TRADING_AVAILABLE");
    expect(controlRoomModel).toContain("BLOCKED");
  });
});
