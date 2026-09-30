import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import type { ComputeDeviceInfo } from "../../types/api";
import { Panel } from "../ui";
import { formatGb } from "./modelsHelpers";

type Props = {
  ws: ModelsWorkspace;
};

function HardwareIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M7 10v4M11 10v4M15 10v4" />
    </svg>
  );
}

function deviceRoleNote(device: ComputeDeviceInfo): string | null {
  const role = (device as unknown as { role?: string }).role;
  if (role === "DISPLAY") return "Display";
  if (role === "AUXILIARY") return "Auxiliary";
  return null;
}

export function ModelsHardwareCard({ ws }: Props) {
  const hw = ws.hardware;
  const devices = hw?.devices ?? [];

  return (
    <Panel title="Hardware Overzicht" icon={<HardwareIcon />} className="lv-v2-models-hardware">
      {!hw ? (
        <p className="lv-v2-muted">{ws.loading ? "Hardware laden…" : "Hardware telemetrie onbeschikbaar"}</p>
      ) : (
        <ul className="lv-v2-models-meter-block lv-v2-models-hardware__list">
          {devices.map((device) => {
            const free = device.freeVramBytes;
            const total = device.totalVramBytes;
            const usedPct = total && free != null ? Math.max(0, Math.min(100, ((total - free) / total) * 100)) : null;
            const role = deviceRoleNote(device);
            return (
              <li key={device.stableDeviceId} className="lv-v2-models-meter-row lv-v2-models-hardware__row">
                <div className="lv-v2-models-meter-row__head">
                  <span>
                    GPU {device.ordinal ?? "—"} - {device.name || "Onbekend"} ({formatGb(total, 0)})
                  </span>
                  <span className="lv-v2-models-meter-row__value">{formatGb(total)}</span>
                </div>
                <div
                  className="lv-v2-models-meter-row__track"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={usedPct == null ? undefined : Math.round(usedPct)}
                >
                  {usedPct != null ? (
                    <div className="lv-v2-models-meter-row__fill" style={{ width: `${usedPct}%` }} />
                  ) : null}
                </div>
                <div className="lv-v2-models-hardware__sub">
                  {free != null ? `${formatGb(free)} vrij` : "UNMEASURED"}
                  {role ? ` (${role})` : ""}
                </div>
              </li>
            );
          })}
          {hw.hostMemory ? (
            <li className="lv-v2-models-meter-row lv-v2-models-hardware__row">
              <div className="lv-v2-models-meter-row__head">
                <span>Systeem RAM ({formatGb(hw.hostMemory.totalBytes, 0)})</span>
                <span className="lv-v2-models-meter-row__value">{formatGb(hw.hostMemory.totalBytes)}</span>
              </div>
              <div
                className="lv-v2-models-meter-row__track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={
                  hw.hostMemory.totalBytes && hw.hostMemory.availableBytes != null
                    ? Math.round(
                        ((hw.hostMemory.totalBytes - hw.hostMemory.availableBytes) / hw.hostMemory.totalBytes) * 100,
                      )
                    : undefined
                }
              >
                {hw.hostMemory.totalBytes && hw.hostMemory.availableBytes != null ? (
                  <div
                    className="lv-v2-models-meter-row__fill"
                    style={{
                      width: `${Math.max(
                        0,
                        Math.min(
                          100,
                          ((hw.hostMemory.totalBytes - hw.hostMemory.availableBytes) / hw.hostMemory.totalBytes) * 100,
                        ),
                      )}%`,
                    }}
                  />
                ) : null}
              </div>
              <div className="lv-v2-models-hardware__sub">
                {hw.hostMemory.availableBytes != null ? `${formatGb(hw.hostMemory.availableBytes)} vrij` : "UNMEASURED"}
              </div>
            </li>
          ) : null}
          {devices.length === 0 ? <p className="lv-v2-muted">Geen GPU's gedetecteerd.</p> : null}
        </ul>
      )}
    </Panel>
  );
}
