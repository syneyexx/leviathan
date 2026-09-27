export interface RingItem {
  seq: number;
}

export function pushRing<T>(items: T[], next: T, capacity: number): T[] {
  const cap = Math.max(1, capacity);
  const copy = items.length >= cap ? items.slice(items.length - cap + 1) : items.slice();
  copy.push(next);
  return copy;
}

export function appendUnique<T extends RingItem>(items: T[], incoming: T[], capacity: number): T[] {
  if (incoming.length === 0) return items;
  const seen = new Set(items.map((item) => item.seq));
  const merged = items.slice();
  for (const item of incoming) {
    if (seen.has(item.seq)) continue;
    seen.add(item.seq);
    merged.push(item);
  }
  if (merged.length > capacity) return merged.slice(merged.length - capacity);
  return merged;
}
