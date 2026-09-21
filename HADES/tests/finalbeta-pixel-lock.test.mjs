import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA pixel lock matches canonical 1672 header boundaries", async () => {
  const css = await read("components/hades/styles/finalbeta/pixel-lock.css");
  const index = await read("components/hades/styles/finalbeta/index.css");

  assert.match(index, /@import "\.\/pixel-lock\.css"/);
  assert.ok(index.indexOf("./pixel-lock.css") > index.indexOf("./contract.css"));
  assert.match(css, /--fb-ref-brand-width:\s*265px/);
  assert.match(css, /--fb-ref-topright-width:\s*261px/);
  assert.match(css, /--fb-ref-nav-hades-ai:\s*155px/);
  assert.match(css, /--fb-ref-nav-llm:\s*135px/);
  assert.match(css, /--fb-ref-nav-media:\s*145px/);
  assert.match(css, /--fb-ref-nav-trading:\s*150px/);
  assert.match(css, /--fb-ref-nav-research:\s*160px/);
  assert.match(css, /--fb-ref-nav-runtime:\s*175px/);
  assert.match(css, /--fb-ref-nav-settings:\s*145px/);
});

test("FINALBETA surfaces override Lux important bridge colors", async () => {
  const css = await read("components/hades/styles/finalbeta/pixel-lock.css");
  const lux = await read("components/hades/styles/lux/pages-bridge.css");

  assert.match(lux, /\.card,[\s\S]*background:\s*var\(--lux-panel\)\s*!important/);
  assert.match(css, /\.fb-root \.card,[\s\S]*#001723[\s\S]*!important/);
  assert.match(css, /\.fb-root \.dash-stat[\s\S]*#00121c[\s\S]*!important/);
  assert.match(css, /\.fb-root \.metric-card,[\s\S]*#011824[\s\S]*!important/);
});

test("FINALBETA header uses reference glyphs and a full-cell logo", async () => {
  const shell = await read("components/hades/finalbeta/shell/finalbeta-shell.tsx");
  const icons = await read("components/hades/finalbeta/topnav-icon.tsx");
  const logo = await read("components/hades/finalbeta/brand-logo.tsx");
  const css = await read("components/hades/styles/finalbeta/pixel-lock.css");

  assert.match(shell, /FinalBetaTopnavIcon/);
  assert.match(shell, /FinalBetaTopnavIcon name=\{item\.icon\} size=\{24\}/);
  assert.match(icons, /strokeWidth:\s*1\.7/);
  assert.match(logo, /width=\{265\}/);
  assert.match(logo, /height=\{77\}/);
  assert.match(css, /\.fb-root \.brand-logo[\s\S]*width:\s*100%[\s\S]*height:\s*100%/);
  assert.match(css, /object-fit:\s*fill/);
});

test("dashboard locks both canonical quotes and reference-specific iconography", async () => {
  const dashboard = await read("components/hades/finalbeta/pages/dashboard-page.tsx");
  const icons = await read("components/hades/finalbeta/dashboard-reference-icon.tsx");
  const css = await read("components/hades/styles/finalbeta/pixel-lock.css");

  assert.match(dashboard, /“Discipline creates freedom\.[\s\S]*Intelligence multiplies it\.”/);
  assert.match(dashboard, /“Sovereign AI\. Local power\.[\s\S]*Infinite possibilities\.”/);
  assert.match(dashboard, /DashboardReferenceIcon/);
  assert.match(dashboard, /icon="activity"/);
  assert.match(dashboard, /icon="results"/);
  assert.match(dashboard, /icon="performance"/);
  assert.match(dashboard, /icon="distribution"/);
  for (const name of ["dashboard", "chat", "coding", "mission", "tasks", "research", "media", "trading", "training", "agents", "plugins", "settings", "sun"]) {
    assert.ok(icons.includes(`${name}:`), `missing dashboard reference icon ${name}`);
  }
  assert.match(css, /\.fb-root \.dash-welcome-mid[\s\S]*text-align:\s*left/);
  assert.match(css, /\.fb-root \.dashboard-sovereign-quote[\s\S]*text-align:\s*left/);
});

test("dashboard final reference replay is loaded last and pins quote/icon details", async () => {
  const index = await read("components/hades/styles/finalbeta/index.css");
  const finalCss = await read("components/hades/styles/finalbeta/reference-final.css");
  const icons = await read("components/hades/finalbeta/dashboard-reference-icon.tsx");

  assert.match(index, /@import "\.\/reference-final\.css"/);
  assert.ok(index.indexOf("./reference-final.css") > index.indexOf("./pixel-lock.css"));
  assert.match(finalCss, /\.dash-welcome-mid[\s\S]*font-size:\s*14px[\s\S]*letter-spacing:\s*0\.045em/);
  assert.match(finalCss, /\.dashboard-sovereign-quote[\s\S]*font-size:\s*14px[\s\S]*letter-spacing:\s*0\.045em/);
  assert.match(finalCss, /grid-template-columns:\s*minmax\(0, 1fr\)\s+231px\s+151px/);
  assert.match(finalCss, /\.dash-stat-ico[\s\S]*width:\s*48px[\s\S]*height:\s*48px/);
  assert.match(icons, /status:[\s\S]*fill="currentColor"/);
  assert.match(icons, /gpu:[\s\S]*fill="currentColor"/);
  assert.match(icons, /strokeWidth="1\.7"/);
});
