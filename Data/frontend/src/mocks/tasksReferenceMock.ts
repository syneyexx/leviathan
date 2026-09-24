export type TaskPriority = "High" | "Medium" | "Low";
export type TaskColumn = "backlog" | "inProgress" | "review" | "done";

export type TaskCard = {
  id: string;
  column: TaskColumn;
  title: string;
  priority: TaskPriority;
  tag: string;
  description: string;
  assignee: string;
  assigneeRole?: string;
  date: string;
  progress?: number;
  project?: string;
  tags?: string[];
  created?: string;
  updated?: string;
  dueFull?: string;
  dueHint?: string;
  statusLabel?: string;
};

export type KpiItem = {
  id: string;
  label: string;
  value: string;
  icon: "layers" | "progress" | "warning" | "check" | "clock" | "robot";
  tone: "cyan" | "blue" | "red" | "green" | "orange";
  delta?: string;
};

export type AgentActivity = {
  id: string;
  name: string;
  status: string;
  confidence: number;
  detail: string;
  ago: string;
  tone: string;
};

export type FeedItem = {
  id: string;
  time: string;
  tone: string;
  parts: Array<{ text: string; emphasis?: boolean; quote?: boolean }>;
};

export type TimelineRow = {
  id: string;
  name: string;
  block: string;
  tone: string;
  start: number;
  span: number;
};

export const TASKS_KPIS: KpiItem[] = [
  { id: "active", label: "Active Tasks", value: "24", icon: "layers", tone: "cyan" },
  { id: "progress", label: "In Progress", value: "8", icon: "progress", tone: "blue" },
  { id: "blocked", label: "Blocked", value: "3", icon: "warning", tone: "red" },
  { id: "completed", label: "Completed Today", value: "12", icon: "check", tone: "green", delta: "↑ +33%" },
  { id: "overdue", label: "Overdue", value: "5", icon: "clock", tone: "orange" },
  { id: "agents", label: "AI Agents Assigned", value: "7", icon: "robot", tone: "cyan" },
];

