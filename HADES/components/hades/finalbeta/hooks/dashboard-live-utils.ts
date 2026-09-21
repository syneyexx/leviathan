/** Live sampling helpers for the FINALBETA dashboard. */

export type MetricSample = {
  t: number;
  cpu: number | null;
  ram: number | null;
  gpu: number | null;
  vram: number | null;
};

export type MetricRange = "1m" | "5m" | "1h" | "24h";

const RANGE_MS: Record<MetricRange, number> = {
  "1m": 60_000,
  "5m": 5 * 60_000,
  "1h": 60 * 60_000,
  "24h": 24 * 60 * 60_000,
};

/** Keep enough samples for a 24h window at ~5s cadence. */
export const HISTORY_CAP = 20_000;

export function factNumber(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (raw && typeof raw === "object" && "value" in raw) {
    const value = (raw as { value: unknown }).value;
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

export function factString(raw: unknown): string | null {
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  if (raw && typeof raw === "object" && "value" in raw) {
    const value = (raw as { value: unknown }).value;
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : digits)} ${units[unit]}`;
}

export function formatUptime(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "—";
  const totalSec = Math.floor(ms / 1000);
  const days = Math.floor(totalSec / 86_400);
  const hours = Math.floor((totalSec % 86_400) / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

export function shortModelName(model: string | null | undefined): string {
  if (!model) return "—";
  const cleaned = model.replace(/^.*[/\\]/, "").trim();
  return cleaned || model;
}

export function pushSample(history: MetricSample[], sample: MetricSample): MetricSample[] {
  const next = history.length ? [...history, sample] : [sample];
  const cutoff = sample.t - RANGE_MS["24h"];
  const pruned = next.filter((row) => row.t >= cutoff);
  if (pruned.length <= HISTORY_CAP) return pruned;
  return pruned.slice(pruned.length - HISTORY_CAP);
}

export function samplesForRange(history: MetricSample[], range: MetricRange, now = Date.now()): MetricSample[] {
  const cutoff = now - RANGE_MS[range];
  return history.filter((row) => row.t >= cutoff);
}

export function sparkPath(values: Array<number | null>, width = 120, height = 36): string {
  const usable = values.map((v) => (v == null || !Number.isFinite(v) ? null : Math.max(0, Math.min(100, v))));
  if (!usable.some((v) => v != null)) {
    return `M0,${height - 4} L${width},${height - 4}`;
  }
  const filled = usable.map((v, i, arr) => {
    if (v != null) return v;
    let left = i - 1;
    while (left >= 0 && arr[left] == null) left -= 1;
    let right = i + 1;
    while (right < arr.length && arr[right] == null) right += 1;
    const leftV = left >= 0 ? arr[left]! : null;
    const rightV = right < arr.length ? arr[right]! : null;
    if (leftV == null) return rightV ?? 0;
    if (rightV == null) return leftV;
    const t = (i - left) / Math.max(1, right - left);
    return leftV + (rightV - leftV) * t;
  });
  const step = filled.length <= 1 ? width : width / (filled.length - 1);
  return filled
    .map((v, i) => {
      const x = i * step;
      const y = height - 2 - (v / 100) * (height - 6);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function sparkArea(values: Array<number | null>, width = 120, height = 36): string {
  const line = sparkPath(values, width, height);
  return `${line} L${width},${height} L0,${height} Z`;
}

export function chartPolyline(values: Array<number | null>, width = 640, height = 168): string {
  return sparkPath(values, width, height);
}

export type DonutSlice = { label: string; count: number; color: string };

const DONUT_COLORS = ["#1aa4ff", "#8d67ff", "#39c8c4", "#f0b429", "#c66965", "#758392", "#20e38d", "#d87849"];

export function buildDonutSlices(counts: Record<string, number>): DonutSlice[] {
  const entries = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) return [{ label: "Idle", count: 1, color: "#758392" }];
  return entries.map(([label, count], index) => ({
    label,
    count,
    color: DONUT_COLORS[index % DONUT_COLORS.length]!,
  }));
}

/** SVG stroke-dasharray segments for a circle with r=14 (C≈87.96). */
export function donutSegments(slices: DonutSlice[]): Array<{ color: string; dash: string; offset: number }> {
  const total = slices.reduce((sum, slice) => sum + slice.count, 0) || 1;
  const circumference = 2 * Math.PI * 14;
  let cursor = 0;
  return slices.map((slice) => {
    const length = (slice.count / total) * circumference;
    const segment = {
      color: slice.color,
      dash: `${length.toFixed(2)} ${(circumference - length).toFixed(2)}`,
      offset: -cursor,
    };
    cursor += length;
    return segment;
  });
}

export function agentVisualState(status?: string | null, health?: string | null): "online" | "running" | "waiting" | "idle" | "error" {
  const s = (status || "").toLowerCase();
  const h = (health || "").toLowerCase();
  if (s === "error" || h === "error") return "error";
  if (s === "running" || s === "busy") return "running";
  if (s === "unavailable" || s === "disabled" || h === "offline") return "waiting";
  if (s === "idle" || h === "healthy") return s === "idle" ? "idle" : "online";
  return "idle";
}

export function agentStateLabel(state: ReturnType<typeof agentVisualState>): string {
  if (state === "online") return "Online";
  if (state === "running") return "Running";
  if (state === "waiting") return "Waiting";
  if (state === "error") return "Error";
  return "Idle";
}
