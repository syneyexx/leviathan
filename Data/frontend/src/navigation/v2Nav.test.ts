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
const llm = V2_PRIMARY_NAV.find((item) => item.id === "llm");
const media = V2_PRIMARY_NAV.find((item) => item.id === "media");
const trading = V2_PRIMARY_NAV.find((item) => item.id === "trading");
const research = V2_PRIMARY_NAV.find((item) => item.id === "research");
const runtime = V2_PRIMARY_NAV.find((item) => item.id === "runtime");
const settings = V2_PRIMARY_NAV.find((item) => item.id === "settings");

describe("v2Nav primary rail contract", () => {
  it("exposes exactly the canonical left-nav groups in order", () => {
    expect(V2_PRIMARY_NAV.map((item) => item.label)).toEqual([
      "Dashboard",
      "LLM",
      "Media Control",
      "Trading Center",
      "Onderzoek & Kennis",
      "Runtime & Tools",
      "Instellingen",
    ]);
  });

  it("derives expandable children from MAIN_MENU and keeps Instellingen flat", () => {
    for (const id of ["dashboard", "llm", "media", "trading", "research", "runtime"] as const) {
      const nav = V2_PRIMARY_NAV.find((item) => item.id === id);
      const main = MAIN_MENU.find((item) => item.id === id);
      expect(nav?.expandable).toBe(true);
      expect(nav?.children?.map((c) => c.label)).toEqual(main?.submenu.map((s) => s.label));
      expect(nav?.children?.map((c) => c.to)).toEqual(main?.submenu.map((s) => s.to));
    }
    expect(settings?.expandable).toBeFalsy();
    expect(settings?.children).toBeUndefined();
    expect(settings?.to).toBe("/settings");
  });
});

describe("v2Nav dashboard group", () => {
  it("marks dashboard group active on /, /chat and /tasks", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(isV2NavItemActive(dashboard, "/")).toBe(true);
    expect(isV2NavItemActive(dashboard, "/tasks")).toBe(true);
    expect(isV2NavItemActive(dashboard, "/chat")).toBe(true);
    expect(isV2NavItemActive(dashboard, "/agents")).toBe(false);
  });

  it("findActiveV2Child resolves home, chat and tasks", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(findActiveV2Child(dashboard, "/")?.id).toBe("dashboard-home");
    expect(findActiveV2Child(dashboard, "/chat")?.id).toBe("chat");
    expect(findActiveV2Child(dashboard, "/tasks")?.id).toBe("taken");
    expect(findActiveV2Child(dashboard, "/tasks/123")?.id).toBe("taken");
    expect(findActiveV2Child(dashboard, "/agents")).toBeNull();
  });

  it("shouldAutoExpandV2Group expands dashboard on its match prefixes", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(shouldAutoExpandV2Group(dashboard, "/")).toBe(true);
    expect(shouldAutoExpandV2Group(dashboard, "/tasks")).toBe(true);
    expect(shouldAutoExpandV2Group(dashboard, "/chat")).toBe(true);
    expect(shouldAutoExpandV2Group(dashboard, "/research")).toBe(false);
  });
});

describe("v2Nav LLM group", () => {
  it("is expandable and derives children from MAIN_MENU('llm')", () => {
    expect(llm).toBeDefined();
    if (!llm) return;
    expect(llm.expandable).toBe(true);
    const fromMenu = v2ChildrenFromMainMenu("llm");
    expect(llm.children?.map((c) => c.to)).toEqual(fromMenu.map((c) => c.to));
    expect(llm.children?.map((c) => c.label)).toEqual([
      "Modellen",
      "Agents",
      "Training",
      "Dataset Manager",
      "Offline Datasets",
      "Statistieken",
    ]);
  });

  it("marks LLM active on all LLM child routes", () => {
    expect(llm).toBeDefined();
    if (!llm) return;
    expect(isV2NavItemActive(llm, "/models")).toBe(true);
    expect(isV2NavItemActive(llm, "/agents")).toBe(true);
    expect(isV2NavItemActive(llm, "/training")).toBe(true);
    expect(isV2NavItemActive(llm, "/dataset-management")).toBe(true);
    expect(isV2NavItemActive(llm, "/offline-datasets")).toBe(true);
    expect(isV2NavItemActive(llm, "/analytics")).toBe(true);
    expect(isV2NavItemActive(llm, "/")).toBe(false);
  });

  it("auto-expands LLM on child routes and marks Modellen active on /models", () => {
    expect(llm).toBeDefined();
    if (!llm) return;
    expect(shouldAutoExpandV2Group(llm, "/models")).toBe(true);
    expect(shouldAutoExpandV2Group(llm, "/agents")).toBe(true);
    expect(shouldAutoExpandV2Group(llm, "/training")).toBe(true);
    expect(findActiveV2Child(llm, "/models")?.label).toBe("Modellen");
    expect(findActiveV2Child(llm, "/agents")?.label).toBe("Agents");
  });
});

describe("v2Nav media / trading / runtime groups", () => {
  it("keeps Media Control children and expands on /media routes", () => {
    expect(media).toBeDefined();
    if (!media) return;
    expect(media.children?.map((c) => c.label)).toEqual([
      "Overzicht",
      "Bibliotheek",
      "Genereren",
      "Bewerken",
      "Planning",
      "Distributie",
    ]);
    expect(shouldAutoExpandV2Group(media, "/media/library")).toBe(true);
    expect(findActiveV2Child(media, "/media/library")?.label).toBe("Bibliotheek");
    expect(shouldAutoExpandV2Group(media, "/media/youtube")).toBe(true);
  });

  it("keeps Trading Center children including Markt Simulatie", () => {
    expect(trading).toBeDefined();
    if (!trading) return;
    expect(trading.children?.map((c) => c.label)).toEqual([
      "Command Hub",
      "Strategy Lab",
      "Trading Desk",
      "Market Data",
    ]);
    expect(shouldAutoExpandV2Group(trading, "/trading/trading-desk")).toBe(true);
    expect(shouldAutoExpandV2Group(trading, "/trading/paper")).toBe(true);
  });

  it("keeps Runtime & Tools children starting with Performance", () => {
    expect(runtime).toBeDefined();
    if (!runtime) return;
    expect(runtime.children?.map((c) => c.label)).toEqual([
      "Performance",
      "Tools",
      "Modules",
      "Skills",
      "MCP",
      "Workflows",
      "Console",
    ]);
    expect(shouldAutoExpandV2Group(runtime, "/performance")).toBe(true);
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
