/** FINALBETA Performance — mock/demo data only (no live API claims). */

export type PerfTab = "overzicht" | "hardware" | "processen" | "modellen" | "netwerk" | "logs";

export type PerfPeriod = "1h" | "6h" | "24h" | "7d";

export const PR_PERF_PERIODS: Array<{ id: PerfPeriod; label: string }> = [
  { id: "1h", label: "Laatste 1 uur" },
  { id: "6h", label: "Laatste 6 uur" },
  { id: "24h", label: "Laatste 24 uur" },
  { id: "7d", label: "Laatste 7 dagen" },
];

export const PR_PERF_TABS: Array<{ id: PerfTab; label: string }> = [
  { id: "overzicht", label: "Overzicht" },
  { id: "hardware", label: "Hardware" },
  { id: "processen", label: "Processen" },
  { id: "modellen", label: "Modellen" },
  { id: "netwerk", label: "Netwerk" },
  { id: "logs", label: "Logs" },
];

export const PR_PERF_QUOTE = "Sovereign AI. Local power. Infinite possibilities.";

export const PR_PERF_KPIS = [
  {
    id: "cpu",
    label: "CPU",
    value: "42%",
    hint: "3.4 / 8.0 GHz",
    icon: "bolt" as const,
    tone: "cyan" as const,
    spark: [28, 34, 31, 38, 42, 36, 40, 33, 37, 41, 39, 42, 35, 44, 38, 42],
    color: "#2dd4bf",
  },
  {
    id: "ram",
    label: "RAM",
    value: "56%",
    hint: "18.0 / 32 GB",
    icon: "database" as const,
    tone: "blue" as const,
    spark: [48, 50, 52, 51, 54, 53, 55, 52, 54, 56, 55, 57, 54, 56, 55, 56],
    color: "#60a5fa",
  },
  {
    id: "gpu",
    label: "GPU",
    value: "71%",
    hint: "NVIDIA RTX 4090",
    icon: "bolt" as const,
    tone: "gold" as const,
    spark: [58, 62, 65, 68, 70, 66, 72, 69, 71, 74, 70, 73, 68, 72, 71, 71],
    color: "#eab94f",
  },
  {
    id: "vram",
    label: "VRAM",
    value: "77%",
    hint: "18.4 / 24 GB",
    icon: "chart" as const,
    tone: "orange" as const,
    spark: [68, 70, 72, 74, 75, 73, 76, 75, 77, 78, 76, 79, 75, 77, 76, 77],
    color: "#f59e0b",
  },
  {
    id: "disk",
    label: "Schijf (NVMe)",
    value: "24%",
    hint: "482 / 2.0 TB",
    icon: "folder" as const,
    tone: "sky" as const,
    spark: [18, 20, 22, 19, 24, 21, 23, 20, 25, 22, 24, 21, 23, 25, 22, 24],
    color: "#38bdf8",
  },
  {
    id: "net",
    label: "Netwerk",
    value: "1.4 Gbps",
    hint: "↓ 980 Mbps  ↑ 420 Mbps",
    icon: "globe" as const,
    tone: "purple" as const,
    spark: [40, 55, 48, 70, 62, 85, 58, 90, 72, 68, 95, 80, 60, 88, 74, 82],
    color: "#a78bfa",
  },
];

export const PR_PERF_TIME_LABELS = ["14:20", "14:30", "14:40", "14:50", "15:00", "15:10", "15:20"];

