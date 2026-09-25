import type { AgentDefinition, DatasetLearningStatus, DatasetRecord } from "../../types/api";

export function DatasetLearningSection({
  agent,
  datasetLearning,
  datasets,
  busy,
  onCancelJob,
  onRetryJob,
  onReindex,
}: {
  agent: AgentDefinition | undefined;
  datasetLearning: DatasetLearningStatus | null;
  datasets: DatasetRecord[];
  busy: boolean;
  onCancelJob: (jobId: string) => void;
  onRetryJob: (jobId: string) => void;
  onReindex: (datasetId: string) => void;
}) {
  return (
    <div className="lv-ag-policy-block">
      <p>
        Dataset access policy: <strong>{agent?.datasetAccess ?? "none"}</strong>
      </p>
      <p className="lv-ag-field-hint">
        Dataset Learning mirrors real <code>dataset_jobs</code> — not fictional missions. Active index
        jobs: {datasetLearning?.activity.activeCount ?? 0}
      </p>
      {(datasetLearning?.activity.active?.length || 0) > 0 ? (
        <ul className="lv-ag-member-list">
          {datasetLearning!.activity.active.map((job) => {
            const act = job.activity;
            const pct = act?.progress != null ? `${Math.round(Number(act.progress) * 100)}%` : "—";
            return (
              <li key={job.jobId}>
                <span>
                  {act?.datasetName || act?.datasetId || job.datasetId || "dataset"} ·{" "}
                  {act?.phase || job.phase || "—"} · {pct}
                  {act?.processed != null ? ` · rows ${act.processed}` : ""}
                  {act?.chunkCount != null ? ` · chunks ${act.chunkCount}` : ""}
                  {act?.relationsAccepted != null
                    ? ` · rel +${act.relationsAccepted}/−${act.relationsRejected ?? 0}`
                    : ""}
                  {act?.embeddingMode ? ` · ${act.embeddingMode}` : ""}
                  {act?.embeddingsSemantic === false ? " (not semantic)" : ""}
                </span>
                <span className="lv-ag-inline-actions">
                  <button
                    type="button"
                    className="lv-ag-btn-stop is-xs"
                    disabled={busy}
                    onClick={() => onCancelJob(job.jobId)}
                  >
                    Cancel
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="lv-ag-empty">No active dataset index jobs.</p>
      )}
      {(datasetLearning?.activity.recent?.length || 0) > 0 ? (
        <>
          <p className="lv-ag-field-hint">Recent index jobs</p>
          <ul className="lv-ag-member-list">
            {datasetLearning!.activity.recent.slice(0, 8).map((job) => {
              const act = job.activity;
              const terminal = ["failed", "cancelled", "interrupted"].includes(
                String(job.status).toLowerCase(),
              );
              return (
                <li key={`recent-${job.jobId}`}>
                  <span>
                    {act?.datasetName || job.datasetId || "dataset"} · {job.status}
                    {act?.phase ? ` · ${act.phase}` : ""}
                    {act?.error ? ` · ${String(act.error).slice(0, 80)}` : ""}
                  </span>
                  <span className="lv-ag-inline-actions">
                    {terminal ? (
                      <button
                        type="button"
                        className="lv-ag-btn-teal is-xs"
                        disabled={busy}
                        onClick={() => onRetryJob(job.jobId)}
                      >
                        Retry
                      </button>
                    ) : null}
                    {job.datasetId && job.status === "completed" ? (
                      <button
                        type="button"
                        className="lv-ag-btn-teal is-xs"
                        disabled={busy}
                        onClick={() => {
                          if (
                            !window.confirm(
                              "Rebuild replaces existing learned results for this dataset. Continue?",
                            )
                          ) {
                            return;
                          }
                          onReindex(String(job.datasetId));
                        }}
                      >
                        Re-index
                      </button>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}
      <p className="lv-ag-field-hint">Fleet datasets available in the system ({datasets.length}):</p>
      {datasets.length === 0 ? (
        <p className="lv-ag-empty">No datasets registered.</p>
      ) : (
        <ul className="lv-ag-member-list">
          {datasets.slice(0, 12).map((d) => (
            <li key={d.datasetId}>
              <span>{d.name}</span>
              <span>
                {d.status} · {d.sourceType}
                {d.brainStatus ? ` · brain:${d.brainStatus}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
