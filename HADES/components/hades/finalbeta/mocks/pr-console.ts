import type { FinalBetaIconName } from "../icons";

export type ConsoleTabId = "live" | "services" | "processen" | "systeem" | "netwerk" | "events";
export type ConsoleLogLevel = "INFO" | "SUCCESS" | "WARN" | "ERROR" | "DEBUG";

export const PR_CONSOLE_QUOTE = "Observe. Diagnose. Control. Infinite possibilities.";

export const PR_CONSOLE_TABS: Array<{ id: ConsoleTabId; label: string }> = [
  { id: "live", label: "Live console" },
  { id: "services", label: "Services" },
  { id: "processen", label: "Processen" },
  { id: "systeem", label: "Systeem" },
  { id: "netwerk", label: "Netwerk" },
  { id: "events", label: "Event log" },
];

export type ConsoleLogLine = {
  id: string;
  time: string;
  level: ConsoleLogLevel;
  service: string;
  message: string;
  link?: string;
};

export const PR_CONSOLE_LOGS: ConsoleLogLine[] = [
  { id: "l1", time: "14:22:15.123", level: "INFO", service: "system", message: "HADES FINALBETA Console gestart - v0.9.0" },
  { id: "l2", time: "14:22:15.227", level: "INFO", service: "core", message: "Initializing system services..." },
  { id: "l3", time: "14:22:15.442", level: "SUCCESS", service: "core", message: "Alle services succesvol geladen (12/12)" },
  { id: "l4", time: "14:22:16.001", level: "WARN", service: "llm", message: "Model 'meta-llama-3.1-8B' heeft hoge geheugendruk (71%)" },
  { id: "l5", time: "14:22:16.334", level: "INFO", service: "api", message: "REST endpoint beschikbaar op ", link: "http://localhost:8000" },
  { id: "l6", time: "14:22:17.118", level: "INFO", service: "media", message: "Media pipeline gereed - 3 apparaten gevonden" },
  { id: "l7", time: "14:22:18.664", level: "DEBUG", service: "trading", message: "Marktdata stream actief (BTC: 67432.18, ETH: 3521.44)" },
  { id: "l8", time: "14:22:19.201", level: "INFO", service: "agent", message: "Agent 'Researcher' geïnitialiseerd en actief" },
  { id: "l9", time: "14:22:20.015", level: "WARN", service: "system", message: "Schijfruimte laag op /data (12% beschikbaar)" },
  { id: "l10", time: "14:22:21.337", level: "INFO", service: "plugin", message: "Plugin 'browser-tools' geladen (v1.2.3)" },
  { id: "l11", time: "14:22:23.998", level: "ERROR", service: "runtime", message: "Fout bij laden van optionele module 'stable-diffusion' (dependency niet gevonden)" },
  { id: "l12", time: "14:22:25.447", level: "INFO", service: "monitor", message: "Systeemstatus: OK - Uptime: 0u 28m 16s" },
  { id: "l13", time: "14:22:27.662", level: "DEBUG", service: "network", message: "Verbinding met HADES-Chat tot stand gebracht" },
  { id: "l14", time: "14:22:30.110", level: "INFO", service: "console", message: "Gebruiker 'admin' aangemeld via lokale sessie" },
  { id: "l15", time: "14:22:31.556", level: "SUCCESS", service: "llm", message: "Inference request voltooid in 842ms (128 tokens)" },
  { id: "l16", time: "14:22:33.201", level: "INFO", service: "trading", message: "1 nieuwe trade signaal gedetecteerd (ETH/USD)" },
  { id: "l17", time: "14:22:34.889", level: "INFO", service: "backup", message: "Automatische backup voltooid (284 MB, 12 bestanden)" },
  { id: "l18", time: "14:22:36.114", level: "WARN", service: "gpu", message: "GPU temperatuur hoog (78°C)" },
  { id: "l19", time: "14:22:38.552", level: "INFO", service: "system", message: "Health check voltooid - Alle kritieke services operationeel" },
  { id: "l20", time: "14:22:41.003", level: "DEBUG", service: "research", message: 'Document geïndexeerd: "ai-agents-survey-2024.pdf"' },
  { id: "l21", time: "14:22:45.778", level: "SUCCESS", service: "console", message: "Commando voltooid: system.health_check" },
];

export const PR_CONSOLE_QUICK: Array<{ id: string; label: string; icon?: FinalBetaIconName }> = [
  { id: "q1", label: "system.status", icon: "terminal" },
  { id: "q2", label: "service.list", icon: "play" },
  { id: "q3", label: "service.restart llm", icon: "play" },
  { id: "q4", label: "gpu.status", icon: "terminal" },
  { id: "q5", label: "logs --follow" },
  { id: "q6", label: "research.index" },
  { id: "q7", label: "trading.signals" },
  { id: "q8", label: "backup.create", icon: "save" },
];