export const PR_PERF_CHARTS = {
  cpuRam: {
    title: "CPU & RAM gebruik",
    yLabels: ["100", "75", "50", "25", "0"],
    series: [
      { id: "cpu", label: "CPU (%)", color: "#2dd4bf", values: [32, 38, 35, 44, 41, 36, 42, 39, 45, 37, 40, 43, 38, 42] },
      { id: "ram", label: "RAM (%)", color: "#60a5fa", values: [48, 50, 51, 52, 53, 54, 55, 54, 56, 55, 56, 57, 55, 56] },
    ],
  },
  gpuVram: {
    title: "GPU & VRAM gebruik",
    yLabels: ["100", "80", "60", "40", "20", "0"],
    series: [
      { id: "gpu", label: "GPU (%)", color: "#eab94f", values: [55, 62, 68, 70, 66, 72, 74, 69, 71, 75, 70, 73, 68, 71] },
      { id: "vram", label: "VRAM (%)", color: "#f59e0b", values: [68, 72, 74, 76, 75, 77, 78, 76, 79, 78, 77, 80, 76, 77] },
    ],
  },
  diskIo: {
    title: "Schijf I/O",
    yLabels: ["1.000", "750", "500", "250", "0"],
    max: 1000,
    series: [
      { id: "read", label: "Lezen (MB/s)", color: "#38bdf8", values: [120, 340, 180, 620, 210, 480, 150, 890, 260, 410, 190, 720, 230, 380] },
      { id: "write", label: "Schrijven (MB/s)", color: "#a78bfa", values: [80, 140, 95, 220, 110, 180, 90, 310, 130, 160, 100, 250, 120, 170] },
    ],
  },
  network: {
    title: "Netwerkverkeer",
    yLabels: ["4.000", "3.000", "2.000", "1.000", "0"],
    max: 4000,
    series: [
      { id: "down", label: "Download (Mbps)", color: "#a78bfa", values: [420, 680, 510, 920, 640, 1100, 780, 2400, 960, 720, 580, 1400, 860, 980] },
      { id: "up", label: "Upload (Mbps)", color: "#38bdf8", values: [180, 260, 210, 340, 250, 420, 290, 680, 310, 280, 220, 450, 300, 420] },
    ],
  },
  latency: {
    title: "Model runtime latency",
    yLabels: ["10.000", "1.000", "100", "10"],
    log: true,
    series: [
      { id: "avg", label: "Gemiddelde (ms)", color: "#eab94f", values: [160, 175, 190, 168, 210, 155, 182, 198, 170, 185, 175, 192, 168, 181] },
      { id: "p95", label: "P95 (ms)", color: "#f59e0b", values: [620, 780, 540, 920, 710, 1100, 680, 1450, 820, 760, 640, 980, 720, 842] },
    ],
    stats: [
      { label: "Laatste", value: "142 ms" },
      { label: "Gemiddeld", value: "181 ms" },
      { label: "P95", value: "842 ms" },
    ],
  },
  queue: {
    title: "Queue depth",
    yLabels: ["50", "40", "30", "20", "10", "0"],
    max: 50,
    series: [
      { id: "active", label: "Verwerking", color: "#2dd4bf", values: [8, 10, 12, 9, 14, 11, 13, 10, 15, 12, 11, 14, 10, 12] },
      { id: "queued", label: "Wachtrij", color: "#3b82f6", values: [18, 22, 26, 20, 30, 24, 28, 22, 32, 27, 25, 29, 23, 28] },
    ],
    stats: [
      { label: "Actief", value: "12" },
      { label: "In wachtrij", value: "28" },
      { label: "Doorvoer", value: "4.8 taken/sec" },
    ],
  },
};

export const PR_PERF_PROCESSES = [
  {
    rank: 1,
    name: "llama-server.exe",
    type: "Model runtime",
    cpu: "34.2%",
    ram: "6.8 GB",
    vram: "14.2 GB",
    status: "Actief",
  },
  {
    rank: 2,
    name: "hades-engine.exe",
    type: "HADES core",
    cpu: "12.4%",
    ram: "2.1 GB",
    vram: "1.1 GB",
    status: "Actief",
  },
  {
    rank: 3,
    name: "python.exe",
    type: "Agent worker",
    cpu: "6.8%",
    ram: "1.4 GB",
    vram: "0.8 GB",
    status: "Actief",
  },
  {
    rank: 4,
    name: "node.exe",
    type: "Frontend / API",
    cpu: "4.1%",
    ram: "0.9 GB",
    vram: "0.2 GB",
    status: "Actief",
  },
  {
    rank: 5,
    name: "postgres.exe",
    type: "Database",
    cpu: "2.3%",
    ram: "1.2 GB",
    vram: "—",
    status: "Actief",
  },
];

