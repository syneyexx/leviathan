/** Plugin & Runtime — mock/demo data locked to screenshot references. */

export type PrTone = "ok" | "warn" | "err" | "muted" | "gold" | "cyan";
export type PrBarTone = "ok" | "cyan" | "gold" | "warn" | "err";

/* ─── Performance ─── */

export const PERF_KPIS = [
  {
    id: "cpu",
    label: "CPU gebruik",
    value: "32%",
    delta: "-12%",
    deltaGood: true,
    spark: [44, 41, 38, 40, 36, 34, 35, 33, 31, 34, 32, 30, 33, 32],
  },
  {
    id: "ram",
    label: "RAM gebruik",
    value: "18.4 GB",
    sub: "van 64 GB",
    pct: 29,
    barTone: "cyan" as PrBarTone,
  },
  {
    id: "gpu",
    label: "GPU / Accelerator",
    value: "41%",
    sub: "A100 40 GB · 24.6 GB",
    spark: [28, 32, 36, 34, 38, 40, 39, 42, 41, 43, 40, 41],
  },
  {
    id: "workers",
    label: "Actieve workers",
    value: "24",
    sub: "van 32",
    delta: "+2",
    deltaGood: true,
    pct: 75,
    barTone: "cyan" as PrBarTone,
  },
  {
    id: "queue",
    label: "Queue diepte",
    value: "18",
    delta: "-36%",
    deltaGood: true,
    spark: [42, 38, 35, 30, 28, 24, 22, 20, 19, 18, 17, 18],
  },
  {
    id: "latency",
    label: "Gem. latentie",
    value: "245 ms",
    delta: "-28%",
    deltaGood: true,
    spark: [340, 320, 300, 290, 280, 270, 260, 255, 250, 248, 246, 245],
  },
  {
    id: "throughput",
    label: "Throughput",
    value: "482",
    sub: "req/min",
    delta: "+18%",
    deltaGood: true,
    spark: [360, 380, 400, 410, 430, 440, 450, 460, 470, 475, 480, 482],
  },
  {
    id: "error",
    label: "Error rate",
    value: "0.3%",
    delta: "-0.2%",
    deltaGood: true,
    warn: true,
    spark: [0.8, 0.7, 0.6, 0.55, 0.5, 0.45, 0.4, 0.38, 0.35, 0.32, 0.3, 0.3],
  },
] as const;

export const PERF_TOOLS = [
  { id: "live", label: "Live monitoring", active: true },
  { id: "profile", label: "Profiling sessie starten", active: false },
  { id: "cache", label: "Cache legen", active: false },
  { id: "worker", label: "Worker herstarten", active: false },
  { id: "diag", label: "Diagnostiek exporteren", active: false },
  { id: "concurrency", label: "Concurrentie afstemmen", active: false },
  { id: "pause", label: "Achtergrondtaken pauzeren", active: false },
] as const;

export type PerfComponentStatus = "Gezond" | "Belast" | "Waarschuwing";

