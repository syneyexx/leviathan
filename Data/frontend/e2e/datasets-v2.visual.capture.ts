/**
 * Local visual capture for Datasets V2 — playwright script (NOT GitHub CI).
 * Writes screenshot under /opt/cursor/artifacts/screenshots/
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { installDatasetsV2VisualFixture } from "./helpers/datasetsV2Visual";

async function main() {
  const out = resolve("/opt/cursor/artifacts/screenshots/datasets-v2-after.png");
  mkdirSync(dirname(out), { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1664, height: 1100 },
    deviceScaleFactor: 1,
  });
  await installDatasetsV2VisualFixture(page);
  await page.goto("http://127.0.0.1:5173/datasets", { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="datasets-inventory"]', { timeout: 15000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: out, fullPage: false });
  await page.screenshot({
    path: resolve("/opt/cursor/artifacts/screenshots/datasets-v2-full.png"),
    fullPage: true,
  });
  await browser.close();
  console.log(`wrote ${out}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
