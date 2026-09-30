import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Panel } from "../ui";
import { formatGb } from "./modelsHelpers";

type Props = {
  ws: ModelsWorkspace;
};

function ChartIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M4 20V10M10 20V4M16 20v-8M20 20V8" />
    </svg>
  );
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export function ModelsResourceEstimateCard({ ws }: Props) {
  const est = ws.estimate;
  const details = (est?.leviathanEstimate as Record<string, unknown> | null)?.details as
    | Record<string, unknown>
    | undefined;
  const profile = details?.resourceProfile as Record<string, unknown> | undefined;
  const weightBytes = readNumber(profile?.weightBytes);
  const kvCacheBytes = readNumber(profile?.kvCacheBytes);
  const vramBytes = readNumber((est?.leviathanEstimate as Record<string, unknown> | null)?.vramNeededBytes);
  const ramBytes = readNumber((est?.leviathanEstimate as Record<string, unknown> | null)?.ramNeededBytes);

  const rows: Array<{ label: string; value: number | null; max: number }> = [
    { label: "Model gewicht (geschat)", value: weightBytes, max: vramBytes || weightBytes || 1 },
    { label: "KV-cache (geschat)", value: kvCacheBytes, max: vramBytes || kvCacheBytes || 1 },
    { label: "Totaal GPU VRAM (geschat)", value: vramBytes, max: vramBytes || 1 },
    { label: "Systeem RAM (geschat)", value: ramBytes, max: ramBytes || 1 },
  ];

  return (
    <Panel title="Geschatte Resource Gebruik" icon={<ChartIcon />} className="lv-v2-models-estimate">
      {!est ? (
        <p className="lv-v2-muted">Nog niet geschat — klik “Eerst schatten”.</p>
      ) : (
        <ul className="lv-v2-models-meter-block">
          {rows.map((row) => (
            <li key={row.label} className="lv-v2-models-meter-row">
              <div className="lv-v2-models-meter-row__head">
                <span>{row.label}</span>
                <span className="lv-v2-models-meter-row__value">{formatGb(row.value)}</span>
              </div>
              <div className="lv-v2-models-meter-row__track">
                {row.value != null ? (
                  <div
                    className="lv-v2-models-meter-row__fill"
                    style={{ width: `${Math.max(2, Math.min(100, (row.value / row.max) * 100))}%` }}
                  />
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      {est?.disagreeMaterially ? (
        <p className="lv-v2-models-cap-note">Leviathan en LM Studio schattingen wijken sterk af.</p>
      ) : null}
    </Panel>
  );
}