export const PERF_COMPONENTS: Array<{
  id: string;
  name: string;
  type: string;
  status: PerfComponentStatus;
  statusTone: PrTone;
  avgLatency: string;
  p95Latency: string;
  throughput: string;
  memory: string;
  cpu: string;
  errors: number;
  lastActive: string;
}> = [
  {
    id: "mcp-bridge",
    name: "mcp-bridge",
    type: "Bridge",
    status: "Gezond",
    statusTone: "ok",
    avgLatency: "120 ms",
    p95Latency: "210 ms",
    throughput: "84 req/min",
    memory: "512 MB",
    cpu: "8%",
    errors: 0,
    lastActive: "2s geleden",
  },
  {
    id: "tools-runtime",
    name: "tools-runtime",
    type: "Runtime",
    status: "Gezond",
    statusTone: "ok",
    avgLatency: "95 ms",
    p95Latency: "180 ms",
    throughput: "112 req/min",
    memory: "640 MB",
    cpu: "11%",
    errors: 0,
    lastActive: "1s geleden",
  },
  {
    id: "function-runtime",
    name: "function-runtime",
    type: "Runtime",
    status: "Gezond",
    statusTone: "ok",
    avgLatency: "75 ms",
    p95Latency: "140 ms",
    throughput: "156 req/min",
    memory: "420 MB",
    cpu: "6%",
    errors: 0,
    lastActive: "3s geleden",
  },
  {
    id: "job-runtime",
    name: "job-runtime",
    type: "Runtime",
    status: "Belast",
    statusTone: "warn",
    avgLatency: "420 ms",
    p95Latency: "1.2 s",
    throughput: "28 req/min",
    memory: "2.8 GB",
    cpu: "28%",
    errors: 3,
    lastActive: "4s geleden",
  },
  {
    id: "knowledge-sync",
    name: "knowledge-sync",
    type: "Sync",
    status: "Waarschuwing",
    statusTone: "err",
    avgLatency: "520 ms",
    p95Latency: "1.6 s",
    throughput: "22 req/min",
    memory: "2.1 GB",
    cpu: "24%",
    errors: 5,
    lastActive: "8s geleden",
  },
  {
    id: "module-manager",
    name: "module-manager",
    type: "Core",
    status: "Gezond",
    statusTone: "ok",
    avgLatency: "88 ms",
    p95Latency: "160 ms",
    throughput: "64 req/min",
    memory: "380 MB",
    cpu: "5%",
    errors: 0,
    lastActive: "5s geleden",
  },
  {
    id: "coding-worker",
    name: "coding-worker",
    type: "Worker",
    status: "Gezond",
    statusTone: "ok",
    avgLatency: "145 ms",
    p95Latency: "280 ms",
    throughput: "48 req/min",
    memory: "1.1 GB",
    cpu: "14%",
    errors: 1,
    lastActive: "6s geleden",
  },
  {
    id: "media-pipeline",
    name: "media-pipeline",
    type: "Pipeline",
    status: "Gezond",
    statusTone: "ok",
    avgLatency: "210 ms",
    p95Latency: "390 ms",
    throughput: "36 req/min",
    memory: "980 MB",
    cpu: "9%",
    errors: 0,
    lastActive: "12s geleden",
  },
];

export const PERF_HOT_PATHS = [
  {
    id: "document.index",
    name: "document.index",
    avg: "1.28 s",
    count: 142,
    spark: [0.8, 0.9, 1.0, 1.1, 1.05, 1.2, 1.15, 1.28, 1.22, 1.3, 1.25, 1.28],
  },
  {
    id: "vector.search",
    name: "vector.search",
    avg: "892 ms",
    count: 318,
    spark: [0.6, 0.7, 0.75, 0.8, 0.78, 0.85, 0.82, 0.9, 0.88, 0.91, 0.89, 0.892],
  },
  {
    id: "knowledge.sync",
    name: "knowledge.sync",
    avg: "760 ms",
    count: 64,
    spark: [0.5, 0.55, 0.6, 0.65, 0.7, 0.72, 0.68, 0.74, 0.76, 0.75, 0.78, 0.76],
  },
  {
    id: "job.dispatch",
    name: "job.dispatch",
    avg: "540 ms",
    count: 210,
    spark: [0.4, 0.42, 0.45, 0.48, 0.5, 0.52, 0.49, 0.53, 0.55, 0.54, 0.56, 0.54],
  },
  {
    id: "mcp.bridge.call",
    name: "mcp.bridge.call",
    avg: "310 ms",
    count: 482,
    spark: [0.28, 0.3, 0.29, 0.31, 0.32, 0.3, 0.33, 0.31, 0.3, 0.32, 0.31, 0.31],
  },
] as const;

export const PERF_WORKER_POOLS: Array<{
  id: string;
  name: string;
  active: number;
  max: number;
  queue: number;
  pct: number;
  barTone: PrBarTone;
}> = [
  { id: "mcp", name: "MCP", active: 6, max: 8, queue: 2, pct: 75, barTone: "cyan" },
  { id: "tools", name: "Tools", active: 8, max: 10, queue: 12, pct: 80, barTone: "gold" },
  { id: "function", name: "Function", active: 4, max: 6, queue: 1, pct: 67, barTone: "cyan" },
  { id: "job", name: "Job", active: 4, max: 4, queue: 18, pct: 100, barTone: "err" },
  { id: "coding", name: "Coding", active: 2, max: 4, queue: 3, pct: 50, barTone: "cyan" },
];

