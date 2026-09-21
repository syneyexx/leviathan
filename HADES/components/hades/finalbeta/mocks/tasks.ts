export type TaskPriority = "Hoog" | "Medium" | "Laag";
export type TaskColumn = "open" | "running" | "review" | "done";
export type TaskProjectTone = "data" | "development" | "research" | "trading";
export type TaskListStatus = TaskColumn | "blocked";

export type FinalBetaKanbanTask = {
  id: string;
  code: string;
  title: string;
  description: string;
  column: TaskColumn;
  priority: TaskPriority;
  date: string;
  tags: string[];
  progress?: number;
  owner: string;
  type: string;
  created: string;
  deadline: string;
  /** Derived / enriched for list · calendar · mijn taken views */
  project?: string;
  projectTone?: TaskProjectTone;
  mine?: boolean;
  blocked?: boolean;
  estimatedTime?: string;
  dependencies?: string[];
  /** Day-of-month in September 2026 for calendar pills */
  calDay?: number;
  mission?: { title: string; sub: string };
  log?: Array<{ title: string; sub: string; ago: string; state: "done" | "doing" | "todo" }>;
  nextSteps?: Array<{ label: string; done: boolean }>;
};

export const TASK_TABS = ["Kanban", "Lijst", "Mijn taken", "Kalender", "Tijdlijn", "Analytics"] as const;

export const TASK_COLUMNS: Array<{
  id: TaskColumn;
  title: string;
  sub: string;
  tone: "blue" | "cyan" | "amber" | "green";
  icon: "list" | "play" | "clock" | "checkcircle";
}> = [
  { id: "open", title: "Open", sub: "Nog te starten", tone: "blue", icon: "list" },
  { id: "running", title: "In uitvoering", sub: "Actief in Work Runtime", tone: "cyan", icon: "play" },
  { id: "review", title: "Wacht op review", sub: "Klaar voor goedkeuring", tone: "amber", icon: "clock" },
  { id: "done", title: "Gereed", sub: "Afgerond & gearchiveerd", tone: "green", icon: "checkcircle" },
];

