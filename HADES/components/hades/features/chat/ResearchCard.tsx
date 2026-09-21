"use client";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/hades/ui";

export type ResearchCardState = {
  project_id: string;
  title: string;
  topic: string;
  status: string;
  round?: number | null;
  max_rounds?: number | null;
  allow_web?: boolean;
  source_count?: number;
  coverage?: string | null;
  conflicts?: string[];
  events?: Array<{ type?: string; message?: string }>;
  citations?: Array<{ title?: string; uri?: string }>;
  success?: boolean | null;
};

function toneForStatus(status: string, sourceCount: number): "success" | "warning" | "danger" | "info" | "neutral" {
  const value = status.toLowerCase();
  if (value === "completed" && sourceCount <= 0) return "danger";
  if (["completed", "ready"].includes(value)) return "success";
  if (["failed", "cancelled"].includes(value)) return "danger";
  if (["needs_more_evidence", "blocked"].includes(value)) return "warning";
  if (["queued", "running", "gathering"].includes(value)) return "info";
  return "neutral";
}

/** Research progress card — zero sources is never shown as success. */
export function ResearchCard({
  research,
  busy = false,
  onStop,
  onGoDeeper,
  onIngest,
  onOpenAdvanced,
  onRefresh,
}: {
  research: ResearchCardState;
  busy?: boolean;
  onStop?: () => void;
  onGoDeeper?: () => void;
  onIngest?: () => void;
  onOpenAdvanced?: () => void;
  onRefresh?: () => void;
}) {
  const sources = research.source_count ?? 0;
  const completedEmpty = research.status.toLowerCase() === "completed" && sources <= 0;
  return (
    <article className="research-card" data-project-id={research.project_id} aria-label="Onderzoek in gesprek">
      <header className="research-card-head">
        <div>
          <strong>{research.title || research.topic}</strong>
          <small>
            {research.allow_web ? "lokaal+web" : "lokaal-prefer"} · {research.project_id}
            {research.round != null && research.max_rounds != null ? ` · ronde ${research.round}/${research.max_rounds}` : null}
          </small>
        </div>
        <StatusBadge tone={toneForStatus(research.status, sources)}>{research.status}</StatusBadge>
      </header>
      {completedEmpty ? (
        <p className="research-card-honesty" role="alert">
          Geen bronnen gevonden — dit is geen succesvol onderzoek.
        </p>
      ) : null}
      <p className="research-card-meta">
        Bronnen: {sources}
        {research.coverage ? ` · dekking: ${research.coverage}` : ""}
      </p>
      {research.conflicts?.length ? (
        <ul className="research-card-conflicts">
          {research.conflicts.slice(0, 5).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {research.events?.length ? (
        <ul className="research-card-events">
          {research.events.slice(-6).map((event, index) => (
            <li key={`${event.type || "evt"}-${index}`}>
              <code>{event.type || "event"}</code> {event.message || ""}
            </li>
          ))}
        </ul>
      ) : null}
      {research.citations?.length ? (
        <ul className="research-card-citations">
          {research.citations.slice(0, 8).map((cite, index) => (
            <li key={`${cite.uri || cite.title || "c"}-${index}`}>
              {cite.title || cite.uri || "bron"}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="research-card-actions">
        {onStop ? <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onStop}>Stop</Button> : null}
        {onGoDeeper ? <Button type="button" size="sm" variant="outline" disabled={busy || completedEmpty} onClick={onGoDeeper}>Ga dieper</Button> : null}
        {onIngest ? <Button type="button" size="sm" variant="outline" disabled={busy || sources <= 0} onClick={onIngest}>Ingest to Knowledge</Button> : null}
        {onRefresh ? <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onRefresh}>Vernieuwen</Button> : null}
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onOpenAdvanced || (() => { window.location.hash = `/research?p=${encodeURIComponent(research.project_id)}`; })}
        >
          Open Advanced Research
        </Button>
      </div>
    </article>
  );
}