export const PERF_HEALTH = [
  { id: "mcp-bridge", name: "mcp-bridge", status: "Gezond" as const, tone: "ok" as PrTone, spark: [70, 72, 74, 73, 75, 76, 78, 77, 79, 80, 78, 82] },
  { id: "tools-runtime", name: "tools-runtime", status: "Gezond" as const, tone: "ok" as PrTone, spark: [68, 70, 71, 72, 74, 73, 75, 76, 74, 77, 78, 79] },
  { id: "function-runtime", name: "function-runtime", status: "Gezond" as const, tone: "ok" as PrTone, spark: [72, 74, 75, 76, 78, 77, 79, 80, 81, 80, 82, 83] },
  { id: "job-runtime", name: "job-runtime", status: "Belast" as const, tone: "warn" as PrTone, spark: [55, 52, 50, 48, 46, 44, 42, 40, 38, 36, 35, 34] },
  { id: "knowledge-sync", name: "knowledge-sync", status: "Waarschuwing" as const, tone: "err" as PrTone, spark: [50, 48, 45, 42, 40, 38, 35, 32, 30, 28, 26, 24] },
  { id: "module-manager", name: "module-manager", status: "Gezond" as const, tone: "ok" as PrTone, spark: [80, 81, 82, 83, 84, 83, 85, 86, 85, 87, 86, 88] },
] as const;

export const PERF_CACHE_IO = [
  { id: "hit", label: "Cache hit rate", value: "87%", pct: 87, spark: [78, 80, 82, 81, 84, 85, 86, 85, 87, 86, 88, 87] },
  { id: "disk", label: "Schijfruimte", value: "42 GB / 200 GB", pct: 21, spark: [18, 19, 19, 20, 20, 21, 21, 20, 21, 22, 21, 21] },
  { id: "io", label: "I/O operaties", value: "1.2k/s", pct: 42, spark: [30, 34, 38, 36, 40, 42, 39, 44, 41, 43, 40, 42] },
] as const;

export const PERF_RESOURCE_ALLOC = [
  { id: "concurrency", label: "Concurrentie (globaal)", current: "16", max: "32" },
  { id: "mcp-workers", label: "MCP workers", current: "6", max: "8" },
  { id: "tools-workers", label: "Tools workers", current: "8", max: "10" },
  { id: "job-workers", label: "Job workers", current: "4", max: "4" },
  { id: "coding-workers", label: "Coding workers", current: "2", max: "4" },
  { id: "queue-limit", label: "Queue limiet", current: "64", max: "128" },
] as const;

export const PERF_ALERTS = [
  {
    id: "a1",
    time: "14:26",
    tone: "warn" as PrTone,
    label: "Waarschuwing",
    message: "Job runtime hoge latentie",
  },
  {
    id: "a2",
    time: "14:18",
    tone: "warn" as PrTone,
    label: "Waarschuwing",
    message: "Tools worker queue > 10",
  },
  {
    id: "a3",
    time: "14:05",
    tone: "err" as PrTone,
    label: "Fout",
    message: "knowledge-sync fouten (5x)",
  },
  {
    id: "a4",
    time: "13:52",
    tone: "warn" as PrTone,
    label: "Waarschuwing",
    message: "Cache miss spike op vector store",
  },
] as const;

/* ─── MCP ─── */

