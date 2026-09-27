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

function asPartRecord(part: unknown): Record<string, unknown> | null {
  if (!part || typeof part !== "object" || Array.isArray(part)) return null;
  return part as Record<string, unknown>;
}

function partKind(part: unknown): string {
  const row = asPartRecord(part);
  if (!row) return "";
  return String(row.kind || row.type || "").toUpperCase();
}

function artifactHref(ref: string): string {
  const id = ref.replace(/^artifact:/i, "").trim();
  if (!id) return "#";
  return `/api/artifacts/${encodeURIComponent(id)}`;
}

function artifactLabel(ref: string, parts: unknown[] | undefined): string {
  const id = ref.replace(/^artifact:/i, "").trim();
  for (const part of parts || []) {
    const row = asPartRecord(part);
    if (!row) continue;
    if (partKind(row) !== "ARTIFACT") continue;
    const nested = row.artifacts;
    if (Array.isArray(nested)) {
      for (const a of nested) {
        const art = asPartRecord(a);
        if (!art) continue;
        const aid = String(art.artifact_id || art.ref || "").replace(/^artifact:/i, "").trim();
        if (aid && aid === id) {
          return String(art.name || art.filename || art.title || ref);
        }
      }
    }
    const aid = String(row.artifact_id || row.ref || "").replace(/^artifact:/i, "").trim();
    if (aid && aid === id) {
      return String(row.name || row.filename || row.title || ref);
    }
  }
  // Prefer short display for bare UUIDs while keeping full ref in title/href.
  if (/^[0-9a-f-]{36}$/i.test(id)) return `artifact ${id.slice(0, 8)}`;
  return ref;
}

function sourceEntries(call: AssistantToolCallTelemetry): Array<{ title: string; url?: string }> {
  const out: Array<{ title: string; url?: string }> = [];
  for (const part of call.parts || []) {
    const row = asPartRecord(part);
    if (!row) continue;
    const kind = partKind(row);
    if (kind === "SOURCE" || kind === "SOURCE_SET") {
      const title = String(row.title || row.name || row.url || "Source");
      const url = row.url != null ? String(row.url) : undefined;
      out.push({ title, url });
    }
    const nested = row.sources;
    if (Array.isArray(nested)) {
      for (const s of nested.slice(0, 12)) {
        const nestedRow = asPartRecord(s);
        if (!nestedRow) continue;
        out.push({
          title: String(nestedRow.title || nestedRow.name || nestedRow.url || "Source"),
          url: nestedRow.url != null ? String(nestedRow.url) : undefined,
        });
      }
    }
  }
  return out.slice(0, 12);
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
        const artifactRefs = (call.artifact_refs || []).filter(Boolean);
        const sources = call.source_count ?? null;
        const results = call.result_count ?? null;
        const sourceRows = sourceEntries(call);
        const progressParts = (call.parts || [])
          .map(asPartRecord)
          .filter((p): p is Record<string, unknown> => !!p && partKind(p) === "PROGRESS")
          .slice(0, 3);
        const tableParts = (call.parts || [])
          .map(asPartRecord)
          .filter((p): p is Record<string, unknown> => !!p && partKind(p) === "TABLE")
          .slice(0, 1);
        const errorParts = (call.parts || [])
          .map(asPartRecord)
          .filter((p): p is Record<string, unknown> => !!p && partKind(p) === "ERROR")
          .slice(0, 2);
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
              {artifactRefs.length > 0 ? <span>{artifactRefs.length} artifacts</span> : null}
              {call.receipt_id ? (
                <span title={call.receipt_id}>receipt {String(call.receipt_id).slice(0, 10)}</span>
              ) : null}
              {call.error ? <span style={{ color: "var(--lv-danger, #c44)" }}>{call.error}</span> : null}
            </div>

            {progressParts.length ? (
              <div style={{ marginTop: 6, opacity: 0.8 }}>
                {progressParts.map((p, idx) => (
                  <div key={idx}>
                    {String(p.message || p.text || p.phase || p.summary || "progress")}
                  </div>
                ))}
              </div>
            ) : null}

            {artifactRefs.length ? (
              <div style={{ marginTop: 8 }} aria-label="Artifacts">
                <div style={{ fontSize: "0.72rem", opacity: 0.7, marginBottom: 4 }}>ARTIFACTS</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {artifactRefs.slice(0, 8).map((ref) => (
                    <a
                      key={ref}
                      href={artifactHref(ref)}
                      target="_blank"
                      rel="noreferrer"
                      title={ref}
                      style={{ color: "inherit", textDecoration: "underline", opacity: 0.9 }}
                    >
                      {artifactLabel(ref, call.parts)}
                    </a>
                  ))}
                </div>
              </div>
            ) : null}

            {sourceRows.length ? (
              <div style={{ marginTop: 8 }} aria-label="Sources">
                <div style={{ fontSize: "0.72rem", opacity: 0.7, marginBottom: 4 }}>
                  SOURCES{sources != null ? ` · ${sources}` : ` · ${sourceRows.length}`}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {sourceRows.map((s, idx) =>
                    s.url ? (
                      <a
                        key={`${s.url}:${idx}`}
                        href={s.url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: "inherit", textDecoration: "underline", opacity: 0.9 }}
                      >
                        {s.title}
                      </a>
                    ) : (
                      <span key={`${s.title}:${idx}`}>{s.title}</span>
                    ),
                  )}
                </div>
              </div>
            ) : null}

            {tableParts.length ? (
              <div style={{ marginTop: 8, opacity: 0.85, fontSize: "0.75rem" }}>
                TABLE · {String(tableParts[0].rows != null ? `${Number(tableParts[0].rows)} rows` : "structured")}
              </div>
            ) : null}

            {errorParts.length ? (
              <div style={{ marginTop: 6, color: "var(--lv-danger, #c44)" }}>
                {errorParts.map((p, idx) => (
                  <div key={idx}>{String(p.message || p.error || p.code || "error")}</div>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
