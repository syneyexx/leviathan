/** FINALBETA Plugin & Runtime — mock/demo data only (no live API claims). */

export const PR_PERF_KPIS = [
  {
    id: "cpu",
    label: "CPU",
    value: "34%",
    icon: "bolt",
    tone: "cyan" as const,
    progress: 34,
    hint: "8 cores · 3.8 GHz",
  },
  {
    id: "ram",
    label: "RAM",
    value: "32.1 / 64 GB",
    icon: "database",
    tone: "blue" as const,
    progress: 50,
    hint: "Workspace + models",
  },
  {
    id: "vram",
    label: "VRAM",
    value: "18.4 / 24 GB",
    icon: "chart",
    tone: "gold" as const,
    progress: 77,
    hint: "RTX 4090 · warm",
  },
  {
    id: "disk",
    label: "Disk",
    value: "412 GB free",
    icon: "folder",
    tone: "green" as const,
    progress: 28,
    hint: "NVMe · 1.8 TB",
  },
];

export const PR_PERF_SERVICES = [
  { id: "lms", name: "LM Studio", detail: ":1234", status: "OK", tone: "green" as const },
  { id: "api", name: "HADES API", detail: "local", status: "OK", tone: "green" as const },
  { id: "router", name: "Tool Router", detail: "strict policy", status: "OK", tone: "green" as const },
  { id: "train", name: "Training worker", detail: "job running", status: "Busy", tone: "gold" as const },
  { id: "mcp", name: "MCP Host", detail: "3 servers", status: "OK", tone: "green" as const },
  { id: "wf", name: "Workflow runner", detail: "idle queue", status: "Idle", tone: "blue" as const },
];

export const PR_PERF_PROCESSES = [
  { name: "hades-api", cpu: "6%", ram: "1.2 GB", gpu: "—", status: "Running" },
  { name: "lmstudio", cpu: "12%", ram: "8.4 GB", gpu: "14.2 GB", status: "Running" },
  { name: "tool-router", cpu: "2%", ram: "420 MB", gpu: "—", status: "Running" },
  { name: "training-worker", cpu: "28%", ram: "6.1 GB", gpu: "4.1 GB", status: "Busy" },
  { name: "mcp-host", cpu: "1%", ram: "180 MB", gpu: "—", status: "Running" },
];

export const PR_PERF_SERIES = {
  cpu: [22, 28, 31, 27, 34, 38, 36, 33, 29, 34, 37, 32, 30, 34],
  ram: [44, 46, 48, 47, 50, 52, 51, 49, 48, 50, 51, 50, 49, 50],
  vram: [62, 65, 68, 70, 72, 74, 76, 75, 73, 77, 78, 76, 75, 77],
};

export const PR_PERF_RUNTIME = [
  { k: "Status", v: "● Online", tone: "green" },
  { k: "Host", v: "DESKTOP-HADES" },
  { k: "Modus", v: "Lokaal / Offline-first" },
  { k: "UI", v: "FINALBETA Plugin Runtime" },
  { k: "Uptime", v: "28d 14h" },
];

export const PR_PERF_ACTIONS = [
  { id: "refresh", label: "Refresh", icon: "refresh", gold: false },
  { id: "runtime", label: "Open Work Runtime", icon: "bolt", gold: true },
  { id: "export", label: "Export metrics", icon: "download", gold: false },
  { id: "throttle", label: "Throttle training", icon: "pause", gold: false },
];

export const PR_PLUGIN_STATS = [
  { id: "total", label: "Plugins", value: "12", hint: "9 running · 3 idle" },
  { id: "router", label: "Tool Router", value: "Healthy", hint: "Strict local policy", tone: "green" as const },
  { id: "perms", label: "Permissions", value: "Strict", hint: "Offline-first" },
  { id: "updates", label: "Updates", value: "2", hint: "Beschikbaar" },
];