export const MCP_KPIS = [
  {
    id: "servers",
    label: "Totaal servers",
    value: "9",
    delta: "+1",
    deltaGood: true,
    spark: [6, 6, 7, 7, 8, 8, 8, 9, 9, 9, 9, 9],
  },
  {
    id: "connected",
    label: "Verbonden servers",
    value: "7",
    sub: "78%",
    pct: 78,
    barTone: "ok" as PrBarTone,
  },
  {
    id: "tools",
    label: "Ontdekte tools",
    value: "86",
    delta: "+12",
    deltaGood: true,
    spark: [60, 64, 68, 70, 72, 74, 76, 78, 80, 82, 84, 86],
  },
  {
    id: "sessions",
    label: "Actieve sessies",
    value: "24",
    delta: "+8",
    deltaGood: true,
    spark: [12, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 24],
  },
  {
    id: "throughput",
    label: "Call throughput",
    value: "482",
    sub: "req/min",
    delta: "+18%",
    deltaGood: true,
    spark: [360, 380, 400, 420, 440, 450, 460, 470, 475, 480, 482, 482],
  },
  {
    id: "approval",
    label: "Goedkeuring vereist",
    value: "3",
    delta: "-40%",
    deltaGood: true,
    warn: true,
  },
  {
    id: "error",
    label: "Foutpercentage",
    value: "0.3%",
    delta: "-0.2%",
    deltaGood: true,
    warn: true,
  },
  {
    id: "latency",
    label: "Gem. latentie",
    value: "245 ms",
    delta: "-22%",
    deltaGood: true,
    spark: [320, 300, 290, 280, 270, 265, 260, 255, 250, 248, 246, 245],
  },
] as const;

export type McpServerStatus = "Verbonden" | "Fout";

export const MCP_SERVERS: Array<{
  id: string;
  name: string;
  transport: "stdio" | "http";
  status: McpServerStatus;
  statusTone: PrTone;
  enabled: boolean;
  tools: number;
  lastHealth: string;
  isolation: string;
  lastError: string;
}> = [
  {
    id: "filesystem",
    name: "filesystem",
    transport: "stdio",
    status: "Verbonden",
    statusTone: "ok",
    enabled: true,
    tools: 12,
    lastHealth: "12s geleden",
    isolation: "Sandbox",
    lastError: "—",
  },
  {
    id: "git",
    name: "git",
    transport: "stdio",
    status: "Verbonden",
    statusTone: "ok",
    enabled: true,
    tools: 9,
    lastHealth: "18s geleden",
    isolation: "Workspace",
    lastError: "—",
  },
  {
    id: "fetch",
    name: "fetch",
    transport: "http",
    status: "Verbonden",
    statusTone: "ok",
    enabled: true,
    tools: 5,
    lastHealth: "8s geleden",
    isolation: "Netwerk",
    lastError: "—",
  },
  {
    id: "github",
    name: "github",
    transport: "http",
    status: "Verbonden",
    statusTone: "ok",
    enabled: true,
    tools: 16,
    lastHealth: "22s geleden",
    isolation: "Netwerk",
    lastError: "—",
  },
  {
    id: "browser",
    name: "browser",
    transport: "http",
    status: "Verbonden",
    statusTone: "ok",
    enabled: true,
    tools: 11,
    lastHealth: "15s geleden",
    isolation: "Geïsoleerd",
    lastError: "—",
  },
  {
    id: "postgres",
    name: "postgres",
    transport: "stdio",
    status: "Verbonden",
    statusTone: "ok",
    enabled: true,
    tools: 7,
    lastHealth: "30s geleden",
    isolation: "Sandbox",
    lastError: "—",
  },
  {
    id: "memory",
    name: "memory",
    transport: "stdio",
    status: "Verbonden",
    statusTone: "ok",
    enabled: true,
    tools: 6,
    lastHealth: "9s geleden",
    isolation: "Workspace",
    lastError: "—",
  },
  {
    id: "docs",
    name: "docs",
    transport: "http",
    status: "Verbonden",
    statusTone: "ok",
    enabled: false,
    tools: 8,
    lastHealth: "2m geleden",
    isolation: "Alleen lezen",
    lastError: "—",
  },
  {
    id: "local-python",
    name: "local-python",
    transport: "stdio",
    status: "Fout",
    statusTone: "err",
    enabled: true,
    tools: 4,
    lastHealth: "1m geleden",
    isolation: "Sandbox",
    lastError: "Python niet gevonden",
  },
];

