import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { findMainMenuByPath, findSubMenuItem, MAIN_MENU } from "../../navigation/menu";

const settingsPageSrc = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "SettingsPage.tsx"),
  "utf8",
);

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

describe("behavior hot-apply settings UX", () => {
  it("states next turn is updated without forcing a new chat or reload", () => {
    expect(settingsPageSrc).toContain("Applied — active from next turn");
    expect(settingsPageSrc).not.toMatch(/open a new chat/i);
    expect(settingsPageSrc).not.toMatch(/window\.location\.reload/);
    expect(settingsPageSrc).not.toMatch(/navigate\(\s*[\"']\/chat/);
    // Save path updates local draft from API effective profile; backend remains authority.
    expect(settingsPageSrc).toContain("patchBehaviorProfile");
    expect(settingsPageSrc).toContain("getBehaviorProfile");
  });
});

describe("settings LLM behavior textareas", () => {
  const pagesCss = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "../../styles/pages.css"),
    "utf8",
  );

  it("uses multiline textarea classes instead of compact lv-input height alone", () => {
    expect(settingsPageSrc).toMatch(/className="lv-input lv-textarea lv-textarea--identity"/);
    expect(settingsPageSrc).toMatch(/className="lv-input lv-textarea lv-textarea--system-prompt"/);
    expect(settingsPageSrc).toMatch(/Identity description[\s\S]*rows=\{6\}/);
    expect(settingsPageSrc).toMatch(/System Prompt[\s\S]*rows=\{12\}/);
  });

  it("defines textarea overrides so 34px input height does not clip multiline fields", () => {
    expect(pagesCss).toMatch(/\.lv-field,\s*\n\.lv-select,\s*\n\.lv-input \{[\s\S]*?height:\s*34px/);
    expect(pagesCss).toMatch(/textarea\.lv-input,\s*\n\.lv-textarea \{/);
    expect(pagesCss).toMatch(/\.lv-textarea--identity \{[\s\S]*?min-height:\s*6\.5rem/);
    expect(pagesCss).toMatch(/\.lv-textarea--system-prompt \{[\s\S]*?min-height:\s*12\.5rem/);
    expect(pagesCss).toContain("resize: vertical");
    // Compact controls keep fixed height; textareas explicitly unset it.
    const textareaBlock = pagesCss.slice(pagesCss.indexOf("textarea.lv-input"));
    expect(textareaBlock).toContain("height: auto");
    expect(textareaBlock).not.toMatch(/textarea\.lv-input[\s\S]{0,200}height:\s*34px/);
  });
});
