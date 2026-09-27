import type { WorkerRowModel } from "../types/backend";

export function WorkersPanel({ rows, summary }: { rows: WorkerRowModel[]; summary: string }) {
  return (
    <section className="panel" aria-label="Workers">
      <header>
        <h2>WORKERS</h2>
        <span className="sub">Worker Fabric · {summary}</span>
      </header>
      <div className="table-wrap">
        {rows.length === 0 ? <div className="empty">No Worker Fabric rows. UNMEASURED until the dashboard responds.</div> : (
          <table>
            <thead>
              <tr>
                <th>ID</th><th>STATE</th><th>CURRENT TASK</th><th>POOL</th><th>CPU</th><th>RAM</th><th>QUEUE</th><th>HEARTBEAT</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td><span className={`dot ${row.state === "BUSY" || row.state === "READY" || row.state === "RUNNING" ? "ok" : row.state === "DEGRADED" ? "warn" : row.state === "FAILED" ? "bad" : ""}`} />{row.state}</td>
                  <td className="task" title={row.task}>{row.task}</td>
                  <td>{row.pool}</td>
                  <td>{row.cpu}</td>
                  <td>{row.ram}</td>
                  <td>{row.queue}</td>
                  <td>{row.heartbeat}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