export const MCP_BRIDGE = {
  title: "LEVIATHAN MCP BRIDGE v1.2.0",
  status: "Operationeel",
  statusTone: "ok" as PrTone,
  uptime: "6d 14h 27m",
  sessions: 24,
  activeServers: "7/9",
  transportMix: [
    { id: "stdio", label: "stdio", pct: 56, tone: "cyan" as PrBarTone },
    { id: "http", label: "http", pct: 44, tone: "cyan" as PrBarTone },
  ],
  healthPct: 100,
} as const;

export const MCP_TOOL_CATALOG = [
  {
    id: "read_file",
    name: "mcp.filesystem.read_file",
    server: "filesystem",
    description: "Lees bestand uit workspace sandbox",
  },
  {
    id: "write_file",
    name: "mcp.filesystem.write_file",
    server: "filesystem",
    description: "Schrijf bestand met goedkeuring",
  },
  {
    id: "git_status",
    name: "mcp.git.status",
    server: "git",
    description: "Toon git status van de repo",
  },
  {
    id: "fetch_url",
    name: "mcp.fetch.get",
    server: "fetch",
    description: "Haal HTTP inhoud op",
  },
  {
    id: "create_issue",
    name: "mcp.github.create_issue",
    server: "github",
    description: "Maak GitHub issue aan",
  },
  {
    id: "browser_nav",
    name: "mcp.browser.navigate",
    server: "browser",
    description: "Navigeer naar URL in isolatie",
  },
  {
    id: "pg_query",
    name: "mcp.postgres.query",
    server: "postgres",
    description: "Voer alleen-lezen SQL query uit",
  },
  {
    id: "memory_search",
    name: "mcp.memory.search",
    server: "memory",
    description: "Zoek in runtime geheugen",
  },
] as const;

export const MCP_AUTH_SUMMARY = [
  { id: "discovered", label: "Ontdekte tools", value: "86" },
  { id: "authorized", label: "Geautoriseerd", value: "73", tone: "ok" as PrTone },
  { id: "queued", label: "In wachtrij", value: "3", tone: "err" as PrTone },
  { id: "blocked", label: "Geblokkeerd", value: "2", tone: "err" as PrTone },
] as const;

export const MCP_AUTH_POLICIES = [
  { id: "fs", label: "Bestandssysteem", value: "Vragen bij schrijven" },
  { id: "code", label: "Code uitvoeren", value: "Alleen sandbox" },
  { id: "net", label: "Netwerk", value: "Toegestane hosts" },
  { id: "git", label: "Git push", value: "Altijd vragen" },
  { id: "db", label: "Database", value: "Alleen lezen" },
] as const;

export const MCP_RECENT_CALLS = [
  {
    id: "c1",
    time: "14:25:42",
    tool: "mcp.github.create_issue",
    requester: "research-agent",
    duration: "842 ms",
    status: "Success",
    statusTone: "ok" as PrTone,
  },
  {
    id: "c2",
    time: "14:25:18",
    tool: "mcp.filesystem.read_file",
    requester: "coding-agent",
    duration: "48 ms",
    status: "Success",
    statusTone: "ok" as PrTone,
  },
  {
    id: "c3",
    time: "14:24:55",
    tool: "mcp.browser.navigate",
    requester: "media-agent",
    duration: "1.2 s",
    status: "Success",
    statusTone: "ok" as PrTone,
  },
  {
    id: "c4",
    time: "14:24:12",
    tool: "mcp.fetch.get",
    requester: "research-agent",
    duration: "3.4 s",
    status: "Timeout",
    statusTone: "err" as PrTone,
  },
  {
    id: "c5",
    time: "14:23:40",
    tool: "mcp.memory.search",
    requester: "chat",
    duration: "112 ms",
    status: "Success",
    statusTone: "ok" as PrTone,
  },
  {
    id: "c6",
    time: "14:22:58",
    tool: "mcp.postgres.query",
    requester: "analytics",
    duration: "265 ms",
    status: "Success",
    statusTone: "ok" as PrTone,
  },
] as const;