export const PR_PLUGINS = [
  {
    id: "ui-ux-pro-max",
    name: "ui-ux-pro-max",
    summary: "Design intelligence",
    category: "Design",
    status: "Running",
    tone: "green" as const,
    version: "1.4.2",
  },
  {
    id: "karpathy-skills",
    name: "karpathy-skills",
    summary: "Coding guidelines",
    category: "Coding",
    status: "Running",
    tone: "green" as const,
    version: "0.9.1",
  },
  {
    id: "web-fetch-local",
    name: "web-fetch-local",
    summary: "Optional network fetch",
    category: "Research",
    status: "Idle",
    tone: "blue" as const,
    version: "0.3.0",
  },
  {
    id: "evidence-vault",
    name: "evidence-vault",
    summary: "Research evidence store",
    category: "Research",
    status: "Running",
    tone: "green" as const,
    version: "2.1.0",
  },
  {
    id: "media-pipeline",
    name: "media-pipeline",
    summary: "Audio/video tools",
    category: "Media",
    status: "Running",
    tone: "green" as const,
    version: "1.2.8",
  },
  {
    id: "trading-agents",
    name: "trading-agents",
    summary: "Strategy helpers",
    category: "Trading",
    status: "Running",
    tone: "green" as const,
    version: "0.7.4",
  },
  {
    id: "no-ai-slop",
    name: "no-ai-slop",
    summary: "Writing quality gates",
    category: "Writing",
    status: "Idle",
    tone: "blue" as const,
    version: "1.0.0",
  },
  {
    id: "desktop-commander",
    name: "desktop-commander-mcp",
    summary: "Local desktop bridge",
    category: "Runtime",
    status: "Running",
    tone: "green" as const,
    version: "0.5.2",
  },
];

export const PR_PLUGIN_CATEGORIES = [
  { id: "design", label: "Design", count: 2, tone: "gold" as const },
  { id: "coding", label: "Coding", count: 3, tone: "cyan" as const },
  { id: "research", label: "Research", count: 4, tone: "blue" as const },
  { id: "media", label: "Media", count: 2, tone: "purple" as const },
  { id: "trading", label: "Trading", count: 1, tone: "green" as const },
];

export const PR_PLUGIN_ACTIONS = [
  { id: "import", label: "Import .HadesPlugin", icon: "download", gold: false },
  { id: "install", label: "Install package", icon: "plus", gold: true },
  { id: "router", label: "Open Tool Router", icon: "link", gold: false },
  { id: "refresh", label: "Refresh status", icon: "refresh", gold: false },
];

export const PR_MCP_SERVERS = [
  {
    id: "filesystem",
    name: "filesystem",
    transport: "stdio · local workspace",
    status: "Connected",
    tone: "green" as const,
    tools: 3,
  },
  {
    id: "browser",
    name: "browser",
    transport: "optional · needsAuth",
    status: "Idle",
    tone: "gold" as const,
    tools: 5,
  },
  {
    id: "memory",
    name: "memory",
    transport: "HADES memory bridge",
    status: "Connected",
    tone: "green" as const,
    tools: 4,
  },
  {
    id: "desktop",
    name: "desktop-commander",
    transport: "stdio · host bridge",
    status: "Connected",
    tone: "green" as const,
    tools: 8,
  },
];

export const PR_MCP_TOOLS: Record<
  string,
  Array<{ id: string; name: string; policy: string; tone: "green" | "gold" | "blue" }>
> = {
  filesystem: [
    { id: "read_file", name: "read_file", policy: "allowed", tone: "green" },
    { id: "write_file", name: "write_file", policy: "confirm", tone: "gold" },
    { id: "list_dir", name: "list_dir", policy: "allowed", tone: "green" },
  ],
  browser: [
    { id: "navigate", name: "navigate", policy: "confirm", tone: "gold" },
    { id: "screenshot", name: "screenshot", policy: "allowed", tone: "green" },
    { id: "click", name: "click", policy: "confirm", tone: "gold" },
  ],
  memory: [
    { id: "memory_search", name: "memory_search", policy: "allowed", tone: "green" },
    { id: "memory_write", name: "memory_write", policy: "confirm", tone: "gold" },
    { id: "memory_list", name: "memory_list", policy: "allowed", tone: "green" },
  ],
  desktop: [
    { id: "run_command", name: "run_command", policy: "confirm", tone: "gold" },
    { id: "read_clipboard", name: "read_clipboard", policy: "allowed", tone: "green" },
    { id: "notify", name: "notify", policy: "allowed", tone: "green" },
  ],
};

