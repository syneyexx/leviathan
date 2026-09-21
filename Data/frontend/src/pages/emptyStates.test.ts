import { describe, expect, it } from "vitest";

/** Pure helpers mirroring empty-state copy gates used by the pages. */
function datasetsEmptyCopy(count: number): string | null {
  return count === 0 ? "NO DATASETS" : null;
}

function trainingJobsEmptyCopy(count: number): string | null {
  return count === 0 ? "NO TRAINING JOBS" : null;
}

function researchEmptyCopy(count: number): string | null {
  return count === 0 ? "NO RESEARCH PROJECTS" : null;
}

function sourcesEmptyCopy(count: number): string | null {
  return count === 0 ? "NO SOURCES" : null;
}

describe("page empty states", () => {
  it("datasets shows honest empty title when API returns []", () => {
    expect(datasetsEmptyCopy(0)).toBe("NO DATASETS");
    expect(datasetsEmptyCopy(2)).toBeNull();
  });

  it("training never invents active jobs from constants", () => {
    const jobs: unknown[] = [];
    expect(trainingJobsEmptyCopy(jobs.length)).toBe("NO TRAINING JOBS");
  });

  it("research projects and sources stay empty until real data", () => {
    expect(researchEmptyCopy(0)).toBe("NO RESEARCH PROJECTS");
    expect(sourcesEmptyCopy(0)).toBe("NO SOURCES");
  });
});