export const TASKS_CARDS: TaskCard[] = [
  {
    id: "bl-1",
    column: "backlog",
    title: "Expand international market research",
    priority: "Low",
    tag: "Market Research",
    description: "Analyze key markets in APAC for 2025 expansion opportunities and competitive landscape.",
    assignee: "Research Agent",
    date: "Apr 28",
    progress: 0,
    project: "APAC Expansion",
    tags: ["Market Research", "APAC"],
    created: "Apr 10, 2025 9:00 AM",
    updated: "Apr 20, 2025 2:14 PM",
    dueFull: "Apr 28, 2025",
    statusLabel: "Backlog",
  },
  {
    id: "bl-2",
    column: "backlog",
    title: "Design mobile app experience",
    priority: "Medium",
    tag: "Product",
    description: "Create v2 wireframes and user flows for the mobile companion experience.",
    assignee: "Emma Park",
    assigneeRole: "Product Designer",
    date: "Apr 30",
    progress: 10,
    project: "Mobile App v2",
    tags: ["Product", "Mobile"],
    created: "Apr 12, 2025 11:20 AM",
    updated: "Apr 21, 2025 4:05 PM",
    dueFull: "Apr 30, 2025",
    statusLabel: "Backlog",
  },
  {
    id: "bl-3",
    column: "backlog",
    title: "Tax optimization strategy",
    priority: "Low",
    tag: "Finance",
    description: "Review international tax structures and propose optimization paths.",
    assignee: "Finance Agent",
    date: "May 2",
    progress: 5,
    project: "Financial Planning Q2",
    tags: ["Finance", "Tax"],
    created: "Apr 14, 2025 8:40 AM",
    updated: "Apr 22, 2025 1:12 PM",
    dueFull: "May 2, 2025",
    statusLabel: "Backlog",
  },
  {
    id: "ip-1",
    column: "inProgress",
    title: "Build Q2 financial model",
    priority: "High",
    tag: "Finance",
    description: "Update model with latest projections, cost structure, and scenario analysis.",
    assignee: "Alex Chen",
    assigneeRole: "Founder",
    date: "Apr 25",
    progress: 65,
    project: "Financial Planning Q2",
    tags: ["Finance", "Planning"],
    created: "Apr 15, 2025 10:24 AM",
    updated: "Apr 23, 2025 8:17 PM",
    dueFull: "Apr 25, 2025",
    dueHint: "(2 days left)",
    statusLabel: "In Progress",
  },
  {
    id: "ip-2",
    column: "inProgress",
    title: "Implement agent memory system",
    priority: "High",
    tag: "Platform",
    description: "Add long-term memory for agents across sessions and missions.",
    assignee: "Coding Agent",
    date: "Apr 26",
    progress: 45,
    project: "Agent Platform",
    tags: ["Platform", "Memory"],
    created: "Apr 16, 2025 9:10 AM",
    updated: "Apr 23, 2025 6:40 PM",
    dueFull: "Apr 26, 2025",
    dueHint: "(3 days left)",
    statusLabel: "In Progress",
  },
  {
    id: "ip-3",
    column: "inProgress",
    title: "Prepare investor update deck",
    priority: "Medium",
    tag: "Investors",
    description: "Q2 progress, traction, and roadmap for investor communications.",
    assignee: "Alex Chen",
    assigneeRole: "Founder",
    date: "Apr 24",
    progress: 80,
    project: "Investor Relations",
    tags: ["Investors", "Deck"],
    created: "Apr 17, 2025 3:00 PM",
    updated: "Apr 23, 2025 5:55 PM",
    dueFull: "Apr 24, 2025",
    dueHint: "(1 day left)",
    statusLabel: "In Progress",
  },
  {
    id: "rv-1",
    column: "review",
    title: "UI polish for dashboard v2",
    priority: "Medium",
    tag: "Design",
    description: "Final visual polish and animations for the operator dashboard.",
    assignee: "Emma Park",
    assigneeRole: "Product Designer",
    date: "Apr 23",
    progress: 90,
    project: "Dashboard v2",
    tags: ["Design", "UI"],
    created: "Apr 8, 2025 2:30 PM",
    updated: "Apr 23, 2025 5:24 PM",
    dueFull: "Apr 23, 2025",
    statusLabel: "Review",
  },
  {
    id: "rv-2",
    column: "review",
    title: "Legal review - partner agreement",
    priority: "High",
    tag: "Legal",
    description: "Review terms with counsel before partner signature.",
    assignee: "Sarah Kim",
    assigneeRole: "Legal Counsel",
    date: "Apr 22",
    progress: 100,
    project: "Partnerships",
    tags: ["Legal", "Contracts"],
    created: "Apr 5, 2025 10:00 AM",
    updated: "Apr 22, 2025 1:48 PM",
    dueFull: "Apr 22, 2025",
    statusLabel: "Review",
  },
  {
    id: "rv-3",
    column: "review",
    title: "Backtesting results analysis",
    priority: "Medium",
    tag: "Trading",
    description: "Analyze latest backtest results and surface risk findings.",
    assignee: "Trading Agent",
    date: "Apr 23",
    progress: 80,
    project: "Trading Desk",
    tags: ["Trading", "Backtest"],
    created: "Apr 18, 2025 7:45 AM",
    updated: "Apr 23, 2025 3:02 PM",
    dueFull: "Apr 23, 2025",
    statusLabel: "Review",
  },
  {
    id: "dn-1",
    column: "done",
    title: "Integrate Stripe payments",
    priority: "High",
    tag: "Platform",
    description: "Live in production with webhook reconciliation complete.",
    assignee: "Coding Agent",
    date: "Apr 20",
    progress: 100,
    project: "Billing Platform",
    tags: ["Platform", "Payments"],
    created: "Apr 1, 2025 9:00 AM",
    updated: "Apr 20, 2025 6:03 PM",
    dueFull: "Apr 20, 2025",
    statusLabel: "Done",
  },
  {
    id: "dn-2",
    column: "done",
    title: "Research AI infra providers",
    priority: "Medium",
    tag: "Research",
    description: "Completed provider analysis and shortlist recommendation.",
    assignee: "Research Agent",
    date: "Apr 21",
    progress: 100,
    project: "Infra Selection",
    tags: ["Research", "Infra"],
    created: "Apr 3, 2025 1:15 PM",
    updated: "Apr 21, 2025 4:40 PM",
    dueFull: "Apr 21, 2025",
    statusLabel: "Done",
  },
  {
    id: "dn-3",
    column: "done",
    title: "Create brand style guide",
    priority: "Low",
    tag: "Design",
    description: "Brand assets and guidelines complete for product surfaces.",
    assignee: "Emma Park",
    assigneeRole: "Product Designer",
    date: "Apr 19",
    progress: 100,
    project: "Brand System",
    tags: ["Design", "Brand"],
    created: "Mar 28, 2025 11:00 AM",
    updated: "Apr 19, 2025 3:20 PM",
    dueFull: "Apr 19, 2025",
    statusLabel: "Done",
  },
];

