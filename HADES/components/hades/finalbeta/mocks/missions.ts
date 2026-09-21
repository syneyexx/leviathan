/** Mock domain data for FINALBETA Phase 1 — replace with real providers in Phase 2. */

export type FinalBetaMission = {
  id: string;
  title: string;
  summary: string;
  status: "concept" | "queued" | "review" | "done";
  statusLabel: string;
};

export const mockMissions: FinalBetaMission[] = [
  {
    id: "m1",
    title: "Interface uitwerken",
    summary: "Opzet en belangrijkste pagina's van de werkruimte.",
    status: "concept",
    statusLabel: "Concept",
  },
  {
    id: "m2",
    title: "Bronnen onderzoeken",
    summary: "Referenties verzamelen en structureren.",
    status: "queued",
    statusLabel: "In wachtrij",
  },
  {
    id: "m3",
    title: "Plugin controleren",
    summary: "Controle op installatie en lokale werking.",
    status: "review",
    statusLabel: "Te controleren",
  },
];

export const mockPlanSteps = [
  { id: "p1", title: "Navigatie afronden", done: true },
  { id: "p2", title: "Pagina's uitwerken", done: false },
  { id: "p3", title: "Review en test", done: false },
];

export const mockAcceptance = {
  title: "Alle pagina's bereikbaar",
  detail: "De belangrijkste navigatie en functies zijn werkend en toetsbaar.",
};

export const mockSystemReadiness = [
  { id: "r1", label: "Lokale runtime", ok: true },
  { id: "r2", label: "Modelendpoint", ok: true },
  { id: "r3", label: "Opslag", ok: true },
];
