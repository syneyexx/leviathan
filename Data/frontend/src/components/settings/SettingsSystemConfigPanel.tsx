import type { SettingsWorkspace } from "../../hooks/useSettingsWorkspace";
import { Button } from "../ui";

type Props = {
  ws: SettingsWorkspace;
};

function SliderRow({
  label,
  value,
  display,
  min,
  max,
  step,
  onChange,
  effectiveHint,
}: {
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step?: number;
  onChange: (n: number) => void;
  effectiveHint?: string;
}) {
  return (
    <div className="lv-v2-settings-slider">
      <div className="lv-v2-settings-slider__head">
        <span>{label}</span>
        <strong>{display}</strong>
      </div>
      <input
        type="range"
        className="lv-v2-range"
        min={min}
        max={max}
        step={step ?? 1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {effectiveHint ? <small>{effectiveHint}</small> : null}
    </div>
  );
}

export function SettingsSystemConfigPanel({ ws }: Props) {
  const gpu = Number(ws.drafts["managed_serving.gpu_memory_limit_pct"] ?? 90);
  const context = Number(ws.drafts["context.token_budget"] ?? 6000);
  const parallel = Number(ws.drafts["resources.max_model_concurrency"] ?? 1);
  const timeout = Number(ws.drafts["model.timeout_seconds"] ?? 300);

  const gpuSetting = ws.byKey.get("managed_serving.gpu_memory_limit_pct");
  const contextSetting = ws.byKey.get("context.token_budget");
  const parallelSetting = ws.byKey.get("resources.max_model_concurrency");
  const timeoutSetting = ws.byKey.get("model.timeout_seconds");

  return (
    <section className="lv-v2-settings-system-config" aria-label="Systeem Configuratie">
      <div className="lv-v2-settings-panel-head">
        <div>
          <h3>Systeem Configuratie</h3>
          <p>Hardware en performance instellingen</p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => ws.setAdvancedOpen((v) => !v)}>
          Geavanceerd
        </Button>
      </div>

      <div className="lv-v2-settings-system-config__body">
        <SliderRow
          label="Maximale GPU memory"
          value={gpu}
          display={`${Math.round(gpu)}%`}
          min={10}
          max={100}
          onChange={(n) => ws.setDraft("managed_serving.gpu_memory_limit_pct", n)}
          effectiveHint={
            gpuSetting && !gpuSetting.effective_now
              ? "Opgeslagen — herstart/apply pending"
              : "Soft ceiling → VRAM reserve headroom (ResourceManager)"
          }
        />
        <SliderRow
          label="Maximale context lengte"
          value={context}
          display={String(Math.round(context))}
          min={Number(contextSetting?.min_value ?? 512)}
          max={Number(contextSetting?.max_value ?? 200000)}
          step={256}
          onChange={(n) => ws.setDraft("context.token_budget", n)}
          effectiveHint="ContextBuilder token budget — effectief begrensd door model window"
        />
        <SliderRow
          label="Parallelle requests"
          value={parallel}
          display={String(Math.round(parallel))}
          min={Number(parallelSetting?.min_value ?? 1)}
          max={Number(parallelSetting?.max_value ?? 64)}
          onChange={(n) => ws.setDraft("resources.max_model_concurrency", n)}
          effectiveHint="Model ResourceManager concurrency ceiling"
        />
        <SliderRow
          label="Request timeout"
          value={timeout}
          display={`${Math.round(timeout)} s`}
          min={Number(timeoutSetting?.min_value ?? 5)}
          max={Number(timeoutSetting?.max_value ?? 3600)}
          step={5}
          onChange={(n) => ws.setDraft("model.timeout_seconds", n)}
          effectiveHint="OpenAI-compatible / provider request timeout"
        />
      </div>

      {ws.advancedOpen ? (
        <div className="lv-v2-settings-advanced">
          <p>
            Geavanceerde runtime-knoppen (bind host/port, workers, managed serving) staan onder{" "}
            <button type="button" className="lv-v2-linkish" onClick={() => ws.selectCategory("python")}>
              Python & Runtime
            </button>
            . Geen plaatsbocontroles hier.
          </p>
        </div>
      ) : null}
    </section>
  );
}
