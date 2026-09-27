import { OperatorDesktop } from "../components/OperatorDesktop";
import { controlGates } from "../domain/controls";
import { fixtureLines, fixtureModel } from "./visualFixture";

/** Test-only screen. Imported only when Vite mode is `fixture`. */
export function FixtureRoot() {
  const model = fixtureModel();
  const gates = controlGates(model.host, true, "READY");
  const noop = () => undefined;
  return (
    <OperatorDesktop
      host={model.host}
      gates={gates}
      bridge="READY"
      bridgeError={null}
      services={model.services}
      workers={model.workers}
      workerSummary={model.workerSummary}
      metrics={model.metrics}
      logs={model.logs}
      ingestion={model.ingestion}
      native={model.native}
      lines={fixtureLines()}
      checks={model.host.preflight.checks}
      paused={false}
      logsPaused={false}
      version="v0.2.6"
      uptime={model.uptime}
      servicesOnline={model.servicesOnline}
      queue={model.queue}
      frozenClock={new Date("2025-01-26T21:39:07Z")}
      utcClock
      onStart={noop}
      onStop={noop}
      onRestart={noop}
      onSafe={noop}
      onFrontend={noop}
      onConfig={noop}
      onLogs={noop}
      onEmergency={noop}
      onPause={noop}
      onClear={noop}
      onLogPause={noop}
    />
  );
}
