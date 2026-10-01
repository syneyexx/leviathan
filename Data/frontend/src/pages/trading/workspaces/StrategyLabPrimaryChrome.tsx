import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { marketSimLabApi } from "../../../api/domains/marketSimLab";

type LabKpi = { label: string; value: string; note: string };

export function StrategyLabPrimaryChrome() {
  const [kpis, setKpis] = useState<LabKpi[]>([]);
  const [ladder, setLadder] = useState<LabKpi[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [overview, labs] = await Promise.all([
        marketSimLabApi.marketSimLabOverview().catch(() => null),
        marketSimLabApi.marketSimLabListRuns(50).catch(() => ({ labs: [] as Record<string, unknown>[] })),
      ]);
      const list = labs.labs || [];
      const byStatus = (pred: (s: string) => boolean) =>
        list.filter((l) => pred(String(l.status || l.state || "").toUpperCase())).length;

      setKpis([
        {
          label: "Research sessions",
          value: String(list.length),
          note: `${byStatus((s) => ["RUNNING", "ACTIVE", "LEARNING", "STARTED"].includes(s))} active`,
        },
        {
          label: "Learning runs",
          value:
            overview && typeof (overview as { learning_run_count?: number }).learning_run_count === "number"
              ? String((overview as { learning_run_count: number }).learning_run_count)
              : "UNMEASURED",
          note: "Durable learning_run ledger",
        },
        {
          label: "Trial ledger",
          value:
            overview && typeof (overview as { trial_ledger_count?: number }).trial_ledger_count === "number"
              ? String((overview as { trial_ledger_count: number }).trial_ledger_count)
              : "UNMEASURED",
          note: "Candidates / trials",
        },
        {
          label: "Qualification",
          value: String((overview as { qualificationState?: string } | null)?.qualificationState ?? "UNMEASURED"),
          note: "Latest decision · live BLOCKED",
        },
      ]);

      const qual = String((overview as { qualificationState?: string } | null)?.qualificationState ?? "UNMEASURED");
      setLadder([
        { label: "Discovered / trials", value: String((overview as { trial_ledger_count?: number } | null)?.trial_ledger_count ?? "UNMEASURED"), note: "Ledger" },
        { label: "Researching", value: String(byStatus((s) => ["RUNNING", "ACTIVE", "LEARNING"].includes(s))), note: "Lab runs" },
        { label: "Qualification", value: qual, note: "Q01–Q11" },
        { label: "Sealed", value: String((overview as { sealedState?: string } | null)?.sealedState ?? "UNMEASURED"), note: "Holdout bind" },
        { label: "Promotion", value: "PAPER", note: "A2–A4 only" },
      ]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section className="lv-tc-lab-chrome" aria-label="Strategy Lab primary">
      <div className="lv-tc-hub__cta" style={{ marginBottom: "0.65rem" }}>
        <Link className="lv-tc-btn lv-tc-btn--primary" to="/trading/strategy-lab?surface=lab">
          + Nieuwe zoekopdracht
        </Link>
        <Link className="lv-tc-btn" to="/trading/command-hub?surface=research-command">
          Research sessie
        </Link>
        <Link className="lv-tc-btn" to="/trading/trading-desk?surface=paper">
          Paper validatie
        </Link>
        <Link className="lv-tc-btn" to="/trading/strategy-lab?surface=strategies">
          Strategieën
        </Link>
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
      <div className="lv-tc-ladder" aria-label="Validation ladder">
        {ladder.map((step, i) => (
          <div key={step.label} className="lv-tc-ladder__step">
            <strong>{step.label}</strong>
            <span>{loading ? "…" : step.value}</span>
            <small>{step.note}</small>
            {i < ladder.length - 1 ? <span className="lv-tc-ladder__arrow" aria-hidden="true">→</span> : null}
          </div>
        ))}
      </div>
    </section>
  );
}
