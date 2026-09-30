import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api/client";
import { marketSimLabApi } from "../../../api/domains/marketSimLab";
import { researchCommandApi } from "../../../api/domains/researchCommand";

export type HubKpi = {
  id: string;
  label: string;
  value: string;
  note: string;
  href?: string;
};

export type HubAttentionItem = {
  id: string;
  category: string;
  message: string;
  priority: "High" | "Medium" | "Low";
};

export type CommandHubOverviewModel = {
  loading: boolean;
  error: string | null;
  kpis: HubKpi[];
  attention: HubAttentionItem[];
  liveTrading: string;
  qualificationState: string;
  refresh: () => Promise<void>;
};

function numOrUnmeasured(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "string" && v.trim() && v !== "undefined") return v;
  return "UNMEASURED";
}

export function useCommandHubOverview(): CommandHubOverviewModel {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [kpis, setKpis] = useState<HubKpi[]>([]);
  const [attention, setAttention] = useState<HubAttentionItem[]>([]);
  const [liveTrading, setLiveTrading] = useState("BLOCKED");
  const [qualificationState, setQualificationState] = useState("UNMEASURED");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [overview, labs, portfolios, deployments, sources, rc, live] = await Promise.all([
        marketSimLabApi.marketSimLabOverview().catch(() => null),
        marketSimLabApi.marketSimLabListRuns(50).catch(() => ({ labs: [] as Record<string, unknown>[] })),
        api.listPortfolios(50).catch(() => ({ portfolios: [] })),
        api.listPaperDeployments({ limit: 50 }).catch(() => ({ deployments: [] })),
        api.listMarketData().catch(() => ({ sources: [] })),
        researchCommandApi.researchCommandSnapshot().catch(() => null),
        api.marketSimLiveTradingStatus().catch(() => ({ LIVE_TRADING_AVAILABLE: "BLOCKED" })),
      ]);

      const liveAvail = String(
        (live as { LIVE_TRADING_AVAILABLE?: string })?.LIVE_TRADING_AVAILABLE ?? "BLOCKED",
      );
      setLiveTrading(liveAvail);

      const qual = String(
        (overview as { qualificationState?: string } | null)?.qualificationState ?? "UNMEASURED",
      );
      setQualificationState(qual);

      const labList = labs.labs || [];
      const activeLabs = labList.filter((l) => {
        const st = String(l.status || l.state || "").toUpperCase();
        return ["RUNNING", "ACTIVE", "LEARNING", "STARTED"].includes(st);
      });

      const portList = portfolios.portfolios || [];
      const depList = deployments.deployments || [];
      const srcList = sources.sources || [];
      const readySrc = srcList.filter((s) => s.status === "READY");

      const trialCount = (overview as { trial_ledger_count?: number } | null)?.trial_ledger_count;
      const learningRuns = (overview as { learning_run_count?: number } | null)?.learning_run_count;

      setKpis([
        {
          id: "candidates",
          label: "Candidate / trials",
          value: numOrUnmeasured(trialCount),
          note: "Trial ledger (backend)",
          href: "/trading/strategy-lab?surface=lab",
        },
        {
          id: "experiments",
          label: "Learning runs",
          value: numOrUnmeasured(learningRuns),
          note: `${activeLabs.length} lab run(s) active`,
          href: "/trading/strategy-lab?surface=lab",
        },
        {
          id: "paper",
          label: "Paper deployments",
          value: String(depList.length),
          note: "Shadow / autonomous paper",
          href: "/trading/trading-desk?surface=paper",
        },
        {
          id: "datasets",
          label: "Databronnen ready",
          value: `${readySrc.length}/${srcList.length || 0}`,
          note: readySrc.length ? "Indexed READY sources" : "Scan in Market Data",
          href: "/trading/market-data",
        },
        {
          id: "wallets",
          label: "Paper portfolios",
          value: String(portList.length),
          note: "Portefeuille wallets",
          href: "/trading/trading-desk?surface=portfolio",
        },
        {
          id: "promo",
          label: "Qualification",
          value: qual,
          note: "Q01–Q11 · live BLOCKED",
          href: "/trading/command-hub?surface=control-room",
        },
      ]);

      const items: HubAttentionItem[] = [];
      if (liveAvail === "BLOCKED") {
        items.push({
          id: "live-blocked",
          category: "Safety",
          message: "LIVE_TRADING_AVAILABLE=BLOCKED — paper / research only",
          priority: "High",
        });
      }
      const blockers = ((overview as { blockers?: unknown[] } | null)?.blockers || []).slice(0, 5);
      for (const [i, b] of blockers.entries()) {
        items.push({
          id: `blocker-${i}`,
          category: "Qualification",
          message: String(b),
          priority: "High",
        });
      }
      if (rc && (rc as { session?: { status?: string } }).session?.status) {
        items.push({
          id: "rc-session",
          category: "Research",
          message: `Research Command session: ${String((rc as { session?: { status?: string } }).session?.status)}`,
          priority: "Medium",
        });
      }
      if (!readySrc.length) {
        items.push({
          id: "no-data",
          category: "Data",
          message: "No READY market data sources — open Market Data to scan/register",
          priority: "Medium",
        });
      }
      if (!items.length) {
        items.push({
          id: "ok",
          category: "System",
          message: "No open attention items from control-plane snapshot",
          priority: "Low",
        });
      }
      setAttention(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Command Hub overview");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { loading, error, kpis, attention, liveTrading, qualificationState, refresh };
}

export function CommandHubOverview() {
  const model = useCommandHubOverview();

  return (
    <section className="lv-tc-hub" aria-label="Command Hub overview">
      <div className="lv-tc-hub__hero">
        <div>
          <p className="lv-tc-hub__kicker">Autonomous Trading Command Hub</p>
          <h2>Research → qualify → paper</h2>
          <p>
            Oversight for autonomous trading research, simulation, and paper execution. Live money remains{" "}
            <strong>{model.liveTrading}</strong>.
          </p>
          <div className="lv-tc-hub__cta">
            <Link className="lv-tc-btn lv-tc-btn--primary" to="/trading/command-hub?surface=research-command">
              + Nieuwe research sessie
            </Link>
            <Link className="lv-tc-btn" to="/trading/trading-desk?surface=paper">
              Paper sessie openen
            </Link>
            <Link className="lv-tc-btn" to="/trading/strategy-lab?surface=lab">
              Strategy Lab
            </Link>
          </div>
          <div className="lv-tc-hub__caps">
            <span>Paper Only</span>
            <span>Offline + Live Data</span>
            <span>Risk Guarded</span>
            <span>Qualification {model.qualificationState}</span>
          </div>
        </div>
      </div>

      {model.error ? (
        <p className="lv-tc-hub__error" role="alert">
          {model.error}
          <button type="button" className="lv-tc-btn" onClick={() => void model.refresh()}>
            Retry
          </button>
        </p>
      ) : null}

      <div className="lv-tc-overview" aria-busy={model.loading}>
        {model.kpis.map((k) => (
          <article key={k.id} className="lv-tc-overview__card">
            <h3>{k.label}</h3>
            <p>{model.loading ? "…" : k.value}</p>
            <span>{k.note}</span>
            {k.href ? (
              <Link className="lv-tc-overview__link" to={k.href}>
                Open
              </Link>
            ) : null}
          </article>
        ))}
      </div>

      <div className="lv-tc-hub__split">
        <section className="lv-tc-hub__panel" aria-label="Attention">
          <header>
            <h3>Attention / Decisions</h3>
            <Link to="/trading/command-hub?surface=control-room">Control Room</Link>
          </header>
          <ul className="lv-tc-hub__attn">
            {model.attention.map((a) => (
              <li key={a.id} data-priority={a.priority}>
                <span className="lv-tc-hub__attn-cat">{a.category}</span>
                <span className="lv-tc-hub__attn-msg">{a.message}</span>
                <span className="lv-tc-hub__attn-pri">{a.priority}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="lv-tc-hub__panel" aria-label="Workspace shortcuts">
          <header>
            <h3>Workspaces</h3>
          </header>
          <ul className="lv-tc-hub__links">
            <li>
              <Link to="/trading/strategy-lab">Strategy Lab</Link> — discovery, validation, simulation
            </li>
            <li>
              <Link to="/trading/trading-desk">Trading Desk</Link> — wallets, positions, paper risk
            </li>
            <li>
              <Link to="/trading/market-data">Market Data</Link> — datasets, feeds, certification
            </li>
            <li>
              <Link to="/trading/command-hub?surface=research-command">Research Command</Link> — session
              composition
            </li>
          </ul>
        </section>
      </div>
    </section>
  );
}
