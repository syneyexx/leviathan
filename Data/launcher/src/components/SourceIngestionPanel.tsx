import type { IngestionModel } from "../types/backend";

function count(value: number | null): string {
  return value == null ? "UNMEASURED" : String(value);
}

export function SourceIngestionPanel({ model }: { model: IngestionModel }) {
  return (
    <section className="panel" aria-label="Source ingestion">
      <header>
        <h2>SOURCE INGESTION</h2>
        <span className="sub">{model.unavailable ? "endpoint unavailable" : "JobStore + containers"}</span>
      </header>
      <div className="counters">
        <span>Queued <b>{count(model.queued)}</b></span>
        <span>Processing <b>{count(model.processing)}</b></span>
        <span>Completed <b>{count(model.completed)}</b></span>
        <span>Failed <b>{count(model.failed)}</b></span>
      </div>
      <div className="progress-total">
        <div className="sub">Overall progress {model.overallProgressPct == null ? "UNMEASURED" : `${model.overallProgressPct}%`}</div>
        <div className="bar"><span style={{ width: `${Math.max(0, Math.min(100, model.overallProgressPct ?? 0))}%` }} /></div>
      </div>
      <div className="table-wrap">
        {model.jobs.length === 0 ? <div className="empty">{model.unavailable ? "Source ingestion read model is unavailable." : "No source-ingestion jobs recorded."}</div> : (
          <table>
            <thead>
              <tr><th>JOB</th><th>SOURCE</th><th>TYPE</th><th>STATE</th><th>PROGRESS</th><th>RATE</th><th>ELAPSED</th><th>WORKER</th></tr>
            </thead>
            <tbody>
              {model.jobs.map((job) => (
                <tr key={job.id} title={job.error || ""}>
                  <td>{job.id}</td>
                  <td className="task">{job.source}</td>
                  <td>{job.type}</td>
                  <td>{job.state}</td>
                  <td>
                    {job.progressPct == null ? "UNMEASURED" : (
                      <><span className="mini-bar"><span style={{ width: `${Math.max(0, Math.min(100, job.progressPct))}%` }} /></span>{job.progressPct}%</>
                    )}
                  </td>
                  <td>{job.throughput}</td>
                  <td>{job.elapsed}</td>
                  <td>{job.worker}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
