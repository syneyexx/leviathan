import { describe, expect, it } from "vitest";
import { MAIN_MENU } from "./menu";
import {
  findActiveV2Child,
  isV2NavItemActive,
  shouldAutoExpandV2Group,
  v2ChildrenFromMainMenu,
  V2_PRIMARY_NAV,
} from "./v2Nav";

const dashboard = V2_PRIMARY_NAV.find((item) => item.id === "dashboard");
const research = V2_PRIMARY_NAV.find((item) => item.id === "research");
const hades = V2_PRIMARY_NAV.find((item) => item.id === "hades");
const lm = V2_PRIMARY_NAV.find((item) => item.id === "lm");

describe("v2Nav dashboard group", () => {
  it("marks dashboard group active on / and /tasks, not /chat", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(isV2NavItemActive(dashboard, "/")).toBe(true);
    expect(isV2NavItemActive(dashboard, "/tasks")).toBe(true);
    expect(isV2NavItemActive(dashboard, "/chat")).toBe(false);
    expect(isV2NavItemActive(dashboard, "/agents")).toBe(false);
  });

  it("findActiveV2Child resolves home and tasks", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(findActiveV2Child(dashboard, "/")?.id).toBe("dashboard-home");
    expect(findActiveV2Child(dashboard, "/tasks")?.id).toBe("taken");
    expect(findActiveV2Child(dashboard, "/tasks/123")?.id).toBe("taken");
    expect(findActiveV2Child(dashboard, "/chat")).toBeNull();
  });

  it("shouldAutoExpandV2Group expands dashboard on its match prefixes", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(shouldAutoExpandV2Group(dashboard, "/")).toBe(true);
    expect(shouldAutoExpandV2Group(dashboard, "/tasks")).toBe(true);
    expect(shouldAutoExpandV2Group(dashboard, "/chat")).toBe(false);
    expect(shouldAutoExpandV2Group(dashboard, "/research")).toBe(false);
  });
});

describe("v2Nav Hades AI group", () => {
  it("is expandable with Screen 1 children", () => {
    expect(hades).toBeDefined();
    if (!hades) return;
    expect(hades.expandable).toBe(true);
    expect(hades.children?.map((c) => c.label)).toEqual([
      "Chat",
      "Reasoning",
      "Agents",
      "Bibliotheek",
      "Prompts",
      "Evaluations",
    ]);
  });

  it("marks Hades active on chat/cognition/prompts/evaluations", () => {
    expect(hades).toBeDefined();
    if (!hades) return;
    expect(isV2NavItemActive(hades, "/chat")).toBe(true);
    expect(isV2NavItemActive(hades, "/cognition")).toBe(true);
    expect(isV2NavItemActive(hades, "/prompts")).toBe(true);
    expect(isV2NavItemActive(hades, "/evaluations")).toBe(true);
    expect(isV2NavItemActive(hades, "/")).toBe(false);
    expect(isV2NavItemActive(hades, "/agents")).toBe(false);
  });

  it("does not claim Agents child ownership on /agents (LM owns it)", () => {
    expect(hades).toBeDefined();
    if (!hades) return;
    expect(findActiveV2Child(hades, "/agents")).toBeNull();
    expect(hades.children?.find((c) => c.id === "hades-agents")?.to).toBe("/agents");
    expect(hades.children?.find((c) => c.id === "hades-agents")?.match).toEqual([]);
  });

  it("auto-expands on /chat and marks Chat child active", () => {
    expect(hades).toBeDefined();
    if (!hades) return;
    expect(shouldAutoExpandV2Group(hades, "/chat")).toBe(true);
    expect(findActiveV2Child(hades, "/chat")?.id).toBe("chat");
    expect(findActiveV2Child(hades, "/cognition")?.label).toBe("Reasoning");
    expect(findActiveV2Child(hades, "/prompts")?.label).toBe("Prompts");
  });
});

