import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

function kpiValue(ws: KnowledgeLibraryWorkspace, key: string): { value: string; sub: string } {
  const o = ws.overview;
  if (!o && ws.overviewError) return { value: "—", sub: "Fout / stale" };
  if (!o) return { value: "…", sub: "Laden" };
  switch (key) {
    case "sources":
      return {
        value: o.total_sources.toLocaleString("nl-NL"),
        sub: "canonical Knowledge sources",
      };
    case "size": {
      const size = ws.formatBytes(o.measured_bytes);
      const cov =
        o.size_coverage_percent != null ? `${o.size_coverage_percent}% gemeten` : "dekking onbekend";
      const unk = o.unknown_size_sources ? ` · ${o.unknown_size_sources} ongemeten` : "";
      return { value: size, sub: `${cov}${unk}` };
    }
    case "types":
      return {
        value: String(o.source_type_count),
        sub: "genormaliseerde types met bronnen",
      };
    case "embed": {
      if (o.embedding.status === "NOT_CONFIGURED") return { value: "N/A", sub: "NOT CONFIGURED" };
      if (o.embedding.status === "UNAVAILABLE") return { value: "N/A", sub: "UNAVAILABLE" };
      if (o.embedding.coverage_percent == null) return { value: "—", sub: o.embedding.status };
      return {
        value: `${o.embedding.coverage_percent}%`,
        sub:
          o.embedding.coverage_percent >= 100
            ? "Alle bronnen geïndexeerd"
            : `${o.embedding.chunks_embedded}/${o.embedding.chunks_total} chunks`,
      };
    }
    case "latest": {
      const li = o.latest_ingestion;
      if (!li?.created_at) return { value: "—", sub: "geen ingestie" };
      const stamp = new Date(li.created_at);
      const label = Number.isNaN(stamp.getTime())
        ? li.created_at
        : stamp.toLocaleString("nl-NL", { dateStyle: "medium", timeStyle: "medium" });
      return { value: label, sub: ws.relativeAge(li.created_at) };
    }
    default:
      return { value: "—", sub: "" };
  }
}

function SparkBars({ values, tone }: { values: number[]; tone: "cyan" | "violet" }) {
  const max = Math.max(1, ...values);
  return (
    <div className={`lv-v2-kl-spark lv-v2-kl-spark--${tone}`} aria-hidden="true">
      {values.map((v, i) => (
        <span key={i} style={{ height: `${Math.max(12, Math.round((v / max) * 100))}%` }} />
      ))}
    </div>
  );
}

function EmbedRing({ pct }: { pct: number }) {
  const r = 16;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, pct));
  const offset = c - (clamped / 100) * c;
  return (
    <svg className="lv-v2-kl-embed-ring" viewBox="0 0 40 40" width="40" height="40" aria-hidden="true">
      <circle cx="20" cy="20" r={r} className="lv-v2-kl-embed-ring__track" />
      <circle
        cx="20"
        cy="20"
        r={r}
        className="lv-v2-kl-embed-ring__value"
        strokeDasharray={c}
        strokeDashoffset={offset}
      />
      <text x="20" y="22" textAnchor="middle">
        {Math.round(clamped)}%
      </text>
    </svg>
  );
}

/** Five real KPI cards — server-side library overview. Sparks only when history exists. */
export function KnowledgeLibraryKpis({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const o = ws.overview;
  const cards = [
    { key: "sources", title: "Totale Bronnen", spark: o?.sparks?.total_sources, tone: "cyan" as const },
    { key: "size", title: "Totale Grootte", spark: o?.sparks?.measured_bytes, tone: "violet" as const },
    { key: "types", title: "Bron Types" },
    { key: "embed", title: "Embedding Status" },
    { key: "latest", title: "Laatste Ingestie" },
  ];
  return (
    <section className="lv-v2-kl-kpis" aria-label="Knowledge Library KPIs">
      {cards.map((c) => {
        const v = kpiValue(ws, c.key);
        const showRing =
          c.key === "embed" &&
          o?.embedding?.coverage_percent != null &&
          o.embedding.status !== "NOT_CONFIGURED" &&
          o.embedding.status !== "UNAVAILABLE";
        return (
          <article key={c.key} className={`lv-v2-kl-kpi lv-v2-kl-kpi--${c.key}`}>
            <div className="lv-v2-kl-kpi__text">
              <header>{c.title}</header>
              <strong>{v.value}</strong>
              <span>{v.sub}</span>
            </div>
            {c.spark && c.spark.length > 1 ? <SparkBars values={c.spark} tone={c.tone!} /> : null}
            {showRing ? <EmbedRing pct={o!.embedding.coverage_percent!} /> : null}
          </article>
        );
      })}
    </section>
  );
}
