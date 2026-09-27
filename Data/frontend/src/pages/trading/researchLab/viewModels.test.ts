import { describe, expect, it } from "vitest";
import {
  actionAvailability,
  asNum,
  autonomyCeilingPct,
  candidateCard,
  countRunsByStatus,
  deriveEvents,
  deriveOverview,
  derivePhases,
  progressPct,
  resolveRunStatus,
  runListItem,
  statusTone,
} from "./viewModels";

describe("Research Lab view models", () => {
  it("maps statuses to tones and action enablement", () => {
    expect(statusTone("RUNNING")).toBe("running");
    expect(statusTone("COMPLETED")).toBe("completed");
    expect(statusTone("PAUSED")).toBe("paused");
    expect(statusTone("FAILED")).toBe("failed");
    expect(statusTone("CREATED")).toBe("draft");

    expect(actionAvailability("CREATED")).toEqual({
      canStart: true,
      canPause: false,
      canResume: false,
      canCancel: true,
    });
    expect(actionAvailability("RUNNING")).toEqual({
      canStart: false,
      canPause: true,
      canResume: false,
      canCancel: true,
    });
    expect(actionAvailability("PAUSED")).toEqual({
      canStart: false,
      canPause: false,
      canResume: true,
      canCancel: true,
    });
    expect(actionAvailability("COMPLETED").canCancel).toBe(false);
    expect(actionAvailability("COMPLETED").canStart).toBe(false);
  });

  it("prefers learning status over lab status", () => {
    expect(resolveRunStatus({ status: "CREATED" }, { status: "RUNNING" })).toBe("RUNNING");
    expect(resolveRunStatus({ status: "PAUSED" }, null)).toBe("PAUSED");
  });

  it("derives overview from real payloads without inventing metrics", () => {
    const learning = {
      status: "RUNNING",
      stage: "TRAIN",
      current_generation: 3,
      generation_budget: 8,
      trials_used: 12,
      trial_budget: 96,
      population_size: 10,
      best_train_candidate: "c1",
      best_validation_candidate: null,
      qualified_candidate: null,
      learner_state: {
        diversity_score: 0.72,
        exploration_rate: 0.15,
        mutation_rates: { numeric: 0.18 },
        fitness_history: [{ best_train_fitness: 0.1 }, { best_train_fitness: 0.2 }],
      },
    };
    const candidates = [
      {
        candidate_id: "c1",
        family: "ma_cross",
        generation: 3,
        strategy_version: 4,
        status: "EVALUATED",
        metadata: {
          stage_results: {
            TRAIN: {
              fitness_score: 1.25,
              accepted: true,
              metrics: {
                sharpe: { value: 1.1, status: "MEASURED" },
                max_drawdown_pct: { value: -8.3, status: "MEASURED" },
                win_rate: { value: 0.55, status: "MEASURED" },
              },
            },
          },
        },
      },
    ];
    const generations = [
      { generation: 1, best_train_fitness: 0.5, median_train_fitness: 0.2, diversity_score: 0.9 },
      { generation: 2, best_train_fitness: 0.8, median_train_fitness: 0.4, diversity_score: 0.7 },
    ];
    const overview = deriveOverview(learning, candidates, generations, {
      ma_cross: 0.6,
      mean_reversion: 0.4,
    });

    expect(overview.currentGeneration).toBe(3);
    expect(overview.trialsUsed).toBe(12);
    expect(overview.mutationRate).toBe(0.18);
    expect(overview.diversity).toBe(0.72);
    expect(overview.bestTrain.id).toBe("c1");
    expect(overview.bestTrain.metrics.sharpe).toBe(1.1);
    expect(overview.bestValidation.id).toBeNull();
    expect(overview.qualified.pending).toBe(true);
    expect(overview.fitnessBest).toEqual([0.5, 0.8]);
    expect(overview.familySlices).toHaveLength(2);
    expect(overview.generationRows).toHaveLength(2);
  });

  it("renders honest empty candidate cards when ids are missing", () => {
    const card = candidateCard([], null, "TRAIN");
    expect(card.id).toBeNull();
    expect(card.label).toBe("Not recorded");
    expect(card.metrics.fitness).toBeNull();
  });

  it("derives phase checklist from learning stage", () => {
    const phases = derivePhases({ stage: "VALIDATING", status: "RUNNING" });
    expect(phases.find((p) => p.id === "train")?.state).toBe("done");
    expect(phases.find((p) => p.id === "validation")?.state).toBe("active");
    expect(phases.find((p) => p.id === "holdout")?.state).toBe("pending");
  });

  it("counts runs by status without fabricating totals", () => {
    const counts = countRunsByStatus([
      { lab_id: "1", status: "RUNNING" },
      { lab_id: "2", status: "COMPLETED" },
      { lab_id: "3", status: "FAILED" },
      { lab_id: "4", status: "CREATED" },
    ]);
    expect(counts.total).toBe(4);
    expect(counts.running).toBe(1);
    expect(counts.completed).toBe(1);
    expect(counts.failed).toBe(1);
    expect(counts.draft).toBe(1);
  });

  it("builds run list items from lab + nested learning", () => {
    const item = runListItem({
      lab_id: "lab-1",
      name: "Alpha search",
      status: "RUNNING",
      strategy_id: "strat-abc",
      source_id: "src-1",
      learning: { trials_used: 54, trial_budget: 96, current_generation: 7, generation_budget: 12 },
    });
    expect(item.labId).toBe("lab-1");
    expect(item.progress).toBeCloseTo((54 / 96) * 100);
    expect(item.generationLabel).toBe("Gen 7/12");
    expect(item.tone).toBe("running");
  });

  it("derives log events only from available payloads", () => {
    const events = deriveEvents(
      { learning_run_id: "lr1", status: "FAILED", error: "boom", created_at: "2024-01-01T00:00:00Z" },
      [{ generation: 1, best_train_fitness: 0.2 }],
      [{ lesson_id: "L1", claim: "avoid overfit", trust: "AGENT_PROPOSED" }],
      [],
    );
    expect(events.some((e) => e.level === "error" && e.message === "boom")).toBe(true);
    expect(events.some((e) => e.source === "generation")).toBe(true);
    expect(events.some((e) => e.source === "lesson")).toBe(true);
  });

  it("parses autonomy ceiling and progress helpers", () => {
    expect(autonomyCeilingPct("A1")).toBe(20);
    expect(autonomyCeilingPct("A4")).toBe(80);
    expect(autonomyCeilingPct(null)).toBeNull();
    expect(progressPct(54, 96)).toBeCloseTo(56.25);
    expect(progressPct(null, 96)).toBeNull();
    expect(asNum("1.5")).toBe(1.5);
    expect(asNum("x")).toBeNull();
  });
});
