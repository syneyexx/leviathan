/** FINALBETA LLM Stats — mock/demo data only (no live API claims). */

export type StatsPeriod = "24h" | "7d" | "30d";
export type ActivityTab = "today" | "7d" | "30d";

export const STATS_PERIODS: Array<{ id: StatsPeriod; label: string }> = [
  { id: "24h", label: "Laatste 24 uur" },
  { id: "7d", label: "Laatste 7 dagen" },
  { id: "30d", label: "Laatste 30 dagen" },
];

export const STATS_KPIS = [
  {
    id: "uptime",
    label: "Uptime",
    value: "28d 14h",
    icon: "clock",
    tone: "cyan" as const,
    trend: { value: "▲ +2.4%", tone: "up" as const },
  },
  {
    id: "cpu",
    label: "CPU (gemiddeld)",
    value: "26%",
    icon: "bolt",
    tone: "blue" as const,
    trend: { value: "▼ -12%", tone: "up" as const },
  },
  {
    id: "ram",
    label: "RAM gebruik",
    value: "11.2 / 32 GB",
    icon: "database",
    tone: "purple" as const,
    progress: 35,
    progressTone: "cyan" as const,
  },
  {
    id: "gpu",
    label: "GPU / VRAM",
    value: "18.4 / 24 GB",
    icon: "chart",
    tone: "gold" as const,
    progress: 77,
    progressTone: "gold" as const,
  },
  {
    id: "agents",
    label: "Actieve agents",
    value: "7 / 12",
    icon: "users",
    tone: "green" as const,
    trend: { value: "+2 actief", tone: "up" as const },
  },
  {
    id: "requests",
    label: "Requests vandaag",
    value: "248.6K",
    icon: "send",
    tone: "cyan" as const,
    trend: { value: "▲ +18%", tone: "up" as const },
  },
  {
    id: "latency",
    label: "Model latency",
    value: "732 ms",
    icon: "line",
    tone: "blue" as const,
    trend: { value: "▼ -18%", tone: "up" as const },
  },
];

/** Synthetic 24h series (0–100) for SVG line chart. */
function series(seed: number, base: number, amp: number, points = 25): number[] {
  const out: number[] = [];
  for (let i = 0; i < points; i += 1) {
    const wave = Math.sin(i * 0.45 + seed) * amp;
    const bump = Math.sin(i * 1.1 + seed * 2) * (amp * 0.35);
    out.push(Math.max(4, Math.min(96, base + wave + bump + ((i * 7 + seed * 13) % 5) - 2)));
  }
  return out;
}

export const STATS_PERF_SERIES = {
  cpu: series(1, 28, 14),
  ram: series(2, 42, 10),
  gpu: series(3, 58, 16),
  vram: series(4, 72, 12),
};

export const STATS_PERF_LEGEND = [
  { id: "cpu", label: "CPU", color: "#38bdf8" },
  { id: "ram", label: "RAM", color: "#22c55e" },
  { id: "gpu", label: "GPU", color: "#eab94f" },
  { id: "vram", label: "VRAM", color: "#a78bfa" },
] as const;

export const STATS_ACTIVITY: Record<
  ActivityTab,
  Array<{
    id: string;
    label: string;
    value: string;
    trend: string;
    bars: number[];
    color: string;
  }>
> = {
  today: [
    { id: "req", label: "Verzoeken (requests)", value: "248.6K", trend: "+18%", bars: [40, 55, 48, 62, 70, 66, 78, 82], color: "#38bdf8" },
    { id: "tasks", label: "Uitgevoerde taken", value: "12.4K", trend: "+6%", bars: [30, 36, 42, 40, 48, 52, 50, 58], color: "#22c55e" },
    { id: "wf", label: "Workflows", value: "842", trend: "+12%", bars: [22, 28, 34, 30, 38, 44, 48, 52], color: "#eab94f" },
    { id: "jobs", label: "Background jobs", value: "1.2K", trend: "+4%", bars: [18, 24, 22, 28, 30, 34, 32, 36], color: "#a78bfa" },
  ],
  "7d": [
    { id: "req", label: "Verzoeken (requests)", value: "1.64M", trend: "+11%", bars: [50, 48, 55, 60, 58, 64, 70, 74], color: "#38bdf8" },
    { id: "tasks", label: "Uitgevoerde taken", value: "78.2K", trend: "+8%", bars: [36, 40, 44, 42, 48, 54, 56, 60], color: "#22c55e" },
    { id: "wf", label: "Workflows", value: "5.1K", trend: "+9%", bars: [28, 30, 34, 36, 40, 42, 46, 50], color: "#eab94f" },
    { id: "jobs", label: "Background jobs", value: "8.4K", trend: "+5%", bars: [24, 26, 28, 30, 32, 34, 36, 38], color: "#a78bfa" },
  ],
  "30d": [
    { id: "req", label: "Verzoeken (requests)", value: "6.9M", trend: "+14%", bars: [44, 50, 52, 58, 62, 68, 72, 78], color: "#38bdf8" },
    { id: "tasks", label: "Uitgevoerde taken", value: "312K", trend: "+7%", bars: [38, 42, 46, 48, 52, 56, 58, 64], color: "#22c55e" },
    { id: "wf", label: "Workflows", value: "19.8K", trend: "+10%", bars: [26, 30, 34, 38, 40, 44, 48, 54], color: "#eab94f" },
    { id: "jobs", label: "Background jobs", value: "34.2K", trend: "+3%", bars: [22, 24, 26, 28, 30, 32, 34, 40], color: "#a78bfa" },
  ],
};

