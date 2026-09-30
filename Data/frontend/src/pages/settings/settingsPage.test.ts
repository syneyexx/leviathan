import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { findMainMenuByPath, findSubMenuItem, MAIN_MENU } from "../../navigation/menu";

const settingsPageSrc = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "SettingsPage.tsx"),
  "utf8",
);
const categoryContentSrc = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../../components/settings/SettingsCategoryContent.tsx"),
  "utf8",
);
const workspaceSrc = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../../hooks/useSettingsWorkspace.ts"),
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

describe("settings V2 shell", () => {
  it("opts into AppShell variant v2 without a page-local CSS file", () => {
    expect(settingsPageSrc).toContain('variant="v2"');
    expect(settingsPageSrc).toContain("lv-v2-page--settings");
    expect(settingsPageSrc).toContain("useSettingsWorkspace");
    expect(settingsPageSrc).not.toMatch(/import\s+["'].*settings-v2\.css/);
  });

  it("wires save/reset through Settings Control Plane APIs", () => {
    expect(workspaceSrc).toContain("patchSettings");
    expect(workspaceSrc).toContain("resetSettingsCategory");
    expect(workspaceSrc).toContain("getStartupRegistration");
    expect(workspaceSrc).toContain("listModelProviders");
  });
});

describe("behavior hot-apply settings UX", () => {
  it("states next turn is updated without forcing a new chat or reload", () => {
    expect(categoryContentSrc).toContain("Applied — active from next turn");
    expect(categoryContentSrc).not.toMatch(/open a new chat/i);
    expect(categoryContentSrc).not.toMatch(/window\.location\.reload/);
    expect(categoryContentSrc).not.toMatch(/navigate\(\s*[\"']\/chat/);
    expect(categoryContentSrc).toContain("patchBehaviorProfile");
    expect(categoryContentSrc).toContain("putBehaviorSystemPrompt");
  });
});

describe("settings LLM behavior textareas", () => {
  const pagesCss = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "../../styles/pages.css"),
    "utf8",
  );

  it("uses multiline textarea classes instead of compact lv-input height alone", () => {
    expect(categoryContentSrc).toMatch(/className="lv-v2-input lv-textarea lv-textarea--identity"/);
    expect(categoryContentSrc).toMatch(/className="lv-v2-input lv-textarea lv-textarea--system-prompt"/);
    expect(categoryContentSrc).toMatch(/Identity description[\s\S]*rows=\{6\}/);
    expect(categoryContentSrc).toMatch(/System Prompt[\s\S]*rows=\{12\}/);
  });

  it("defines textarea overrides so 34px input height does not clip multiline fields", () => {
    expect(pagesCss).toMatch(/\.lv-field,\s*\n\.lv-select,\s*\n\.lv-input \{[\s\S]*?height:\s*34px/);
    expect(pagesCss).toMatch(/textarea\.lv-input,\s*\n\.lv-textarea \{/);
    expect(pagesCss).toMatch(/\.lv-textarea--identity \{[\s\S]*?min-height:\s*6\.5rem/);
    expect(pagesCss).toMatch(/\.lv-textarea--system-prompt \{[\s\S]*?min-height:\s*12\.5rem/);
    expect(pagesCss).toContain("resize: vertical");
    const textareaBlock = pagesCss.slice(pagesCss.indexOf("textarea.lv-input"));
    expect(textareaBlock).toContain("height: auto");
    expect(textareaBlock).not.toMatch(/textarea\.lv-input[\s\S]{0,200}height:\s*34px/);
  });
});
