export function ResearchLabStatusFooter({
  counts,
  refreshing,
  liveBlocked,
}: {
  counts: {
    total: number;
    completed: number;
    running: number;
    queued: number;
    failed: number;
  };
  refreshing?: boolean;
  liveBlocked: boolean;
}) {
  return (
    <footer className="lv-rl-footer" aria-label="Research Lab status">
      <span>
        Total runs <strong>{counts.total}</strong>
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
        Failed <strong className={counts.failed ? "is-bad" : undefined}>{counts.failed}</strong>
      </span>
      <span className={liveBlocked ? "is-good" : "is-bad"} style={{ marginLeft: "auto" }}>
        {liveBlocked ? "Live trading blocked · research on simulation" : "Live trading flag unexpected"}
        {refreshing ? " · refreshing…" : ""}
      </span>
    </footer>
  );
}
