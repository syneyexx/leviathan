export type FinalBetaAgent = {
  id: string;
  name: string;
  description: string;
  status: "idle" | "running" | "error";
  statusLabel: string;
  model: string;
};

export const mockAgents: FinalBetaAgent[] = [
  {
    id: "a1",
    name: "Research agent",
    description: "Verzamelt en structureert bronnen lokaal.",
    status: "idle",
    statusLabel: "Klaar",
    model: "qwen3-14b-instruct",
  },
  {
    id: "a2",
    name: "Coding agent",
    description: "Plant en wijzigt code in de werkruimte.",
    status: "running",
    statusLabel: "Bezig",
    model: "qwen2.5-coder-14b",
  },
  {
    id: "a3",
    name: "Ops agent",
    description: "Bewaakt runtime- en pluginstatus.",
    status: "idle",
    statusLabel: "Klaar",
    model: "lokaal",
  },
];
