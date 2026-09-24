import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { mapTaskListFilters } from "./tasks/taskUtils";

const here = dirname(fileURLToPath(import.meta.url));

describe("TasksPage production contracts", () => {
  it("does not import tasksReferenceMock", () => {
    const src = readFileSync(join(here, "TasksPage.tsx"), "utf8");
    expect(src).not.toMatch(/tasksReferenceMock/);
    expect(src).not.toMatch(/from ["'].*mocks\/tasksReferenceMock/);
    expect(src).toMatch(/api\.listTasks|api\.taskSummary/);
  });

  it("maps status filter in-progress aliases to boardColumn in_progress", () => {
    expect(
      mapTaskListFilters({
        search: "",
        priority: "all-priorities",
        status: "in-progress",
        assignee: "all-assignees",
        datePreset: "all",
      }).boardColumn,
    ).toBe("in_progress");

    expect(
      mapTaskListFilters({
        search: "q",
        priority: "medium",
        status: "review",
        assignee: "all-assignees",
        datePreset: "month",
        timezone: "UTC",
      }),
    ).toMatchObject({
      search: "q",
      priority: "medium",
      boardColumn: "review",
      datePreset: "month",
      timezone: "UTC",
    });
  });

  it("omits all-* sentinel filter values", () => {
    const mapped = mapTaskListFilters({
      search: "   ",
      priority: "all-priorities",
      status: "all-statuses",
      assignee: "all-assignees",
      datePreset: "all",
    });
    expect(mapped.search).toBeUndefined();
    expect(mapped.priority).toBeUndefined();
    expect(mapped.boardColumn).toBeUndefined();
    expect(mapped.assignee).toBeUndefined();
    expect(mapped.datePreset).toBeUndefined();
  });
});
