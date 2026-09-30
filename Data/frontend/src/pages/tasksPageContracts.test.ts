import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { mapTaskListFilters } from "./tasks/taskUtils";

const here = dirname(fileURLToPath(import.meta.url));

describe("TasksPage production contracts", () => {
  it("does not import tasksReferenceMock or page-local CSS", () => {
    const src = readFileSync(join(here, "TasksPage.tsx"), "utf8");
    expect(src).not.toMatch(/tasksReferenceMock/);
    expect(src).not.toMatch(/from ["'].*mocks\/tasksReferenceMock/);
    expect(src).not.toMatch(/tasks-reference\.css/);
    expect(src).toMatch(/useTasksWorkspace|TasksOverviewTable/);
    expect(src).toMatch(/variant=\"v2\"/);
  });

  it("maps operational status and type filters", () => {
    expect(
      mapTaskListFilters({
        search: "",
        priority: "all",
        status: "running",
        type: "trading",
        assignee: "all",
        datePreset: "all",
      }),
    ).toMatchObject({
      operationalStatus: "running",
      taskType: "trading",
    });
  });

  it("maps legacy board column status aliases", () => {
    expect(
      mapTaskListFilters({
        search: "",
        priority: "all-priorities",
        status: "in-progress",
        type: "all-types",
        assignee: "all-assignees",
        datePreset: "all",
      }).boardColumn,
    ).toBe("in_progress");
  });

  it("omits all-* sentinel filter values", () => {
    const mapped = mapTaskListFilters({
      search: "   ",
      priority: "all-priorities",
      status: "all-statuses",
      type: "all-types",
      assignee: "all-assignees",
      datePreset: "all",
    });
    expect(mapped.search).toBeUndefined();
    expect(mapped.priority).toBeUndefined();
    expect(mapped.boardColumn).toBeUndefined();
    expect(mapped.operationalStatus).toBeUndefined();
    expect(mapped.taskType).toBeUndefined();
    expect(mapped.assignee).toBeUndefined();
    expect(mapped.datePreset).toBeUndefined();
  });
});
