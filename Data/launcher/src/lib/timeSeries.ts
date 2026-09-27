export function pushSample(history: Array<number | null>, value: number | null, capacity = 120): Array<number | null> {
  const next = history.length >= capacity ? history.slice(history.length - capacity + 1) : history.slice();
  next.push(typeof value === "number" && Number.isFinite(value) ? value : null);
  return next;
}

export function lastMeasured(history: Array<number | null>): number | null {
  for (let i = history.length - 1; i >= 0; i -= 1) {
    const value = history[i];
    if (typeof value === "number") return value;
  }
  return null;
}
