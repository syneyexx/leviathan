import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(join(here, relative), "utf8");

describe("LEVIATHAN ritual operator theme", () => {
  it("loads the ritual design system after the existing page styles", () => {
    const main = read("main.tsx");
    const themeIndex = main.indexOf('import "./styles/ritual-theme.css"');
    const pagesIndex = main.indexOf('import "./styles/ritual-pages.css"');
    const specialIndex = main.indexOf('import "./styles/ritual-special.css"');
    const polishIndex = main.indexOf('import "./styles/ritual-polish.css"');
    const legacyIndex = main.indexOf('import "./styles/datasets-dashboard.css"');

    expect(themeIndex).toBeGreaterThan(legacyIndex);
    expect(pagesIndex).toBeGreaterThan(themeIndex);
    expect(specialIndex).toBeGreaterThan(pagesIndex);
    expect(polishIndex).toBeGreaterThan(specialIndex);
  });

  it("applies the ritual shell and route section class through the shared AppShell", () => {
    const shell = read("layouts/AppShell.tsx");
    expect(shell).toContain('"lv-ritual-shell"');
    expect(shell).toContain("`lv-section-${section.id}`");
    expect(shell).toContain("data-lv-route={location.pathname}");
  });

  it("keeps every primary operator route represented", () => {
    const app = read("App.tsx");
    const routes = [
      "/",
      "/status",
      "/tasks",
      "/chat",
      "/coding",
      "/models",
      "/training",
      "/dataset-management",
      "/offline-datasets",
      "/agents",
      "/analytics",
      "/media",
      "/media/youtube",
      "/media/tiktok",
      "/media/instagram",
      "/media/facebook",
      "/media/queue",
      "/media/viral",
      "/media/calendar",
      "/media/analytics",
      "/media/library",
      "/media/personas",
      "/trading",
      "/trading/simulatie",
      "/trading/strategieen",
      "/trading/marktdata",
      "/trading/portefeuille",
      "/trading/paper",
      "/trading/broker",
      "/trading/onderzoek",
      "/trading/lab",
      "/trading/control-room",
      "/research",
      "/brain",
      "/cognition",
      "/memory",
      "/knowledge",
      "/evidence",
      "/datasets",
      "/performance",
      "/tools",
      "/modules",
      "/mcp",
      "/workflows",
      "/console",
      "/settings",
      "/chat.html",
    ];

    for (const route of routes) expect(app).toContain(`path="${route}"`);
  });

  it("keeps System Status as a real page rather than redirecting it to Tasks", () => {
    const app = read("App.tsx");
    const menu = read("navigation/menu.ts");
    expect(app).toContain('import { StatusPage } from "./pages/StatusPage"');
    expect(app).toContain('<Route path="/status" element={<StatusPage />} />');
    expect(app).not.toContain('<Route path="/status" element={<Navigate to="/tasks" replace />} />');
    expect(menu).toContain('{ id: "status", label: "System Status", to: "/status" }');
  });

  it("exposes Cognition in the knowledge navigation instead of leaving it orphaned", () => {
    const menu = read("navigation/menu.ts");
    expect(menu).toContain('{ id: "cognition", label: "Cognition", to: "/cognition" }');
    expect(menu).toContain('"/cognition"');
  });

  it("ships the ritual artwork as local application assets", () => {
    const publicDir = join(here, "../public/assets");
    expect(existsSync(join(publicDir, "leviathan-ritual-skyline.svg"))).toBe(true);
    expect(existsSync(join(publicDir, "leviathan-ritual-seal.svg"))).toBe(true);
    expect(existsSync(join(publicDir, "leviathan-ritual-manuscript.svg"))).toBe(true);
  });
});
