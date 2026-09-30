import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Panel } from "../ui";

type Props = {
  ws: ModelsWorkspace;
};

function GaugeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M5 19a7 7 0 1 1 14 0" />
      <path d="M12 12l3-3" />
    </svg>
  );
}

export function ModelsPerformanceCard({ ws }: Props) {
  const run = ws.optimization;
  const best = run?.candidates.find((c) => c.index === run.bestIndex) ?? run?.candidates.at(-1) ?? null;

  const ttft = best?.ttftSeconds ?? null;
  const promptTps = best?.promptTps ?? null;
  const genTps = best?.generationTps ?? null;

  const measured = ttft != null || promptTps != null || genTps != null;

  return (
    <Panel title="Verwachte Performance" icon={<GaugeIcon />} className="lv-v2-models-performance">
      {!measured ? (
        <p className="lv-v2-muted">Nog niet gemeten — voer een optimalisatie uit voor een schatting.</p>
      ) : (
        <div className="lv-v2-perf-stats">
          <div className="lv-v2-perf-stat">
            <span className="lv-v2-perf-stat__label">Time to first token (TTFT)</span>
            <span className="lv-v2-perf-stat__value">{ttft != null ? `~${ttft.toFixed(1)} s` : "—"}</span>
          </div>
          <div className="lv-v2-perf-stat">
            <span className="lv-v2-perf-stat__label">Prompt processing</span>
            <span className="lv-v2-perf-stat__value">{promptTps != null ? `~${Math.round(promptTps)} tok/s` : "—"}</span>
          </div>
          <div className="lv-v2-perf-stat">
            <span className="lv-v2-perf-stat__label">Generation</span>
            <span className="lv-v2-perf-stat__value">{genTps != null ? `~${genTps.toFixed(1)} tok/s` : "—"}</span>
          </div>
        </div>
      )}
      <p className="lv-v2-models-cap-note">Dit is een schatting op basis van eerdere benchmarks en je hardware.</p>
    </Panel>
  );
}
