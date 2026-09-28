import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const pagePath = resolve(__dirname, "researchLab/ResearchLabPage.tsx");
const entryPath = resolve(__dirname, "ResearchLabPage.tsx");
const cssPath = resolve(__dirname, "../../styles/trading-research-lab.css");
const apiPath = resolve(__dirname, "../../api/domains/marketSimLab.ts");
const hookPath = resolve(__dirname, "researchLab/hooks/useResearchLab.ts");
const vmPath = resolve(__dirname, "researchLab/viewModels.ts");

describe("Research Lab page contracts", () => {
  const page = readFileSync(pagePath, "utf8");
  const entry = readFileSync(entryPath, "utf8");
  const css = readFileSync(cssPath, "utf8");
  const api = readFileSync(apiPath, "utf8");
  const hook = readFileSync(hookPath, "utf8");
  const vm = readFileSync(vmPath, "utf8");

  it("keeps Research Lab route entry and wraps lv-main", () => {
    expect(entry).toContain('from "./researchLab/ResearchLabPage"');
    expect(page).toContain('className="lv-main lv-tp-main lv-rl-page"');
    expect(page).toContain("RESEARCH LAB");
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
    expect(hook).toContain("marketSimLabCreateRun");
    expect(hook).toContain("marketSimLabStartRun");
    expect(hook).toContain("marketSimLabPauseRun");
  });

  it("exposes dashboard regions and truthful empty-state copy", () => {
    expect(page).toContain("ResearchRunListRail");
    expect(page).toContain("ResearchLabOverview");
    expect(page).toContain("ResearchRunDetailPanel");
    expect(page).toContain("ResearchLabCreateModal");
    expect(page).toContain("No research runs");
    expect(page).toContain("market simulation");
    expect(page).toContain("HYPOTHESES");
    expect(page).toContain("EXPERIMENTS");
    expect(vm).toContain("actionAvailability");
    expect(css).toContain(".lv-rl-charts-3");
    expect(css).toContain(".lv-rl-footer-quote");
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