export const MCP_TRANSPORTS = [
  {
    id: "stdio",
    label: "STDIO Transport",
    servers: 4,
    latency: "120 ms",
    status: "Actief",
    statusTone: "ok" as PrTone,
  },
  {
    id: "http",
    label: "HTTP Transport",
    servers: 5,
    latency: "380 ms",
    status: "Actief",
    statusTone: "ok" as PrTone,
  },
] as const;

export const MCP_ALERTS = [
  {
    id: "a1",
    time: "14:21",
    tone: "err" as PrTone,
    label: "Fout",
    message: "local-python: Python niet gevonden",
  },
  {
    id: "a2",
    time: "14:12",
    tone: "warn" as PrTone,
    label: "Waarschuwing",
    message: "fetch timeout op externe host",
  },
  {
    id: "a3",
    time: "13:58",
    tone: "cyan" as PrTone,
    label: "Info",
    message: "3 nieuwe tools ontdekt via github",
  },
  {
    id: "a4",
    time: "13:40",
    tone: "warn" as PrTone,
    label: "Waarschuwing",
    message: "Goedkeuring wachtrij > 2",
  },
] as const;

export const MCP_QUICK_ACTIONS = [
  { id: "add", label: "Server toevoegen" },
  { id: "rediscover", label: "Tools herontdekken" },
  { id: "restart", label: "Bridge herstarten" },
  { id: "config", label: "Configuratie openen" },
] as const;

/* ─── Console ─── */

export const CONSOLE_STATUS_CARDS = [
  {
    id: "system",
    label: "System status",
    value: "All systems operational",
    tone: "ok" as PrTone,
  },
  {
    id: "uptime",
    label: "Uptime",
    value: "3d 14h 27m",
  },
  {
    id: "lograte",
    label: "Log rate",
    value: "128 lines/s",
  },
  {
    id: "processes",
    label: "Active processes",
    value: "12",
  },
] as const;

export const CONSOLE_LOG_TABS = [
  "System Logs",
  "Runtime",
  "Agents",
  "Plugins",
  "Training",
  "MCP",
  "LLM",
  "Errors",
] as const;

export type ConsoleLogLevel = "INFO" | "SUCCESS" | "WARNING" | "ERROR";

export const CONSOLE_LOG_LINES: Array<{
  id: string;
  time: string;
  level: ConsoleLogLevel;
  message: string;
}> = [
  { id: "l1", time: "2026-09-22 14:37:12", level: "INFO", message: "HADES runtime initialized" },
  { id: "l2", time: "2026-09-22 14:37:12", level: "INFO", message: "Loading configuration from config.yaml" },
  { id: "l3", time: "2026-09-22 14:37:13", level: "INFO", message: "Plugin manager started (12 plugins)" },
  { id: "l4", time: "2026-09-22 14:37:14", level: "INFO", message: "MCP server listening on port 8765" },
  { id: "l5", time: "2026-09-22 14:37:15", level: "INFO", message: "Model manager ready" },
  { id: "l6", time: "2026-09-22 14:37:15", level: "SUCCESS", message: "All systems operational" },
  { id: "l7", time: "2026-09-22 14:38:01", level: "INFO", message: "Agent 'research' started (pid: 12432)" },
  { id: "l8", time: "2026-09-22 14:38:02", level: "INFO", message: "Agent 'coding' started (pid: 12456)" },
  { id: "l9", time: "2026-09-22 14:38:03", level: "INFO", message: "Agent 'trading' started (pid: 12478)" },
  {
    id: "l10",
    time: "2026-09-22 14:41:17",
    level: "INFO",
    message: "Dataset loaded: jtatman/combined_coder_python (12,430 samples)",
  },
  { id: "l11", time: "2026-09-22 14:41:18", level: "INFO", message: "Training job created: train_7f3d2a1b" },
  { id: "l12", time: "2026-09-22 14:41:19", level: "INFO", message: "GPU 0: 84% util, 14.2/16.0 GB" },
  { id: "l13", time: "2026-09-22 14:42:01", level: "WARNING", message: "High memory usage detected (87%)" },
  { id: "l14", time: "2026-09-22 14:42:03", level: "INFO", message: "Auto-optimizing batch size (from 8 to 4)" },
  {
    id: "l15",
    time: "2026-09-22 14:42:15",
    level: "INFO",
    message: "Training step 100/1000 - loss: 2.341 - lr: 1.0e-4",
  },
  { id: "l16", time: "2026-09-22 14:43:22", level: "INFO", message: "MCP client connected: cursor (192.168.1.45)" },
  { id: "l17", time: "2026-09-22 14:43:45", level: "ERROR", message: "Plugin 'web_crawler' timeout (30s)" },
  { id: "l18", time: "2026-09-22 14:43:46", level: "INFO", message: "Retrying plugin 'web_crawler' (1/3)" },
  { id: "l19", time: "2026-09-22 14:43:52", level: "SUCCESS", message: "Plugin 'web_crawler' recovered" },
  { id: "l20", time: "2026-09-22 14:45:01", level: "INFO", message: "Model inference request (qwen2.5-coder:7b)" },
  { id: "l21", time: "2026-09-22 14:45:02", level: "INFO", message: "Response generated in 2.4s (342 tokens)" },
  { id: "l22", time: "2026-09-22 14:46:11", level: "INFO", message: "Saving checkpoint: checkpoints/step_100" },
  { id: "l23", time: "2026-09-22 14:46:12", level: "SUCCESS", message: "Checkpoint saved successfully" },
  { id: "l24", time: "2026-09-22 14:47:33", level: "INFO", message: "System health check completed" },
  { id: "l25", time: "2026-09-22 14:47:33", level: "INFO", message: "All services running normally" },
];

