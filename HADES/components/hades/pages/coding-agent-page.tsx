"use client";

import { useHadesCodingRuntime } from "@/components/hades/features/coding/hooks/useHadesCodingRuntime";
import { buildStatusLabel } from "@/components/hades/features/coding/coding-runtime-core";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/**
 * Legacy Lux Coding Agent — thin live shell over shared runtime.
 * Canonical product UI is FINALBETA Coding (`#/fb/coding`).
 */
export function CodingAgentPage() {
  const coding = useHadesCodingRuntime();

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
      <header className="space-y-1">
        <h1 className="text-lg font-semibold">Coding Agent</h1>
        <p className="m-0 text-sm text-muted-foreground">
          Gedeelde Coding-runtime. Volledige UI: Settings → Interface → FINALBETA → Coding.
        </p>
        <a className="text-sm underline" href="#/fb/coding">
          Open FINALBETA Coding
        </a>
      </header>

      {coding.metaError ? <p className="text-sm text-destructive">{coding.metaError}</p> : null}
      {coding.connectionLost ? <p className="text-sm text-amber-700">Connection lost — reconnecting…</p> : null}

      <label className="grid gap-1 text-sm">
        Source repo
        <Input value={coding.sourceRepo} onChange={(e) => coding.setSourceRepo(e.target.value)} placeholder="C:\\Projects\\repo" />
      </label>
      <label className="grid gap-1 text-sm">
        Goal
        <Textarea value={coding.composerGoal} onChange={(e) => coding.setComposerGoal(e.target.value)} rows={4} />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => void coding.submitBuild()} disabled={coding.building}>
          {coding.building ? "Bezig…" : coding.backgroundRun ? "Start achtergrondjob" : "Start run"}
        </Button>
        <Button type="button" variant="outline" onClick={() => void coding.refreshRecentJobs()}>
          Jobs vernieuwen
        </Button>
        {coding.activeJobId ? (
          <Button type="button" variant="outline" onClick={() => void coding.cancelJob()}>
            Annuleer job
          </Button>
        ) : null}
      </div>

      {coding.activeJobId ? (
        <div className="rounded-lg border p-3 text-sm">
          <strong>Actieve job:</strong> {coding.activeJobId}
          <div>
            Status: {buildStatusLabel(String(coding.jobSnapshot?.status || "—"))} · fase {coding.jobPhase}
          </div>
          {coding.frontierStatus ? <div>Frontier: {buildStatusLabel(coding.frontierStatus)}</div> : null}
        </div>
      ) : null}

      <section className="space-y-2">
        <h2 className="text-sm font-medium">Recente jobs</h2>
        <ul className="m-0 list-none space-y-1 p-0">
          {coding.recentJobs.slice(0, 8).map((job) => {
            const id = String(job.id || "");
            return (
              <li key={id}>
                <button
                  type="button"
                  className="w-full rounded border px-2 py-1 text-left text-xs"
                  onClick={() => void coding.attachJob(id)}
                >
                  {id.slice(0, 12)}… · {buildStatusLabel(String(job.status || ""))} · {String(job.goal || job.title || "").slice(0, 60)}
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
