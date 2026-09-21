import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("VERIFY_HADES wrapper cannot downgrade the canonical full release gate", async () => {
  const script = await read("VERIFY_HADES.bat");

  assert.match(script, /set "VERIFY_ARGS=%\*"/);
  for (const allowed of ["--host", "--lm-studio", "--browser", "--voice", "--sandbox", "--host-report"]) {
    assert.ok(script.includes(`"${allowed}"`), `missing allowed host-probe flag ${allowed}`);
  }

  assert.match(script, /Ongeldige VERIFY_HADES optie/);
  assert.match(script, /Deze wrapper voert altijd de volledige releasegate uit/);
  assert.match(script, /verify_hades\.py %VERIFY_ARGS%/);
  assert.doesNotMatch(
    script,
    /verify_hades\.py[^\r\n]*(--quick|--python-only|--host-only)/,
    "VERIFY_HADES must never invoke a release-skipping mode",
  );
  assert.match(script, /Alle deterministic HADES releasechecks zijn geslaagd/);
});
