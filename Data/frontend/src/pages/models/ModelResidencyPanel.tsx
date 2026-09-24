import type { ModelResidency, ModelRuntimeBinding, ResidencyPolicy } from "../../types/api";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function ModelResidencyPanel({
  residency,
  binding,
  policy,
  onSavePolicy,
  busy,
}: {
  residency: ModelResidency | null;
  binding: ModelRuntimeBinding | null;
  policy: ResidencyPolicy | null;
  onSavePolicy: (next: Partial<ResidencyPolicy>) => Promise<void>;
  busy: boolean;
}) {
  if (!residency) {
    return (
      <article className="lv-panel lv-card">
        <div className="lv-section-label">Residency</div>
        <p className="lv-muted">No residency data yet.</p>
      </article>
    );
  }

  const external = !residency.managed || residency.state === "EXTERNAL";
  const canUnload = residency.managed && residency.activeLeaseCount === 0;

  return (
    <article className="lv-panel lv-card">
      <div className="lv-section-label">Residency</div>
      <dl className="lv-models-dl">
        <div>
          <dt>Runtime</dt>
          <dd>{dash(binding?.runtimeKind ?? residency.runtimeKind)}</dd>
        </div>
        <div>
          <dt>Managed</dt>
          <dd>{residency.managed ? "Managed" : "External"}</dd>
        </div>
        <div>
          <dt>State</dt>
          <dd>{residency.state}</dd>
        </div>
        <div>
          <dt>Placement</dt>
          <dd>{residency.placement}</dd>
        </div>
        {residency.assignedDevices && residency.assignedDevices.length > 0 ? (
          <div>
            <dt>Assigned devices</dt>
            <dd>
              {residency.assignedDevices
                .map((d) => `${d.stableDeviceId}${d.ordinal != null ? ` (ord ${d.ordinal})` : ""}`)
                .join(", ")}
            </dd>
          </div>
        ) : null}
        {residency.placementReceipt ? (
          <div>
            <dt>Placement receipt</dt>
            <dd>
              {residency.placementReceipt.state}
              {residency.placementReceipt.mismatch ? " · MISMATCH" : ""}
              {residency.placementReceipt.provenance
                ? ` · ${residency.placementReceipt.provenance}`
                : ""}
            </dd>
          </div>
        ) : null}
        {residency.reservationIds && residency.reservationIds.length > 0 ? (
          <div>
            <dt>Reservations</dt>
            <dd>{residency.reservationIds.length} held</dd>
          </div>
        ) : null}
        <div>
          <dt>Active consumers</dt>
          <dd>
            {residency.activeLeaseCount}{" "}
            {residency.consumers.length ? `(${residency.consumers.join(", ")})` : ""}
          </dd>
        </div>
        <div>
          <dt>Worker PID</dt>
          <dd>{residency.managed ? dash(residency.pid) : "n/a (external)"}</dd>
        </div>
        <div>
          <dt>Endpoint</dt>
          <dd>{dash(residency.endpoint)}</dd>
        </div>
        <div>
          <dt>Servability</dt>
          <dd>
            {dash(binding?.servabilityState)}
            {binding?.servabilityReason ? ` — ${binding.servabilityReason}` : ""}
          </dd>
        </div>
        <div>
          <dt>Last error</dt>
          <dd>{dash(residency.lastError)}</dd>
        </div>
      </dl>

      {external ? (
        <p className="lv-muted">
          Lifecycle is managed externally. Unload is disabled for this provider.
        </p>
      ) : null}
      {!canUnload && residency.managed ? (
        <p className="lv-muted">Unload blocked while active leases &gt; 0.</p>
      ) : null}

      {policy ? (
        <div className="lv-models-field">
          <label>
            Policy
            <select
              className="lv-select"
              disabled={busy}
              value={policy.policy}
              onChange={(e) => {
                void onSavePolicy({ policy: e.target.value });
              }}
            >
              <option value="KEEP_HOT">KEEP_HOT</option>
              <option value="IDLE_UNLOAD">IDLE_UNLOAD</option>
            </select>
          </label>
          <label>
            Idle unload seconds
            <input
              className="lv-input"
              type="number"
              min={0}
              disabled={busy}
              defaultValue={policy.idleUnloadSeconds}
              onBlur={(e) => {
                const v = Number(e.target.value);
                if (!Number.isNaN(v)) void onSavePolicy({ idleUnloadSeconds: v });
              }}
            />
          </label>
        </div>
      ) : null}

      {residency.resourceEstimate ? (
        <div className="lv-section-label">Resource estimate</div>
      ) : null}
      {residency.resourceEstimate ? (
        <dl className="lv-models-dl">
          <div>
            <dt>Verdict</dt>
            <dd>{residency.resourceEstimate.verdict}</dd>
          </div>
          <div>
            <dt>RAM available</dt>
            <dd>
              {dash(residency.resourceEstimate.ramAvailableBytes)} (
              {residency.resourceEstimate.ramAvailableProvenance})
            </dd>
          </div>
          <div>
            <dt>VRAM available</dt>
            <dd>
              {dash(residency.resourceEstimate.vramAvailableBytes)} (
              {residency.resourceEstimate.vramAvailableProvenance})
            </dd>
          </div>
        </dl>
      ) : null}
    </article>
  );
}