export const COLUMN_META: Record<
  TaskColumn,
  { title: string; count: number; tone: string; icon: "clipboard" | "layers" | "shield" | "check" }
> = {
  backlog: { title: "Backlog", count: 6, tone: "muted", icon: "clipboard" },
  inProgress: { title: "In Progress", count: 8, tone: "cyan", icon: "layers" },
  review: { title: "Review", count: 5, tone: "gold", icon: "shield" },
  done: { title: "Done", count: 12, tone: "green", icon: "check" },
};

export const AGENT_ACTIVITY: AgentActivity[] = [
  {
    id: "a1",
    name: "Research Agent",
    status: "Researching",
    confidence: 87,
    detail: "Gathering APAC market data...",
    ago: "12m",
    tone: "green",
  },
  {
    id: "a2",
    name: "Coding Agent",
    status: "Coding",
    confidence: 92,
    detail: "Implementing memory system...",
    ago: "28m",
    tone: "cyan",
  },
  {
    id: "a3",
    name: "Trading Agent",
    status: "Analyzing",
    confidence: 78,
    detail: "Running backtests (1,247 iterations)...",
    ago: "41m",
    tone: "gold",
  },
  {
    id: "a4",
    name: "Planning Agent",
    status: "Planning",
    confidence: 90,
    detail: "Generating task breakdown for Q2...",
    ago: "15m",
    tone: "purple",
  },
];

export const ACTIVITY_FEED: FeedItem[] = [
  {
    id: "f1",
    time: "8:17 PM",
    tone: "blue",
    parts: [
      { text: "Alex Chen", emphasis: true },
      { text: " updated " },
      { text: "Build Q2 financial model", quote: true },
      { text: " (65%)" },
    ],
  },
  {
    id: "f2",
    time: "6:03 PM",
    tone: "green",
    parts: [
      { text: "Coding Agent", emphasis: true },
      { text: " completed " },
      { text: "Integrate Stripe payments", quote: true },
    ],
  },
  {
    id: "f3",
    time: "5:24 PM",
    tone: "purple",
    parts: [
      { text: "Emma Park", emphasis: true },
      { text: " moved " },
      { text: "UI polish for dashboard v2", quote: true },
      { text: " to Review" },
    ],
  },
  {
    id: "f4",
    time: "4:11 PM",
    tone: "cyan",
    parts: [
      { text: "Planning Agent", emphasis: true },
      { text: " created 4 new tasks from project brief" },
    ],
  },
  {
    id: "f5",
    time: "3:02 PM",
    tone: "gold",
    parts: [
      { text: "Trading Agent", emphasis: true },
      { text: " completed " },
      { text: "Backtest analysis", quote: true },
    ],
  },
  {
    id: "f6",
    time: "1:48 PM",
    tone: "red",
    parts: [
      { text: "Sarah Kim", emphasis: true },
      { text: " added a note to " },
      { text: "Legal review - partner agreement", quote: true },
    ],
  },
  {
    id: "f7",
    time: "11:17 AM",
    tone: "green",
    parts: [
      { text: "Research Agent", emphasis: true },
      { text: " discovered 3 new market opportunities" },
    ],
  },
  {
    id: "f8",
    time: "9:03 AM",
    tone: "blue",
    parts: [
      { text: "Alex Chen", emphasis: true },
      { text: " assigned " },
      { text: "Tax optimization strategy", quote: true },
      { text: " to Finance Agent" },
    ],
  },
];

export const TIMELINE_ROWS: TimelineRow[] = [
  { id: "t1", name: "Alex Chen", block: "Q2 Financial Model", tone: "blue", start: 1, span: 3 },
  { id: "t2", name: "Emma Park", block: "UI Polish", tone: "purple", start: 2, span: 2 },
  { id: "t3", name: "Research Agent", block: "Market Research", tone: "green", start: 0, span: 3 },
  { id: "t4", name: "Coding Agent", block: "Agent Memory System", tone: "cyan", start: 2, span: 3 },
  { id: "t5", name: "Trading Agent", block: "Backtest Analysis", tone: "gold", start: 1, span: 2 },
];

export const WORKLOAD = [
  { name: "Alex Chen", count: 8, tone: "blue" },
  { name: "Emma Park", count: 6, tone: "purple" },
  { name: "Research Agent", count: 7, tone: "green" },
  { name: "Coding Agent", count: 5, tone: "cyan" },
  { name: "Trading Agent", count: 4, tone: "gold" },
] as const;

export const WEEKDAY_BARS = [42, 58, 71, 64, 88, 36, 28] as const;
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export const DEFAULT_SELECTED_TASK_ID = "ip-1";