export const PR_CONSOLE_HISTORY: Array<{ id: string; time: string; command: string }> = [
  { id: "h1", time: "14:21", command: "system.health_check" },
  { id: "h2", time: "14:18", command: "service.restart media" },
  { id: "h3", time: "14:15", command: "logs --follow --service llm" },
  { id: "h4", time: "14:12", command: "docker ps" },
  { id: "h5", time: "14:09", command: "nvidia-smi" },
];

export const PR_CONSOLE_PROCESSES: Array<{
  pid: number;
  name: string;
  cpu: string;
  memory: string;
  status: string;
}> = [
  { pid: 4123, name: "hades-core", cpu: "2.1%", memory: "1.2 GB", status: "Actief" },
  { pid: 4187, name: "llama-server", cpu: "18.4%", memory: "13.6 GB", status: "Actief" },
  { pid: 4251, name: "trading-engine", cpu: "4.6%", memory: "1.1 GB", status: "Actief" },
  { pid: 4310, name: "media-pipeline", cpu: "3.2%", memory: "2.4 GB", status: "Actief" },
  { pid: 4380, name: "agent-worker", cpu: "5.8%", memory: "3.1 GB", status: "Actief" },
];

export const PR_CONSOLE_RESOURCES: Array<{
  id: string;
  label: string;
  value: string;
  pct: number;
  tone?: "gold" | "blue";
}> = [
  { id: "cpu", label: "CPU", value: "18%", pct: 18, tone: "gold" },
  { id: "ram", label: "Werkgeheugen", value: "9.6 / 32 GB", pct: 30, tone: "gold" },
  { id: "gpu", label: "GPU (NVIDIA RTX 4090)", value: "42%", pct: 42, tone: "gold" },
  { id: "vram", label: "VRAM", value: "10.8 / 24 GB", pct: 45, tone: "gold" },
  { id: "disk", label: "Schijf (/data)", value: "1.2 / 4 TB", pct: 29, tone: "gold" },
  { id: "net", label: "Netwerk", value: "12% / 18 MB/s", pct: 12, tone: "blue" },
];

export const PR_CONSOLE_STATUS: Array<{
  k: string;
  v: string;
  tone?: "gold" | "green";
}> = [
  { k: "Route", v: "Auto", tone: "gold" },
  { k: "Model", v: "Qwen 2.5 Coder", tone: "gold" },
  { k: "Agenten actief", v: "3", tone: "gold" },
  { k: "Taken actief", v: "2", tone: "green" },
  { k: "Latency", v: "1.4s", tone: "green" },
  { k: "Backend", v: "Online", tone: "green" },
];

export const PR_CONSOLE_FILTERS: Array<{
  id: ConsoleLogLevel;
  label: string;
  count: string;
  checked: boolean;
  tone: "blue" | "green" | "gold" | "red" | "cyan";
}> = [
  { id: "INFO", label: "INFO", count: "1.284", checked: true, tone: "blue" },
  { id: "SUCCESS", label: "SUCCESS", count: "342", checked: true, tone: "blue" },
  { id: "WARN", label: "WARN", count: "89", checked: true, tone: "gold" },
  { id: "ERROR", label: "ERROR", count: "12", checked: true, tone: "gold" },
  { id: "DEBUG", label: "DEBUG", count: "561", checked: true, tone: "blue" },
];

export const PR_CONSOLE_HEALTH: Array<{
  id: string;
  name: string;
  icon: FinalBetaIconName;
}> = [
  { id: "core", name: "HADES Core", icon: "brain" },
  { id: "llm", name: "LLM Service", icon: "bolt" },
  { id: "media", name: "Media Pipeline", icon: "image" },
  { id: "trading", name: "Trading Engine", icon: "shield" },
  { id: "agent", name: "Agent Runtime", icon: "link" },
  { id: "plugin", name: "Plugin Manager", icon: "grid" },
  { id: "vector", name: "Vector DB", icon: "database" },
  { id: "web", name: "Web UI", icon: "globe" },
];

export const PR_CONSOLE_ENV: Array<{ k: string; v: string }> = [
  { k: "Versie", v: "FINALBETA v0.9.0" },
  { k: "Host", v: "DESKTOP-HADES" },
  { k: "Platform", v: "Windows 11" },
  { k: "Uptime", v: "0u 28m 16s" },
  { k: "Tijd", v: "17 feb 2025, 14:22" },
  { k: "Gebruiker", v: "admin (lokaal)" },
  { k: "Python", v: "3.11.8" },
  { k: "Docker", v: "28 containers" },
];