export const PR_MCP_ACTIONS = [
  { id: "add", label: "Add server", icon: "plus", gold: true },
  { id: "refresh", label: "Refresh", icon: "refresh", gold: false },
  { id: "policy", label: "Edit policy", icon: "shield", gold: false },
  { id: "catalog", label: "Open catalog", icon: "book", gold: false },
];

export const PR_WORKFLOWS = [
  {
    id: "ingest",
    name: "Ingest → Brain → Chat",
    nodes: 3,
    status: "Ready",
    tone: "green" as const,
    lastRun: "Vandaag 11:02",
  },
  {
    id: "train",
    name: "Train → Eval → Report",
    nodes: 5,
    status: "Idle",
    tone: "blue" as const,
    lastRun: "Gisteren 18:40",
  },
  {
    id: "media",
    name: "Media export pack",
    nodes: 4,
    status: "Ready",
    tone: "green" as const,
    lastRun: "2d geleden",
  },
  {
    id: "research",
    name: "Research → Evidence → Memory",
    nodes: 4,
    status: "Draft",
    tone: "gold" as const,
    lastRun: "Nooit",
  },
];

export const PR_FLOW_NODES = [
  { id: "n1", title: "Ingest files", role: "Trigger", x: 24, y: 48, gold: true },
  { id: "n2", title: "Dataset Brain", role: "Index", x: 210, y: 120, gold: false },
  { id: "n3", title: "Notify Chat", role: "Output", x: 400, y: 48, gold: false },
];

export const PR_WORKFLOW_ACTIONS = [
  { id: "run", label: "Run", icon: "play", gold: false },
  { id: "new", label: "+ Workflow", icon: "plus", gold: true },
  { id: "validate", label: "Validate", icon: "check", gold: false },
  { id: "history", label: "Run history", icon: "clock", gold: false },
];

export const PR_CONSOLE_BUILD = [
  { k: "App", v: "HADES FINALBETA" },
  { k: "UI revision", v: "Plugin Runtime v0.9" },
  { k: "Node", v: "local" },
  { k: "OS", v: "Windows 11" },
  { k: "Python", v: "3.12 · venv" },
  { k: "Build", v: "23df48f" },
];

export const PR_CONSOLE_HEALTH = [
  { name: "API reachability", status: "OK", tone: "green" as const },
  { name: "LM Studio", status: "OK", tone: "green" as const },
  { name: "Persistence", status: "OK", tone: "green" as const },
  { name: "Plugin runtime", status: "OK", tone: "green" as const },
  { name: "MCP host", status: "OK", tone: "green" as const },
  { name: "Network (optional)", status: "Skipped", tone: "blue" as const },
];

export const PR_CONSOLE_LOGS = [
  "[14:22:01] training.worker job=run-20241114-1422 started",
  "[14:22:08] atme.planner strategy=adaptive confidence=0.92",
  "[14:28:16] training.worker step=2480 loss=0.842 vram=13.6",
  "[14:31:02] tool_router policy=strict allow=fs,memory deny=shell",
  "[14:33:44] mcp.host server=filesystem status=connected tools=3",
  "[14:36:11] workflow.runner idle queue=0 last=ingest→brain→chat",
  "[14:38:55] performance.sample cpu=34% ram=50% vram=77%",
];

export const PR_CONSOLE_ACTIONS = [
  { id: "export", label: "Export diagnostics", icon: "download", gold: true },
  { id: "refresh", label: "Refresh", icon: "refresh", gold: false },
  { id: "clear", label: "Clear console", icon: "trash", gold: false },
  { id: "runtime", label: "Open Work Runtime", icon: "bolt", gold: false },
];
