import { describe, expect, it } from "vitest";
import {
  findMainMenuByPath,
  findSubMenuItem,
  isMainMenuActive,
  submenuHref,
} from "./menu";

describe("navigation menu", () => {
  it("maps dashboard and chat under Hades AI", () => {
    expect(findMainMenuByPath("/").id).toBe("hades");
    expect(findMainMenuByPath("/chat").id).toBe("hades");
    expect(findMainMenuByPath("/tasks").id).toBe("hades");
    expect(findMainMenuByPath("/coding").id).toBe("hades");
  });

  it("maps models/training/analytics under LLM", () => {
    expect(findMainMenuByPath("/models").id).toBe("llm");
    expect(findMainMenuByPath("/training").id).toBe("llm");
    expect(findMainMenuByPath("/analytics").id).toBe("llm");
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

  it("resolves submenu from path and tab query", () => {
    const media = findMainMenuByPath("/media");
    expect(findSubMenuItem(media, "/media", null)?.id).toBe("overzicht");
    expect(findSubMenuItem(media, "/media", "youtube")?.id).toBe("youtube");
    expect(submenuHref(media, media.submenu[1])).toBe("/media/youtube");
    expect(findMainMenuByPath("/media/youtube").id).toBe("media");
    expect(findMainMenuByPath("/agents").id).toBe("agents");
  });

  it("leaves dashboard submenu inactive on Hades landing", () => {
    const hades = findMainMenuByPath("/");
    expect(findSubMenuItem(hades, "/", null)).toBeNull();
  });
});
