import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA Training page wires pixel mock via FinalBetaShell", async () => {
  const page = await read("components/hades/finalbeta/pages/model-training-page.tsx");
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/training-pixel.css");
  const index = await read("components/hades/styles/finalbeta/index.css");
  const mocks = await read("components/hades/finalbeta/mocks/training-pixel.ts");

  assert.match(page, /"use client"/);
  assert.match(page, /FinalBetaShell/);
  assert.match(page, /page="model-training"/);
  assert.match(page, /trn-app/);
  assert.match(page, /trn-main/);
  assert.match(page, /trn-page/);
  assert.match(page, /MODEL TRAINING|Model Training/i);
  assert.match(page, /from ["']\.\.\/mocks\/training-pixel["']/);
  assert.doesNotMatch(page, /FinalBetaPageRender/);
  assert.doesNotMatch(page, /TrainingTabOverzicht/);

  assert.match(app, /page === "model-training"/);
  assert.match(app, /ModelTrainingPage onNavigate=\{navigate\}/);
  assert.doesNotMatch(app, /"model-training": ModelTrainingPage/);

  assert.match(css, /\.fb-root \.trn-page/);
  assert.match(css, /\.fb-root \.trn-app/);
  assert.match(index, /@import "\.\/v2\/training-pixel\.css"/);

  assert.match(mocks, /Llama 3\.1/);
  assert.match(mocks, /Actieve Runs|ACTIEVE RUNS/i);
});