export const PR_PERF_THERMAL = [
  { id: "cpu", label: "CPU", value: "67°C", status: "Normaal", tone: "green" as const, progress: 67 },
  { id: "gpu", label: "GPU", value: "72°C", status: "Verhoogd", tone: "gold" as const, progress: 72 },
  { id: "vram", label: "VRAM", value: "68°C", status: "Normaal", tone: "green" as const, progress: 68 },
  { id: "sys", label: "Systeem", value: "42°C", status: "Normaal", tone: "cyan" as const, progress: 42 },
];

export const PR_PERF_POWER = {
  total: "312 W",
  limit: "450 W",
  spark: [280, 295, 310, 298, 320, 305, 330, 312, 325, 308, 318, 302, 315, 312],
};

export const PR_PERF_BOTTLENECK = {
  headline: "GPU vormt momenteel de grootste beperking in de pipeline.",
  tip: "Tip: Overweeg batch size te verlagen of quantization te gebruiken.",
  bars: [
    { id: "gpu", label: "GPU", value: 71, tone: "gold" as const },
    { id: "vram", label: "VRAM", value: 77, tone: "orange" as const },
    { id: "cpu", label: "CPU", value: 42, tone: "blue" as const },
    { id: "disk", label: "Schijf I/O", value: 24, tone: "blue" as const },
    { id: "net", label: "Netwerk", value: 18, tone: "blue" as const },
  ],
};

export const PR_PERF_HARDWARE = [
  { id: "gpu", label: "GPU", value: "NVIDIA RTX 4090" },
  {
    id: "vram",
    label: "VRAM",
    value: "18.4 / 24 GB",
    progress: 77,
    tone: "orange" as const,
    pct: "77%",
  },
  {
    id: "ram",
    label: "RAM",
    value: "18.0 / 32 GB",
    progress: 56,
    tone: "blue" as const,
    pct: "56%",
  },
  {
    id: "cpu",
    label: "CPU",
    value: "AMD Ryzen 9 7950X",
    progress: 42,
    tone: "cyan" as const,
    pct: "42%",
  },
  {
    id: "disk",
    label: "Schijf",
    value: "482 / 2.0 TB",
    progress: 24,
    tone: "sky" as const,
    pct: "24%",
  },
  {
    id: "net",
    label: "Netwerk",
    value: "1.4 Gbps",
    detail: "↑ 420 Mbps",
  },
  {
    id: "temp",
    label: "Temperatuur",
    value: "72°C",
    badge: "Verhoogd",
    tone: "gold" as const,
  },
];

export const PR_PERF_SERVICES = [
  { id: "llm", name: "LLM Runtime", icon: "bolt" as const },
  { id: "sched", name: "Model Scheduler", icon: "calendar" as const },
  { id: "vector", name: "Vector Database", icon: "database" as const },
  { id: "media", name: "Media Pipeline", icon: "image" as const },
  { id: "agent", name: "Agent Orchestrator", icon: "users" as const },
  { id: "trade", name: "Trading Connector", icon: "candle" as const },
  { id: "web", name: "Web UI", icon: "globe" as const },
  { id: "api", name: "API Server", icon: "terminal" as const },
];

export const PR_PERF_SHORTCUTS = [
  { id: "logs", label: "Logs openen", icon: "file" as const },
  { id: "diag", label: "Systeemdiagnose", icon: "shield" as const },
  { id: "report", label: "Prestatie rapport", icon: "download" as const },
  { id: "alert", label: "Alert configuratie", icon: "sliders" as const },
];
