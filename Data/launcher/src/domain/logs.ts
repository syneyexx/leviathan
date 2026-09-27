import type { LogRowModel } from "../types/backend";
import { redactText } from "../lib/redaction";
import { shortTime } from "../lib/format";

export function mapEvent(event: Record<string, unknown>, index: number): LogRowModel {
  return {
    id: String(event.sequence ?? event.id ?? index),
    time: shortTime(typeof event.timestamp === "string" ? event.timestamp : typeof event.at === "string" ? event.at : null),
    level: String(event.level || "info").toUpperCase(),
    module: String(event.subsystem || event.category || event.source || "host"),
    message: redactText(String(event.message || "")),
  };
}

export function filterLogs(rows: LogRowModel[], query: string, level: string, module = "ALL"): LogRowModel[] {
  const q = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (level && level !== "ALL" && row.level !== level.toUpperCase()) return false;
    if (module && module !== "ALL" && row.module !== module) return false;
    if (!q) return true;
    return `${row.module} ${row.message} ${row.level}`.toLowerCase().includes(q);
  });
}