export const mockKanbanTasks: FinalBetaKanbanTask[] = [
  {
    id: "t-open-1",
    code: "TASK-2024-021",
    title: "Marktanalyse crypto Q4",
    description: "Macro-signalen, liquiditeit en correlaties voor Q4-strategie.",
    column: "open",
    priority: "Hoog",
    date: "18 sep 2026",
    tags: ["Trading", "Research"],
    owner: "Market Agent",
    type: "Analyse",
    created: "10 sep 2026, 09:12",
    deadline: "18 sep 2026",
  },
  {
    id: "t-open-2",
    code: "TASK-2024-022",
    title: "HADES-Chat fine-tuning",
    description: "Dataset-curatie en evaluatie voor chat-respons kwaliteit.",
    column: "open",
    priority: "Medium",
    date: "20 sep 2026",
    tags: ["LLM", "Training"],
    owner: "Training Agent",
    type: "Training",
    created: "11 sep 2026, 14:02",
    deadline: "20 sep 2026",
  },
  {
    id: "t-open-3",
    code: "TASK-2024-023",
    title: "Website content vernieuwen",
    description: "Landing, docs en feature-copy voor FINALBETA release.",
    column: "open",
    priority: "Laag",
    date: "22 sep 2026",
    tags: ["Media", "Content"],
    owner: "Content Agent",
    type: "Content",
    created: "12 sep 2026, 11:40",
    deadline: "22 sep 2026",
  },
  {
    id: "t-open-4",
    code: "TASK-2024-024",
    title: "Integratie externe data API",
    description: "Connector, rate limits en offline fallback valideren.",
    column: "open",
    priority: "Medium",
    date: "19 sep 2026",
    tags: ["Data", "API"],
    owner: "Data Agent",
    type: "Integratie",
    created: "9 sep 2026, 16:18",
    deadline: "19 sep 2026",
  },
  {
    id: "t-open-5",
    code: "TASK-2024-025",
    title: "Plugin permission audit",
    description: "Review van tool-scopes en sandboxed install paths.",
    column: "open",
    priority: "Medium",
    date: "21 sep 2026",
    tags: ["Runtime", "Security"],
    owner: "Security Agent",
    type: "Audit",
    created: "13 sep 2026, 08:55",
    deadline: "21 sep 2026",
  },
  {
    id: "t-open-6",
    code: "TASK-2024-026",
    title: "Voice intake pipeline",
    description: "Spraak-naar-taak parsing en confirm-flow afronden.",
    column: "open",
    priority: "Laag",
    date: "24 sep 2026",
    tags: ["Voice", "UX"],
    owner: "UX Agent",
    type: "Feature",
    created: "14 sep 2026, 13:20",
    deadline: "24 sep 2026",
  },
  {
    id: "t-run-1",
    code: "TASK-2024-017",
    title: "Dataset verwerking",
    description:
      "Verwerk en indexeer 142.6K documenten voor de HADES knowledge base. Inclusief chunking, embeddings en dedupe naar de Wereldkennis Database.",
    column: "running",
    priority: "Hoog",
    date: "12 sep 2026",
    tags: ["Data", "Knowledge"],
    progress: 65,
    owner: "Data Agent",
    type: "Data verwerking",
    created: "5 sep 2026, 10:24",
    deadline: "12 sep 2026",
    mission: { title: "Wereldkennis Database", sub: "Missie · Knowledge Core" },
    log: [
      { title: "Verwerking gestart", sub: "Batch A geïnitialiseerd", ago: "2u geleden", state: "done" },
      { title: "42.6K documenten verwerkt", sub: "Embedding pass 1/3", ago: "1u geleden", state: "done" },
      { title: "Index-opbouw actief", sub: "Chunk merge + dedupe", ago: "18m geleden", state: "doing" },
      { title: "Validatie wacht", sub: "Quality gate na batch B", ago: "gepland", state: "todo" },
    ],
    nextSteps: [
      { label: "Validatie afronden", done: false },
      { label: "Index optimaliseren", done: false },
      { label: "Rapport publiceren naar Knowledge", done: false },
    ],
  },
  {
    id: "t-run-2",
    code: "TASK-2024-018",
    title: "Trading strategie backtest",
    description: "Walk-forward backtest op paper ledger met risk caps.",
    column: "running",
    priority: "Hoog",
    date: "14 sep 2026",
    tags: ["Trading", "Lab"],
    progress: 42,
    owner: "Trading Agent",
    type: "Backtest",
    created: "6 sep 2026, 09:05",
    deadline: "14 sep 2026",
  },
  {
    id: "t-run-3",
    code: "TASK-2024-019",
    title: "Video content genereren",
    description: "Script, voiceover en render voor Media Control queue.",
    column: "running",
    priority: "Medium",
    date: "15 sep 2026",
    tags: ["Media", "Video"],
    progress: 28,
    owner: "Media Agent",
    type: "Productie",
    created: "7 sep 2026, 15:44",
    deadline: "15 sep 2026",
  },
  {
    id: "t-run-4",
    code: "TASK-2024-020",
    title: "Agent evaluatie",
    description: "Eval Lab suite voor planner/coder/research agents.",
    column: "running",
    priority: "Medium",
    date: "16 sep 2026",
    tags: ["Agents", "Eval"],
    progress: 51,
    owner: "Eval Agent",
    type: "Evaluatie",
    created: "8 sep 2026, 12:10",
    deadline: "16 sep 2026",
  },
  {
    id: "t-run-5",
    code: "TASK-2024-027",
    title: "Context compiler tuning",
    description: "Token budget en retrieval ranking herijken.",
    column: "running",
    priority: "Laag",
    date: "17 sep 2026",
    tags: ["Runtime", "Context"],
    progress: 18,
    owner: "Core Agent",
    type: "Optimalisatie",
    created: "12 sep 2026, 10:00",
    deadline: "17 sep 2026",
  },
  {
    id: "t-rev-1",
    code: "TASK-2024-011",
    title: "Onderzoeksrapport AI regulering",
    description: "Bronnen samengevoegd; wacht op human review.",
    column: "review",
    priority: "Hoog",
    date: "11 sep 2026",
    tags: ["Research", "Policy"],
    owner: "Research Agent",
    type: "Rapport",
    created: "1 sep 2026, 09:30",
    deadline: "11 sep 2026",
  },
  {
    id: "t-rev-2",
    code: "TASK-2024-012",
    title: "Model evaluatie resultaten",
    description: "Benchmark-set en scorecards ter goedkeuring.",
    column: "review",
    priority: "Medium",
    date: "12 sep 2026",
    tags: ["LLM", "Eval"],
    owner: "Eval Agent",
    type: "Review",
    created: "2 sep 2026, 11:15",
    deadline: "12 sep 2026",
  },
  {
    id: "t-rev-3",
    code: "TASK-2024-013",
    title: "UI/UX verbeteringen",
    description: "Taken-flow en inspector density review.",
    column: "review",
    priority: "Medium",
    date: "13 sep 2026",
    tags: ["UI", "UX"],
    owner: "UX Agent",
    type: "Design",
    created: "3 sep 2026, 16:45",
    deadline: "13 sep 2026",
  },
  {
    id: "t-rev-4",
    code: "TASK-2024-014",
    title: "Knowledge base update",
    description: "Nieuwe clusters en evidence-links ter validatie.",
    column: "review",
    priority: "Laag",
    date: "14 sep 2026",
    tags: ["Knowledge", "Brain"],
    owner: "Knowledge Agent",
    type: "Update",
    created: "4 sep 2026, 08:20",
    deadline: "14 sep 2026",
  },
  {
    id: "t-done-1",
    code: "TASK-2024-001",
    title: "HADES Core v0.9 deploy",
    description: "Release gate groen; deploy afgerond.",
    column: "done",
    priority: "Hoog",
    date: "8 sep 2026",
    tags: ["Core", "Release"],
    progress: 100,
    owner: "Ops Agent",
    type: "Deploy",
    created: "28 aug 2026, 10:00",
    deadline: "8 sep 2026",
  },
  {
    id: "t-done-2",
    code: "TASK-2024-002",
    title: "Data pipeline optimalisatie",
    description: "Throughput +38% na chunking rewrite.",
    column: "done",
    priority: "Medium",
    date: "7 sep 2026",
    tags: ["Data", "Perf"],
    progress: 100,
    owner: "Data Agent",
    type: "Optimalisatie",
    created: "25 aug 2026, 14:22",
    deadline: "7 sep 2026",
  },
  {
    id: "t-done-3",
    code: "TASK-2024-003",
    title: "Onderzoeksagent v1.2",
    description: "Citation hardening en offline fallback.",
    column: "done",
    priority: "Medium",
    date: "6 sep 2026",
    tags: ["Agents", "Research"],
    progress: 100,
    owner: "Research Agent",
    type: "Release",
    created: "20 aug 2026, 09:40",
    deadline: "6 sep 2026",
  },
  {
    id: "t-done-4",
    code: "TASK-2024-004",
    title: "Trading dashboard updates",
    description: "PnL tiles en strategy lab tabs live.",
    column: "done",
    priority: "Laag",
    date: "5 sep 2026",
    tags: ["Trading", "UI"],
    progress: 100,
    owner: "Trading Agent",
    type: "UI",
    created: "18 aug 2026, 13:05",
    deadline: "5 sep 2026",
  },
  {
    id: "t-done-5",
    code: "TASK-2024-005",
    title: "Chat handoff contract",
    description: "Dashboard → Chat payload contract vastgelegd.",
    column: "done",
    priority: "Medium",
    date: "4 sep 2026",
    tags: ["Chat", "API"],
    progress: 100,
    owner: "Core Agent",
    type: "Contract",
    created: "15 aug 2026, 11:11",
    deadline: "4 sep 2026",
  },
  {
    id: "t-done-6",
    code: "TASK-2024-006",
    title: "Native runtime handshake",
    description: "Bridge modes en diagnostics geverifieerd.",
    column: "done",
    priority: "Hoog",
    date: "3 sep 2026",
    tags: ["Native", "Runtime"],
    progress: 100,
    owner: "Ops Agent",
    type: "Infra",
    created: "12 aug 2026, 17:30",
    deadline: "3 sep 2026",
  },
  {
    id: "t-done-7",
    code: "TASK-2024-007",
    title: "Evidence vault import",
    description: "PDF/HTML ingest + hash chain ok.",
    column: "done",
    priority: "Laag",
    date: "2 sep 2026",
    tags: ["Evidence", "Files"],
    progress: 100,
    owner: "Knowledge Agent",
    type: "Import",
    created: "10 aug 2026, 10:50",
    deadline: "2 sep 2026",
  },
  {
    id: "t-done-8",
    code: "TASK-2024-008",
    title: "FINALBETA shell lock",
    description: "Topbar/sidebar geometry locked op 1672×941.",
    column: "done",
    priority: "Medium",
    date: "1 sep 2026",
    tags: ["UI", "FINALBETA"],
    progress: 100,
    owner: "UX Agent",
    type: "UI",
    created: "8 aug 2026, 12:00",
    deadline: "1 sep 2026",
  },
];

