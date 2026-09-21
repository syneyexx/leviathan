/** FINALBETA Workflows — mock/demo data only (no live API claims). */

export type WfTab = "overzicht" | "workflows" | "templates" | "triggers" | "runs" | "logs";
export type WfStatus = "Actief" | "Pauze" | "Fout";
export type WfTone = "green" | "gold" | "red";
export type CanvasTab = "canvas" | "config" | "runs" | "logs";
export type CanvasNodeKind = "trigger" | "action" | "condition" | "end";

export const PR_WF_QUOTE = "Automate intelligence. Multiply impact.";

export const PR_WF_TABS: Array<{ id: WfTab; label: string }> = [
  { id: "overzicht", label: "Overzicht" },
  { id: "workflows", label: "Workflows" },
  { id: "templates", label: "Templates" },
  { id: "triggers", label: "Triggers" },
  { id: "runs", label: "Uitvoeringen" },
  { id: "logs", label: "Logs" },
];

export const PR_WF_CANVAS_TABS: Array<{ id: CanvasTab; label: string }> = [
  { id: "canvas", label: "Canvas" },
  { id: "config", label: "Configuratie" },
  { id: "runs", label: "Uitvoeringen" },
  { id: "logs", label: "Logs" },
];

export const PR_WF_STATS = [
  {
    id: "total",
    label: "Totaal workflows",
    value: "12",
    hint: "+3 deze week",
    hintTone: "up" as const,
    icon: "list" as const,
  },
  {
    id: "active",
    label: "Actieve workflows",
    value: "9",
    hint: "75% van totaal",
    hintTone: "flat" as const,
    icon: "play" as const,
  },
  {
    id: "runs24",
    label: "Uitvoeringen (24u)",
    value: "148",
    hint: "+42%",
    hintTone: "up" as const,
    icon: "bolt" as const,
  },
  {
    id: "success",
    label: "Succespercentage",
    value: "96.6%",
    hint: "143 geslaagd / 148",
    hintTone: "flat" as const,
    icon: "checkcircle" as const,
  },
];

export type WfListItem = {
  id: string;
  name: string;
  summary: string;
  status: WfStatus;
  tone: WfTone;
  lastRun: string;
};

export const PR_WF_LIST: WfListItem[] = [
  {
    id: "nieuws",
    name: "Nieuws analyse",
    summary: "Analyseer en verwerk nieuwsartikelen",
    status: "Actief",
    tone: "green",
    lastRun: "17 feb 2025, 14:22",
  },
  {
    id: "markt",
    name: "Marktmonitor",
    summary: "Volg tickers en sentiment",
    status: "Actief",
    tone: "green",
    lastRun: "17 feb 2025, 14:10",
  },
  {
    id: "research",
    name: "Research assistent",
    summary: "Bronnen verzamelen en samenvatten",
    status: "Actief",
    tone: "green",
    lastRun: "17 feb 2025, 13:48",
  },
  {
    id: "content",
    name: "Content pipeline",
    summary: "Draft → review → publicatie",
    status: "Pauze",
    tone: "gold",
    lastRun: "16 feb 2025, 22:01",
  },
  {
    id: "enrich",
    name: "Data verrijking",
    summary: "Entity linking en metadata",
    status: "Actief",
    tone: "green",
    lastRun: "17 feb 2025, 12:55",
  },
  {
    id: "email",
    name: "E-mail verwerking",
    summary: "Inbox triage en routing",
    status: "Actief",
    tone: "green",
    lastRun: "17 feb 2025, 12:30",
  },
  {
    id: "trading",
    name: "Trading signals",
    summary: "Signalen naar TradingCenter",
    status: "Fout",
    tone: "red",
    lastRun: "17 feb 2025, 11:02",
  },
  {
    id: "backup",
    name: "Backup routine",
    summary: "Lokale snapshot & vault sync",
    status: "Actief",
    tone: "green",
    lastRun: "17 feb 2025, 06:00",
  },
  {
    id: "dataset",
    name: "Dataset training",
    summary: "Train → eval → report",
    status: "Pauze",
    tone: "gold",
    lastRun: "15 feb 2025, 19:40",
  },
  {
    id: "social",
    name: "Social monitor",
    summary: "Mentions en trend alerts",
    status: "Actief",
    tone: "green",
    lastRun: "17 feb 2025, 14:05",
  },
];

export type CanvasNode = {
  id: string;
  kind: CanvasNodeKind;
  title: string;
  detail: string;
  x: number;
  y: number;
  w?: number;
};