describe("v2Nav research group", () => {
  it("is expandable and derives children from MAIN_MENU", () => {
    expect(research).toBeDefined();
    if (!research) return;
    expect(research.expandable).toBe(true);
    const fromMenu = v2ChildrenFromMainMenu("research");
    expect(research.children?.map((c) => c.to)).toEqual(fromMenu.map((c) => c.to));
    const main = MAIN_MENU.find((m) => m.id === "research");
    expect(main).toBeDefined();
    expect(research.children?.map((c) => c.to)).toEqual(main!.submenu.map((s) => s.to));
  });

  it("marks research group active on brain/memory/knowledge/evidence", () => {
    expect(research).toBeDefined();
    if (!research) return;
    expect(isV2NavItemActive(research, "/brain")).toBe(true);
    expect(isV2NavItemActive(research, "/memory")).toBe(true);
    expect(isV2NavItemActive(research, "/knowledge")).toBe(true);
    expect(isV2NavItemActive(research, "/evidence")).toBe(true);
    expect(isV2NavItemActive(research, "/research")).toBe(true);
    expect(isV2NavItemActive(research, "/")).toBe(false);
  });

  it("auto-expands on /brain and marks Brain child active", () => {
    expect(research).toBeDefined();
    if (!research) return;
    expect(shouldAutoExpandV2Group(research, "/brain")).toBe(true);
    expect(findActiveV2Child(research, "/brain")?.id).toBe("brain");
    expect(findActiveV2Child(research, "/memory")?.id).toBe("geheugen");
    expect(findActiveV2Child(research, "/knowledge")?.label).toBe("Knowledge Library");
  });

  it("does not duplicate dashboard children into research", () => {
    expect(research?.children?.some((c) => c.to === "/chat")).toBe(false);
  });
});

describe("v2Nav LM group", () => {
  it("is expandable and derives children from MAIN_MENU('llm')", () => {
    expect(lm).toBeDefined();
    if (!lm) return;
    expect(lm.expandable).toBe(true);
    const fromMenu = v2ChildrenFromMainMenu("llm");
    expect(lm.children?.map((c) => c.to)).toEqual(fromMenu.map((c) => c.to));
    const main = MAIN_MENU.find((m) => m.id === "llm");
    expect(main).toBeDefined();
    expect(lm.children?.map((c) => c.to)).toEqual(main!.submenu.map((s) => s.to));
    expect(lm.children?.map((c) => c.label)).toContain("Modellen");
    expect(lm.children?.map((c) => c.label)).toContain("Agents");
  });

  it("marks LM active on /models and /agents — MAIN_MENU owns Agents under LLM", () => {
    expect(lm).toBeDefined();
    if (!lm) return;
    expect(isV2NavItemActive(lm, "/models")).toBe(true);
    expect(isV2NavItemActive(lm, "/agents")).toBe(true);
    expect(isV2NavItemActive(lm, "/training")).toBe(false);
    expect(isV2NavItemActive(lm, "/dataset-management")).toBe(false);
    expect(isV2NavItemActive(lm, "/offline-datasets")).toBe(false);
    expect(isV2NavItemActive(lm, "/analytics")).toBe(false);
  });

  it("shouldAutoExpandV2Group expands LM on /models and /agents", () => {
    expect(lm).toBeDefined();
    if (!lm) return;
    expect(shouldAutoExpandV2Group(lm, "/models")).toBe(true);
    expect(shouldAutoExpandV2Group(lm, "/agents")).toBe(true);
    expect(shouldAutoExpandV2Group(lm, "/training")).toBe(false);
    expect(shouldAutoExpandV2Group(lm, "/dataset-management")).toBe(false);
  });

  it("findActiveV2Child marks Modellen on /models and Agents on /agents", () => {
    expect(lm).toBeDefined();
    if (!lm) return;
    expect(findActiveV2Child(lm, "/models")?.label).toBe("Modellen");
    expect(findActiveV2Child(lm, "/agents")?.label).toBe("Agents");
  });

  it("does not keep a standalone top-level Agents rail owner", () => {
    expect(V2_PRIMARY_NAV.some((item) => item.id === "agents" && !item.expandable)).toBe(false);
    expect(V2_PRIMARY_NAV.find((item) => item.id === "agents")).toBeUndefined();
  });
});
