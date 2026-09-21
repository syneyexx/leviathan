import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA evidence page is live claim vault with shell preserved", async () => {
  const page = await read("components/hades/finalbeta/pages/evidence-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/evidence.css");
  const hook = await read("components/hades/features/evidence/hooks/useHadesEvidence.ts");

  assert.match(page, /useHadesEvidence/);
  assert.match(page, /data-live="evidence"/);
  assert.match(page, /Evidence Vault/);
  assert.match(page, /Bewijsketen/);
  assert.match(page, /Claim details/);
  assert.doesNotMatch(page, /mockEvidenceClaims/);
  assert.doesNotMatch(page, /EVIDENCE_STATS/);
  assert.match(hook, /hadesApi\.claims/);
  assert.match(css, /\.fb-root \.evidence-page/);
});
