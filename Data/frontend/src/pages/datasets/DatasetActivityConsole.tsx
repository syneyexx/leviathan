import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DatasetActivityEntry, DatasetJob } from "../../types/api";
import {
  type ActivityFilter,
  type TransferSample,
  downloadSummary,
  entriesToPlainText,
  estimatedRemainingSeconds,
  filterEntries,
  formatBytes,
  formatClock,
  formatDuration,
  formatRate,
  isActiveJob,
  isCancelledJob,
  isCompletedJob,
  isErrorJob,
  jobTypeLabel,
  observedTransferRate,
  pickActiveJob,
  progressRatio,
} from "./datasetActivity";

type Props = {
  jobs: DatasetJob[];
  entries: DatasetActivityEntry[];
  preferredJobId?: string | null;
  onPreferredJobIdChange?: (jobId: string | null) => void;
  apiError?: string | null;
  live: boolean;
  busy?: boolean;
  onCancelJob?: (jobId: string) => void | Promise<void>;
  onClearView?: () => void;
};

export function DatasetActivityConsole({
  jobs,
  entries,
  preferredJobId = null,
  onPreferredJobIdChange,
  apiError = null,
  live,
  busy = false,
  onCancelJob,
  onClearView,
}: Props) {
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const [jobFilter, setJobFilter] = useState<string>("all");
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const logRef = useRef<HTMLDivElement>(null);
  const rateSamplesRef = useRef<TransferSample[]>([]);
  const [rateBytesPerSec, setRateBytesPerSec] = useState<number | null>(null);

  const activeJob = useMemo(
    () => pickActiveJob(jobs, preferredJobId || (jobFilter !== "all" ? jobFilter : null)),
    [jobs, preferredJobId, jobFilter],
  );

  const visible = useMemo(
    () => filterEntries(entries, filter, jobFilter === "all" ? "all" : jobFilter),
    [entries, filter, jobFilter],
  );

  const summaryJob = activeJob ?? (jobFilter !== "all" ? jobs.find((j) => j.jobId === jobFilter) ?? null : null);
  const dl = summaryJob ? downloadSummary(summaryJob) : null;
  const ratio = summaryJob ? progressRatio(summaryJob) : null;

  useEffect(() => {
    if (!activeJob) {
      rateSamplesRef.current = [];
      setRateBytesPerSec(null);
      return;
    }
    const bytes = downloadSummary(activeJob)?.bytesDownloaded;
    if (bytes == null) return;
    const sample = { atMs: Date.now(), bytes };
    const next = [...rateSamplesRef.current, sample].slice(-24);
    rateSamplesRef.current = next;
    setRateBytesPerSec(observedTransferRate(next));
  }, [activeJob?.jobId, activeJob?.updatedAt, activeJob?.checkpoint?.bytesDownloaded, activeJob?.download?.bytesDownloaded]);

  const etaSec =
    activeJob && dl
      ? estimatedRemainingSeconds(dl.bytesDownloaded, dl.bytesTotal, rateBytesPerSec)
      : null;

  useEffect(() => {
    if (!pinnedToBottom || !logRef.current) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [visible, pinnedToBottom]);

  const onScroll = useCallback(() => {
    const el = logRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    setPinnedToBottom(distance < 48);
  }, []);

  const jumpToLatest = useCallback(() => {
    setPinnedToBottom(true);
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const copyLog = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(entriesToPlainText(visible));
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1600);
    } catch {
      setCopyState("failed");
      window.setTimeout(() => setCopyState("idle"), 2000);
    }
  }, [visible]);

  const statusTone = summaryJob
    ? isErrorJob(summaryJob)
      ? "error"
      : isCompletedJob(summaryJob)
        ? "success"
        : isCancelledJob(summaryJob)
          ? "muted"
          : isActiveJob(summaryJob)
            ? "active"
            : "info"
    : "muted";

  return (
    <section className="lv-dac" aria-label="Dataset Activity">
      <header className="lv-dac-head">
        <div className="lv-dac-title-row">
          <h2 className="lv-dac-title">Dataset Activity</h2>
          <span className={`lv-dac-live${live ? " is-live" : " is-idle"}`} aria-live="polite">
            {live ? "LIVE" : "IDLE"}
          </span>
        </div>
        <p className="lv-dac-sub">Real-time operational console · backend job truth</p>
        <div className="lv-dac-toolbar">
          <div className="lv-dac-filters" role="tablist" aria-label="Activity filters">
            {(["all", "active", "errors", "completed"] as ActivityFilter[]).map((f) => (
              <button
                key={f}
                type="button"
                role="tab"
                aria-selected={filter === f}
                className={`lv-dac-chip${filter === f ? " is-active" : ""}`}
                onClick={() => setFilter(f)}
              >
                {f === "all" ? "All" : f === "active" ? "Active" : f === "errors" ? "Errors" : "Completed"}
              </button>
            ))}
          </div>
          <label className="lv-dac-job-select">
            <span className="lv-sr-only">Job</span>
            <select
              value={jobFilter}
              onChange={(e) => {
                const v = e.target.value;
                setJobFilter(v);
                onPreferredJobIdChange?.(v === "all" ? null : v);
              }}
              aria-label="Filter by job"
            >
              <option value="all">All jobs</option>
              {jobs.map((j) => (
                <option key={j.jobId} value={j.jobId}>
                  {jobTypeLabel(j.jobType)} · {j.status} · {j.jobId.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <div className="lv-dac-actions">
            <button type="button" className="lv-dh-btn" onClick={() => void copyLog()} aria-label="Copy log">
              {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy log"}
            </button>
            <button
              type="button"
              className="lv-dh-btn"
              onClick={() => onClearView?.()}
              aria-label="Clear view"
              disabled={!onClearView}
            >
              Clear view
            </button>
          </div>
        </div>
      </header>

      {apiError ? (
        <div className="lv-dac-banner is-error" role="alert">
          Jobs API: {apiError}
        </div>
      ) : null}

      {summaryJob ? (
        <div className={`lv-dac-active is-${statusTone}`} aria-live="polite">
          <div className="lv-dac-active-top">
            <div>
              <div className="lv-dac-active-label">{jobTypeLabel(summaryJob.jobType)}</div>
              <div className="lv-dac-active-meta">
                {dl?.repositoryId ? (
                  <span>
                    {dl.repositoryId}
                    {dl.filename ? ` · ${dl.filename}` : ""}
                  </span>
                ) : summaryJob.datasetId ? (
                  <span>Dataset {summaryJob.datasetId.slice(0, 12)}</span>
                ) : (
                  <span>Job {summaryJob.jobId.slice(0, 12)}</span>
                )}
              </div>
            </div>
            <div className="lv-dac-active-status">
              <span className="lv-dac-status-text">{summaryJob.status}</span>
              {summaryJob.phase ? <span className="lv-dac-phase">{summaryJob.phase}</span> : null}
            </div>
          </div>

          <dl className="lv-dac-stats">
            {dl?.bytesDownloaded != null ? (
              <div>
                <dt>Progress</dt>
                <dd>
                  {dl.bytesTotal != null
                    ? `${formatBytes(dl.bytesDownloaded)} / ${formatBytes(dl.bytesTotal)}`
                    : `${formatBytes(dl.bytesDownloaded)} downloaded · total size unknown`}
                </dd>
              </div>
            ) : null}
            {dl?.filesTotal != null ? (
              <div>
                <dt>Files</dt>
                <dd>
                  {dl.filesCompleted ?? 0} / {dl.filesTotal}
                </dd>
              </div>
            ) : null}
            {formatRate(rateBytesPerSec) ? (
              <div>
                <dt>Observed rate</dt>
                <dd>{formatRate(rateBytesPerSec)}</dd>
              </div>
            ) : null}
            {formatDuration(etaSec) ? (
              <div>
                <dt>Estimated remaining</dt>
                <dd>{formatDuration(etaSec)}</dd>
              </div>
            ) : null}
            {(dl?.attempts ?? 0) > 1 || (dl?.rateLimitEvents ?? 0) > 0 ? (
              <div>
                <dt>Retries</dt>
                <dd>
                  attempt {dl?.attempts ?? "—"}
                  {dl?.rateLimitEvents != null ? ` · 429×${dl.rateLimitEvents}` : ""}
                  {dl?.lastHttpStatus != null ? ` · HTTP ${dl.lastHttpStatus}` : ""}
                </dd>
              </div>
            ) : null}
            {summaryJob.error ? (
              <div className="lv-dac-error-row">
                <dt>Error</dt>
                <dd>{summaryJob.error}</dd>
              </div>
            ) : null}
          </dl>

          {ratio != null ? (
            <div
              className="lv-dac-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(ratio * 100)}
              aria-label="Download progress"
            >
              <i style={{ width: `${Math.round(ratio * 1000) / 10}%` }} />
              <span className="lv-dac-bar-label">{(Math.round(ratio * 1000) / 10).toFixed(1)}%</span>
            </div>
          ) : null}

          {isActiveJob(summaryJob) && onCancelJob ? (
            <div className="lv-dac-active-actions">
              <button
                type="button"
                className="lv-dh-btn"
                disabled={busy || summaryJob.cancelRequested}
                onClick={() => void onCancelJob(summaryJob.jobId)}
              >
                {summaryJob.cancelRequested ? "Cancel requested…" : "Cancel job"}
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="lv-dac-empty-active" role="status">
          No active dataset job. Recent activity appears below when jobs exist.
        </div>
      )}

      <div className="lv-dac-log-wrap">
        <div
          ref={logRef}
          className="lv-dac-log"
          role="log"
          aria-label="Dataset activity log"
          tabIndex={0}
          onScroll={onScroll}
        >
          {visible.length === 0 ? (
            <div className="lv-dac-log-empty">No activity entries for this filter.</div>
          ) : (
            visible.map((entry) => <ActivityLine key={entry.id} entry={entry} />)
          )}
        </div>
        {!pinnedToBottom ? (
          <button type="button" className="lv-dac-jump" onClick={jumpToLatest}>
            ↓ Jump to latest
          </button>
        ) : null}
      </div>
    </section>
  );
}

function ActivityLine({ entry }: { entry: DatasetActivityEntry }) {
  return (
    <div className={`lv-dac-line is-${entry.level}`}>
      <span className="lv-dac-ts">{formatClock(entry.timestamp)}</span>
      <span className="lv-dac-stage">{entry.stage || entry.level.toUpperCase()}</span>
      <span className="lv-dac-msg">{entry.message}</span>
    </div>
  );
}
