import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("PREPARE_HADES installs and verifies frontend dev dependencies", async () => {
  const prepare = await read("PREPARE_HADES.bat");
  assert.match(prepare, /npm ci --include=dev --no-audit --no-fund/);
  assert.match(prepare, /node_modules\\@vitejs\\plugin-react\\package\.json/);
  assert.match(prepare, /node_modules\\\.bin\\tsc\.cmd/);
});

test("BUILD_HADES_NATIVE pins install prefix during configure and avoids install-time --prefix quoting", async () => {
  const nativeBuild = await read("BUILD_HADES_NATIVE.bat");
  assert.match(nativeBuild, /CMAKE_INSTALL_PREFIX:PATH="%INSTALL_PREFIX%"/);
  assert.match(nativeBuild, /cmake --install "%BUILD_DIR%" --config Release/);
  assert.doesNotMatch(nativeBuild, /cmake --install[^\r\n]*--prefix/);
});
