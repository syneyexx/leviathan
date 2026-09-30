/**
 * Leviathan V2 LLM / Model Training — canonical `/training`.
 * Screen 1 engine + hardware + datasets + trainable models + runs workspace.
 * No page-local CSS — layout lives in `styles/leviathan-v2.css` under
 * `.lv-v2-page--training`.
 */

import { TrainingCheckpointsPanel } from "../components/training/TrainingCheckpointsPanel";
import { TrainingConfigPanel } from "../components/training/TrainingConfigPanel";
import { TrainingDatasetPanel } from "../components/training/TrainingDatasetPanel";
import { TrainingEngineCard } from "../components/training/TrainingEngineCard";
import { TrainingHardwareCard } from "../components/training/TrainingHardwareCard";
import { TrainingMetricsChart } from "../components/training/TrainingMetricsChart";
import { TrainingModelPanel } from "../components/training/TrainingModelPanel";
import { TrainingPreflightDrawer } from "../components/training/TrainingPreflightDrawer";
import { TrainingRunDetailPanel } from "../components/training/TrainingRunDetailPanel";
import { TrainingRunsPanel } from "../components/training/TrainingRunsPanel";
import { TrainingStatsCard } from "../components/training/TrainingStatsCard";
import { Button } from "../components/ui";
import { useTrainingWorkspace } from "../hooks/useTrainingWorkspace";
import { AppShell } from "../layouts/AppShell";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function TrainingPage() {
  const ws = useTrainingWorkspace();
  const frozen = visualFixtureNow();

  const actions = (
    <>
      <Button variant="secondary" size="sm" loading={ws.refreshing} onClick={() => void ws.refresh()}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M20 12a8 8 0 1 1-2.2-5.5" />
          <path d="M20 4v5h-5" />
        </svg>
        Refresh
      </Button>
      <Button variant="primary" size="sm" onClick={() => ws.openNewTraining()}>
        + Nieuwe training
      </Button>
    </>
  );

  return (
    <AppShell
      variant="v2"
      v2Title="LLM / Model Training"
      v2Subtitle="Train, fine-tune en optimaliseer lokale taalmodellen en agents."
      v2Online={ws.online}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={actions}
      v2HideRefresh
    >
      <main className="lv-v2-page lv-v2-page--training">
        <section className="lv-v2-training-row lv-v2-training-row--1" aria-label="Engine en hardware">
          <TrainingEngineCard ws={ws} />
          <TrainingHardwareCard ws={ws} />
          <TrainingStatsCard ws={ws} />
        </section>

        <section className="lv-v2-training-row lv-v2-training-row--2" aria-label="Datasets, models en parameters">
          <TrainingDatasetPanel ws={ws} />
          <TrainingModelPanel ws={ws} />
          <TrainingConfigPanel ws={ws} />
        </section>

        <section className="lv-v2-training-row lv-v2-training-row--3" aria-label="Runs en grafieken">
          <TrainingRunsPanel ws={ws} />
          <TrainingMetricsChart ws={ws} />
        </section>

        <section className="lv-v2-training-row lv-v2-training-row--4" aria-label="Run details en checkpoints">
          <TrainingRunDetailPanel ws={ws} />
          <TrainingCheckpointsPanel ws={ws} />
        </section>

        {ws.error ? (
          <p className="lv-v2-models-cap-note" role="alert">
            {ws.error}
          </p>
        ) : null}
      </main>

      <TrainingPreflightDrawer ws={ws} />
    </AppShell>
  );
}
