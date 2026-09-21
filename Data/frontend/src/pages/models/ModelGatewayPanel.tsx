import type { GatewaySnapshot } from "../../types/api";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function ModelGatewayPanel({ gateway }: { gateway: GatewaySnapshot | null }) {
  if (!gateway) {
    return (
      <article className="lv-panel lv-card">
        <div className="lv-section-label">Model Gateway</div>
        <p className="lv-muted">Gateway metrics unavailable</p>
      </article>
    );
  }

  return (
    <article className="lv-panel lv-card">
      <div className="lv-section-label">Model Gateway</div>
      <div className="lv-meta-grid">
        <div className="lv-meta-item">
          <span>Models in use</span>
          <strong>{gateway.modelsInUse.length ? gateway.modelsInUse.join(", ") : "—"}</strong>
        </div>
        <div className="lv-meta-item">
          <span>Active calls</span>
          <strong>{gateway.activeCalls}</strong>
        </div>
        <div className="lv-meta-item">
          <span>Queue depth</span>
          <strong>{gateway.queueDepth}</strong>
        </div>
        <div className="lv-meta-item">
          <span>Capacity</span>
          <strong>
            {gateway.capacity.globalInflight}
            {" / "}
            {gateway.capacity.globalLimit == null ? "∞" : gateway.capacity.globalLimit}
          </strong>
        </div>
        <div className="lv-meta-item">
          <span>Last fallback</span>
          <strong>{dash(gateway.lastFallbackReason)}</strong>
        </div>
        <div className="lv-meta-item">
          <span>Calls failed</span>
          <strong>{gateway.callsFailed}</strong>
        </div>
        <div className="lv-meta-item">
          <span>Capacity timeouts</span>
          <strong>{gateway.capacityTimeouts}</strong>
        </div>
        <div className="lv-meta-item">
          <span>Last error</span>
          <strong>{dash(gateway.lastError)}</strong>
        </div>
      </div>
    </article>
  );
}
