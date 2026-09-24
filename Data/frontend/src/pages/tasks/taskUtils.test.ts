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
} from "./taskUtils";
import { ApiError } from "../../api/client";

describe("taskUtils", () => {
  it("errMsg prefers ApiError message", () => {
    expect(errMsg(new ApiError(400, "Nope"), "fallback")).toBe("Nope");
    expect(errMsg(new Error("x"), "fallback")).toBe("fallback");
  });

  it("formats due dates and relative times", () => {
    const iso = "2026-04-25T15:00:00.000Z";
    expect(formatDue(iso)).toMatch(/Apr/);
    expect(formatDue(null)).toBe("—");
    expect(formatRelative(new Date().toISOString())).toMatch(/just now|m/);
  });

  it("maps priority labels and classes", () => {
    expect(priorityLabel("high")).toBe("High");
    expect(priorityLabel("LOW")).toBe("Low");
    expect(priorityClass("high")).toBe("lv-tasks-badge--high");
    expect(priorityClass("medium")).toBe("lv-tasks-badge--medium");
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

  it("displayProgressPct handles 0–1 and 0–100", () => {
    expect(displayProgressPct({ displayProgress: 0.65, progress: null, executionProgress: null })).toBe(65);
    expect(displayProgressPct({ displayProgress: 65, progress: null, executionProgress: null })).toBe(65);
    expect(displayProgressPct({ displayProgress: null, progress: 0.2, executionProgress: null })).toBe(20);
  });

  it("mapTaskListFilters maps toolbar UI to API params", () => {
    expect(
      mapTaskListFilters({
        search: " model ",
        priority: "high",
        status: "in_progress",
        assignee: "agent-1",
        datePreset: "today",
        timezone: "Europe/Amsterdam",
      }),
    ).toEqual({
      search: "model",
      priority: "high",
      boardColumn: "in_progress",
      assignee: "agent-1",
      datePreset: "today",
      timezone: "Europe/Amsterdam",
    });

    expect(
      mapTaskListFilters({
        search: "",
        priority: "all-priorities",
        status: "all-statuses",
        assignee: "all-assignees",
        datePreset: "week",
      }),
    ).toEqual({ datePreset: "week" });

    expect(
      mapTaskListFilters({
        search: "",
        priority: "all-priorities",
        status: "in-progress",
        assignee: "all-assignees",
        datePreset: "all",
      }),
    ).toEqual({ boardColumn: "in_progress" });
  });
});
