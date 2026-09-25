import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const pagePath = resolve(__dirname, "PortefeuillePage.tsx");
const cssPath = resolve(__dirname, "../../styles/trading-portefeuille.css");
const clientPath = resolve(__dirname, "../../api/client.ts");
const typesPath = resolve(__dirname, "../../types/api.ts");

describe("Portefeuille page contracts", () => {
  const page = readFileSync(pagePath, "utf8");
  const css = readFileSync(cssPath, "utf8");
  const client = readFileSync(clientPath, "utf8");
  const types = readFileSync(typesPath, "utf8");

  it("keeps user-facing PORTEFEUILLE name and wraps lv-main", () => {
    expect(page).toContain("PORTEFEUILLE");
    expect(page).toContain('className="lv-main lv-tp-main lv-portefeuille-page"');
    expect(page).not.toMatch(/PORTFOLIO TRADINGCENTER/);
  });

  it("wires real API methods instead of hardcoded screenshot equity", () => {
    expect(client).toContain("portfolioDashboard");
    expect(client).toContain("createPortfolio");
    expect(client).toContain("closeSelectedPortfolioPositions");
    expect(page).toContain("api.portfolioDashboard");
    expect(page).toContain("api.createPortfolio");
    expect(page).not.toContain("1428351");
    expect(page).not.toContain("1,428,351");
  });

  it("declares typed dashboard models", () => {
    expect(types).toContain("export type PaperPortfolio");
    expect(types).toContain("export type PortfolioDashboard");
    expect(types).toContain("export type PortfolioRecommendation");
  });

  it("scopes visual styles under lv-portefeuille-*", () => {
    expect(css).toContain(".lv-portefeuille-page");
    expect(css).toContain(".lv-portefeuille-kpis");
    expect(css).toContain(".lv-portefeuille-positions-tools");
    expect(page).toContain("trading-portefeuille.css");
  });

  it("exposes empty / create / lifecycle / export controls", () => {
    expect(page).toContain("Create Paper Portefeuille");
    expect(page).toContain("PAPER / SIMULATED");
    expect(page).toContain("Execute All");
    expect(page).toContain("Export Report");
    expect(page).toContain("Save Allocation");
    expect(page).toContain("View Detailed Analysis");
    expect(page).toContain('lifecycle("start")');
  });
});
