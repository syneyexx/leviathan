import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA dashboard live hooks wire to HADES APIs", async () => {
  const hook = await read("components/hades/finalbeta/hooks/use-dashboard-live.ts");
  const page = await read("components/hades/finalbeta/pages/dashboard-page.tsx");
  const native = await read("backend/native_routes.py");
  const py = await read("backend/infrastructure/native/python_live_metrics.py");

  assert.match(hook, /hadesApi\.health/);
  assert.match(hook, /hadesApi\.agents/);
  assert.match(hook, /hadesApi\.nativeMetrics/);
  assert.match(hook, /hadesTrainingApi\.hardware/);
  assert.match(page, /useDashboardLive/);
  assert.match(page, /Actieve chatmodel/);
  assert.match(page, /Actieve code model/);
  assert.match(page, /donutSegments/);
  assert.match(native, /collect_python_live_metrics/);
  assert.match(py, /def collect_python_live_metrics/);
});
