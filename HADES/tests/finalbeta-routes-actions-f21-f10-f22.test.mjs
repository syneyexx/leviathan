/**
 * T9/F-21+F-10+F-22: FINALBETA route table and live action wiring contracts.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel) => readFileSync(join(root, rel), "utf8");

describe("T9 FINALBETA route + action honesty", () => {
  it("uses a single #/fb/ hash schema with explicit Lux redirects", () => {
    const routes = read("components/hades/finalbeta/routes.ts");
    assert.match(routes, /luxHashToFinalBetaRedirect/);
    assert.match(routes, /Single hash schema for FINALBETA/);
    // Bare Lux pages are no longer accepted inside readFinalBetaPageFromHash.
    assert.doesNotMatch(
      routes,
      /else if \(parts\[0\] && isFinalBetaPageId\(parts\[0\]\)\) page = parts\[0\]/,
    );
    const app = read("components/hades/finalbeta/finalbeta-app.tsx");
    assert.match(app, /luxHashToFinalBetaRedirect/);
  });

  it("does not export unmounted MissionControl/System pages", () => {
    const index = read("components/hades/finalbeta/pages/index.ts");
    assert.doesNotMatch(index, /MissionControlPage/);
    assert.doesNotMatch(index, /SystemPage/);
  });

  it("wires workflow create to the Gen2 template API (no data-toast)", () => {
    const page = read("components/hades/finalbeta/pages/workflows-page.tsx");
    assert.match(page, /createFromFirstTemplate|createFromTemplate/);
    assert.doesNotMatch(page, /data-toast="Nieuwe workflow via API\/templates"/);
    const hook = read("components/hades/features/workflows/hooks/useHadesWorkflows.ts");
    assert.match(hook, /createFromTemplate/);
  });

  it("wires knowledge inspector actions instead of toast-only", () => {
    const page = read("components/hades/finalbeta/pages/knowledge-page.tsx");
    assert.match(page, /runKnowledgeAction/);
    assert.doesNotMatch(
      page,
      /KNOWLEDGE_ACTIONS\.map\(\(action\) => \(\s*<button[\s\S]*?data-toast=\{action\.label\}/,
    );
  });

  it("implements settings pageId/initialTab scrolling", () => {
    const page = read("components/hades/finalbeta/pages/finalbeta-settings-page.tsx");
    assert.doesNotMatch(page, /void initialTab/);
    assert.match(page, /set-section-general/);
    assert.match(page, /scrollIntoView/);
  });

  it("gives performance tabs real content branches", () => {
    const page = read("components/hades/finalbeta/pages/performance-page.tsx");
    assert.match(page, /tab === "logs"/);
    assert.match(page, /tab === "modellen"/);
    assert.match(page, /role="tabpanel"/);
  });
});
