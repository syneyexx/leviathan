import type { ComputeDeviceInfo, ModelHardwareInventory } from "../../types/api";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "Unknown";
  return String(value);
}

function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Unknown";
  const gb = value / (1024 * 1024 * 1024);
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  const mb = value / (1024 * 1024);
  return `${mb.toFixed(0)} MB`;
}

export function HardwareInventoryPanel({
  hardware,
  loading,
}: {
  hardware: ModelHardwareInventory | null;
  loading?: boolean;
}) {
  if (loading && !hardware) {
    return (
      <article className="lv-panel lv-card">
        <div className="lv-section-label">Hardware</div>
        <p className="lv-muted">Loading hardware inventory…</p>
      </article>
    );
  }

  if (!hardware) {
    return (
      <article className="lv-panel lv-card">
        <div className="lv-section-label">Hardware</div>
        <p className="lv-muted">Hardware telemetry unavailable</p>
      </article>
    );
  }

  const devices = hardware.devices ?? [];
  const noGpu = devices.length === 0;

  return (
    <article className="lv-panel lv-card lv-hardware-panel">
      <div className="lv-section-label">Hardware inventory</div>
      <dl className="lv-models-dl">
        <div>
          <dt>Telemetry</dt>
          <dd>{hardware.telemetryHealth}</dd>
        </div>
        <div>
          <dt>Host RAM</dt>
          <dd>
            {formatBytes(hardware.hostMemory?.availableBytes)} available /{" "}
            {formatBytes(hardware.hostMemory?.totalBytes)} total
            {hardware.hostMemory?.pressure
              ? ` · pressure ${hardware.hostMemory.pressure}`
              : ""}
          </dd>
        </div>
        <div>
          <dt>Physical accelerators</dt>
          <dd>{devices.length}</dd>
        </div>
        <div>
          <dt>Aggregate physical VRAM</dt>
          <dd>{formatBytes(hardware.aggregatePhysicalVramBytes)}</dd>
        </div>
        <div>
          <dt>Largest single GPU</dt>
          <dd>{formatBytes(hardware.largestSingleDeviceTotalBytes)}</dd>
        </div>
      </dl>
      <p className="lv-muted" style={{ marginTop: "0.5rem" }}>
        Aggregate VRAM is informational only — it is not contiguous capacity for one model.
      </p>

      {noGpu ? (
        <p className="lv-muted" style={{ marginTop: "0.75rem" }}>
          No local accelerator detected
        </p>
      ) : (
        <div className="lv-hardware-device-list" style={{ marginTop: "0.75rem", display: "grid", gap: "0.75rem" }}>
          {devices.map((device: ComputeDeviceInfo) => (
            <div key={device.stableDeviceId} className="lv-hardware-device">
              <strong>
                {device.name ?? "GPU"}{" "}
                {device.ordinal !== null && device.ordinal !== undefined
                  ? `(ordinal ${device.ordinal})`
                  : ""}
              </strong>
              <div className="lv-muted" style={{ fontSize: "0.85rem" }}>
                {device.stableDeviceId}
                {!device.enabledForNewWork ? " · disabled for new work" : ""}
                {device.health !== "HEALTHY" ? ` · ${device.health}` : ""}
              </div>
              <dl className="lv-models-dl" style={{ marginTop: "0.35rem" }}>
                <div>
                  <dt>VRAM</dt>
                  <dd>
                    {formatBytes(device.usedVramBytes)} used / {formatBytes(device.totalVramBytes)}{" "}
                    total · {formatBytes(device.freeVramBytes)} free
                  </dd>
                </div>
                <div>
                  <dt>Utilization</dt>
                  <dd>
                    {device.utilizationPct === null || device.utilizationPct === undefined
                      ? "Unknown"
                      : `${device.utilizationPct.toFixed(0)}%`}
                  </dd>
                </div>
                <div>
                  <dt>Temperature</dt>
                  <dd>
                    {device.temperatureC === null || device.temperatureC === undefined
                      ? "Unknown"
                      : `${device.temperatureC}°C`}
                  </dd>
                </div>
                <div>
                  <dt>Vendor / backend</dt>
                  <dd>
                    {dash(device.vendor)} / {dash(device.backend)}
                  </dd>
                </div>
              </dl>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}
