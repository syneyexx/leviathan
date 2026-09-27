import { useEffect, useState } from "react";
import { CommandErrorDialog, OperatorDesktop, TracePanel } from "./components/OperatorDesktop";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { useOperator } from "./hooks/useOperator";
import { tauriAvailable } from "./lib/api";

export function App() {
  const operator = useOperator();
  const [dialog, setDialog] = useState<"emergency" | "close" | null>(null);
  const [windowError, setWindowError] = useState<string | null>(null);
  useEffect(() => {
    if (!tauriAvailable()) return;
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/event").then((mod) => {
      void mod.listen("host://close-requested", () => setDialog("close")).then((fn) => {
        unlisten = fn;
      }).catch((error: unknown) => {
        setWindowError(error instanceof Error ? error.message : "Close listener failed");
      });
    }).catch((error: unknown) => {
      setWindowError(error instanceof Error ? error.message : "Tauri event import failed");
    });
    return () => unlisten?.();
  }, []);
  const { model, gates, actions, lines, bridge, bridgeError, commandError } = operator;
  const alert = commandError || (windowError ? { action: "window", message: windowError, at: "" } : null);
  return (
    <>
      <OperatorDesktop
        host={model.host}
        gates={gates}
        bridge={bridge}
        bridgeError={bridgeError}
        services={model.services}
        workers={model.workers}
        workerSummary={model.workerSummary}
        metrics={model.metrics}
        logs={model.logs}
        ingestion={model.ingestion}
        native={model.native}
        lines={lines}
        checks={model.host.preflight.checks}
        paused={operator.paused}
        logsPaused={operator.logsPaused}
        version={model.host.version}
        uptime={model.uptime}
        servicesOnline={model.servicesOnline}
        queue={model.queue}
        onStart={actions.start}
        onStop={actions.stop}
        onRestart={actions.restart}
        onSafe={actions.safe}
        onFrontend={actions.frontend}
        onConfig={actions.config}
        onLogs={actions.logs}
        onEmergency={() => setDialog("emergency")}
        onPause={actions.togglePause}
        onClear={actions.clearConsole}
        onLogPause={actions.toggleLogPause}
        onWindowError={setWindowError}
      />
      <TracePanel />
      {alert && (
        <CommandErrorDialog
          error={{ action: alert.action, message: alert.message, at: alert.at || new Date().toISOString() }}
          onClose={() => {
            operator.clearCommandError();
            setWindowError(null);
          }}
        />
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
