import { describe, expect, it } from "vitest";
import {
  allSubMenuRoutes,
  findMainMenuByPath,
  findSubMenuItem,
  isMainMenuActive,
  MAIN_MENU,
} from "./menu";

describe("navigation menu", () => {
  it("maps dashboard and chat under Hades AI", () => {
    expect(findMainMenuByPath("/").id).toBe("hades");
    expect(findMainMenuByPath("/chat").id).toBe("hades");
    expect(findMainMenuByPath("/tasks").id).toBe("hades");
    expect(findMainMenuByPath("/coding").id).toBe("hades");
  });

  it("maps models/training/agents/analytics under LLM", () => {
    expect(findMainMenuByPath("/models").id).toBe("llm");
    expect(findMainMenuByPath("/training").id).toBe("llm");
    expect(findMainMenuByPath("/agents").id).toBe("llm");
    expect(findMainMenuByPath("/analytics").id).toBe("llm");
    expect(findMainMenuByPath("/agents").submenu.some((item) => item.id === "agents")).toBe(true);
  });

  it("labels Coding Agent under Hades and Workflows under Plugin & Runtime", () => {
    const hades = findMainMenuByPath("/coding");
    expect(hades.submenu.find((item) => item.id === "coding")?.label).toBe("Coding Agent");
    const runtime = findMainMenuByPath("/workflows");
    expect(runtime.id).toBe("runtime");
    expect(runtime.submenu.some((item) => item.id === "workflows" && item.to === "/workflows")).toBe(true);
  });

  it("restores Brain under Onderzoek & Kennis", () => {
    const section = findMainMenuByPath("/brain");
    expect(section.id).toBe("research");
    expect(section.submenu.some((item) => item.id === "brain" && item.to === "/brain")).toBe(true);
  });

  it("renames plugins entry to Modules under Plugin & Runtime", () => {
    const section = findMainMenuByPath("/tools");
    expect(section.id).toBe("runtime");
    const modules = section.submenu.find((item) => item.id === "modules");
    expect(modules?.label).toBe("Modules");
    expect(modules?.to).toBe("/tools");
  });

  it("marks hoofdmenu active only for the owning section", () => {
    const llm = findMainMenuByPath("/models");
    expect(isMainMenuActive(llm, "/models")).toBe(true);
    expect(isMainMenuActive(llm, "/chat")).toBe(false);
  });

  it("resolves nested media and trading submenu routes", () => {
    const media = findMainMenuByPath("/media/youtube");
    expect(media.id).toBe("media");
    expect(findSubMenuItem(media, "/media")?.id).toBe("overzicht");
    expect(findSubMenuItem(media, "/media/youtube")?.id).toBe("youtube");
    expect(findSubMenuItem(media, "/media/queue")?.id).toBe("queue");
    expect(findSubMenuItem(media, "/media/viral")?.label).toBe("Viral Radar");
    expect(findSubMenuItem(media, "/media/calendar")?.label).toBe("Calendar");
    expect(findSubMenuItem(media, "/media/library")?.label).toBe("Bibliotheek");
    expect(findSubMenuItem(media, "/media/personas")?.label).toBe("Personas");
    expect(findMainMenuByPath("/trading/simulatie").id).toBe("trading");
    expect(findSubMenuItem(findMainMenuByPath("/trading/paper"), "/trading/paper")?.id).toBe("paper");
    expect(findMainMenuByPath("/evidence").id).toBe("research");
    expect(findSubMenuItem(findMainMenuByPath("/evidence"), "/evidence")?.label).toBe("Evidence Vault");
  });

  it("leaves dashboard submenu inactive on Hades landing", () => {
    const hades = findMainMenuByPath("/");
    expect(findSubMenuItem(hades, "/")).toBeNull();
  });

  it("gives every submenu item a dedicated route", () => {
    const routes = allSubMenuRoutes();
    expect(routes.length).toBeGreaterThan(30);
    expect(routes.every((item) => Boolean(item.to))).toBe(true);
    expect(MAIN_MENU.every((section) => section.submenu.length > 0)).toBe(true);
  });
});
