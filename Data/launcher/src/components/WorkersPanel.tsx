import { useMemo, useState } from "react";
import type { WorkerRowModel } from "../types/backend";

export function WorkersPanel({ rows, summary }: { rows: WorkerRowModel[]; summary: string }) {
  const [pool, setPool] = useState("ALL");
  const pools = useMemo(() => ["ALL", ...Array.from(new Set(rows.map((row) => row.pool).filter(Boolean)))], [rows]);
  const visible = pool === "ALL" ? rows : rows.filter((row) => row.pool === pool);
  return (
    <section className="panel" aria-label="Workers">
      <header>
        <div className="panel-head">
          <h2>WORKERS</h2>
          <span className="badge">{summary}</span>
        </div>
        <span className="sub">Worker Fabric</span>
      </header>
      <div className="toolbar">
        <label className="sub" htmlFor="worker-filter">Filter</label>
        <select id="worker-filter" aria-label="Worker filter" value={pool} onChange={(event) => setPool(event.target.value)}>
          {pools.map((item) => <option key={item}>{item}</option>)}
        </select>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th><th>STATE</th><th>CURRENT TASK</th><th>POOL</th><th>CPU</th><th>RAM</th><th>QUEUE</th><th>HEARTBEAT</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr><td colSpan={8} className="empty">{rows.length === 0 ? "No Worker Fabric rows. UNMEASURED until the dashboard responds." : "No workers match this filter."}</td></tr>
            ) : visible.map((row) => (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td><span className={`dot ${row.state === "BUSY" || row.state === "READY" || row.state === "RUNNING" ? "ok" : row.state === "DEGRADED" ? "warn" : row.state === "FAILED" ? "bad" : ""}`} />{row.state}</td>
                <td className="task" title={row.task}>{row.task}</td>
                <td>{row.pool}</td>
                <td>{cpuBar(row.cpu)}{row.cpu}</td>
                <td>{row.ram}</td>
                <td>{row.queue}</td>
                <td>{row.heartbeat}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function cpuBar(cpu: string) {
  const value = Number.parseFloat(cpu);
  if (!Number.isFinite(value)) return null;
  return <span className="mini-bar"><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></span>;
}