export const PR_WF_CANVAS_NODES: CanvasNode[] = [
  { id: "t1", kind: "trigger", title: "Elke 15 minuten", detail: "Scheduler", x: 210, y: 18, w: 150 },
  { id: "a1", kind: "action", title: "Haal nieuws op", detail: "News API", x: 210, y: 88, w: 150 },
  { id: "a2", kind: "action", title: "Analyseer met LLM", detail: "HADES-Llama-3B", x: 200, y: 158, w: 170 },
  { id: "c1", kind: "condition", title: "Relevante content?", detail: "> 0.7 score", x: 218, y: 236, w: 134 },
  { id: "a3", kind: "action", title: "Genereer samenvatting", detail: "HADES-Chat", x: 28, y: 340, w: 158 },
  { id: "a4", kind: "action", title: "Sla op in kennisbank", detail: "Vector DB", x: 206, y: 340, w: 158 },
  { id: "a5", kind: "action", title: "Stuur notificatie", detail: "Discord / E-mail", x: 384, y: 340, w: 158 },
  { id: "a6", kind: "action", title: "Log resultaat", detail: "Audit log", x: 430, y: 250, w: 130 },
  { id: "e1", kind: "end", title: "Einde", detail: "Workflow voltooid", x: 206, y: 430, w: 158 },
];

export type CanvasEdge = {
  id: string;
  from: string;
  to: string;
  tone?: "yes" | "no" | "default";
  label?: string;
};

export const PR_WF_CANVAS_EDGES: CanvasEdge[] = [
  { id: "e-t1-a1", from: "t1", to: "a1" },
  { id: "e-a1-a2", from: "a1", to: "a2" },
  { id: "e-a2-c1", from: "a2", to: "c1" },
  { id: "e-c1-a3", from: "c1", to: "a3", tone: "yes", label: "Ja" },
  { id: "e-c1-a4", from: "c1", to: "a4", tone: "yes" },
  { id: "e-c1-a5", from: "c1", to: "a5", tone: "yes" },
  { id: "e-c1-a6", from: "c1", to: "a6", tone: "no", label: "Nee" },
  { id: "e-a3-e1", from: "a3", to: "e1" },
  { id: "e-a4-e1", from: "a4", to: "e1" },
  { id: "e-a5-e1", from: "a5", to: "e1" },
  { id: "e-a6-e1", from: "a6", to: "e1", tone: "no" },
];

export const PR_WF_DETAIL = {
  name: "Nieuws analyse",
  description:
    "Analyseert binnenkomende nieuwsfeeds, scoort relevantie en routeert naar kennisbank of notificaties.",
  status: "Actief" as WfStatus,
  tone: "green" as WfTone,
  owner: "HADES Local",
  created: "12 jan 2025",
  updated: "17 feb 2025, 14:22",
  version: "v1.4.2",
};

export const PR_WF_TRIGGERS = [
  { id: "schedule", label: "Tijdschema", status: "Actief", tone: "green" as WfTone },
  { id: "webhook", label: "Webhook", status: "Uit", tone: "gray" as const },
  { id: "event", label: "Gebeurtenis", status: "Uit", tone: "gray" as const },
  { id: "cron", label: "CRON expressie", status: "Uit", tone: "gray" as const },
];

export const PR_WF_RUNS = [
  { id: "r1", when: "17 feb 14:22", status: "Geslaagd", tone: "green" as WfTone, duration: "2m 14s" },
  { id: "r2", when: "17 feb 14:07", status: "Geslaagd", tone: "green" as WfTone, duration: "2m 08s" },
  { id: "r3", when: "17 feb 13:52", status: "Fout", tone: "red" as WfTone, duration: "48s" },
  { id: "r4", when: "17 feb 13:37", status: "Geslaagd", tone: "green" as WfTone, duration: "2m 21s" },
  { id: "r5", when: "17 feb 13:22", status: "Geslaagd", tone: "green" as WfTone, duration: "2m 11s" },
];

export const PR_WF_PERF = [
  {
    id: "runs",
    label: "Uitvoeringen",
    value: "148",
    color: "#38bdf8",
    bars: [18, 22, 20, 26, 24, 28, 30],
  },
  {
    id: "success",
    label: "Succesratio",
    value: "96.6%",
    color: "#22c55e",
    bars: [94, 95, 97, 96, 98, 96, 97],
  },
  {
    id: "duration",
    label: "Gem. duur",
    value: "2m 18s",
    color: "#eab94f",
    bars: [12, 14, 11, 15, 13, 14, 12],
  },
  {
    id: "errors",
    label: "Fouten",
    value: "0",
    color: "#ef4444",
    bars: [2, 1, 0, 1, 0, 1, 0],
  },
];

export const PR_WF_ACTIONS = [
  { id: "run", label: "Live testen", icon: "play" as const, gold: true },
  { id: "edit", label: "Bewerken", icon: "sliders" as const, gold: false },
  { id: "import", label: "Importeren", icon: "download" as const, gold: false },
  { id: "new", label: "Nieuwe workflow", icon: "plus" as const, gold: false },
];

export const PR_WF_STATUS_FILTERS = [
  { id: "all", label: "Alle statussen" },
  { id: "Actief", label: "Actief" },
  { id: "Pauze", label: "Pauze" },
  { id: "Fout", label: "Fout" },
] as const;
