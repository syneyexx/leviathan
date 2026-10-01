/**
 * Preview chart eligibility — only show timeseries when timestamp/x AND numeric measure exist.
 * Never invent price series from arbitrary numeric columns alone.
 */

export type PreviewSeries = {
  values: number[];
  label: string;
  xLabel: string;
};

const TIME_KEYS = /^(ts|timestamp|time|date|datetime|created_at|updated_at|x)$/i;
const MEASURE_KEYS =
  /^(value|price|close|open|high|low|amount|count|score|metric|y|measure)$/i;

function isNumeric(v: unknown): boolean {
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "string" && v.trim() !== "") return !Number.isNaN(Number(v));
  return false;
}

function looksLikeTimestamp(v: unknown): boolean {
  if (typeof v === "number" && Number.isFinite(v)) return true;
  if (typeof v !== "string" || !v.trim()) return false;
  if (/^\d{10,13}$/.test(v.trim())) return true;
  const t = Date.parse(v);
  return Number.isFinite(t);
}

/**
 * Require BOTH a time/x column and a numeric measure column with evidence.
 * Returns null when evidence is insufficient — caller shows normal preview.
 */
export function seriesFromPreview(
  rows: Array<Record<string, unknown>>,
): PreviewSeries | null {
  if (rows.length < 3) return null;
  const keys = Object.keys(rows[0] ?? {});
  if (keys.length < 2) return null;

  const sample = rows.slice(0, 24);
  const timeKey =
    keys.find((k) => TIME_KEYS.test(k) && sample.every((r) => looksLikeTimestamp(r[k]))) ??
    keys.find((k) => sample.every((r) => looksLikeTimestamp(r[k])) && !MEASURE_KEYS.test(k));

  if (!timeKey) return null;

  const measureKey =
    keys.find(
      (k) =>
        k !== timeKey &&
        MEASURE_KEYS.test(k) &&
        sample.every((r) => isNumeric(r[k])),
    ) ??
    keys.find((k) => k !== timeKey && sample.every((r) => isNumeric(r[k])));

  if (!measureKey) return null;

  // Require measure key to look like a measure OR time key to be explicitly named —
  // avoid charting random id+count pairs without temporal axis naming.
  if (!TIME_KEYS.test(timeKey) && !MEASURE_KEYS.test(measureKey)) {
    return null;
  }

  const values = sample
    .map((r) => Number(r[measureKey]))
    .filter((n) => Number.isFinite(n));
  if (values.length < 3) return null;

  return { values, label: measureKey, xLabel: timeKey };
}
