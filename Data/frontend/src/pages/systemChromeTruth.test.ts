import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const roots = [
  "McpPage.tsx",
  "GeheugenPage.tsx",
  "WorkflowsPage.tsx",
  "EvidenceVaultPage.tsx",
].map((f) => resolve(__dirname, f));

describe("FRONTEND-006 system chrome honesty", () => {
  it("does not hardcode SYSTEMS ONLINE/OPERATIONAL as live truth", () => {
    for (const path of roots) {
      const src = readFileSync(path, "utf8");
      expect(src).not.toMatch(/SYSTEMS ONLINE/);
      expect(src).not.toMatch(/SYSTEMS OPERATIONAL/);
    }
  });
});
