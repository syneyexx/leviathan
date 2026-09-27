export function ResearchLabStatusFooter({
  counts,
  refreshing,
  apiHealthy,
}: {
  counts: {
    total: number;
    completed: number;
    running: number;
    queued: number;
    failed: number;
  };
  refreshing?: boolean;
  apiHealthy: boolean;
}) {
  return (
    <footer className="lv-rl-footer" aria-label="Research Lab status">
      <div className={`lv-rl-footer-sys${apiHealthy ? "" : " is-degraded"}`}>
        {apiHealthy ? "All systems operational" : "Systems degraded"}
        {refreshing ? " · refreshing…" : ""}
      </div>
      <p className="lv-rl-footer-quote">
        Better strategies are not found, they are evolved.
        <cite>— LEVIATHAN</cite>
      </p>
      <div className="lv-rl-footer-counts">
        <span>
          Total <strong>{counts.total}</strong>
        </span>
        <span>
          Completed <strong>{counts.completed}</strong>
        </span>
        <span>
          Running <strong>{counts.running}</strong>
        </span>
        <span>
          Queued <strong>{counts.queued}</strong>
        </span>
        <span>
          Failed <strong>{counts.failed}</strong>
        </span>
      </div>
    </footer>
  );
}
