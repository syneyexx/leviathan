/**
 * Format model parameter counts as B / M / K (e.g. 14B, 7.5M, 125K).
 */

export function formatModelParams(n: number | null | undefined): string | null {
  if (n == null || !Number.isFinite(n) || n <= 0) return null;
  if (n >= 1e9) {
    const v = n / 1e9;
    return `${Number.isInteger(v) ? v.toFixed(0) : trimOneDecimal(v)}B`;
  }
  if (n >= 1e6) {
    const v = n / 1e6;
    return `${Number.isInteger(v) ? v.toFixed(0) : trimOneDecimal(v)}M`;
  }
  if (n >= 1e3) {
    const v = n / 1e3;
    return `${Number.isInteger(v) ? v.toFixed(0) : trimOneDecimal(v)}K`;
  }
  return String(Math.round(n));
}

function trimOneDecimal(v: number): string {
  return v.toFixed(1).replace(/\.0$/, "");
}

/** @deprecated Prefer formatModelParams — thin alias for callers. */
export function formatParamCount(n: number | null | undefined): string | null {
  return formatModelParams(n);
}

/** Display helper: UNMEASURED when unknown (inspector / strips). */
export function formatParameterCount(n: number | null | undefined): string {
  return formatModelParams(n) ?? "UNMEASURED";
}
