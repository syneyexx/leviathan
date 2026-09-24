import type { DownloadJob } from "../../types/api";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function progressLabel(job: DownloadJob): string {
  if (job.bytesDownloaded == null) return "—";
  const down = job.bytesDownloaded;
  if (job.totalBytes != null && job.totalBytes > 0) {
    const pct = Math.min(100, Math.round((down / job.totalBytes) * 100));
    return `${down} / ${job.totalBytes} (${pct}%)`;
  }
  return String(down);
}

export function ModelDownloadManager({
  downloads,
  onRefresh,
  onCancel,
  busy = false,
}: {
  downloads: DownloadJob[];
  onRefresh: () => Promise<void>;
  onCancel: (id: string) => Promise<void>;
  busy?: boolean;
}) {
  return (
    <article className="lv-panel lv-card">
      <div className="lv-card-head">
        <div className="lv-section-label">Downloads</div>
        <button className="lv-link" type="button" disabled={busy} onClick={() => void onRefresh()}>
          Refresh
        </button>
      </div>
      {downloads.length === 0 ? (
        <p className="lv-muted">No download jobs</p>
      ) : (
        <table className="lv-models-table">
          <thead>
            <tr>
              <th>State</th>
              <th>Source</th>
              <th>Repository</th>
              <th>Progress</th>
              <th>Speed</th>
              <th>Error</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {downloads.map((job) => (
              <tr key={job.id}>
                <td>{job.state}</td>
                <td>{job.source}</td>
                <td>{dash(job.repositoryId)}</td>
                <td>{progressLabel(job)}</td>
                <td>{job.speedBps == null ? "—" : `${Math.round(job.speedBps)} B/s`}</td>
                <td>{dash(job.error)}</td>
                <td>
                  {["QUEUED", "DOWNLOADING", "PAUSED", "VERIFYING"].includes(job.state) ? (
                    <button
                      className="lv-btn"
                      type="button"
                      disabled={busy}
                      onClick={() => void onCancel(job.id)}
                    >
                      Cancel
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </article>
  );
}
