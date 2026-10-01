/**
 * Tag edit helpers — normalize, dedupe, never wipe canonical tags with empty draft.
 */

export function normalizeTag(raw: string): string {
  return raw.trim().replace(/\s+/g, " ");
}

/** Case-insensitive dedupe; preserves first-seen casing. */
export function normalizeTagList(tags: Iterable<string>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of tags) {
    const t = normalizeTag(raw);
    if (!t) continue;
    const key = t.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(t);
  }
  return out;
}

export function parseTagDraft(draft: string): string[] {
  return normalizeTagList(draft.split(/[,;\n]/));
}

/**
 * Resolve tags to save. Empty draft with existing tags → blocked (do not wipe).
 * Empty draft with no existing → noop.
 */
export function resolveTagsToSave(
  draft: string,
  existing: string[],
): { kind: "save"; tags: string[] } | { kind: "blocked"; message: string } | { kind: "noop"; message?: string } {
  const parsed = parseTagDraft(draft);
  const current = normalizeTagList(existing);
  if (parsed.length === 0) {
    if (current.length > 0) {
      return {
        kind: "blocked",
        message: "Tags niet gewist — leeg concept wist bestaande tags niet stilzwijgend",
      };
    }
    return { kind: "noop", message: "Geen tags om op te slaan" };
  }
  return { kind: "save", tags: parsed };
}

export function addTag(tags: string[], next: string): string[] {
  return normalizeTagList([...tags, next]);
}

export function removeTag(tags: string[], remove: string): string[] {
  const key = normalizeTag(remove).toLowerCase();
  return tags.filter((t) => t.toLowerCase() !== key);
}

/** Initialize chip list from canonical dataset tags. */
export function initTagsFromDataset(ds: {
  semanticTags?: string[] | null;
  semanticProfile?: { tags?: string[] | null } | null;
  metadata?: Record<string, unknown> | null;
} | null): string[] {
  if (!ds) return [];
  const semantic = ds.semanticTags ?? ds.semanticProfile?.tags;
  if (Array.isArray(semantic) && semantic.length) {
    return normalizeTagList(semantic.map(String));
  }
  const meta = ds.metadata ?? undefined;
  const raw = meta?.semanticTags ?? meta?.tags;
  if (Array.isArray(raw)) return normalizeTagList(raw.map(String));
  return [];
}
