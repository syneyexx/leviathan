import { useMemo, useState } from "react";
import type { ConsoleLine } from "../types/host";
import type { PreflightCheck } from "../types/host";
import { VirtualList } from "./VirtualList";

export function MainConsole({
  lines,
  checks,
  paused,
  onPause,
  onClear,
}: {
  lines: ConsoleLine[];
  checks: PreflightCheck[];
  paused: boolean;
  onPause: () => void;
  onClear: () => void;
}) {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("ALL");
  const sources = useMemo(() => ["ALL", ...Array.from(new Set(lines.map((line) => line.source)))], [lines]);
  const visible = lines.filter((line) => {
    if (source !== "ALL" && line.source !== source) return false;
    if (!query.trim()) return true;
    return `${line.text} ${line.level} ${line.source}`.toLowerCase().includes(query.trim().toLowerCase());
  });
  return (
    <section className="panel" aria-label="Main console">
      <header>
        <h2>MAIN CONSOLE</h2>
        <span className="sub">Backend host sequence and captured output</span>
      </header>
      <div className="toolbar">
        <button className="btn" type="button" onClick={onPause}>{paused ? "Resume" : "Pause"}</button>
        <button className="btn" type="button" onClick={onClear} title="Clears the view only. Log files are kept.">Clear view</button>
        <input aria-label="Search console" placeholder="Search" value={query} onChange={(event) => setQuery(event.target.value)} />
        <select aria-label="Source filter" value={source} onChange={(event) => setSource(event.target.value)}>
          {sources.map((item) => <option key={item}>{item}</option>)}
        </select>
      </div>
      {checks.some((check) => check.status === "FAIL") && (
        <div className="checks">
          <ul>
            {checks.filter((check) => check.status === "FAIL").map((check) => (
              <li key={check.id} className="FAIL">{check.id}: {check.detail} {check.remediation}</li>
            ))}
          </ul>
        </div>
      )}
      <VirtualList
        items={visible}
        rowHeight={18}
        render={(line) => (
          <div className="row">
            <span className="ts">{line.at.slice(11, 19)}</span>
            <span className="src">{line.source}</span>
            <span className={`lvl ${line.level}`}>{line.level}</span>
            <span className="msg">{line.text}</span>
          </div>
        )}
      />
    </section>
  );
}