const MINE_IDS = new Set([
  "t-open-2",
  "t-open-5",
  "t-run-1",
  "t-run-5",
  "t-rev-3",
  "t-done-1",
  "t-done-5",
  "t-done-8",
]);

const BLOCKED_IDS = new Set(["t-open-5", "t-run-5"]);

const ESTIMATES: Record<string, string> = {
  "t-open-2": "6u",
  "t-open-5": "3u",
  "t-run-1": "12u",
  "t-run-5": "4u",
  "t-rev-3": "2u",
  "t-done-1": "8u",
  "t-done-5": "5u",
  "t-done-8": "10u",
};

const DEPS: Record<string, string[]> = {
  "t-open-2": ["t-done-5"],
  "t-run-1": ["t-done-2"],
  "t-run-5": ["t-run-1"],
  "t-rev-3": ["t-done-8"],
};

function inferProject(task: FinalBetaKanbanTask): { project: string; projectTone: TaskProjectTone } {
  const tags = task.tags.map((t) => t.toLowerCase());
  if (tags.some((t) => t.includes("trad") || t.includes("lab") || t.includes("market"))) {
    return { project: "Trading", projectTone: "trading" };
  }
  if (tags.some((t) => t.includes("research") || t.includes("policy") || t.includes("knowledge") || t.includes("evidence") || t.includes("brain"))) {
    return { project: "Research", projectTone: "research" };
  }
  if (tags.some((t) => t.includes("data") || t.includes("api") || t.includes("perf") || t.includes("dataset"))) {
    return { project: "Data", projectTone: "data" };
  }
  return { project: "Development", projectTone: "development" };
}

