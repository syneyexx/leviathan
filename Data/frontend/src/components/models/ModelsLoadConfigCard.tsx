import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Panel } from "../ui";
import { FieldRow, RangeControl, ToggleControl } from "./ModelsFormControls";

type Props = {
  ws: ModelsWorkspace;
};

const EVAL_BATCH_OPTIONS = [64, 128, 256, 512, 1024];
const NUM_EXPERTS_OPTIONS = [1, 2, 4, 8];
const CPU_THREADS_OPTIONS = [2, 4, 8, 16];

function ConfigIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
    </svg>
  );
}

export function ModelsLoadConfigCard({ ws }: Props) {
  const { draft, setDraft, capSupport, capNote } = ws;
  const disabled = !ws.selectedId;

  return (
    <Panel title="Load Configuratie" icon={<ConfigIcon />} className="lv-v2-models-load-config">
      <p className="lv-v2-muted lv-v2-models-load-config__desc">
        Instellingen die worden gebruikt bij het laden van het model in LM Studio.
      </p>

      <FieldRow label="Context lengte" note={capNote("contextLength")}>
        <input
          type="number"
          min={512}
          step={512}
          disabled={disabled || capSupport("contextLength") === "UNSUPPORTED"}
          value={draft.contextLength}
          onChange={(e) => setDraft({ contextLength: Number(e.target.value) })}
        />
      </FieldRow>

      <FieldRow label="Evaluatie batch size" note={capNote("evalBatch")}>
        <select
          className="lv-v2-select"
          disabled={disabled || capSupport("evalBatch") === "UNSUPPORTED"}
          value={draft.evalBatchSize}
          onChange={(e) => setDraft({ evalBatchSize: Number(e.target.value) })}
        >
          {EVAL_BATCH_OPTIONS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow label="GPU offload (algemeen)" note={capNote("gpuRatio")}>
        <RangeControl
          value={draft.gpuOffloadRatio * 100}
          disabled={disabled || capSupport("gpuRatio") === "UNSUPPORTED"}
          onChange={(v) => setDraft({ gpuOffloadRatio: v / 100 })}
        />
      </FieldRow>

      <FieldRow label="Flash Attention" note={capNote("flashAttention")}>
        <ToggleControl
          checked={draft.flashAttention}
          disabled={disabled || capSupport("flashAttention") === "UNSUPPORTED"}
          onChange={(v) => setDraft({ flashAttention: v })}
        />
      </FieldRow>

      <FieldRow label="KV-cache naar GPU" note={capNote("kvGpuOffload")}>
        <ToggleControl
          checked={draft.offloadKvCacheToGpu}
          disabled={disabled || capSupport("kvGpuOffload") === "UNSUPPORTED"}
          onChange={(v) => setDraft({ offloadKvCacheToGpu: v })}
        />
      </FieldRow>

      <FieldRow label="Num Experts (MoE)" note={capNote("moeNumExperts")}>
        <select
          className="lv-v2-select"
          disabled={disabled || capSupport("moeNumExperts") === "UNSUPPORTED"}
          value={draft.numExperts ?? "auto"}
          onChange={(e) => setDraft({ numExperts: e.target.value === "auto" ? null : Number(e.target.value) })}
        >
          <option value="auto">Auto</option>
          {NUM_EXPERTS_OPTIONS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow
        label="CPU threads (inferentie)"
        note={capNote("cpuThreads") || "Inferentie-profiel — niet meegestuurd bij load"}
      >
        <select
          className="lv-v2-select"
          disabled={disabled || capSupport("cpuThreads") !== "SUPPORTED"}
          value={draft.cpuThreads ?? "auto"}
          onChange={(e) => setDraft({ cpuThreads: e.target.value === "auto" ? null : Number(e.target.value) })}
        >
          <option value="auto">Auto</option>
          {CPU_THREADS_OPTIONS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow label="Seed (optioneel)" note={capNote("seed")}>
        <input
          type="number"
          placeholder="-1"
          disabled={disabled || capSupport("seed") !== "SUPPORTED"}
          value={draft.seed ?? ""}
          onChange={(e) => setDraft({ seed: e.target.value === "" ? null : Number(e.target.value) })}
        />
      </FieldRow>
    </Panel>
  );
}
