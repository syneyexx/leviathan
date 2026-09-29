import { describe, expect, it } from "vitest";
import {
  findActiveV2Child,
  isV2NavItemActive,
  shouldAutoExpandV2Group,
  V2_PRIMARY_NAV,
} from "./v2Nav";

const dashboard = V2_PRIMARY_NAV.find((item) => item.id === "dashboard");

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
