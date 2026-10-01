import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const pagePath = resolve(__dirname, "researchLab/ResearchLabPage.tsx");
const cssPath = resolve(__dirname, "../../styles/trading-research-lab.css");
const apiPath = resolve(__dirname, "../../api/domains/marketSimLab.ts");
const hookPath = resolve(__dirname, "researchLab/hooks/useResearchLab.ts");
const vmPath = resolve(__dirname, "researchLab/viewModels.ts");
const modalPath = resolve(__dirname, "researchLab/components/ResearchLabCreateModal.tsx");
const hypPath = resolve(__dirname, "researchLab/components/ResearchLabHypothesesPanel.tsx");
const percPath = resolve(__dirname, "researchLab/components/ResearchLabPerceptionPanel.tsx");
const researchCenterPath = resolve(__dirname, "researchCenter/ResearchCenterPage.tsx");

describe("Research Lab page contracts", () => {
  const page = readFileSync(pagePath, "utf8");
  const css = readFileSync(cssPath, "utf8");
  const api = readFileSync(apiPath, "utf8");
  const hook = readFileSync(hookPath, "utf8");
  const vm = readFileSync(vmPath, "utf8");
  const modal = readFileSync(modalPath, "utf8");
  const hyp = readFileSync(hypPath, "utf8");
  const perc = readFileSync(percPath, "utf8");
  const researchCenter = readFileSync(researchCenterPath, "utf8");

  it("keeps Research Lab modules as shared authority (entry via Research Centrum)", () => {
    expect(page).toContain('className="lv-main lv-tp-main lv-rl-page"');
    expect(page).toContain("RESEARCH LAB");
    expect(researchCenter).toContain("ResearchLabPage");
    expect(researchCenter).toMatch(/section === "lab"/);
  });

  it("scopes styles under lv-rl-* and imports dedicated stylesheet", () => {
    expect(page).toContain("trading-research-lab.css");
    expect(css).toContain(".lv-rl-page");
    expect(css).toContain(".lv-rl-layout");
    expect(css).toContain(".lv-rl-rail");
    expect(css).toContain(".lv-rl-detail");
  });

  it("wires real lab lifecycle APIs including create", () => {
    expect(api).toContain("marketSimLabListRuns");
    expect(api).toContain("marketSimLabCreateRun");
    expect(api).toContain("marketSimLabStartRun");
    expect(api).toContain("marketSimLabPauseRun");
    expect(api).toContain("marketSimLabResumeRun");
    expect(api).toContain("marketSimLabCancelRun");
    expect(api).toContain("marketSimLabLearning");
    expect(api).toContain("marketSimLabHypotheses");
    expect(api).toContain("marketSimLabPerception");
    expect(api).toContain("marketSimStrategyFamilies");
    expect(hook).toContain("marketSimLabCreateRun");
    expect(hook).toContain("marketSimLabStartRun");
    expect(hook).toContain("marketSimLabPauseRun");
    expect(hook).toContain("marketSimLabHypotheses");
    expect(hook).toContain("marketSimLabPerception");
  });

  it("exposes dashboard regions and truthful empty-state copy", () => {
    expect(page).toContain("ResearchRunListRail");
    expect(page).toContain("ResearchLabOverview");
    expect(page).toContain("ResearchRunDetailPanel");
    expect(page).toContain("ResearchLabCreateModal");
    expect(page).toContain("ResearchLabHypothesesPanel");
    expect(page).toContain("ResearchLabPerceptionPanel");
    expect(page).toContain("No research runs");
    expect(page).toContain("market simulation");
    expect(page).toContain("HYPOTHESES");
    expect(page).toContain("EXPERIMENTS");
    expect(vm).toContain("actionAvailability");
    expect(vm).toContain('"hypotheses"');
    expect(vm).toContain('"perception"');
    expect(vm).toContain('"lessons"');
    expect(vm).toContain('"paper"');
    expect(css).toContain(".lv-rl-charts-3");
    expect(css).toContain(".lv-rl-footer-quote");
  });

  it("supports autonomous discovery create without required strategy", () => {
    expect(hook).toContain('runMode: "AUTONOMOUS_DISCOVERY"');
    expect(hook).toContain("researchObjective");
    expect(hook).toContain("enableChartVision");
    expect(hook).toContain("modelBudget");
    expect(hook).toContain("agentProposalRate");
    expect(hook).toContain('d.runMode === "SEED_EXISTING_STRATEGY" && !d.strategyId');
    expect(hook).toContain("A READY market-data source is required.");
    expect(hook).toContain("runMode: d.runMode");
    expect(hook).toContain("enableChartVision: d.enableChartVision");
    expect(modal).toContain("Autonomous Discovery");
    expect(modal).toContain("Seed Existing Strategy");
    expect(modal).toContain("Research objective");
    expect(modal).toContain("Advanced research settings");
    expect(modal).toContain("Enable chart vision");
    expect(modal).toContain("does not expose brokerage or execution controls");
    expect(modal).not.toContain("Kill switch");
    expect(modal).not.toContain("Place order");
  });

  it("supports seed existing strategy mode with strategy required", () => {
    expect(hook).toContain("SEED_EXISTING_STRATEGY");
    expect(hook).toContain("Strategy is required when seeding an existing strategy.");
    expect(modal).toContain("Strategy");
    expect(modal).toContain("canSubmit");
  });

  it("keeps honest empty states for hypotheses and perception", () => {
    expect(hyp).toContain("EMPTY / UNMEASURED");
    expect(hyp).toContain("falsification");
    expect(hyp).toContain("mechanism");
    expect(perc).toContain("UNMEASURED");
    expect(perc).toContain("UNAVAILABLE");
    expect(perc).toContain("Conflicts");
  });

  it("does not invent fake metrics or demo run ids", () => {
    expect(page).not.toContain("Qwen3.8 27B");
    expect(hook).not.toContain("fakeRuns");
    expect(vm).toContain('label: id ? String(id) : "Not recorded"');
  });

  it("polls only while run is active and cleans up interval", () => {
    expect(hook).toContain("setInterval");
    expect(hook).toContain("clearInterval");
    expect(hook).toContain("POLL_MS");
    expect(hook).toContain("shouldPoll");
  });
});
