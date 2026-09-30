import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Panel } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function HardwareIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M7 10v4M11 10v4M15 10v4" />
    </svg>
  );
}

function pct(used: number | null | undefined, total: number | null | undefined): number | null {
  if (used == null || total == null || total <= 0) return null;
  return Math.max(0, Math.min(100, (used / total) * 100));
}

export function TrainingHardwareCard({ ws }: Props) {
  const hw = ws.hardware;
  const gpus = hw?.gpus ?? [];

  return (
    <Panel title="Hardware Overzicht" icon={<HardwareIcon />} className="lv-v2-training-hardware">
      {!hw ? (
        <p className="lv-v2-muted">{ws.loading ? "Hardware laden…" : ws.hwError || "Hardware telemetrie onbeschikbaar"}</p>
      ) : (
        <ul className="lv-v2-models-meter-block lv-v2-training-hardware__list">
          {gpus.map((gpu) => {
            const total = gpu.totalVramBytes;
            const used =
              gpu.usedVramBytes ??
              (total != null && gpu.freeVramBytes != null ? total - gpu.freeVramBytes : null);
            const usedPct = gpu.utilizationPct ?? pct(used, total);
            const deviceKey = gpu.stableDeviceId || `gpu-${gpu.index}`;
            const selected = ws.draft.selectedStableDeviceId === deviceKey;
            return (
              <li key={deviceKey} className={`lv-v2-models-meter-row lv-v2-training-hardware__row${selected ? " is-selected" : ""}`}>
                <button
                  type="button"
                  className="lv-v2-training-hardware__pick"
                  aria-pressed={selected}
                  onClick={() =>
                    ws.setDraft({
                      deviceStrategy: "single",
                      selectedStableDeviceId: deviceKey,
                    })
                  }
                >
                  <div className="lv-v2-models-meter-row__head">
                    <span>
                      GPU {gpu.index} - {gpu.name || "Onbekend"}
                      {total != null ? ` (${ws.formatBytes(total, 0)})` : ""}
                    </span>
                    <span className="lv-v2-models-meter-row__value">
                      {used != null && total != null
                        ? `${ws.formatBytes(used)} / ${ws.formatBytes(total, 0)}`
                        : usedPct != null
                          ? `${Math.round(usedPct)}%`
                          : "UNMEASURED"}
                    </span>
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
                  <div className="lv-v2-training-hardware__sub">
                    {gpu.freeVramBytes != null ? `${ws.formatBytes(gpu.freeVramBytes)} vrij` : "UNMEASURED"}
                    {selected ? " · geselecteerd" : ""}
                    {gpu.stableDeviceId ? ` · ${gpu.stableDeviceId}` : ""}
                  </div>
                </button>
              </li>
            );
          })}
          {hw.ramTotalBytes != null ? (
            <li className="lv-v2-models-meter-row lv-v2-training-hardware__row">
              <div className="lv-v2-models-meter-row__head">
                <span>Systeem RAM ({ws.formatBytes(hw.ramTotalBytes, 0)})</span>
                <span className="lv-v2-models-meter-row__value">{ws.formatBytes(hw.ramTotalBytes)}</span>
              </div>
              <div
                className="lv-v2-models-meter-row__track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={
                  hw.ramAvailableBytes != null
                    ? Math.round(((hw.ramTotalBytes - hw.ramAvailableBytes) / hw.ramTotalBytes) * 100)
                    : undefined
                }
              >
                {hw.ramAvailableBytes != null ? (
                  <div
                    className="lv-v2-models-meter-row__fill"
                    style={{
                      width: `${Math.max(
                        0,
                        Math.min(100, ((hw.ramTotalBytes - hw.ramAvailableBytes) / hw.ramTotalBytes) * 100),
                      )}%`,
                    }}
                  />
                ) : null}
              </div>
              <div className="lv-v2-training-hardware__sub">
                {hw.ramAvailableBytes != null ? `${ws.formatBytes(hw.ramAvailableBytes)} vrij` : "UNMEASURED"}
              </div>
            </li>
          ) : null}
          {gpus.length === 0 ? <p className="lv-v2-muted">Geen GPU&apos;s gedetecteerd.</p> : null}
          <div className="lv-v2-training-hardware__strategy">
            <label>
              Device strategie
              <select
                value={ws.draft.deviceStrategy}
                onChange={(e) => ws.setDraft({ deviceStrategy: e.target.value })}
              >
                <option value="auto">Auto</option>
                <option value="single">Single GPU</option>
              </select>
            </label>
          </div>
        </ul>
      )}
    </Panel>
  );
}
