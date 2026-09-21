import type { DownloadJob } from "../../types/api";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function ModelDownloadManager({
  downloads,
  onRefresh,
  onCancel,
}: {
  downloads: DownloadJob[];
  onRefresh: () => Promise<void>;
  onCancel: (id: string) => Promise<void>;
}) {
  return (
    <article className="lv-panel lv-card">
      <div className="lv-card-head">
        <div className="lv-section-label">Downloads</div>
        <button className="lv-link" type="button" onClick={() => void onRefresh()}>
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
                <td>
                  {job.bytesDownloaded == null
                    ? "—"
                    : `${job.bytesDownloaded}${job.totalBytes != null ? ` / ${job.totalBytes}` : ""}`}
                </td>
                <td>{dash(job.error)}</td>
                <td>
                  {["QUEUED", "DOWNLOADING", "PAUSED", "VERIFYING"].includes(job.state) ? (
                    <button className="lv-btn" type="button" onClick={() => void onCancel(job.id)}>
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
