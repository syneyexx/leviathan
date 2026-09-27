import { useState } from "react";
import type { LogRowModel } from "../types/backend";
import { filterLogs } from "../domain/logs";

export function StructuredLogs({ rows, paused, onPause }: { rows: LogRowModel[]; paused: boolean; onPause: () => void }) {
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState("ALL");
  const visible = filterLogs(rows, query, level).slice(0, 200);
  return (
    <section className="panel" aria-label="Structured logs">
      <header>
        <h2>LOGS</h2>
        <span className="sub">Observability events</span>
      </header>
      <div className="toolbar">
        <button className="btn" type="button" onClick={onPause}>{paused ? "Resume" : "Pause"}</button>
        <select aria-label="Level filter" value={level} onChange={(event) => setLevel(event.target.value)}>
          {["ALL", "INFO", "WARNING", "ERROR", "SUCCESS"].map((item) => <option key={item}>{item}</option>)}
        </select>
        <input aria-label="Search logs" placeholder="Search" value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>
      <div className="table-wrap">
        {visible.length === 0 ? <div className="empty">No structured events yet.</div> : (
          <table>
            <thead><tr><th>TIME</th><th>LEVEL</th><th>MODULE</th><th>MESSAGE</th></tr></thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.id}>
                  <td>{row.time}</td>
                  <td className={`tone-${row.level === "ERROR" ? "bad" : row.level === "WARNING" ? "warn" : "ok"}`}>{row.level}</td>
                  <td>{row.module}</td>
                  <td className="task" title={row.message}>{row.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
