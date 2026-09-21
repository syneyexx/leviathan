"use client";

import { ExecutionProgress } from "@/components/hades/features/agent-ux";
import { ToolCallCard } from "./ToolCallCard";
import type { ChatExecutionState } from "./types";

export function ExecutionTrace({ execution, running = false }: { execution: ChatExecutionState | null; running?: boolean }) {
  if (!execution) return null;
  return (
    <section className="execution-trace" aria-labelledby="execution-trace-title">
      <strong id="execution-trace-title" className="visually-hidden">Uitvoering</strong>
      <ExecutionProgress events={execution.live_events} status={running ? "running" : execution.status} />
      {execution.tools?.length ? (
        <div className="agent-tool-list" aria-label="Toolaanroepen">
          {execution.tools.map((tool, index) => (
            <ToolCallCard call={tool} compact key={`${String(tool.call_id || tool.tool_name || index)}-${index}`} />
          ))}
        </div>
      ) : null}
      {execution.live_events?.length && running ? (
        <small aria-live="polite">Live gebeurtenissen: {execution.live_events.length}{execution.stream_text ? " · uitvoer actief" : ""}</small>
      ) : null}
    </section>
  );
}
