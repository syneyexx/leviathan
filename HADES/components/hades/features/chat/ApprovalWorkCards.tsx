"use client";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/hades/ui";

export type ApprovalCardItem = {
  id: string;
  tool_name?: string;
  kind?: string;
  summary?: string;
  timed_out?: boolean;
  status?: string;
};

/** In-thread approval — Approve/Reject without leaving the conversation. */
export function ApprovalCard({
  item,
  busy = false,
  onApprove,
  onReject,
}: {
  item: ApprovalCardItem;
  busy?: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <article className="approval-card" data-approval-id={item.id} aria-label="Goedkeuring vereist">
      <header className="approval-card-head">
        <div>
          <strong>{item.tool_name || item.kind || "Actie"}</strong>
          <small>{item.summary || item.id}</small>
        </div>
        <StatusBadge tone="warning">{item.timed_out ? "timeout/pending" : (item.status || "pending")}</StatusBadge>
      </header>
      <p className="approval-card-note">Timeout blijft pending — nooit auto-allow.</p>
      <div className="approval-card-actions">
        <Button type="button" size="sm" disabled={busy} onClick={onApprove}>Approve</Button>
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onReject}>Reject</Button>
      </div>
    </article>
  );
}

export type WorkCardState = {
  task_id: string;
  title?: string;
  status: string;
  current_step?: string | null;
  executor?: string | null;
  pending?: boolean;
  verification?: string | null;
};

export function WorkCard({
  work,
  onOpenAdvanced,
}: {
  work: WorkCardState;
  onOpenAdvanced?: () => void;
}) {
  return (
    <article className="work-card" data-task-id={work.task_id} aria-label="Work Runtime in gesprek">
      <header className="work-card-head">
        <div>
          <strong>{work.title || "Work-taak"}</strong>
          <small>{work.task_id}{work.executor ? ` · ${work.executor}` : ""}</small>
        </div>
        <StatusBadge tone={work.status === "completed" ? "success" : work.status === "failed" ? "danger" : "info"}>
          {work.status}
        </StatusBadge>
      </header>
      {work.current_step ? <p className="work-card-step">Stap: {work.current_step}</p> : null}
      {work.pending ? <p className="work-card-pending">Wacht op goedkeuring / input</p> : null}
      {work.verification ? <p className="work-card-verify">Verificatie: {work.verification}</p> : null}
      <div className="work-card-actions">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onOpenAdvanced || (() => { window.location.hash = `/tasks?task=${encodeURIComponent(work.task_id)}`; })}
        >
          Open Advanced Tasks
        </Button>
      </div>
    </article>
  );
}
