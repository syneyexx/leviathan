/** Shared formatting helpers for Models V2 cards. No production fixture numbers here. */

const GIB = 1024 ** 3;

export function formatGb(bytes: number | null | undefined, digits = 1): string {
  if (bytes == null) return "—";
  return `${(bytes / GIB).toFixed(digits)} GB`;
}

export function formatPct(ratio: number | null | undefined): string {
  if (ratio == null || Number.isNaN(ratio)) return "—";
  return `${Math.round(ratio * 100)}%`;
}

export function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function formatParams(count: number | null | undefined): string | null {
  if (!count) return null;
  if (count >= 1e9) return `${(count / 1e9).toFixed(1)}B`;
  if (count >= 1e6) return `${(count / 1e6).toFixed(0)}M`;
  return String(count);
}
