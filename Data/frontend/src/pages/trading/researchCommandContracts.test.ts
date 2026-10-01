import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const page = readFileSync(resolve(__dirname, "researchCommand/ResearchCommandPage.tsx"), "utf8");
const panels = readFileSync(resolve(__dirname, "researchCommand/ResearchCommandPanels.tsx"), "utf8");
const hook = readFileSync(resolve(__dirname, "researchCommand/useResearchCommand.ts"), "utf8");
const drawers = readFileSync(resolve(__dirname, "researchCommand/ResearchCommandDrawers.tsx"), "utf8");
const css = readFileSync(resolve(__dirname, "../../styles/trading-research-command.css"), "utf8");
const api = readFileSync(resolve(__dirname, "../../api/domains/researchCommand.ts"), "utf8");
const researchCenter = readFileSync(resolve(__dirname, "researchCenter/ResearchCenterPage.tsx"), "utf8");

const forbidden = [
  "127,438",
  "127438",
  "Research Alpha",
  "Alpha-01",
  "80,422",
  "Momentum Fractal",
  "Generation 7",
  "78%",
];

describe("Research Command page contracts", () => {
  it("keeps research command content reachable (embedded via Research Centrum)", () => {
    expect(researchCenter).toContain("ResearchCommandPage");
    expect(researchCenter).toContain('section === "research-command"');
    expect(page).toContain('className="lv-main lv-tp-main lv-rc-page"');
    expect(page).toContain("Research Command");
    expect(page).not.toContain("AppSidebar");
  });

  it("renders the reference regions and paper action bar", () => {
    expect(panels).toContain("Active Research Session");
    expect(panels).toContain("Standard Agent Team");
    expect(panels).toContain("Wallet & Portfolio");
    expect(panels).toContain("What They're Watching");
    expect(panels).toContain("Live Thinking / Reasoning Stream");
    expect(panels).toContain("public agent rationale");
    expect(panels).toContain("Thesis & Why");
    expect(panels).toContain("Positioning & Intent");
    expect(panels).toContain("Open Positions & PnL");
    expect(panels).toContain("Strategy Evolution");
    expect(panels).toContain("Execution Guardrails");
    expect(page).toContain("Start Session");
    expect(page).toContain("Pause");
    expect(page).toContain("Flatten All");
    expect(page).toContain("Review Evidence");
    expect(page).toContain("Open Paper Mode");
    expect(css).toContain(".lv-rc-grid");
    expect(css).toContain("minmax(0, 1.18fr)");
  });

  it("preserves orchestra, feed, causal news, signals, and decisions", () => {
    expect(hook).toContain("createTradeOrchestra");
    expect(hook).toContain("launchTradeMission");
    expect(hook).toContain("createTradingNewsFeed");
    expect(hook).toContain("pollTradingNews");
    expect(hook).toContain("updateTradingNewsFeed");
    expect(hook).toContain("deleteTradingNewsFeed");
    expect(panels).toContain("Causal as of");
    expect(panels).toContain("available_at");
    expect(panels).toContain("News signals");
    expect(panels).toContain("data, not execution authority");
    expect(drawers).toContain("Append-only public decision chain");
    expect(drawers).toContain("DECLARED_FREE");
    expect(drawers).toContain("Poll all");
  });

  it("wires session, paper flatten, evolution, and paper navigation", () => {
    expect(api).toContain("/api/market-sim/research-command");
    expect(api).toContain("/flatten");
    expect(api).toContain("FLATTEN_PAPER");
    expect(hook).toContain('navigate("/trading/live-agents');
    expect(hook).toContain("researchCommandStart");
    expect(hook).toContain("researchCommandPause");
    expect(hook).toContain("researchCommandFlatten");
    expect(hook).toContain("researchCommandEvolve");
    expect(hook).toContain("setInterval");
    expect(hook).toContain("clearInterval");
    expect(hook).toContain("visibilityState");
    expect(hook).toContain("abort()");
    expect(drawers).toContain("Confirm PAPER flatten");
    expect(panels).toContain("Live order submission remains blocked");
    expect(panels).toContain("Arm kill switch");
    expect(hook).toContain("/trading/agents?agent=");
  });

  it("does not hardcode screenshot values", () => {
    const blob = [page, panels, hook, drawers, css].join("\n");
    for (const needle of forbidden) {
      expect(blob).not.toContain(needle);
    }
  });
});
