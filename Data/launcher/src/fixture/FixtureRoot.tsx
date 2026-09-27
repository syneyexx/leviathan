import { Banner } from "../components/Banner";
import { MainConsole } from "../components/MainConsole";
import { NativeRuntimeConsole } from "../components/NativeRuntimeConsole";
import { RuntimeControl } from "../components/RuntimeControl";
import { ServiceHealthStrip } from "../components/ServiceHealthStrip";
import { SourceIngestionPanel } from "../components/SourceIngestionPanel";
import { StatusBar } from "../components/StatusBar";
import { StructuredLogs } from "../components/StructuredLogs";
import { SystemOverview } from "../components/SystemOverview";
import { TitleBar } from "../components/TitleBar";
import { WorkersPanel } from "../components/WorkersPanel";
import { controlGates } from "../domain/controls";
import { fixtureLines, fixtureModel } from "./visualFixture";

/** Test-only screen. Imported only when Vite mode is `fixture`. */
export function FixtureRoot() {
  const model = fixtureModel();
  const gates = controlGates(model.host, true);
  const noop = () => undefined;
  return (
    <div className="app" data-visual-fixture="1">
      <TitleBar />
      <Banner frozen={new Date("2026-09-27T21:39:07")} />
      <RuntimeControl
        host={model.host}
        gates={gates}
        onStart={noop}
        onStop={noop}
        onRestart={noop}
        onSafe={noop}
        onFrontend={noop}
        onConfig={noop}
        onLogs={noop}
        onEmergency={noop}
      />
      <ServiceHealthStrip cards={model.services} />
      <div className="mid">
        <MainConsole lines={fixtureLines()} checks={[]} paused={false} onPause={noop} onClear={noop} />
        <WorkersPanel rows={model.workers} summary={model.workerSummary} />
        <SystemOverview metrics={model.metrics} />
      </div>
      <div className="low">
        <StructuredLogs rows={model.logs} paused={false} onPause={noop} />
        <SourceIngestionPanel model={model.ingestion} />
        <NativeRuntimeConsole model={model.native} />
      </div>
      <StatusBar version={model.host.version} uptime={model.uptime} services={model.servicesOnline} workers={model.workerSummary} queue={model.queue} />
    </div>
  );
}
