import {
  TRAINING_LR_SCHEDULERS,
  TRAINING_METHOD_LABELS,
  TRAINING_OPTIMIZERS,
  TRAINING_PRECISION_OPTIONS,
  PRODUCTION_TRAINING_METHODS,
} from "../../training/constants";
import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Panel } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function ConfigIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
    </svg>
  );
}

function Toggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className={`lv-v2-training-toggle${disabled ? " is-disabled" : ""}`}>
      <span>{label}</span>
      <span className="lv-v2-toggle">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
      </span>
    </label>
  );
}

export function TrainingConfigPanel({ ws }: Props) {
  const d = ws.draft;
  const showLora = d.method === "lora" || d.method === "qlora";
  const flashOk = ws.capabilities?.canUseFlashAttention !== false;
  const eightBitOk = ws.capabilities?.canUse8bitOptimizer !== false;

  return (
    <Panel title="Trainings Parameters" icon={<ConfigIcon />} className="lv-v2-training-config">
      <div className="lv-v2-training-config__grid">
        <div className="lv-v2-training-config__col">
          <label className="lv-v2-training-field">
            Naam
            <input
              value={d.name}
              onChange={(e) => ws.setDraft({ name: e.target.value })}
            />
          </label>

          <label className="lv-v2-training-field">
            Training type
            <select
              value={d.method}
              onChange={(e) => {
                const method = e.target.value;
                ws.setDraft({
                  method,
                  loadIn4bit: method === "qlora",
                });
              }}
            >
              {PRODUCTION_TRAINING_METHODS.map((m) => {
                const reason = ws.methodDisabledReason(m);
                return (
                  <option key={m} value={m} disabled={Boolean(reason)}>
                    {TRAINING_METHOD_LABELS[m] || m}
                    {reason ? ` (${reason})` : ""}
                  </option>
                );
              })}
            </select>
          </label>
          {ws.methodDisabledReason(d.method) ? (
            <p className="lv-v2-models-cap-note">{ws.methodDisabledReason(d.method)}</p>
          ) : null}

          <label className="lv-v2-training-field">
            Learning rate
            <input
              type="number"
              step="any"
              value={d.learningRate}
              onChange={(e) => ws.setDraft({ learningRate: Number(e.target.value) || 0 })}
            />
          </label>

          <label className="lv-v2-training-field">
            Batch size
            <input
              type="number"
              min={1}
              value={d.trainBatchSize}
              onChange={(e) => ws.setDraft({ trainBatchSize: Math.max(1, Number(e.target.value) || 1) })}
            />
          </label>

          <label className="lv-v2-training-field">
            Epochs
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={d.epochs}
              onChange={(e) => ws.setDraft({ epochs: Number(e.target.value) || 1 })}
            />
          </label>

          <label className="lv-v2-training-field">
            Max sequence length
            <input
              type="number"
              min={8}
              value={d.maxSeqLength}
              onChange={(e) => ws.setDraft({ maxSeqLength: Math.max(8, Number(e.target.value) || 8) })}
            />
          </label>

          {showLora ? (
            <>
              <label className="lv-v2-training-field">
                LoRA rank
                <input
                  type="number"
                  min={1}
                  value={d.loraR}
                  onChange={(e) => ws.setDraft({ loraR: Math.max(1, Number(e.target.value) || 1) })}
                />
              </label>
              <label className="lv-v2-training-field">
                LoRA alpha
                <input
                  type="number"
                  min={1}
                  value={d.loraAlpha}
                  onChange={(e) => ws.setDraft({ loraAlpha: Math.max(1, Number(e.target.value) || 1) })}
                />
              </label>
            </>
          ) : null}

          <label className="lv-v2-training-field">
            Weight decay
            <input
              type="number"
              step="any"
              value={d.weightDecay}
              onChange={(e) => ws.setDraft({ weightDecay: Number(e.target.value) || 0 })}
            />
          </label>
        </div>

        <div className="lv-v2-training-config__col">
          <label className="lv-v2-training-field">
            Optimizer
            <select
              value={d.optimizer}
              onChange={(e) => ws.setDraft({ optimizer: e.target.value })}
            >
              {TRAINING_OPTIMIZERS.map((o) => (
                <option
                  key={o.value}
                  value={o.value}
                  disabled={o.value.includes("8bit") && !eightBitOk}
                >
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <label className="lv-v2-training-field">
            Scheduler
            <select
              value={d.lrSchedulerType}
              onChange={(e) => ws.setDraft({ lrSchedulerType: e.target.value })}
            >
              {TRAINING_LR_SCHEDULERS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>

          <label className="lv-v2-training-field">
            Warmup steps
            <input
              type="number"
              min={0}
              value={d.warmupSteps}
              onChange={(e) => ws.setDraft({ warmupSteps: Math.max(0, Number(e.target.value) || 0) })}
            />
          </label>

          <label className="lv-v2-training-field">
            Precision
            <select
              value={d.precision}
              onChange={(e) => ws.setDraft({ precision: e.target.value })}
            >
              {TRAINING_PRECISION_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>

          <div className="lv-v2-training-config__toggles">
            <Toggle
              label="Gradient checkpointing"
              checked={d.gradientCheckpointing}
              onChange={(v) => ws.setDraft({ gradientCheckpointing: v })}
            />
            <Toggle
              label="Mixed precision (BF16)"
              checked={d.precision === "bf16"}
              onChange={(v) => ws.setDraft({ precision: v ? "bf16" : "fp32" })}
            />
            <Toggle
              label="Flash Attention"
              checked={d.flashAttention}
              disabled={!flashOk && !d.flashAttention}
              onChange={(v) => ws.setDraft({ flashAttention: v })}
            />
            <Toggle
              label="Evaluatie tijdens training"
              checked={d.evalDuringTraining}
              onChange={(v) => ws.setDraft({ evalDuringTraining: v })}
            />
            <Toggle
              label="Automatisch opslaan"
              checked={d.autoSave}
              onChange={(v) => ws.setDraft({ autoSave: v })}
            />
          </div>
        </div>
      </div>
    </Panel>
  );
}