function parseCalDay(deadline: string): number | undefined {
  const m = deadline.match(/^(\d{1,2})\s+sep/i);
  return m ? Number(m[1]) : undefined;
}

/** Enrich kanban rows for list / mijn / kalender views (mutates in place once). */
for (const task of mockKanbanTasks) {
  const inferred = inferProject(task);
  task.project = task.project ?? inferred.project;
  task.projectTone = task.projectTone ?? inferred.projectTone;
  task.mine = MINE_IDS.has(task.id);
  task.blocked = BLOCKED_IDS.has(task.id);
  task.estimatedTime = ESTIMATES[task.id];
  task.dependencies = DEPS[task.id];
  task.calDay = parseCalDay(task.deadline) ?? parseCalDay(task.date);
}

export const LIST_STATUS_FILTERS: Array<{ id: "all" | TaskListStatus; label: string }> = [
  { id: "all", label: "Alle" },
  { id: "open", label: "Open" },
  { id: "running", label: "In uitvoering" },
  { id: "review", label: "Review" },
  { id: "done", label: "Gereed" },
  { id: "blocked", label: "Geblokkeerd" },
];

export const MY_TASK_CHIPS = ["Vandaag", "Aankomend", "Deze week", "Verlopen", "Geblokkeerd"] as const;

export type MyTaskChip = (typeof MY_TASK_CHIPS)[number];

export function listStatusOf(task: FinalBetaKanbanTask): TaskListStatus {
  return task.blocked ? "blocked" : task.column;
}

export function listStatusLabel(status: TaskListStatus): string {
  if (status === "open") return "Open";
  if (status === "running") return "In uitvoering";
  if (status === "review") return "Review";
  if (status === "done") return "Gereed";
  return "Geblokkeerd";
}

export const mockMySummary = {
  today: 3,
  overdue: 2,
  blocked: 2,
  completionPct: 62,
};

