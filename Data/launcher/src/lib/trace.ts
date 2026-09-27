import { commandFailureMessage } from "./errors";
import { invokeHost, tauriAvailable } from "./api";

export interface TraceEntry {
  event: string;
  detail: string;
  at: string;
}

const buffer: TraceEntry[] = [];
const listeners = new Set<(entries: TraceEntry[]) => void>();

export function traceEnabled(): boolean {
  return import.meta.env.DEV || import.meta.env.VITE_LEVIATHAN_TRACE === "1";
}

export function traceEntries(): TraceEntry[] {
  return buffer.slice();
}

export function subscribeTrace(listener: (entries: TraceEntry[]) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Development interaction trace. Production builds do not record or display it. */
export function traceUi(event: string, detail = ""): void {
  if (!traceEnabled()) return;
  const entry = { event, detail, at: new Date().toISOString() };
  buffer.push(entry);
  if (buffer.length > 40) buffer.shift();
  console.info(`[leviathan] ${event}${detail ? ` ${detail}` : ""}`);
  for (const listener of listeners) listener(buffer.slice());
  if (!tauriAvailable()) return;
  void invokeHost("host_trace", { event, detail }).catch((error: unknown) => {
    console.info(`[leviathan] TRACE_TRANSPORT ${commandFailureMessage(error)}`);
  });
}
