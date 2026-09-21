"use client";

export type ProvenanceLabel = { kind: string; label: string };

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asMentionList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>> : [];
}

function asSourceList(value: unknown): ProvenanceLabel[] {
  if (!Array.isArray(value)) return [];
  const labels: ProvenanceLabel[] = [];
  for (const item of value) {
    const row = asRecord(item);
    const label = String(row?.label || "").trim();
    if (!label) continue;
    labels.push({ kind: String(row?.kind || "source"), label });
  }
  return labels;
}

/** Collect compact provenance labels from live retrieval or persisted message metadata. */
export function collectProvenanceLabels(
  retrieval?: Record<string, unknown> | null,
  retrievalSummary?: Record<string, unknown> | null,
): ProvenanceLabel[] {
  const seen = new Set<string>();
  const labels: ProvenanceLabel[] = [];

  const add = (kind: string, label: string) => {
    const trimmed = label.trim();
    if (!trimmed) return;
    const key = `${kind}:${trimmed}`;
    if (seen.has(key)) return;
    seen.add(key);
    labels.push({ kind, label: trimmed });
  };

  for (const source of [...asSourceList(retrieval?.sources), ...asSourceList(retrievalSummary?.sources)]) {
    add(source.kind, source.label);
  }

  for (const mention of [...asMentionList(retrieval?.mentions), ...asMentionList(retrievalSummary?.mentions)]) {
    const raw = String(mention.raw || "").trim();
    const kind = String(mention.kind || "mention");
    const ref = String(mention.ref || "").trim();
    add("mention", raw || `@${kind}${ref ? `:${ref}` : ""}`);
  }

  const memories = Number(retrieval?.memories ?? retrievalSummary?.memories ?? 0);
  const knowledge = Number(retrieval?.knowledge_chunks ?? retrievalSummary?.knowledge_chunks ?? 0);
  const hasMemoryLabel = labels.some((item) => item.kind === "memory" || item.label.toLowerCase().includes("memory"));
  const hasKnowledgeLabel = labels.some((item) => item.kind === "knowledge" || item.label.toLowerCase().includes("knowledge") || item.kind === "mention");

  if (memories > 0 && !hasMemoryLabel) add("memory", `${memories} geheugenitem(s)`);
  if (knowledge > 0 && !hasKnowledgeLabel) add("knowledge", `${knowledge} kennischunk(s)`);

  return labels.slice(0, 16);
}

type ChatProvenanceListProps = {
  retrieval?: Record<string, unknown> | null;
  retrievalSummary?: Record<string, unknown> | null;
  className?: string;
  compact?: boolean;
};

export function ChatProvenanceList({ retrieval, retrievalSummary, className, compact = false }: ChatProvenanceListProps) {
  const labels = collectProvenanceLabels(retrieval, retrievalSummary);

  return (
    <div className={className ?? "chat-provenance"} aria-label="Bronnen en provenance">
      <strong className="chat-provenance-title">Bronnen</strong>
      {labels.length ? (
        <ul className={compact ? "chat-provenance-list compact" : "chat-provenance-list"}>
          {labels.map((item) => (
            <li key={`${item.kind}:${item.label}`}>
              <span className="chat-provenance-kind">{item.kind}</span>
              <span className="chat-provenance-label">{item.label}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="chat-provenance-empty">Geen lokale bronnen geciteerd</p>
      )}
    </div>
  );
}
