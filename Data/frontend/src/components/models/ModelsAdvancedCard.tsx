import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Panel } from "../ui";
import { FieldRow, ToggleControl } from "./ModelsFormControls";

type Props = {
  ws: ModelsWorkspace;
};

const KV_DTYPE_OPTIONS = [
  { id: "auto", label: "Auto (Q8)" },
  { id: "q8_0", label: "Q8" },
  { id: "q4_0", label: "Q4" },
  { id: "f16", label: "F16" },
];

const SHARDING_MODES = [
  { id: "auto", label: "Auto" },
  { id: "NONE", label: "Geen" },
  { id: "TENSOR_SPLIT", label: "Tensor Split" },
  { id: "TENSOR_PARALLEL", label: "Tensor Parallel" },
  { id: "PIPELINE_PARALLEL", label: "Pipeline Parallel" },
];

function WrenchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M14 7l3 3-8 8H6v-3l8-8z" />
      <path d="M12 5l2-2 5 5-2 2" />
    </svg>
  );
}

export function ModelsAdvancedCard({ ws }: Props) {
  const { draft, setDraft, capSupport, capNote } = ws;
  const disabled = !ws.selectedId;
  const devices = ws.hardware?.devices ?? [];
  const speculativeCap = capSupport("speculativeDecoding");
  const draftModels = ws.models.filter((m) => m.id !== ws.selectedId);

  return (
    <Panel title="Geavanceerde Opties" icon={<WrenchIcon />} className="lv-v2-models-advanced">
      <FieldRow label="KV-cache dtype" note={capNote("kvQuantization")}>
        <select
          className="lv-v2-select"
          disabled={disabled || capSupport("kvQuantization") === "UNSUPPORTED"}
          value={draft.kvCacheDtype}
          onChange={(e) => setDraft({ kvCacheDtype: e.target.value })}
        >
          {KV_DTYPE_OPTIONS.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow label="Tensor parallel size">
        <select
          className="lv-v2-select"
          disabled={disabled}
          value={draft.tensorParallelSize}
          onChange={(e) => setDraft({ tensorParallelSize: Number(e.target.value) })}
        >
          {[1, 2, 4, 8].map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow label="Main GPU ordinal" note={capNote("mainGpu")}>
        <select
          className="lv-v2-select"
          disabled={disabled || capSupport("mainGpu") === "UNSUPPORTED"}
          value={draft.mainGpuOrdinal ?? "auto"}
          onChange={(e) => setDraft({ mainGpuOrdinal: e.target.value === "auto" ? null : Number(e.target.value) })}
        >
          <option value="auto">Auto</option>
          {devices.map((d) => (
            <option key={d.stableDeviceId} value={d.ordinal ?? 0}>
              GPU {d.ordinal ?? 0}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow label="Sharding mode" note={capNote("gpuSplit")}>
        <select
          className="lv-v2-select"
          disabled={disabled || capSupport("gpuSplit") === "UNSUPPORTED"}
          value={draft.shardingMode}
          onChange={(e) => setDraft({ shardingMode: e.target.value })}
        >
          {SHARDING_MODES.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow label="Continuous batching" note={capNote("continuousBatching")}>
        <ToggleControl
          checked={draft.continuousBatching}
          disabled={disabled || capSupport("continuousBatching") === "UNSUPPORTED"}
          onChange={(v) => setDraft({ continuousBatching: v })}
        />
      </FieldRow>

      <FieldRow label="Prefix cache" note={capNote("prefixCache")}>
        <ToggleControl
          checked={draft.prefixCache}
          disabled={disabled || capSupport("prefixCache") === "UNSUPPORTED"}
          onChange={(v) => setDraft({ prefixCache: v })}
        />
      </FieldRow>

      <FieldRow label="Speculative decoding" note={capNote("speculativeDecoding")}>
        <ToggleControl
          checked={draft.speculativeDecoding}
          disabled={disabled || speculativeCap === "UNSUPPORTED"}
          onChange={(v) => setDraft({ speculativeDecoding: v })}
        />
      </FieldRow>

      <FieldRow label="Draft model (optioneel)" note={capNote("draftModel")}>
        <select
          className="lv-v2-select"
          disabled={disabled || capSupport("draftModel") === "UNSUPPORTED" || !draft.speculativeDecoding}
          value={draft.draftModelId ?? "none"}
          onChange={(e) => setDraft({ draftModelId: e.target.value === "none" ? null : e.target.value })}
        >
          <option value="none">Geen</option>
          {draftModels.map((m) => (
            <option key={m.id} value={m.id}>
              {m.displayName || m.id}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow label="Speculative tokens">
        <input
          type="number"
          min={0}
          disabled={disabled || speculativeCap === "UNSUPPORTED" || !draft.speculativeDecoding}
          value={draft.speculativeTokens}
          onChange={(e) => setDraft({ speculativeTokens: Number(e.target.value) })}
        />
      </FieldRow>
    </Panel>
  );
}
