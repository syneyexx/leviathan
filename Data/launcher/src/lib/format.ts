export function displayNumber(value: number | null | undefined, digits = 0): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "UNMEASURED";
  return value.toFixed(digits);
}

export function displayPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "UNMEASURED";
  return `${value.toFixed(1)}%`;
}

export function formatClock(date: Date): { date: string; time: string; zone: string } {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "local";
  return { date: `${year}-${month}-${day}`, time: `${hour}:${minute}:${second}`, zone };
}

export function formatUptime(startedAt: string | null, now = Date.now()): string {
  if (!startedAt) return "UNMEASURED";
  const then = Date.parse(startedAt);
  if (Number.isNaN(then)) return "UNMEASURED";
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m ${seconds % 60}s`;
}

export function shortTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value.slice(11, 19) || value;
  const date = new Date(parsed);
  return formatClock(date).time;
}