export type ConsoleProcessStatus = "Running" | "Idle";

export const CONSOLE_PROCESSES: Array<{
  id: string;
  name: string;
  status: ConsoleProcessStatus;
  statusTone: PrTone;
  action: "Stop" | "Start";
}> = [
  { id: "core", name: "HADES Core", status: "Running", statusTone: "ok", action: "Stop" },
  { id: "model", name: "Model Server", status: "Running", statusTone: "ok", action: "Stop" },
  { id: "mcp", name: "MCP Server", status: "Running", statusTone: "ok", action: "Stop" },
  { id: "plugins", name: "Plugin Manager", status: "Running", statusTone: "ok", action: "Stop" },
  { id: "dataset", name: "Dataset Worker", status: "Idle", statusTone: "cyan", action: "Start" },
  { id: "training", name: "Training Worker", status: "Running", statusTone: "ok", action: "Stop" },
];

export const CONSOLE_QUICK_ACTIONS = [
  { id: "restart", label: "Restart Core" },
  { id: "reload", label: "Reload Config" },
  { id: "cache", label: "Clear Cache" },
  { id: "logs", label: "Open Logs Folder" },
] as const;

export const CONSOLE_RESOURCES: Array<{
  id: string;
  label: string;
  value: string;
  pct: number;
  tone: PrBarTone;
}> = [
  { id: "cpu", label: "CPU", value: "24%", pct: 24, tone: "ok" },
  { id: "ram", label: "RAM", value: "8.4 / 32 GB", pct: 26, tone: "cyan" },
  { id: "gpu0", label: "GPU 0", value: "14.2 / 16 GB", pct: 84, tone: "gold" },
  { id: "gpu1", label: "GPU 1", value: "2.1 / 16 GB", pct: 13, tone: "cyan" },
];

export const CONSOLE_COMMAND_HISTORY = [
  { id: "h1", time: "14:37", command: "status" },
  { id: "h2", time: "14:35", command: "gpu" },
  { id: "h3", time: "14:32", command: "ps" },
  { id: "h4", time: "14:28", command: "plugins" },
  { id: "h5", time: "14:25", command: "mcp status" },
] as const;

export const CONSOLE_COMMON_COMMANDS = [
  "status",
  "ps",
  "gpu",
  "memory",
  "plugins",
  "mcp",
  "models",
  "datasets",
  "clear",
  "help",
] as const;

export const CONSOLE_TOOLBAR = ["Clear", "Export", "Filter", "Pause"] as const;
