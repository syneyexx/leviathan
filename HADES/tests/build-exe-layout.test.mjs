import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("PyInstaller build stays isolated and uses the pinned optional build toolchain", async () => {
  const [script, gitignore, requirements] = await Promise.all([
    read("BUILD_HADES_EXE.bat"),
    read(".gitignore"),
    read("tools/requirements-pyinstaller.txt"),
  ]);

  assert.match(script, /\.hades-cache\\pyinstaller-venv/);
  assert.match(script, /--distpath\s+"%PYI_DIST%"/);
  assert.match(script, /--workpath\s+"%PYI_WORK%"/);
  assert.match(script, /--specpath\s+"%PYI_SPEC%"/);
  assert.match(script, /"%BUILD_PYTHON%" -m pip install -r "tools\\requirements-pyinstaller\.txt"/);
  assert.doesNotMatch(
    script,
    /"backend\\\.venv\\Scripts\\python\.exe" -m pip install pyinstaller/,
    "optional EXE packaging must not mutate the backend runtime venv with build-only tooling",
  );
  assert.doesNotMatch(
    script,
    /-m pip install pyinstaller(?:\s|$)/,
    "PyInstaller must not float to an arbitrary newest release",
  );
  assert.doesNotMatch(
    script,
    /copy \/Y "dist\\HADES\.exe"/,
    "PyInstaller output must not depend on the repository-root dist directory",
  );

  assert.match(requirements, /^pyinstaller==6\.22\.2$/m);
  assert.match(requirements, /^pyinstaller-hooks-contrib==2026\.7$/m);
  assert.match(gitignore, /^\.hades-cache\/$/m);
  assert.match(gitignore, /^\/HADES\.exe$/m);
});
