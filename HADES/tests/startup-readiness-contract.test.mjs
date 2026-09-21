import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("Windows startup reports success only after shared HADES identity verification", async () => {
  const [oneClick, start, launcher, health] = await Promise.all([
    read("HADES.bat"),
    read("START_HADES.bat"),
    read("HADES_LAUNCHER.py"),
    read("tools/local_startup_health.py"),
  ]);

  assert.match(oneClick, /"backend\\\.venv\\Scripts\\python\.exe" "HADES_LAUNCHER\.py"/);
  assert.match(oneClick, /exit \/b %errorlevel%/);
  assert.doesNotMatch(
    oneClick,
    /start\s+"HADES Launcher"\s+\/b/i,
    "one-click launcher must not return success before HADES_LAUNCHER finishes readiness verification",
  );

  assert.ok(
    /npm run dev/.test(start) && /npm run start/.test(start) && /dist\\index\.html/.test(start),
    "START_HADES must support vite dev and production dist via npm run start",
  );
  assert.match(launcher, /frontend_shell_command/);
  assert.match(start, /tools\\local_startup_health\.py/);
  assert.match(start, /if errorlevel 1/);
  assert.ok(
    start.indexOf("tools\\local_startup_health.py") < start.indexOf("HADES draait lokaal"),
    "START_HADES must verify readiness before claiming success",
  );

  assert.match(launcher, /from tools\.local_startup_health import FRONTEND_URL, wait_for_local_hades/);
  assert.match(launcher, /if not wait_for_local_hades\(\):/);
  assert.match(launcher, /fail\(/);
  assert.doesNotMatch(
    launcher,
    /for _ in range\(60\):[\s\S]*webbrowser\.open\([^)]*\)\s*$/m,
    "launcher must not open the browser unconditionally after a readiness timeout",
  );

  assert.match(health, /BACKEND_LIVENESS_URL = "http:\/\/127\.0\.0\.1:8000\/openapi\.json"/);
  assert.match(health, /BACKEND_IDENTITY = "HADES Local Bridge"/);
  assert.match(health, /FRONTEND_IDENTITY = "HADES — Local AI Workspace"/);
  assert.doesNotMatch(
    health,
    /DEFAULT_TARGETS\s*=\s*\([^)]*api\/health/,
    "startup liveness must not depend on the provider-heavy /api/health route",
  );
  assert.match(health, /FRONTEND_URL = "http:\/\/127\.0\.0\.1:3000\/"/);
  assert.match(health, /return expected_text in rendered/);
});
