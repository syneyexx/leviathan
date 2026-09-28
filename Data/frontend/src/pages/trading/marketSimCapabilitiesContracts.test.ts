import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const typesPath = resolve(__dirname, "../../types/api.ts");
const clientPath = resolve(__dirname, "../../api/client.ts");
const paperHookPath = resolve(__dirname, "paper/hooks/usePaperTradingOperator.ts");
const paperPagePath = resolve(__dirname, "paper/PaperTradingPage.tsx");
const controlRoomPath = resolve(__dirname, "InstitutionalControlRoomPage.tsx");
const controlRoomModelPath = resolve(__dirname, "controlRoom/viewModel.ts");

describe("Trading Center typed capability contracts", () => {
  const types = readFileSync(typesPath, "utf8");
  const client = readFileSync(clientPath, "utf8");
  const paper = readFileSync(paperHookPath, "utf8");
  const paperPage = readFileSync(paperPagePath, "utf8");
  const controlRoom = readFileSync(controlRoomPath, "utf8");
  const controlRoomModel = readFileSync(controlRoomModelPath, "utf8");

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

  it("Paper Trading consumes backend capabilities without fabricating Sharpe", () => {
    expect(paper).toContain("marketSimCapabilities");
    expect(paperPage).toContain("lv-main lv-tp-main");
    expect(paper).not.toMatch(/sharpe\s*[:=]\s*1\.[0-9]/i);
    expect(paper).not.toContain("institutional ready");
    expect(paperPage).not.toContain("institutional ready");
  });

  it("Control Room treats live trading as blocked by default", () => {
    expect(controlRoom).toContain("marketSimInstitutionalControlRoom");
    expect(controlRoom).not.toContain("setInterval");
    expect(controlRoomModel).toContain("LIVE_TRADING_AVAILABLE");
    expect(controlRoomModel).toContain("BLOCKED");
  });
});
