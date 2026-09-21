import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("Windows native build uses Ninja only with an active MSVC environment", async () => {
  const script = await read("BUILD_HADES_NATIVE.bat");

  assert.match(script, /set "MSVC_ACTIVE=0"/);
  assert.match(script, /set "MSVC_ACTIVE=1"/);
  assert.match(script, /set "GENERATOR=Visual Studio 17 2022"/);
  assert.match(script, /set "ARCH_ARGS=-A x64"/);

  const activeBranch = script.indexOf('if "%MSVC_ACTIVE%"=="1" (');
  const ninjaProbe = script.indexOf("where ninja");
  const ninjaGenerator = script.indexOf('set "GENERATOR=Ninja"');
  assert.ok(activeBranch >= 0, "MSVC-active branch missing");
  assert.ok(ninjaProbe > activeBranch, "Ninja must only be probed after confirming an active MSVC environment");
  assert.ok(ninjaGenerator > ninjaProbe, "Ninja generator must only be selected after its executable is found");
  assert.match(script, /Using Visual Studio 17 2022 generator/);
});
