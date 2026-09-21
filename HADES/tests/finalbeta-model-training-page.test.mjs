import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA model training page wires interactive tabs via FinalBetaShell", async () => {
  const page = await read("components/hades/finalbeta/pages/model-training-page.tsx");
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/model-training.css");
  const index = await read("components/hades/styles/finalbeta/index.css");
  const mocks = await read("components/hades/finalbeta/mocks/model-training.ts");
  const barrel = await read("components/hades/finalbeta/pages/model-training/index.ts");

  assert.match(page, /"use client"/);
  assert.match(page, /FinalBetaShell/);
  assert.match(page, /useState/);
  assert.match(page, /TrainingTabOverzicht/);
  assert.match(page, /TrainingTabDatasets/);
  assert.match(page, /TrainingTabModel/);
  assert.match(page, /TrainingTabFramework/);
  assert.match(page, /TrainingTabRuns/);
  assert.match(page, /TRAINING_TABS/);
  assert.match(page, /page="model-training"/);
  assert.match(page, /training-page/);
  assert.doesNotMatch(page, /FinalBetaPageRender/);

  assert.match(app, /page === "model-training"/);
  assert.match(app, /ModelTrainingPage onNavigate=\{navigate\}/);
  assert.doesNotMatch(app, /"model-training": ModelTrainingPage/);

  assert.match(css, /\.fb-root \.training-page/);
  assert.match(css, /\.fb-root \.training-stat-row/);
  assert.match(css, /\.fb-root \.training-neural/);
  assert.match(css, /\.fb-root \.training-table/);
  assert.match(index, /@import "\.\/v2\/model-training\.css"/);

  assert.match(mocks, /TRAINING_TABS/);
  assert.match(mocks, /14\.2M/);
  assert.match(mocks, /Qwen2\.5-Coder/);
  assert.match(mocks, /Brain nodes/);
  assert.match(mocks, /mockRuns/);
  assert.match(mocks, /DATASET_DETAIL_TABS/);

  for (const name of [
    "TrainingTabOverzicht",
    "TrainingTabDatasets",
    "TrainingTabModel",
    "TrainingTabFramework",
    "TrainingTabRuns",
  ]) {
    assert.match(barrel, new RegExp(name));
  }
});

test("FINALBETA model training tab panels cover mockup sections", async () => {
  const datasets = await read("components/hades/finalbeta/pages/model-training/tab-datasets.tsx");
  const model = await read("components/hades/finalbeta/pages/model-training/tab-model.tsx");
  const framework = await read("components/hades/finalbeta/pages/model-training/tab-framework.tsx");
  const runs = await read("components/hades/finalbeta/pages/model-training/tab-runs.tsx");

  assert.match(datasets, /Dataset Library/);
  assert.match(datasets, /Dataset Details/);
  assert.match(datasets, /Preprocessing Pipeline/);
  assert.match(datasets, /Dataset Sources/);
  assert.match(datasets, /HADES Core/);
  assert.match(datasets, /Storage breakdown/);
  assert.match(datasets, /DATASET_DETAIL_TABS/);

  assert.match(model, /Model Configuration/);
  assert.match(model, /Selected Model Details/);
  assert.match(model, /Capability Comparison/);
  assert.match(model, /Compatibility checklist/);
  assert.match(model, /Model Profiles/);
  assert.match(model, /OmniRoute/);

  assert.match(framework, /Framework Training Matrix/);
  assert.match(framework, /Neural Architecture/);
  assert.match(framework, /Evaluation Signals/);
  assert.match(framework, /Start framework training/);
  assert.match(framework, /FRAMEWORK_NODES/);

  assert.match(runs, /Run Monitor/);
  assert.match(runs, /Run details/);
  assert.match(runs, /RUN_DETAIL_TABS/);
  assert.match(runs, /Metrics timeline/);
  assert.match(runs, /Snelle acties/);
  assert.match(runs, /Pause/);
  assert.match(runs, /Resume/);
  assert.match(runs, /Stop/);
});
