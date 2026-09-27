import { useEffect, useState } from "react";
import type { IngestionModel, LogRowModel, MetricCardModel, NativeModel, ServiceCardModel, WorkerRowModel } from "../types/backend";
import type { BridgeState, CommandError, ConsoleLine, ControlGate, HostSnapshot, PreflightCheck } from "../types/host";
import { commandFailureMessage } from "../lib/errors";
import { subscribeTrace, traceEntries, type TraceEntry } from "../lib/trace";
import { Banner } from "./Banner";
import { ErrorBoundary } from "./ErrorBoundary";
import { MainConsole } from "./MainConsole";
import { NativeRuntimeConsole } from "./NativeRuntimeConsole";
import { ReferenceStage } from "./ReferenceStage";
import { RuntimeControl } from "./RuntimeControl";
import { ServiceHealthStrip } from "./ServiceHealthStrip";
import { SourceIngestionPanel } from "./SourceIngestionPanel";
import { StatusBar } from "./StatusBar";
import { StructuredLogs } from "./StructuredLogs";
import { SystemOverview } from "./SystemOverview";
import { TitleBar } from "./TitleBar";
import { WorkersPanel } from "./WorkersPanel";

export function OperatorDesktop({
  host,
  gates,
  bridge,
  bridgeError,
  services,
  workers,
  workerSummary,
  metrics,
  logs,
  ingestion,
  native,
  lines,
  checks,
  paused,
  logsPaused,
  version,
  uptime,
  servicesOnline,
  queue,
  frozenClock,
  utcClock = false,
  onStart,
  onStop,
  onRestart,
  onSafe,
  onFrontend,
  onConfig,
  onLogs,
  onEmergency,
  onPause,
  onClear,
  onLogPause,
  onWindowError,
}: {
  host: HostSnapshot;
  gates: Record<string, ControlGate>;
  bridge: BridgeState;
  bridgeError: string | null;
  services: ServiceCardModel[];
  workers: WorkerRowModel[];
  workerSummary: string;
  metrics: MetricCardModel[];
  logs: LogRowModel[];
  ingestion: IngestionModel;
  native: NativeModel;
  lines: ConsoleLine[];
  checks: PreflightCheck[];
  paused: boolean;
  logsPaused: boolean;
  version: string;
  uptime: string;
  servicesOnline: string;
  queue: string;
  frozenClock?: Date;
  utcClock?: boolean;
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
  onSafe: () => void;
  onFrontend: () => void;
  onConfig: () => void;
  onLogs: () => void;
  onEmergency: () => void;
  onPause: () => void;
  onClear: () => void;
  onLogPause: () => void;
  onWindowError?: (message: string) => void;
}) {
  const [copyNote, setCopyNote] = useState<string | null>(null);
  async function copyDiagnostic() {
    const text = bridgeError || "HOST BRIDGE FAILURE";
    try {
      await navigator.clipboard.writeText(text);
      setCopyNote("Diagnostic copied.");
    } catch (error) {
      setCopyNote(commandFailureMessage(error));
    }
  }
  return (
    <ReferenceStage>
      <div className="app">
        <TitleBar onError={onWindowError} />
        <Banner frozen={frozenClock} utc={utcClock} />
        <RuntimeControl
          host={host}
          gates={gates}
          bridge={bridge}
          onStart={onStart}
          onStop={onStop}
          onRestart={onRestart}
          onSafe={onSafe}
          onFrontend={onFrontend}
          onConfig={onConfig}
          onLogs={onLogs}
          onEmergency={onEmergency}
        />
        {bridge === "FAILED" && (
          <div className="bridge-fail" role="alert">
            <h2>HOST BRIDGE FAILURE</h2>
            <p>Operator controls are disabled. This is not a stopped backend.</p>
            <code>{bridgeError}</code>
            <div className="actions">
              <button className="btn" type="button" onClick={() => void copyDiagnostic()}>Copy diagnostic</button>
            </div>
            {copyNote && <p>{copyNote}</p>}
          </div>
        )}
        <ErrorBoundary><ServiceHealthStrip cards={services} /></ErrorBoundary>
        <div className="mid">
          <ErrorBoundary><MainConsole lines={lines} checks={checks} paused={paused} onPause={onPause} onClear={onClear} /></ErrorBoundary>
          <ErrorBoundary><WorkersPanel rows={workers} summary={workerSummary} /></ErrorBoundary>
          <ErrorBoundary><SystemOverview metrics={metrics} /></ErrorBoundary>
        </div>
        <div className="low">
          <ErrorBoundary><StructuredLogs rows={logs} paused={logsPaused} onPause={onLogPause} /></ErrorBoundary>
          <ErrorBoundary><SourceIngestionPanel model={ingestion} /></ErrorBoundary>
          <ErrorBoundary><NativeRuntimeConsole model={native} /></ErrorBoundary>
        </div>
        <StatusBar version={version} uptime={uptime} services={servicesOnline} workers={workerSummary} queue={queue} />
      </div>
    </ReferenceStage>
  );
}

export function CommandErrorDialog({ error, onClose }: { error: CommandError; onClose: () => void }) {
  return (
    <div className="dialog-backdrop" role="presentation">
      <div className="dialog" role="alertdialog">
        <h3>{error.action}</h3>
        <p>{error.message}</p>
        <div className="when">{error.at}</div>
        <div className="actions"><button className="btn" type="button" onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}

export function TracePanel() {
  const [entries, setEntries] = useState<TraceEntry[]>(() => traceEntries());
  useEffect(() => subscribeTrace(setEntries), []);
  if (!import.meta.env.DEV || import.meta.env.MODE === "fixture") return null;
  return (
    <aside className="trace-panel" aria-label="Interaction trace">
      {entries.length === 0 ? "trace idle" : entries.map((entry) => (
        <div key={`${entry.at}-${entry.event}`}>{entry.at.slice(11, 23)} {entry.event} {entry.detail}</div>
      ))}
    </aside>
  );
}
