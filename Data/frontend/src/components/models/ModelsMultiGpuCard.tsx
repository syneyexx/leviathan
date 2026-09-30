import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Panel } from "../ui";
import { FieldRow, ToggleControl } from "./ModelsFormControls";
import { formatGb } from "./modelsHelpers";

type Props = {
  ws: ModelsWorkspace;
};

const SPLIT_MODES = [
  { id: "auto", label: "Auto (Optimaliseren)" },
  { id: "evenly", label: "Gelijk verdelen" },
  { id: "priority", label: "Prioriteit" },
  { id: "manual", label: "Handmatig" },
  { id: "single", label: "Enkele GPU" },
];

function GpuIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <rect x="3" y="7" width="15" height="10" rx="2" />
      <path d="M18 10h3v4h-3" />
      <path d="M7 10v4M11 10v4" />
    </svg>
  );
}

export function ModelsMultiGpuCard({ ws }: Props) {
  const { draft, setDraft, setGpuAllocation, capSupport, capNote } = ws;
  const disabled = !ws.selectedId;
  const devices = ws.hardware?.devices ?? [];
  const manual = draft.gpuSplitMode === "manual";
  const sliderUnsupported = capSupport("customGpuSplit") === "UNSUPPORTED";

  return (
    <Panel title="Multi-GPU Verdelen" icon={<GpuIcon />} className="lv-v2-models-multi-gpu">
      <p className="lv-v2-muted lv-v2-models-load-config__desc">
        Verdeel de model-lagen over je GPU's.
      </p>

      <FieldRow label="Verdelingsmodus" note={capNote("gpuSplit")}>
        <select
          className="lv-v2-select"
          disabled={disabled || capSupport("gpuSplit") === "UNSUPPORTED"}
          value={draft.gpuSplitMode}
          onChange={(e) => setDraft({ gpuSplitMode: e.target.value })}
        >
          {SPLIT_MODES.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </FieldRow>

      {devices.length === 0 ? (
        <p className="lv-v2-muted">Geen GPU's gedetecteerd.</p>
      ) : (
        <ul className="lv-v2-models-multi-gpu__list">
          {devices.map((device) => {
            const ratio = manual
              ? draft.gpuAllocation[device.stableDeviceId] ?? draft.gpuOffloadRatio
              : draft.gpuOffloadRatio;
            const usedBytes = device.totalVramBytes != null ? ratio * device.totalVramBytes : null;
            return (
              <li key={device.stableDeviceId} className="lv-v2-models-multi-gpu__row">
                <div className="lv-v2-models-multi-gpu__row-head">
                  <span>
                    GPU {device.ordinal ?? "—"} - {device.name || "Onbekend"} ({formatGb(device.totalVramBytes, 0)})
                  </span>
                </div>
                <div className="lv-v2-models-range">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={Math.round(ratio * 100)}
                    disabled={disabled || !manual || sliderUnsupported}
                    onChange={(e) => setGpuAllocation(device.stableDeviceId, Number(e.target.value) / 100)}
                    className="lv-v2-range"
                  />
                  <span className="lv-v2-models-range__value">{Math.round(ratio * 100)}%</span>
                </div>
                <div className="lv-v2-models-hardware__sub">
                  {usedBytes != null
                    ? `~${formatGb(usedBytes)} (van ${formatGb(device.totalVramBytes, 0)})`
                    : "UNMEASURED"}
                  {!manual ? " · automatisch" : ""}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <ToggleControl
        checked={draft.keepDisplayHeadroom}
        disabled={disabled}
        onChange={(v) => setDraft({ keepDisplayHeadroom: v })}
        label="Display GPU headroom behouden"
      />
      <p className="lv-v2-models-cap-note lv-v2-models-multi-gpu__hint">
        De definitieve verdeling kan afwijken op basis van modelgrootte en geheugeninschatting.
      </p>
    </Panel>
  );
}
