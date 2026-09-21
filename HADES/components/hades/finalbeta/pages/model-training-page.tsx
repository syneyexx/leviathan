"use client";

import { useState, type ReactNode } from "react";
import { TRAINING_TABS, type TrainingTab } from "../mocks/model-training";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";
import {
  TrainingDatasetsInspector,
  TrainingFrameworkInspector,
  TrainingModelInspector,
  TrainingOverzichtInspector,
  TrainingRunsInspector,
  TrainingTabDatasets,
  TrainingTabFramework,
  TrainingTabModel,
  TrainingTabOverzicht,
  TrainingTabRuns,
} from "./model-training";

type Props = { onNavigate: FinalBetaNavigate };

export function ModelTrainingPage({ onNavigate }: Props) {
  const [tab, setTab] = useState<TrainingTab>("Overzicht");

  const tabsNav = (
    <nav className="tabs" data-tabs="main" aria-label="Model Training weergaven">
      {TRAINING_TABS.map((item) => (
        <button
          key={item}
          type="button"
          className={`tab${tab === item ? " active" : ""}`}
          data-tab={item.toLowerCase()}
          onClick={() => setTab(item)}
        >
          {item}
        </button>
      ))}
    </nav>
  );

  let panel: ReactNode = null;
  let inspector: ReactNode = null;

  if (tab === "Overzicht") {
    panel = <TrainingTabOverzicht tabs={tabsNav} />;
    inspector = <TrainingOverzichtInspector />;
  } else if (tab === "Datasets") {
    panel = <TrainingTabDatasets tabs={tabsNav} />;
    inspector = <TrainingDatasetsInspector />;
  } else if (tab === "Model") {
    panel = <TrainingTabModel tabs={tabsNav} />;
    inspector = <TrainingModelInspector />;
  } else if (tab === "Framework") {
    panel = <TrainingTabFramework tabs={tabsNav} />;
    inspector = <TrainingFrameworkInspector />;
  } else {
    panel = <TrainingTabRuns tabs={tabsNav} />;
    inspector = <TrainingRunsInspector />;
  }

  return (
    <FinalBetaShell
      page="model-training"
      body={<div className="training-page">{panel}</div>}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="training-app"
      mainClassName="training-main"
    />
  );
}
