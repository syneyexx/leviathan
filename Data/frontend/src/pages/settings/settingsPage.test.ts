import { describe, expect, it } from "vitest";
import { findMainMenuByPath, findSubMenuItem, MAIN_MENU } from "../../navigation/menu";

describe("settings navigation", () => {
  it("keeps settings under one /settings page with section query links", () => {
    const section = findMainMenuByPath("/settings");
    expect(section.id).toBe("settings");
    expect(section.submenu.every((item) => item.to.startsWith("/settings"))).toBe(true);
    expect(section.submenu.some((item) => item.to.includes("?"))).toBe(true);
    expect(section.submenu.every((item) => !item.to.startsWith("/settings/"))).toBe(true);
  });

  it("highlights settings section from query string", () => {
    const section = findMainMenuByPath("/settings");
    expect(findSubMenuItem(section, "/settings", "?section=knowledge_rag")?.id).toBe("knowledge-rag");
    expect(findSubMenuItem(section, "/settings", "?section=tools_mcp")?.id).toBe("tools-mcp");
  });

  it("does not invent duplicate editable settings routes as separate pages", () => {
    const settings = MAIN_MENU.find((item) => item.id === "settings");
    expect(settings).toBeTruthy();
    const paths = new Set(settings!.submenu.map((item) => item.to.split("?")[0]));
    expect(paths.size).toBe(1);
    expect(paths.has("/settings")).toBe(true);
  });
});
