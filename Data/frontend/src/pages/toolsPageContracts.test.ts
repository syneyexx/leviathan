import { describe, expect, it } from "vitest";
import { TOOLS_V2_VISUAL_FIXTURE, isToolsVisualFixtureActive } from "../mocks/toolsV2VisualFixture";

describe("Tools V2 contracts", () => {
  it("fixture is gated and never implies production defaults", () => {
    expect(isToolsVisualFixtureActive()).toBe(false);
    expect(TOOLS_V2_VISUAL_FIXTURE.overview.total_capabilities).toBe(48);
    expect(TOOLS_V2_VISUAL_FIXTURE.overview.truth?.fixture_only).toBe(true);
  });

  it("fixture contains required Screen 1 sections", () => {
    expect(TOOLS_V2_VISUAL_FIXTURE.tools.length).toBeGreaterThan(5);
    expect(TOOLS_V2_VISUAL_FIXTURE.overview.mcp_servers.length).toBeGreaterThan(0);
    expect(TOOLS_V2_VISUAL_FIXTURE.overview.plugins.length).toBeGreaterThan(0);
    expect(TOOLS_V2_VISUAL_FIXTURE.overview.recent_calls.length).toBeGreaterThan(0);
    expect(TOOLS_V2_VISUAL_FIXTURE.detail.capability.id).toBe("web_search");
  });
});