export type CalendarDeadline = {
  id: string;
  title: string;
  when: string;
  tone: TaskProjectTone;
};

export const mockUpcomingDeadlines: CalendarDeadline[] = [
  { id: "t-run-1", title: "Dataset verwerking", when: "12 sep · verlopen", tone: "data" },
  { id: "t-run-5", title: "Context compiler tuning", when: "17 sep · vandaag", tone: "development" },
  { id: "t-open-1", title: "Marktanalyse crypto Q4", when: "18 sep", tone: "trading" },
  { id: "t-open-4", title: "Integratie externe data API", when: "19 sep", tone: "data" },
  { id: "t-open-2", title: "HADES-Chat fine-tuning", when: "20 sep", tone: "development" },
];

export type SprintMilestone = {
  id: string;
  title: string;
  progress: number;
  tone: "gold" | "cyan" | "green" | "purple";
};

export const mockSprintMilestones: SprintMilestone[] = [
  { id: "sm1", title: "Sprint 1 — Core lock", progress: 100, tone: "green" },
  { id: "sm2", title: "Sprint 2 — Knowledge index", progress: 72, tone: "cyan" },
  { id: "sm3", title: "Sprint 3 — Agent eval", progress: 45, tone: "gold" },
  { id: "sm4", title: "Sprint 4 — FINALBETA polish", progress: 18, tone: "purple" },
];

export const mockMonthStats = {
  planned: 23,
  completed: 8,
  blocked: 2,
  hoursLogged: 94,
};

export type TimelineKind = "task" | "milestone" | "blocker";

export type TimelineItem = {
  id: string;
  title: string;
  kind: TimelineKind;
  startLabel: string;
  endLabel: string;
  /** Day offset from 1 Sep 2026 (inclusive start) */
  startDay: number;
  /** Inclusive end day offset from 1 Sep 2026 */
  endDay: number;
  progress: number;
  dependsOn?: string[];
  color: string;
};

export type TimelineGroup = {
  id: string;
  title: string;
  items: TimelineItem[];
};

