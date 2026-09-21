export type PracticeScenario = {
  id: string;
  title: string;
  description: string;
  kind: string;
};

export type PracticeResult = {
  scenario_id: string;
  passed: boolean;
  trace: Record<string, unknown>;
  notes: string[];
};

export type AgentMutationAction = "enable" | "disable" | "cancel" | "refresh";
