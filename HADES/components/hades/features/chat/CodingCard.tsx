"use client";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/hades/ui";

export type CodingCardJob = {
  job_id: string;
  status: string;
  goal?: string;
  source_repo?: string;
  phase?: string;
  files_changed?: string[];
  unified_diff?: string;
  test_output?: string;
  diagnostics?: string;
  conflict?: string | null;
  verification?: string | null;
  poll?: string;
};

function toneForStatus(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  const value = status.toLowerCase();
  if (["completed", "applied", "verified"].includes(value)) return "success";
  if (["failed", "cancelled", "tests_failed", "conflict"].includes(value)) return "danger";
  if (["queued", "running", "investigating", "repairing", "pause_requested", "paused"].includes(value)) return "info";
  return "warning";
}

/** Conversation coding card — displays existing Coding Agent job truth; no parallel engine. */
export function CodingCard({
  job,
  busy = false,
  onApplyAll,
  onReject,
  onRestore,
  onRepairOnce,
  onOpenAdvanced,
  onRefresh,
}: {
  job: CodingCardJob;
  busy?: boolean;
  onApplyAll?: () => void;
  onReject?: () => void;
  onRestore?: () => void;
  onRepairOnce?: () => void;
  onOpenAdvanced?: () => void;
  onRefresh?: () => void;
}) {
  const canApply = Boolean(onApplyAll) && !["applied", "failed", "cancelled"].includes(job.status.toLowerCase());
  return (
    <article className="coding-card" data-job-id={job.job_id} aria-label="Coding-job in gesprek">
      <header className="coding-card-head">
        <div>
          <strong>{job.goal || "Coding-job"}</strong>
          <small>{job.source_repo || "workspace"} · {job.job_id}</small>
        </div>
        <StatusBadge tone={toneForStatus(job.status)}>{job.status}</StatusBadge>
      </header>
      {job.phase ? <p className="coding-card-phase">Fase: {job.phase}</p> : null}
      {job.conflict ? (
        <p className="coding-card-conflict" role="alert">Bronconflict: {job.conflict}</p>
      ) : null}
      {job.files_changed?.length ? (
        <ul className="coding-card-files">
          {job.files_changed.slice(0, 12).map((path) => (
            <li key={path}><code>{path}</code></li>
          ))}
        </ul>
      ) : null}
      {job.unified_diff ? (
        <pre className="coding-card-diff" tabIndex={0}>{job.unified_diff.slice(0, 12_000)}</pre>
      ) : null}
      {job.test_output ? (
        <pre className="coding-card-tests" tabIndex={0}>{job.test_output.slice(0, 4_000)}</pre>
      ) : null}
      {job.diagnostics ? <p className="coding-card-diag">{job.diagnostics}</p> : null}
      {job.verification ? <p className="coding-card-verify">Verificatie: {job.verification}</p> : null}
      <div className="coding-card-actions">
        {canApply ? (
          <Button type="button" size="sm" disabled={busy} onClick={onApplyAll}>Apply all</Button>
        ) : null}
        {onReject ? (
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onReject}>Reject</Button>
        ) : null}
        {onRestore ? (
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onRestore}>Restore</Button>
        ) : null}
        {onRepairOnce ? (
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onRepairOnce}>Repair once</Button>
        ) : null}
        {onRefresh ? (
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onRefresh}>Vernieuwen</Button>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onOpenAdvanced || (() => { window.location.hash = `/fb/coding?codingJob=${encodeURIComponent(job.job_id)}`; })}
        >
          Open FINALBETA Coding
        </Button>
      </div>
    </article>
  );
}
