import type { AssistantToolCallTelemetry } from "../../types/api";

type Props = {
  toolCalls?: AssistantToolCallTelemetry[] | null;
};

function durationLabel(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return "";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

function statusTone(call: AssistantToolCallTelemetry): string {
  if (call.success === false) return "failed";
  const status = (call.status || "").toUpperCase();
  if (status.includes("CANCEL")) return "cancelled";
  if (status.includes("PROGRESS") || status.includes("RUNNING") || status.includes("START")) {
    return "running";
  }
  if (call.success === true || status === "COMPLETED" || status === "OK" || status === "SUCCESS") {
    return "ok";
  }
  return "neutral";
}

/** Render bounded tool/artifact/source cards from backend telemetry — never invent counts. */
export function CapabilityResultCards({ toolCalls }: Props) {
  const rows = (toolCalls || []).filter((c) => c?.capability_id);
  if (!rows.length) return null;

  return (
    <div
      className="lv-capability-cards"
      aria-label="Capability results"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.55rem",
        marginTop: "0.65rem",
      }}
    >
      {rows.map((call) => {
        const tone = statusTone(call);
        const dur = durationLabel(call.duration_ms);
        const title = call.module_id || call.capability_id;
        const artifacts = call.artifact_refs?.length ?? 0;
        const sources = call.source_count ?? null;
        const results = call.result_count ?? null;
        return (
          <div
            key={`${call.capability_id}:${call.receipt_id || call.status}`}
            className={`lv-capability-card is-${tone}`}
            style={{
              border: "1px solid color-mix(in srgb, currentColor 14%, transparent)",
              borderRadius: 6,
              padding: "0.55rem 0.7rem",
              background: "color-mix(in srgb, currentColor 4%, transparent)",
              fontSize: "0.82rem",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
              <strong style={{ fontWeight: 600 }}>{title}</strong>
              <span style={{ opacity: 0.8, whiteSpace: "nowrap" }}>
                {call.status}
                {dur ? ` · ${dur}` : ""}
              </span>
            </div>
            {call.summary ? (
              <div style={{ marginTop: 4, opacity: 0.85 }}>{call.summary}</div>
            ) : null}
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "0.55rem",
                marginTop: 6,
                opacity: 0.75,
                fontSize: "0.75rem",
              }}
            >
              {call.provider ? <span>Provider {call.provider}</span> : null}
              {results != null ? <span>{results} results</span> : null}
              {sources != null ? <span>{sources} sources</span> : null}
              {artifacts > 0 ? <span>{artifacts} artifacts</span> : null}
              {call.receipt_id ? (
                <span title={call.receipt_id}>receipt {String(call.receipt_id).slice(0, 10)}</span>
              ) : null}
              {call.error ? <span style={{ color: "var(--lv-danger, #c44)" }}>{call.error}</span> : null}
            </div>
            {call.parts?.some((p) => String(p.kind || "").toUpperCase() === "PROGRESS") ? (
              <div style={{ marginTop: 6, opacity: 0.8 }}>
                {(call.parts || [])
                  .filter((p) => String(p.kind || "").toUpperCase() === "PROGRESS")
                  .slice(0, 3)
                  .map((p, idx) => (
                    <div key={idx}>{String(p.message || p.phase || "progress")}</div>
                  ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
