import type { BridgeState, ControlGate, HostSnapshot } from "../types/host";
import { hostStatusLabel } from "../domain/controls";
import { traceUi } from "../lib/trace";
import { IconConfig, IconEmergency, IconFrontend, IconLogs, IconRestart, IconSafe, IconStart, IconStop } from "./icons";

export function RuntimeControl({
  host,
  gates,
  bridge,
  onStart,
  onStop,
  onRestart,
  onSafe,
  onFrontend,
  onConfig,
  onLogs,
  onEmergency,
}: {
  host: HostSnapshot;
  gates: Record<string, ControlGate>;
  bridge: BridgeState;
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
  onSafe: () => void;
  onFrontend: () => void;
  onConfig: () => void;
  onLogs: () => void;
  onEmergency: () => void;
}) {
  const status = bridge === "FAILED"
    ? { title: "HOST BRIDGE FAILURE", detail: "The renderer is not connected to the host shell." }
    : bridge === "CONNECTING"
      ? { title: "Connecting", detail: "Waiting for host_snapshot." }
      : hostStatusLabel(host);
  return (
    <section className="runtime" aria-label="Runtime control" data-host-state={host.state} data-bridge={bridge}>
      <div className="runtime-label">
        <div className="k">RUNTIME CONTROL</div>
        <p>Operate the LEVIATHAN backend host.</p>
      </div>
      <div className="actions">
        <button
          className="btn primary"
          type="button"
          disabled={!gates.start.enabled}
          title={gates.start.reason}
          onKeyDown={(event) => {
            if (event.key === "Enter") traceUi("ACTION_START_ENTER", "host_start");
            if (event.key === " ") traceUi("ACTION_START_SPACE", "host_start");
          }}
          onClick={onStart}
        >
          <IconStart />Start Leviathan
        </button>
        <button className="btn" type="button" disabled={!gates.stop.enabled} title={gates.stop.reason} onClick={onStop}><IconStop />Stop</button>
        <button className="btn" type="button" disabled={!gates.restart.enabled} title={gates.restart.reason} onClick={onRestart}><IconRestart />Restart</button>
        <button className={host.safeModeArmed || host.safeModeActive ? "btn safe-on" : "btn"} type="button" disabled={!gates.safeMode.enabled} title={gates.safeMode.reason} onClick={onSafe}><IconSafe />Safe Mode</button>
      </div>
      <div className="status-center">
        <div className="k">SYSTEM STATUS</div>
        <strong>{status.title}</strong>
        <span className="detail">{status.detail}</span>
        {(host.safeModeArmed || host.safeModeActive) && bridge === "READY" && <span className="safe">SAFE MODE</span>}
      </div>
      <div className="utils">
        <button className="btn" type="button" disabled={!gates.frontend.enabled} title={gates.frontend.reason} onClick={onFrontend}><IconFrontend />Open Frontend</button>
        <button className="btn" type="button" disabled={bridge !== "READY"} title="Open the operator .env file" onClick={onConfig}><IconConfig />Open Config</button>
        <button className="btn" type="button" disabled={bridge !== "READY"} title="Open Data/logs/launcher" onClick={onLogs}><IconLogs />Open Logs Folder</button>
        <button className="btn danger" type="button" disabled={!gates.emergency.enabled} title={gates.emergency.reason} onClick={onEmergency}><IconEmergency />Emergency Shutdown</button>
      </div>
    </section>
  );
}
