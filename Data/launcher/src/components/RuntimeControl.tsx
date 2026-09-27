import type { ControlGate } from "../types/host";
import { hostStatusLabel } from "../domain/controls";
import type { HostSnapshot } from "../types/host";

export function RuntimeControl({
  host,
  gates,
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
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
  onSafe: () => void;
  onFrontend: () => void;
  onConfig: () => void;
  onLogs: () => void;
  onEmergency: () => void;
}) {
  const status = hostStatusLabel(host);
  return (
    <section className="runtime" aria-label="Runtime control">
      <div className="actions">
        <button className="btn primary" type="button" disabled={!gates.start.enabled} title={gates.start.reason} onClick={onStart}><span className="glyph">▶</span>Start Leviathan</button>
        <button className="btn" type="button" disabled={!gates.stop.enabled} title={gates.stop.reason} onClick={onStop}><span className="glyph">■</span>Stop</button>
        <button className="btn" type="button" disabled={!gates.restart.enabled} title={gates.restart.reason} onClick={onRestart}><span className="glyph">↻</span>Restart</button>
        <button className={host.safeModeArmed || host.safeModeActive ? "btn safe-on" : "btn"} type="button" disabled={!gates.safeMode.enabled} title={gates.safeMode.reason} onClick={onSafe}><span className="glyph">◇</span>Safe Mode</button>
      </div>
      <div className="status-center">
        <div className="k">SYSTEM STATUS</div>
        <strong>{status.title}</strong>
        {(host.safeModeArmed || host.safeModeActive) && <span className="safe">SAFE MODE</span>}
      </div>
      <div className="utils">
        <button className="btn" type="button" disabled={!gates.frontend.enabled} title={gates.frontend.reason} onClick={onFrontend}><span className="glyph">▣</span>Open Frontend</button>
        <button className="btn" type="button" title="Open the operator .env file" onClick={onConfig}><span className="glyph">⚙</span>Open Config</button>
        <button className="btn" type="button" title="Open Data/logs/launcher" onClick={onLogs}><span className="glyph">▤</span>Open Logs Folder</button>
        <button className="btn danger" type="button" disabled={!gates.emergency.enabled} title={gates.emergency.reason} onClick={onEmergency}><span className="glyph">⛔</span>Emergency Shutdown</button>
      </div>
    </section>
  );
}
