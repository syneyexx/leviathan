import type { IngestionModel } from "../types/backend";

function count(value: number | null): string {
  return value == null ? "UNMEASURED" : String(value);
}

export function SourceIngestionPanel({ model }: { model: IngestionModel }) {
  return (
    <section className="panel" aria-label="Source ingestion">
      <header>
        <h2>SOURCE INGESTION</h2>
        <span className="sub">{model.unavailable ? "endpoint unavailable" : "Document ingestion, processing and indexing."}</span>
      </header>
      <div className="statline">
        <div><b>{count(model.queued)}</b><span>Queued</span></div>
        <div><b>{count(model.processing)}</b><span>Processing</span></div>
        <div><b>{count(model.completed)}</b><span>Completed</span></div>
        <div><b className={model.failed ? "bad" : ""}>{count(model.failed)}</b><span>Failed</span></div>
        <div className="progress-total">
          <div className="sub">Overall Progress <b>{model.overallProgressPct == null ? "UNMEASURED" : `${model.overallProgressPct}%`}</b></div>
          <div className="bar"><span style={{ width: `${Math.max(0, Math.min(100, model.overallProgressPct ?? 0))}%` }} /></div>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>DOCUMENT</th><th>TYPE</th><th>STATUS</th><th>PROGRESS</th><th>TIME</th></tr>
          </thead>
          <tbody>
            {model.jobs.length === 0 ? (
              <tr><td colSpan={6} className="empty">{model.unavailable ? "Source ingestion read model is unavailable." : "No source-ingestion jobs recorded."}</td></tr>
            ) : model.jobs.map((job) => (
              <tr key={job.id} title={[job.worker, job.throughput, job.error].filter(Boolean).join(" · ")}>
                <td>{job.id}</td>
                <td className="task">{job.source}</td>
                <td>{job.type}</td>
                <td><span className={`dot ${job.state === "Completed" || job.state === "completed" ? "ok" : job.state === "Processing" || job.state === "processing" || job.state === "parsing" ? "info" : job.state === "failed" || job.state === "Failed" ? "bad" : ""}`} />{job.state}</td>
                <td>
                  {job.progressPct == null ? "UNMEASURED" : (
                    <><span className="mini-bar"><span style={{ width: `${Math.max(0, Math.min(100, job.progressPct))}%` }} /></span>{job.progressPct}%</>
                  )}
                </td>
                <td>{job.elapsed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