export const mockTimelineGroups: TimelineGroup[] = [
  {
    id: "g-platform",
    title: "Platform Kern",
    items: [
      {
        id: "tl-core",
        title: "HADES Core v0.9 deploy",
        kind: "task",
        startLabel: "1 sep",
        endLabel: "8 sep",
        startDay: 1,
        endDay: 8,
        progress: 100,
        color: "#20e38d",
      },
      {
        id: "tl-native",
        title: "Native runtime handshake",
        kind: "task",
        startLabel: "28 aug",
        endLabel: "3 sep",
        startDay: 0,
        endDay: 3,
        progress: 100,
        color: "#4aa3ff",
      },
      {
        id: "tl-ms-core",
        title: "Core freeze",
        kind: "milestone",
        startLabel: "8 sep",
        endLabel: "8 sep",
        startDay: 8,
        endDay: 8,
        progress: 100,
        color: "#f0b429",
      },
    ],
  },
  {
    id: "g-ai",
    title: "AI & Agents",
    items: [
      {
        id: "tl-chat",
        title: "HADES-Chat fine-tuning",
        kind: "task",
        startLabel: "11 sep",
        endLabel: "20 sep",
        startDay: 11,
        endDay: 20,
        progress: 22,
        dependsOn: ["tl-context"],
        color: "#4aa3ff",
      },
      {
        id: "tl-context",
        title: "Context compiler tuning",
        kind: "blocker",
        startLabel: "12 sep",
        endLabel: "17 sep",
        startDay: 12,
        endDay: 17,
        progress: 18,
        color: "#ff6b6b",
      },
      {
        id: "tl-eval",
        title: "Agent evaluatie",
        kind: "task",
        startLabel: "8 sep",
        endLabel: "16 sep",
        startDay: 8,
        endDay: 16,
        progress: 51,
        color: "#a78bfa",
      },
      {
        id: "tl-ms-agents",
        title: "Eval gate",
        kind: "milestone",
        startLabel: "16 sep",
        endLabel: "16 sep",
        startDay: 16,
        endDay: 16,
        progress: 100,
        color: "#f0b429",
      },
    ],
  },
  {
    id: "g-data",
    title: "Data & Kennis",
    items: [
      {
        id: "tl-dataset",
        title: "Dataset verwerking",
        kind: "task",
        startLabel: "5 sep",
        endLabel: "12 sep",
        startDay: 5,
        endDay: 12,
        progress: 65,
        color: "#20e38d",
      },
      {
        id: "tl-api",
        title: "Integratie externe data API",
        kind: "task",
        startLabel: "9 sep",
        endLabel: "19 sep",
        startDay: 9,
        endDay: 19,
        progress: 30,
        dependsOn: ["tl-dataset"],
        color: "#20c8e8",
      },
      {
        id: "tl-kb",
        title: "Knowledge base update",
        kind: "task",
        startLabel: "4 sep",
        endLabel: "14 sep",
        startDay: 4,
        endDay: 14,
        progress: 80,
        color: "#a78bfa",
      },
      {
        id: "tl-ms-data",
        title: "Index live",
        kind: "milestone",
        startLabel: "14 sep",
        endLabel: "14 sep",
        startDay: 14,
        endDay: 14,
        progress: 100,
        color: "#f0b429",
      },
    ],
  },
  {
    id: "g-product",
    title: "Product & UI",
    items: [
      {
        id: "tl-shell",
        title: "FINALBETA shell lock",
        kind: "task",
        startLabel: "25 aug",
        endLabel: "1 sep",
        startDay: 0,
        endDay: 1,
        progress: 100,
        color: "#4aa3ff",
      },
      {
        id: "tl-ux",
        title: "UI/UX verbeteringen",
        kind: "task",
        startLabel: "3 sep",
        endLabel: "13 sep",
        startDay: 3,
        endDay: 13,
        progress: 70,
        dependsOn: ["tl-shell"],
        color: "#f0b429",
      },
      {
        id: "tl-content",
        title: "Website content vernieuwen",
        kind: "task",
        startLabel: "12 sep",
        endLabel: "22 sep",
        startDay: 12,
        endDay: 22,
        progress: 15,
        color: "#20c8e8",
      },
      {
        id: "tl-ms-ui",
        title: "UI review",
        kind: "milestone",
        startLabel: "13 sep",
        endLabel: "13 sep",
        startDay: 13,
        endDay: 13,
        progress: 100,
        color: "#ff6b6b",
      },
    ],
  },
];

/** Sprint banners across Sep–Dec 2026 (day offsets from 1 Sep). */
export const mockTimelineSprints: Array<{ id: string; label: string; startDay: number; endDay: number; color: string }> = [
  { id: "s1", label: "Sprint 1", startDay: 1, endDay: 14, color: "#20e38d" },
  { id: "s2", label: "Sprint 2", startDay: 15, endDay: 28, color: "#20c8e8" },
  { id: "s3", label: "Sprint 3", startDay: 29, endDay: 56, color: "#f0b429" },
  { id: "s4", label: "Sprint 4", startDay: 57, endDay: 90, color: "#a78bfa" },
];

/** Timeline span: Sep 1 → Dec 31 2026 ≈ 122 days. */
export const TIMELINE_TOTAL_DAYS = 122;
export const TIMELINE_TODAY_DAY = 17; // 17 sep 2026
export const TIMELINE_MONTHS = [
  { label: "Sep", startDay: 1, days: 30 },
  { label: "Okt", startDay: 31, days: 31 },
  { label: "Nov", startDay: 62, days: 30 },
  { label: "Dec", startDay: 92, days: 31 },
] as const;

/** @deprecated Kept for older FINALBETA stubs that still import mockTasks. */
export type FinalBetaTask = {
  id: string;
  title: string;
  phase: string;
  status: "running" | "queued" | "done" | "blocked";
  statusLabel: string;
};

export const mockTasks: FinalBetaTask[] = mockKanbanTasks.slice(0, 3).map((task) => ({
  id: task.id,
  title: task.title,
  phase: task.column === "running" ? "Uitvoering" : task.column === "review" ? "Review" : "Planning",
  status: task.column === "running" ? "running" : task.column === "done" ? "done" : "queued",
  statusLabel: task.column === "running" ? "Actief" : task.column === "done" ? "Gereed" : "Wachtrij",
}));
