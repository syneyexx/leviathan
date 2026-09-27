import { useEffect, useState } from "react";
import { Banner } from "./components/Banner";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { MainConsole } from "./components/MainConsole";
import { NativeRuntimeConsole } from "./components/NativeRuntimeConsole";
import { RuntimeControl } from "./components/RuntimeControl";
import { ServiceHealthStrip } from "./components/ServiceHealthStrip";
import { SourceIngestionPanel } from "./components/SourceIngestionPanel";
import { StatusBar } from "./components/StatusBar";
import { StructuredLogs } from "./components/StructuredLogs";
import { SystemOverview } from "./components/SystemOverview";
import { TitleBar } from "./components/TitleBar";
import { WorkersPanel } from "./components/WorkersPanel";
import { useOperator } from "./hooks/useOperator";
import { tauriAvailable } from "./lib/api";

export function App() {
  const operator = useOperator();
  const [dialog, setDialog] = useState<"emergency" | "close" | null>(null);
  useEffect(() => {
    if (!tauriAvailable()) return;
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/event").then((mod) => {
      void mod.listen("host://close-requested", () => setDialog("close")).then((fn) => {
        unlisten = fn;
      });
    });
    return () => unlisten?.();
  }, []);
  const { model, gates, actions, lines } = operator;
  return (
    <>
    <div className="app">
        <TitleBar />
        <Banner />
        <RuntimeControl
          host={model.host}
          gates={gates}
          onStart={actions.start}
          onStop={actions.stop}
          onRestart={actions.restart}
          onSafe={actions.safe}
          onFrontend={actions.frontend}
          onConfig={actions.config}
          onLogs={actions.logs}
          onEmergency={() => setDialog("emergency")}
        />
        <ErrorBoundary><ServiceHealthStrip cards={model.services} /></ErrorBoundary>
        <div className="mid">
          <ErrorBoundary><MainConsole lines={lines} checks={model.host.preflight.checks} paused={operator.paused} onPause={actions.togglePause} onClear={actions.clearConsole} /></ErrorBoundary>
          <ErrorBoundary><WorkersPanel rows={model.workers} summary={model.workerSummary} /></ErrorBoundary>
          <ErrorBoundary><SystemOverview metrics={model.metrics} /></ErrorBoundary>
        </div>
        <div className="low">
          <ErrorBoundary><StructuredLogs rows={model.logs} paused={operator.logsPaused} onPause={actions.toggleLogPause} /></ErrorBoundary>
          <ErrorBoundary><SourceIngestionPanel model={model.ingestion} /></ErrorBoundary>
          <ErrorBoundary><NativeRuntimeConsole model={model.native} /></ErrorBoundary>
        </div>
        <StatusBar version={model.host.version} uptime={model.uptime} services={model.servicesOnline} workers={model.workerSummary} queue={model.queue} />
      </div>
      {operator.notice && (
        <div className="dialog-backdrop" role="presentation">
          <div className="dialog" role="alertdialog">
            <h3>Host</h3>
            <p>{operator.notice}</p>
            <div className="actions"><button className="btn" type="button" onClick={operator.clearNotice}>Close</button></div>
          </div>
        </div>
      )}
      {dialog === "emergency" && (
        <ConfirmDialog
          title="Emergency Shutdown"
          body="Force-terminate only the process tree owned by this host. This is not a clean shutdown."
          confirmLabel="Terminate owned tree"
          cancelLabel="Cancel"
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            setDialog(null);
            actions.emergency();
          }}
        />
      )}
      {dialog === "close" && (
        <ConfirmDialog
          title="LEVIATHAN is running."
          body="Stop the owned backend before exiting, or cancel and leave it running."
          confirmLabel="Stop Leviathan and Exit"
          cancelLabel="Cancel"
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            setDialog(null);
            actions.confirmClose();
          }}
        />
      )}
    </>
  );
}
