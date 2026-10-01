import { describe, expect, it } from "vitest";
import {
  canAttachFiles,
  readyArtifactIds,
  validateLocalFile,
  visionClaimAllowed,
  type ChatAttachment,
} from "./attachments";
import { mapRunStatusToOutcome } from "../../pages/chat/hooks/useChatTurn";
import {
  isReasoningModeId,
  parseReasoningMode,
  reasoningModeForApi,
  REASONING_MODE_IDS,
} from "./reasoningModes";

describe("attachments honesty", () => {
  it("gates unknown/disabled attachment capability", () => {
    expect(canAttachFiles(null).ok).toBe(false);
    expect(canAttachFiles(false).ok).toBe(false);
    expect(canAttachFiles(true).ok).toBe(true);
  });

  it("rejects empty and oversized local files", () => {
    const empty = new File([], "empty.txt", { type: "text/plain" });
    expect(validateLocalFile(empty).ok).toBe(false);
    const ok = new File(["hello"], "a.txt", { type: "text/plain" });
    expect(validateLocalFile(ok).ok).toBe(true);
  });

  it("collects only ready artifact ids", () => {
    const items: ChatAttachment[] = [
      {
        localId: "1",
        fileName: "a.txt",
        mimeType: "text/plain",
        sizeBytes: 1,
        artifactId: "art-1",
        state: "ready",
        error: null,
        unavailableReason: null,
      },
      {
        localId: "2",
        fileName: "b.txt",
        mimeType: "text/plain",
        sizeBytes: 1,
        artifactId: null,
        state: "failed",
        error: "x",
        unavailableReason: null,
      },
    ];
    expect(readyArtifactIds(items)).toEqual(["art-1"]);
  });

  it("does not claim vision without model/capability path", () => {
    expect(
      visionClaimAllowed({
        hasImageAttachment: true,
        modelSupportsVision: null,
        visionCapabilityActive: false,
      }).claim,
    ).toBe(false);
    expect(
      visionClaimAllowed({
        hasImageAttachment: true,
        modelSupportsVision: true,
        visionCapabilityActive: false,
      }).claim,
    ).toBe(true);
  });
});

describe("mapRunStatusToOutcome", () => {
  it("maps durable turn/run states", () => {
    expect(mapRunStatusToOutcome({ turn: { run_state: "COMPLETED" } })).toBe("completed");
    expect(mapRunStatusToOutcome({ turn: { run_state: "CANCELLED" } })).toBe("cancelled");
    expect(mapRunStatusToOutcome({ turn: { run_state: "FAILED" } })).toBe("failed");
    expect(mapRunStatusToOutcome({ turn: { run_state: "STREAMING" } })).toBe("running");
    expect(mapRunStatusToOutcome({ run: { state: "EXECUTING" } })).toBe("running");
    expect(mapRunStatusToOutcome({})).toBe("unknown");
  });

  it("treats CANCELLED as distinct from FAILED (cancel race)", () => {
    expect(mapRunStatusToOutcome({ turn: { run_state: "CANCELLED" } })).not.toBe("failed");
    expect(mapRunStatusToOutcome({ run: { state: "CANCELLED" } })).toBe("cancelled");
    // Turn CANCELLED wins even if run still looks failed-ish naming
    expect(
      mapRunStatusToOutcome({
        turn: { run_state: "CANCELLED" },
        run: { state: "FAILED" },
      }),
    ).toBe("cancelled");
  });
});

describe("ReasoningModeId includes standard", () => {
  it("keeps standard in the wire set", () => {
    expect([...REASONING_MODE_IDS]).toContain("standard");
    expect(isReasoningModeId("standard")).toBe(true);
    expect(parseReasoningMode("standard")).toBe("standard");
    expect(reasoningModeForApi("standard")).toBe("standard");
    expect(reasoningModeForApi("auto")).toBeNull();
  });
});
