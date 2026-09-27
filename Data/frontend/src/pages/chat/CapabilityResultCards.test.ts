import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AssistantToolCallTelemetry } from "../../types/api";
import { CapabilityResultCards } from "./CapabilityResultCards";

describe("CapabilityResultCards", () => {
  it("renders module/status/artifacts/sources without inventing counts", () => {
    const toolCalls: AssistantToolCallTelemetry[] = [
      {
        capability_id: "external.agent_reach.search",
        module_id: "agent-reach",
        status: "COMPLETED",
        success: true,
        duration_ms: 4200,
        receipt_id: "rcpt_1",
        summary: "31 results",
        provider: "CLI",
        result_count: 31,
        source_count: 12,
        artifact_refs: ["artifact:report-1"],
        parts: [
          { kind: "SOURCE", title: "Example thread", url: "https://example.test/a" },
          { kind: "PROGRESS", text: "Searching Reddit..." },
        ],
      },
    ];
    const html = renderToStaticMarkup(
      createElement(CapabilityResultCards, { toolCalls }),
    );
    expect(html).toContain("agent-reach");
    expect(html).toContain("COMPLETED");
    expect(html).toContain("4.2 s");
    expect(html).toContain("31 results");
    expect(html).toContain("12 sources");
    expect(html).toContain("artifact:report-1");
    expect(html).toContain("Example thread");
    expect(html).toContain("Searching Reddit...");
  });

  it("returns null when there are no capability rows", () => {
    const html = renderToStaticMarkup(createElement(CapabilityResultCards, { toolCalls: [] }));
    expect(html).toBe("");
  });
});