export const STATS_MODEL_SUMMARY = [
  { id: "lat", label: "Gem. latency", value: "732 ms" },
  { id: "tok", label: "Tokens verwerkt", value: "12.4M" },
  { id: "thr", label: "Throughput", value: "48.2 t/s" },
  { id: "ok", label: "Succes rate", value: "98.6%" },
];

export const STATS_MODELS = [
  { id: "llama", name: "meta-llama/Llama-3.1-8B", status: "Actief", requests: "86.2K", latency: "612 ms", success: 99.1 },
  { id: "qwen", name: "Qwen2.5-Coder", status: "Actief", requests: "64.8K", latency: "548 ms", success: 98.8 },
  { id: "deepseek", name: "DeepSeek-R1", status: "Actief", requests: "41.3K", latency: "980 ms", success: 97.4 },
  { id: "hades", name: "HADES-Chat", status: "Actief", requests: "56.3K", latency: "720 ms", success: 98.9 },
];

export const STATS_AGENTS = [
  { rank: 1, name: "Research Agent", icon: "search", tasks: "4.8K", success: "99.2%", duration: "1.4s" },
  { rank: 2, name: "Coding Agent", icon: "code", tasks: "3.6K", success: "97.8%", duration: "2.1s" },
  { rank: 3, name: "Trading Agent", icon: "chart", tasks: "2.9K", success: "96.4%", duration: "0.9s" },
  { rank: 4, name: "Media Agent", icon: "image", tasks: "2.1K", success: "98.1%", duration: "3.2s" },
  { rank: 5, name: "Knowledge Agent", icon: "book", tasks: "1.8K", success: "99.0%", duration: "1.7s" },
  { rank: 6, name: "Safety Agent", icon: "shield", tasks: "1.4K", success: "99.6%", duration: "0.6s" },
  { rank: 7, name: "Router Agent", icon: "refresh", tasks: "1.1K", success: "98.4%", duration: "0.4s" },
];

export const STATS_MEDIA = [
  { id: "crawls", label: "Web crawls", value: "1.842", trend: "+12%", icon: "globe" },
  { id: "pages", label: "Pagina's geanalyseerd", value: "24.6K", trend: "+8%", icon: "file" },
  { id: "media", label: "Media gegenereerd", value: "386", trend: "+21%", icon: "image" },
  { id: "social", label: "Social media jobs", value: "142", trend: "+5%", icon: "users" },
];

export const STATS_TASK_SLICES = [
  { label: "Onderzoek & Kennis", count: 28, color: "#38bdf8" },
  { label: "Content & media", count: 24, color: "#22d3ee" },
  { label: "Trading & analyse", count: 18, color: "#a78bfa" },
  { label: "Code & ontwikkeling", count: 14, color: "#eab94f" },
  { label: "Agents & workflows", count: 11, color: "#22c55e" },
  { label: "Overig", count: 5, color: "#758392" },
];

export const STATS_EVENTS = [
  { time: "23:14", level: "INFO" as const, component: "LLM Engine", message: "Model Qwen2.5-Coder geladen" },
  { time: "22:58", level: "WARN" as const, component: "GPU Monitor", message: "Hoge GPU belasting (77%)" },
  { time: "22:41", level: "INFO" as const, component: "Agents", message: "Research Agent taak afgerond" },
  { time: "22:19", level: "ERROR" as const, component: "Workflows", message: "Background job timeout (#4821)" },
  { time: "21:56", level: "INFO" as const, component: "Media", message: "Social media job gepland" },
  { time: "21:33", level: "WARN" as const, component: "Latency", message: "Model latency boven limiet" },
  { time: "21:12", level: "INFO" as const, component: "Router", message: "Traffic herverdeeld naar Llama-3.1" },
];

export const STATS_RUNTIME = [
  { k: "Versie", v: "v0.9.0" },
  { k: "Status", v: "Online", tone: "green" as const },
  { k: "Mode", v: "Productie" },
  { k: "Host", v: "DESKTOP-HADES" },
  { k: "OS", v: "Windows 11" },
  { k: "Uptime", v: "28d 14h 37m" },
];

export const STATS_LIVE_SERVICES = [
  "LLM Engine",
  "Agents Runtime",
  "Media Pipeline",
  "Trading Engine",
  "Knowledge Index",
  "Workflow Runner",
  "Metrics Collector",
  "Alert Service",
];

export const STATS_THRESHOLDS = [
  { label: "CPU gebruik > 80%", value: 62, tone: "gold" as const },
  { label: "RAM gebruik > 85%", value: 35, tone: "green" as const },
  { label: "GPU / VRAM > 90%", value: 77, tone: "gold" as const },
  { label: "Model latency > 1200ms", value: 61, tone: "gold" as const },
  { label: "Error rate > 2%", value: 18, tone: "green" as const },
];

export const STATS_ALERTS = [
  { text: "Hoge GPU belasting", ago: "2u" },
  { text: "Model latency boven limiet", ago: "4u" },
  { text: "Background job timeout", ago: "6u" },
  { text: "Disk cache bijna vol", ago: "9u" },
  { text: "Agent queue backlog", ago: "12u" },
];

export const STATS_QUICK_ACTIONS = [
  { id: "report", label: "Rapport genereren", icon: "file" },
  { id: "monitor", label: "Live monitor", icon: "line" },
  { id: "export", label: "Exporteren", icon: "download" },
  { id: "settings", label: "Instellingen", icon: "settings" },
];
