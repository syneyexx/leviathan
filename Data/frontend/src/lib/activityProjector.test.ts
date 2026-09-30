import { describe, expect, it } from "vitest";
import { ActivityClientProjector, compactHeadline, formatMeasuredProgress } from "./activityProjector";
import type { ActivityEvent } from "../types/activity";

function ev(partial: Partial<ActivityEvent> & Pick<ActivityEvent, "eventId" | "title" | "lifecycle">): ActivityEvent {
  return {
    operationId: "op1",
    sequence: 1,
    actorType: "leviathan",
    category: "SYSTEM",
    phase: "unknown",
    ...partial,
  };
}

describe("ActivityClientProjector", () => {
  it("dedupes and prefers terminal lifecycle", () => {
    const p = new ActivityClientProjector();
    p.ingest(
      ev({
        eventId: "k",
        title: "Knowledge retrieval",
        lifecycle: "running",
        sequence: 1,
        category: "KNOWLEDGE",
        phase: "knowledge_retrieval",
      }),
    );
    p.ingest(
      ev({
        eventId: "k",
        title: "Knowledge retrieved",
        lifecycle: "completed",
        sequence: 2,
        category: "KNOWLEDGE",
        phase: "knowledge_retrieval",
        resultCount: 17,
      }),
    );
    p.ingest(
      ev({
        eventId: "k",
        title: "Knowledge retrieval",
        lifecycle: "running",
        sequence: 1,
        category: "KNOWLEDGE",
        phase: "knowledge_retrieval",
      }),
    );
    const projection = p.project();
    expect(projection.events).toHaveLength(1);
    expect(projection.events[0]?.lifecycle).toBe("completed");
    expect(projection.events[0]?.resultCount).toBe(17);
  });

  it("marks disconnected as stale without inventing completion", () => {
    const p = new ActivityClientProjector();
    p.ingest(ev({ eventId: "m", title: "Model", lifecycle: "running", sequence: 1 }));
    p.markDisconnected();
    const projection = p.project();
    expect(projection.disconnected).toBe(true);
    expect(projection.stale).toBe(true);
    expect(projection.events[0]?.lifecycle).toBe("running");
    expect(compactHeadline(projection)).toBe("Activity stream disconnected");
  });

  it("does not format unmeasured progress as percentage", () => {
    expect(formatMeasuredProgress({ kind: "indeterminate" })).toBeNull();
    expect(formatMeasuredProgress({ kind: "unknown" })).toBeNull();
    expect(
      formatMeasuredProgress({
        kind: "measured",
        numerator: 62,
        denominator: 100,
        unit: "documents",
      }),
    ).toBe("62 / 100 documents (62%)");
  });
});
