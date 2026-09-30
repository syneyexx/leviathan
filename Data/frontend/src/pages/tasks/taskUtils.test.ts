import { describe, expect, it } from "vitest";
import {
  boardColumnLabel,
  displayProgressPct,
  errMsg,
  formatDue,
  formatRelative,
  initials,
  mapTaskListFilters,
  normalizeBoardColumn,
  priorityClass,
  priorityLabel,
  statusLabel,
  taskTypeLabel,
} from "./taskUtils";
import { ApiError } from "../../api/client";

describe("taskUtils", () => {
  it("errMsg prefers ApiError message", () => {
    expect(errMsg(new ApiError(400, "Nope"), "fallback")).toBe("Nope");
    expect(errMsg(new Error("x"), "fallback")).toBe("fallback");
  });

  it("formats due dates and relative times", () => {
    const iso = "2026-04-25T15:00:00.000Z";
    expect(formatDue(iso)).toMatch(/apr|Apr|4/i);
    expect(formatDue(null)).toBe("—");
    expect(formatRelative(new Date().toISOString())).toMatch(/zojuist|m|u|d/);
  });

  it("maps priority labels and classes", () => {
    expect(priorityLabel("high")).toBe("Hoog");
    expect(priorityLabel("LOW")).toBe("Laag");
    expect(priorityClass("high")).toBe("lv-v2-tasks-badge--priority-high");
    expect(priorityClass("medium")).toBe("lv-v2-tasks-badge--priority-normal");
  });

  it("normalizes board columns", () => {
    expect(normalizeBoardColumn("in-progress")).toBe("in_progress");
    expect(normalizeBoardColumn("in_progress")).toBe("in_progress");
    expect(boardColumnLabel("review")).toBe("Review");
  });

  it("initials from names", () => {
    expect(initials("Alex Chen")).toBe("AC");
    expect(initials("Research")).toBe("RE");
  });

  it("displayProgressPct handles measured and unknown", () => {
    expect(displayProgressPct({ displayProgress: 0.65, progress: null, executionProgress: null })).toBe(65);
    expect(displayProgressPct({ displayProgress: 65, progress: null, executionProgress: null })).toBe(65);
    expect(displayProgressPct({ displayProgress: null, progress: 0.2, executionProgress: null })).toBe(20);
    expect(
      displayProgressPct({
        displayProgress: null,
        progress: null,
        executionProgress: null,
        progressKnown: false,
      }),
    ).toBeNull();
    expect(
      displayProgressPct({
        displayProgress: 0,
        progress: null,
        executionProgress: null,
        progressKnown: true,
      }),
    ).toBe(0);
  });

  it("maps Dutch status/type labels", () => {
    expect(statusLabel("running")).toBe("Actief");
    expect(statusLabel("failed")).toBe("Mislukt");
    expect(taskTypeLabel("research")).toBe("Research");
    expect(taskTypeLabel("general")).toBe("Algemeen");
  });

  it("mapTaskListFilters maps toolbar UI to API params", () => {
    expect(
      mapTaskListFilters({
        search: " model ",
        priority: "high",
        status: "running",
        type: "research",
        assignee: "agent-1",
        datePreset: "today",
        timezone: "Europe/Amsterdam",
      }),
    ).toEqual({
      search: "model",
      priority: "high",
      operationalStatus: "running",
      taskType: "research",
      assignee: "agent-1",
      datePreset: "today",
      timezone: "Europe/Amsterdam",
    });

    expect(
      mapTaskListFilters({
        search: "",
        priority: "all",
        status: "all",
        type: "all",
        assignee: "all",
        datePreset: "week",
      }),
    ).toEqual({ datePreset: "week" });

    expect(
      mapTaskListFilters({
        search: "",
        priority: "all-priorities",
        status: "in-progress",
        type: "all-types",
        assignee: "all-assignees",
        datePreset: "all",
      }),
    ).toEqual({ boardColumn: "in_progress" });
  });
});
