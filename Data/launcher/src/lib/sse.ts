export function nextSseDelay(attempt: number): number {
  const n = Math.max(0, Math.min(attempt, 6));
  return Math.min(15_000, 500 * 2 ** n);
}

export function parseSseId(raw: string | null): number | null {
  if (!raw) return null;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) return null;
  return Math.floor(value);
}
