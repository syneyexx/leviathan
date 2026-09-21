import type { ModelsStatus } from "../../types/api";

function cell(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function ModelStatusCards({
  status,
  loading,
}: {
  status: ModelsStatus | null;
  loading: boolean;
}) {
  const cards = [
    { label: "RUNTIME", value: loading ? "…" : cell(status?.runtime) },
    { label: "AVAILABLE MODELS", value: loading ? "…" : cell(status?.availableModels) },
    { label: "ACTIVE MODEL", value: loading ? "…" : cell(status?.activeModel) },
    { label: "LOADED MODELS", value: loading ? "…" : cell(status?.loadedModels) },
    {
      label: "DISCOVERY LATENCY",
      value: loading
        ? "…"
        : status?.discoveryLatencyMs == null
          ? "—"
          : `${Math.round(status.discoveryLatencyMs)} ms`,
    },
    { label: "GATEWAY HEALTH", value: loading ? "…" : cell(status?.gatewayHealth) },
  ];

  return (
    <div className="lv-models-status-row" aria-label="Models status">
      {cards.map((card) => (
        <article key={card.label} className="lv-models-status-card">
          <span>{card.label}</span>
          <strong title={card.value}>{card.value}</strong>
        </article>
      ))}
    </div>
  );
}
