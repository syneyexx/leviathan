import { Button, Dialog, ProgressBar } from "../ui";
import type { SystemTelemetryResponse } from "../../types/api";

type CommandsProps = {
  open: boolean;
  onClose: () => void;
  command: string;
  onCommand: (v: string) => void;
  commands: string[];
  busy: boolean;
  history: Array<{ id: string; time: string; command: string; ok: boolean }>;
  onRun: (raw?: string) => void;
};

export function ConsoleCommandsDialog({
  open,
  onClose,
  command,
  onCommand,
  commands,
  busy,
  history,
  onRun,
}: CommandsProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Operator commands"
      description="Canonical /api/console/command — geen shell bypass."
      cancelLabel="Sluiten"
      confirmLabel={busy ? "Bezig…" : "Uitvoeren"}
      busy={busy}
      onConfirm={() => onRun()}
    >
      <div className="lv-v2-console-cmd-dialog">
        <label>
          <span>Commando</span>
          <input
            value={command}
            onChange={(e) => onCommand(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onRun();
              }
            }}
            placeholder="help · modules list · mcp list · health"
            spellCheck={false}
            disabled={busy}
          />
        </label>
        <div className="lv-v2-console-common">
          {(commands.length ? commands : ["help", "health", "events 30", "modules list", "mcp list"]).map(
            (chip) => (
              <Button
                key={chip}
                variant="ghost"
                size="sm"
                onClick={() => onRun(chip)}
                disabled={busy}
              >
                {chip}
              </Button>
            ),
          )}
        </div>
        <div className="lv-v2-console-cmd-history">
          {history.length === 0 ? (
            <p className="lv-v2-muted">Nog geen commando’s deze sessie</p>
          ) : (
            history.map((h) => (
              <button key={h.id} type="button" onClick={() => onCommand(h.command)}>
                <span>{h.time}</span>
                <span className={h.ok ? "ok" : "err"}>{h.command}</span>
              </button>
            ))
          )}
        </div>
      </div>
    </Dialog>
  );
}

type ResourcesProps = {
  open: boolean;
  onClose: () => void;
  sample: SystemTelemetryResponse | null;
  error: string | null;
};

export function ConsoleResourcesDialog({ open, onClose, sample, error }: ResourcesProps) {
  const cpu = sample?.dashboard.cpuPct;
  const ram = sample?.dashboard.ramPct;
  const gpu = sample?.dashboard.gpuPct;
  const vram = sample?.dashboard.vramPct;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Resources"
      description="SystemTelemetrySampler — gemeten of UNAVAILABLE."
      cancelLabel="Sluiten"
    >
      <div className="lv-v2-console-resources-dialog">
        {error ? <p className="lv-v2-warn">{error}</p> : null}
        {(
          [
            ["CPU", cpu],
            ["RAM", ram],
            ["GPU", gpu],
            ["VRAM", vram],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="lv-v2-console-resource-row">
            <div className="head">
              <span>{label}</span>
              <span>{value == null ? "UNAVAILABLE" : `${value.toFixed(0)}%`}</span>
            </div>
            {value != null ? <ProgressBar value={value} /> : null}
          </div>
        ))}
      </div>
    </Dialog>
  );
}
