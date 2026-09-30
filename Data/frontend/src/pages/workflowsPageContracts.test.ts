import { describe, expect, it } from "vitest";
import {
  WORKFLOWS_V2_DEFINITIONS,
  WORKFLOWS_V2_OVERVIEW,
  WORKFLOWS_V2_VISUAL_FIXTURE,
  isWorkflowsVisualFixtureActive,
} from "../mocks/workflowsV2VisualFixture";
import {
  definitionIsActive,
  definitionIsInactive,
  definitionIsTemplate,
  executionStateLabelNl,
  formatDurationMs,
  statusLabelNl,
} from "./workflows/useWorkflowsWorkspace";

describe("workflows V2 page contracts", () => {
  it("fixture has 24 non-template definitions with 8 active / 12 inactive / 6 templates", () => {
    const nonTemplate = WORKFLOWS_V2_DEFINITIONS.filter((d) => !definitionIsTemplate(d.status));
    expect(nonTemplate).toHaveLength(24);
    expect(WORKFLOWS_V2_DEFINITIONS.filter((d) => definitionIsActive(d.status))).toHaveLength(8);
    expect(WORKFLOWS_V2_DEFINITIONS.filter((d) => d.status === "INACTIVE")).toHaveLength(12);
    expect(WORKFLOWS_V2_DEFINITIONS.filter((d) => d.status === "DRAFT")).toHaveLength(4);
    expect(WORKFLOWS_V2_DEFINITIONS.filter((d) => definitionIsTemplate(d.status))).toHaveLength(6);
    expect(WORKFLOWS_V2_OVERVIEW.counts).toMatchObject({
      total_definitions: 24,
      active_definitions: 8,
      inactive_definitions: 12,
      draft_definitions: 4,
      templates: 6,
      running_executions: 4,
    });
  });

  it("Research Pipeline graph matches reference node set", () => {
    const research = WORKFLOWS_V2_DEFINITIONS.find((d) => d.workflow_id === "wf-research-pipeline");
    expect(research).toBeTruthy();
    const labels = (research?.graph?.nodes ?? []).map((n) => n.label);
    expect(labels).toEqual(
      expect.arrayContaining([
        "Trigger",
        "Web Search",
        "Research Agent",
        "Data Transform",
        "Condition",
        "Generate Report",
        "Save to Knowledge",
        "Notify",
      ]),
    );
    const yes = research?.graph?.edges.find((e) => e.label === "Ja");
    const no = research?.graph?.edges.find((e) => e.label === "Nee");
    expect(yes?.target).toBe("n-generate-report");
    expect(no?.target).toBe("n-notify");
  });

  it("KPI strip matches screenshot targets", () => {
    const byId = Object.fromEntries(WORKFLOWS_V2_OVERVIEW.kpis.map((k) => [k.id, k]));
    expect(byId.total_workflows.value).toBe(24);
    expect(byId.active_workflows.value).toBe(8);
    expect(byId.success_rate.value).toBe(92.4);
    expect(byId.avg_duration.value).toBe(2.3);
    expect(byId.total_executions.value).toBe(1842);
    expect(WORKFLOWS_V2_OVERVIEW.resources.cpu.utilization_pct).toBe(42);
    expect(WORKFLOWS_V2_OVERVIEW.resources.workers.busy).toBe(3);
    expect(WORKFLOWS_V2_OVERVIEW.resources.workers.capacity).toBe(4);
  });

  it("fixture gate is inactive outside Playwright flag", () => {
    expect(isWorkflowsVisualFixtureActive()).toBe(false);
    expect(WORKFLOWS_V2_VISUAL_FIXTURE.selectedWorkflowId).toBe("wf-research-pipeline");
  });

  it("status helpers treat definition status separately from execution state", () => {
    expect(definitionIsActive("ACTIVE")).toBe(true);
    expect(definitionIsActive("RUNNING")).toBe(false);
    expect(definitionIsInactive("INACTIVE")).toBe(true);
    expect(definitionIsInactive("DRAFT")).toBe(true);
    expect(statusLabelNl("ACTIVE")).toBe("Actief");
    expect(statusLabelNl("INACTIVE")).toBe("Inactief");
    expect(executionStateLabelNl("COMPLETED")).toBe("Succesvol");
    expect(executionStateLabelNl("FAILED")).toBe("Gefaald");
    expect(formatDurationMs(138_000)).toBe("2.3 min");
  });
});
