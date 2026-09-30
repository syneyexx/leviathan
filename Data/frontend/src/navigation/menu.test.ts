import { describe, expect, it } from "vitest";
import {
  allSubMenuRoutes,
  findMainMenuByPath,
  findSubMenuItem,
  isMainMenuActive,
  MAIN_MENU,
} from "./menu";

describe("navigation menu", () => {
  it("exposes exactly the canonical left-nav hoofdmenu labels", () => {
    expect(MAIN_MENU.map((item) => item.label)).toEqual([
      "Dashboard",
      "LLM",
      "Media Control",
      "Trading Center",
      "Onderzoek & Kennis",
      "Runtime & Tools",
      "Instellingen",
    ]);
  });

  it("maps dashboard, chat and tasks under Dashboard", () => {
    expect(findMainMenuByPath("/").id).toBe("dashboard");
    expect(findMainMenuByPath("/chat").id).toBe("dashboard");
    expect(findMainMenuByPath("/tasks").id).toBe("dashboard");
    const dashboard = findMainMenuByPath("/");
    expect(dashboard.submenu.map((item) => item.label)).toEqual([
      "Dashboard",
      "Chat",
      "Taken",
    ]);
  });

  it("maps models/training/agents/analytics/dataset pages under LLM", () => {
    expect(findMainMenuByPath("/models").id).toBe("llm");
    expect(findMainMenuByPath("/training").id).toBe("llm");
    expect(findMainMenuByPath("/agents").id).toBe("llm");
    expect(findMainMenuByPath("/analytics").id).toBe("llm");
    expect(findMainMenuByPath("/dataset-management").id).toBe("llm");
    expect(findMainMenuByPath("/offline-datasets").id).toBe("llm");
    const llm = findMainMenuByPath("/models");
    expect(llm.submenu.map((item) => item.label)).toEqual([
      "Modellen",
      "Agents",
      "Training",
      "Dataset Manager",
      "Offline Datasets",
      "Statistieken",
    ]);
  });

  it("labels Workflows under Runtime & Tools", () => {
    const runtime = findMainMenuByPath("/workflows");
    expect(runtime.id).toBe("runtime");
    expect(runtime.label).toBe("Runtime & Tools");
    expect(runtime.submenu.some((item) => item.id === "workflows" && item.to === "/workflows")).toBe(true);
  });

  it("restores Brain under Onderzoek & Kennis and keeps Datasets", () => {
    const section = findMainMenuByPath("/brain");
    expect(section.id).toBe("research");
    expect(section.submenu.some((item) => item.id === "brain" && item.to === "/brain")).toBe(true);
    expect(section.submenu.some((item) => item.id === "datasets" && item.label === "Datasets")).toBe(true);
    expect(section.submenu.some((item) => item.label === "Bestanden")).toBe(false);
    expect(findMainMenuByPath("/datasets").id).toBe("research");
    expect(findMainMenuByPath("/knowledge").id).toBe("research");
  });

  it("labels Datasets under Onderzoek & Kennis", () => {
    const section = findMainMenuByPath("/datasets");
    expect(section.id).toBe("research");
    const datasets = section.submenu.find((item) => item.to === "/datasets");
    expect(datasets?.id).toBe("datasets");
    expect(datasets?.label).toBe("Datasets");
    expect(section.submenu.some((item) => item.label === "Bestanden")).toBe(false);
    expect(section.submenu.some((item) => item.id === "geheugen" && item.label === "Geheugen")).toBe(true);
    expect(section.submenu.some((item) => item.id === "knowledge" && item.label === "Knowledge Library")).toBe(
      true,
    );
  });

  it("splits Tools and Modules under Runtime & Tools", () => {
    const section = findMainMenuByPath("/tools");
    expect(section.id).toBe("runtime");
    const tools = section.submenu.find((item) => item.id === "tools");
    expect(tools?.label).toBe("Tools");
    expect(tools?.to).toBe("/tools");
    const modules = section.submenu.find((item) => item.id === "modules");
    expect(modules?.label).toBe("Modules");
    expect(modules?.to).toBe("/modules");
    expect(findMainMenuByPath("/modules").id).toBe("runtime");
    expect(section.submenu.map((item) => item.label)).toEqual([
      "Performance",
      "Tools",
      "Modules",
      "Skills",
      "MCP",
      "Workflows",
      "Console",
    ]);
    const skills = section.submenu.find((item) => item.id === "skills");
    expect(skills?.to).toBe("/skills");
    expect(findMainMenuByPath("/skills").id).toBe("runtime");
  });

  it("marks hoofdmenu active only for the owning section", () => {
    const llm = findMainMenuByPath("/models");
    expect(isMainMenuActive(llm, "/models")).toBe(true);
    expect(isMainMenuActive(llm, "/chat")).toBe(false);
  });

  it("resolves nested media and trading submenu routes", () => {
    const media = findMainMenuByPath("/media/library");
    expect(media.id).toBe("media");
    expect(findSubMenuItem(media, "/media")?.id).toBe("overzicht");
    expect(findSubMenuItem(media, "/media/library")?.id).toBe("library");
    expect(findSubMenuItem(media, "/media/library")?.label).toBe("Bibliotheek");
    expect(findSubMenuItem(media, "/media/genereren")?.label).toBe("Genereren");
    expect(findSubMenuItem(media, "/media/bewerken")?.label).toBe("Bewerken");
    expect(findSubMenuItem(media, "/media/planning")?.label).toBe("Planning");
    expect(findSubMenuItem(media, "/media/distributie")?.label).toBe("Distributie");
    // Deep platform routes remain under Media Control even when not in primary submenu.
    expect(findMainMenuByPath("/media/youtube").id).toBe("media");
    expect(findMainMenuByPath("/trading/command-hub").id).toBe("trading");
    expect(findMainMenuByPath("/trading/command-hub").label).toBe("Trading Center");
    expect(findSubMenuItem(findMainMenuByPath("/trading/command-hub"), "/trading/command-hub")?.label).toBe(
      "Command Hub",
    );
    expect(findSubMenuItem(findMainMenuByPath("/trading/trading-desk"), "/trading/trading-desk")?.id).toBe(
      "trading-desk",
    );
    expect(findSubMenuItem(findMainMenuByPath("/trading/strategy-lab"), "/trading/strategy-lab")?.label).toBe(
      "Strategy Lab",
    );
    expect(findSubMenuItem(findMainMenuByPath("/trading/market-data"), "/trading/market-data")?.label).toBe(
      "Market Data",
    );
    // Legacy paths still belong to Trading Center section via /trading prefix match.
    expect(findMainMenuByPath("/trading/paper").id).toBe("trading");
    expect(findMainMenuByPath("/trading/simulatie").id).toBe("trading");
    expect(findMainMenuByPath("/evidence").id).toBe("research");
    expect(findSubMenuItem(findMainMenuByPath("/evidence"), "/evidence")?.label).toBe("Evidence Vault");
  });

  it("highlights Dashboard submenu home on /", () => {
    const dashboard = findMainMenuByPath("/");
    expect(findSubMenuItem(dashboard, "/")?.id).toBe("dashboard-home");
  });

  it("gives every submenu item a dedicated route", () => {
    const routes = allSubMenuRoutes();
    expect(routes.length).toBeGreaterThan(30);
    expect(routes.every((item) => Boolean(item.to))).toBe(true);
    expect(MAIN_MENU.every((section) => section.submenu.length > 0)).toBe(true);
  });
});
