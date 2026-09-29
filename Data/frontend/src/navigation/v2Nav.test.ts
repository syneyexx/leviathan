import { describe, expect, it } from "vitest";
import {
  allV2SubMenuRoutes,
  expectedPreservedLegacyRoutes,
  findActiveV2Child,
  findV2NavByPath,
  isV2NavItemActive,
  shouldAutoExpandV2Group,
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

describe("v2Nav brain / research group", () => {
  it("marks research group + Brain child active on /brain and auto-expands", () => {
    expect(research).toBeDefined();
    if (!research) return;
    expect(findV2NavByPath("/brain").id).toBe("research");
    expect(isV2NavItemActive(research, "/brain")).toBe(true);
    expect(findActiveV2Child(research, "/brain")?.id).toBe("brain");
    expect(findActiveV2Child(research, "/brain")?.to).toBe("/brain");
    expect(shouldAutoExpandV2Group(research, "/brain")).toBe(true);
  });
});

describe("v2Nav preserved legacy routes", () => {
  it("expectedPreservedLegacyRoutes includes coding, youtube, paper, and settings", () => {
    const preserved = expectedPreservedLegacyRoutes();
    expect(preserved).toContain("/coding");
    expect(preserved).toContain("/media/youtube");
    expect(preserved).toContain("/trading/paper");
    const settingsRoutes = preserved.filter(
      (route) => route === "/settings" || route.startsWith("/settings?"),
    );
    expect(settingsRoutes.length).toBeGreaterThan(0);
  });

  it("all preserved routes appear in some V2 child `to`", () => {
    const childTos = new Set(allV2SubMenuRoutes().map((child) => child.to));
    for (const route of expectedPreservedLegacyRoutes()) {
      expect(childTos.has(route)).toBe(true);
    }
  });
});
