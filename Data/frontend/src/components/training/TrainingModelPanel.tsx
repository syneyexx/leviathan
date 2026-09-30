import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Badge, Panel } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function ModelIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 9h8M8 12h8M8 15h5" />
    </svg>
  );
}

function methodBadgeForModel(tags: string[] | undefined): { id: string; tone: "training" | "info" | "success" | "muted" } {
  const lower = (tags || []).map((t) => t.toLowerCase());
  if (lower.includes("qlora")) return { id: "QLoRA", tone: "success" };
  if (lower.includes("lora")) return { id: "LoRA", tone: "info" };
  if (lower.includes("dpo")) return { id: "DPO", tone: "info" };
  if (lower.includes("sft")) return { id: "SFT", tone: "training" };
  return { id: "Trainable", tone: "muted" };
}

function formatParams(n: number | null | undefined): string {
  if (n == null) return "";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M`;
  return String(n);
}

export function TrainingModelPanel({ ws }: Props) {
  return (
    <Panel title="Models voor Training" icon={<ModelIcon />} className="lv-v2-training-models">
      <input
        className="lv-v2-input lv-v2-training-models__search"
        placeholder="Zoek modellen…"
        value={ws.modelQuery}
        onChange={(e) => ws.setModelQuery(e.target.value)}
        aria-label="Zoek modellen"
      />

      {ws.trainableModels.length === 0 ? (
        <p className="lv-v2-muted">
          {ws.loading
            ? "Modellen laden…"
            : "Geen trainable modellen (GGUF inference-blobs zijn uitgesloten)."}
        </p>
      ) : (
        <ul className="lv-v2-training-list">
          {ws.trainableModels.map((m) => {
            const selected = ws.selectedModelId === m.id;
            const badge = methodBadgeForModel(m.tags);
            return (
              <li key={m.id}>
                <button
                  type="button"
                  className={`lv-v2-training-list__item${selected ? " is-selected" : ""}`}
                  aria-pressed={selected}
                  onClick={() => ws.selectModel(m.id)}
                >
                  <span className="lv-v2-training-list__icon" aria-hidden="true">
                    <ModelIcon />
                  </span>
                  <span className="lv-v2-training-list__body">
                    <span className="lv-v2-training-list__title">{m.displayName || m.id}</span>
                    <span className="lv-v2-training-list__meta">
                      {[m.family, formatParams(m.parameterCount), m.format || m.source]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  <Badge tone={badge.tone}>{badge.id}</Badge>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
