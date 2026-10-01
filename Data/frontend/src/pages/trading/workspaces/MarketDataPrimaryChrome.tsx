import { useCallback, useEffect, useState } from "react";
import { api } from "../../../api/client";

type MdKpi = { label: string; value: string; note: string };

export function MarketDataPrimaryChrome() {
  const [kpis, setKpis] = useState<MdKpi[]>([]);
  const [loading, setLoading] = useState(true);
  const [sealHint, setSealHint] = useState<string>("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [status, data] = await Promise.all([
        api.marketSimStatus().catch(() => null),
        api.listMarketData().catch(() => ({ sources: [] })),
      ]);
      const sources = data.sources || [];
      const ready = sources.filter((s) => s.status === "READY").length;
      const invalid = sources.filter((s) => s.status === "INVALID").length;
      const fail = sources.filter((s) => {
        const q = (s.metadata as { qualityVerdict?: string } | undefined)?.qualityVerdict;
        return q === "FAIL";
      }).length;
      const warn = sources.filter((s) => {
        const q = (s.metadata as { qualityVerdict?: string } | undefined)?.qualityVerdict;
        return q === "WARN";
      }).length;

      setKpis([
        {
          label: "Offline / indexed",
          value: String(status?.health.sources_indexed ?? sources.length),
          note: status?.health.exists ? "markets root exists" : "markets root missing",
        },
        { label: "Ready", value: String(status?.health.sources_ready ?? ready), note: "Validated OHLCV" },
        { label: "Invalid", value: String(invalid), note: "Failed validation" },
        { label: "Quality FAIL", value: String(fail), note: "Honest quality verdict" },
        { label: "Quality WARN", value: String(warn), note: "Gaps / outliers" },
        {
          label: "Feature",
          value: status?.enabled ? "ON" : "OFF",
          note: "LEVIATHAN_FEATURE_MARKET_SIM",
        },
      ]);
      setSealHint(
        "ADVANCED: dataset seal binds SEALED holdout (Q10). Use API POST /datasets/{id}/{version}/seal — UI seal dialog lands when operator workflow requires write confirmation.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section className="lv-tc-md-chrome" aria-label="Market Data primary">
      <div className="lv-tc-hub__cta" style={{ marginBottom: "0.65rem" }}>
        <button type="button" className="lv-tc-btn lv-tc-btn--primary" onClick={() => void refresh()}>
          Refresh metrics
        </button>
        <span className="lv-tc-badge lv-tc-badge--exec">PAPER DATA PATH</span>
      </div>
      <div className="lv-tc-overview" aria-busy={loading}>
        {kpis.map((k) => (
          <article key={k.label} className="lv-tc-overview__card">
            <h3>{k.label}</h3>
            <p>{loading ? "…" : k.value}</p>
            <span>{k.note}</span>
          </article>
        ))}
      </div>
      <p className="lv-tc-overview__note">{sealHint}</p>
    </section>
  );
}
