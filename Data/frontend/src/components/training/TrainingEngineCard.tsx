import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Badge, Button, Panel, StatusDot } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function EngineIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
      <circle cx="12" cy="12" r="4" />
      <path d="M7.5 7.5l2 2M14.5 14.5l2 2M16.5 7.5l-2 2M9.5 14.5l-2 2" />
    </svg>
  );
}

function packageVersion(ws: TrainingWorkspace, name: string): string | null {
  const pkg = ws.capabilities?.packages?.find((p) => p.name.toLowerCase() === name.toLowerCase());
  if (!pkg) return null;
  if (!pkg.available) return null;
  return pkg.version ? `v${pkg.version}` : "ok";
}

export function TrainingEngineCard({ ws }: Props) {
  const caps = ws.capabilities;
  const ready = caps?.ready === true;
  const torch = packageVersion(ws, "torch") ?? packageVersion(ws, "pytorch");
  const transformers = packageVersion(ws, "transformers");
  const peft = packageVersion(ws, "peft");
  const methods = caps?.productionMethods?.length
    ? caps.productionMethods
    : ["sft", "lora", "qlora", "dpo"].filter((m) => {
        if (m === "sft") return caps?.canRunSft !== false;
        if (m === "lora") return caps?.canRunLora;
        if (m === "qlora") return caps?.canRunQlora;
        if (m === "dpo") return caps?.canRunDpo;
        return false;
      });

  return (
    <Panel title="Training Engine" icon={<EngineIcon />} className="lv-v2-training-engine">
      <p className="lv-v2-muted lv-v2-training-engine__desc">
        Leviathan Trainer — lokale fine-tune pipeline op PyTorch / Transformers / PEFT.
      </p>

      <div className="lv-v2-training-engine__select-wrap">
        <div className="lv-v2-select-card" aria-label="Training engine">
          <span className="lv-v2-select-card__icon lv-v2-select-card__icon--model" aria-hidden="true">
            <EngineIcon />
          </span>
          <span className="lv-v2-select-card__body">
            <span className="lv-v2-select-card__value">Leviathan Trainer</span>
            <span className="lv-v2-select-card__meta">
              {[torch && `torch ${torch}`, transformers && `transformers ${transformers}`, peft && `peft ${peft}`]
                .filter(Boolean)
                .join(" · ") || "Capability probe"}
            </span>
          </span>
        </div>
      </div>

      <div className="lv-v2-training-engine__status">
        <StatusDot tone={ready ? "success" : caps ? "warning" : "muted"} pulse={ready} />
        <span>{ready ? "Klaar" : caps ? "Niet gereed" : ws.loading ? "Laden…" : "Onbekend"}</span>
        {caps?.cudaAvailable != null ? (
          <span className="lv-v2-muted">{caps.cudaAvailable ? "CUDA" : "CPU"}</span>
        ) : null}
      </div>

      <div className="lv-v2-training-engine__methods" aria-label="Beschikbare methoden">
        {(["sft", "lora", "qlora", "dpo"] as const).map((m) => {
          const on = methods.includes(m);
          return (
            <Badge key={m} tone={on ? "success" : "muted"}>
              {m.toUpperCase()}
            </Badge>
          );
        })}
      </div>

      <div className="lv-v2-training-engine__actions">
        <Button variant="secondary" size="sm" loading={ws.refreshing} onClick={() => void ws.refresh()}>
          Herprobeer
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void ws.runPreflight()}>
          Preflight
        </Button>
      </div>

      {ws.capsError ? (
        <p className="lv-v2-models-cap-note" role="status">
          {ws.capsError}
        </p>
      ) : null}
    </Panel>
  );
}
