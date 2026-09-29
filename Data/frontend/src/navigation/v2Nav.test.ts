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

describe("v2Nav dashboard group", () => {
  it("marks dashboard group active on /, /chat, and /tasks", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(isV2NavItemActive(dashboard, "/")).toBe(true);
    expect(isV2NavItemActive(dashboard, "/chat")).toBe(true);
    expect(isV2NavItemActive(dashboard, "/tasks")).toBe(true);
    expect(isV2NavItemActive(dashboard, "/agents")).toBe(false);
  });

  it("findActiveV2Child resolves home, chat, and tasks", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(findActiveV2Child(dashboard, "/")?.id).toBe("dashboard-home");
    expect(findActiveV2Child(dashboard, "/chat")?.id).toBe("chat");
    expect(findActiveV2Child(dashboard, "/tasks")?.id).toBe("taken");
    expect(findActiveV2Child(dashboard, "/tasks/123")?.id).toBe("taken");
  });

  it("shouldAutoExpandV2Group expands dashboard on its match prefixes", () => {
    expect(dashboard).toBeDefined();
    if (!dashboard) return;
    expect(shouldAutoExpandV2Group(dashboard, "/")).toBe(true);
    expect(shouldAutoExpandV2Group(dashboard, "/chat")).toBe(true);
    expect(shouldAutoExpandV2Group(dashboard, "/tasks")).toBe(true);
    expect(shouldAutoExpandV2Group(dashboard, "/research")).toBe(false);
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
