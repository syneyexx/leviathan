import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api/client";
import type { PaperPortfolio } from "../../../types/api";

type WalletRow = {
  id: string;
  name: string;
  status: string;
  cash: string;
  equity: string;
  currency: string;
};

function money(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) {
    return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  if (typeof v === "string" && v.trim()) return v;
  return "UNMEASURED";
}

/**
 * WAVE 2 — first-class paper/agent wallet surface (backend WalletLedger / portfolios COMPLETE;
 * legacy UI had only weak exposure).
 */
export function AgentWalletsPanel() {
  const [rows, setRows] = useState<WalletRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { portfolios } = await api.listPortfolios(50);
      const detailed = await Promise.all(
        (portfolios || []).slice(0, 12).map(async (p: PaperPortfolio) => {
          const pid = p.portfolio_id;
          // Prefer list payload fields; dashboard fills gaps when available.
          let cash = money(p.cash);
          let equity = money(p.equity);
          try {
            const dash = await api.portfolioDashboard(pid);
            const kpis = (dash as { kpis?: { cash_balance?: unknown; total_equity?: unknown } }).kpis;
            if (kpis?.cash_balance != null) cash = money(kpis.cash_balance);
            if (kpis?.total_equity != null) equity = money(kpis.total_equity);
          } catch {
            /* keep list values */
          }
          return {
            id: pid,
            name: p.name || pid,
            status: String(p.status || "—"),
            cash,
            equity,
            currency: String(p.base_currency || "USD"),
          } satisfies WalletRow;
        }),
      );
      setRows(detailed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load wallets");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section className="lv-tc-wallets" aria-label="Paper wallets">
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3>Wallets (Paper)</h3>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          <button type="button" className="lv-tc-btn" onClick={() => void refresh()} disabled={loading}>
            Refresh
          </button>
          <Link className="lv-tc-btn" to="/trading/trading-desk?surface=portfolio">
            Portefeuille
          </Link>
        </div>
      </header>
      {error ? <p className="is-muted">{error}</p> : null}
      {loading && !rows.length ? <p className="is-muted">Loading wallets…</p> : null}
      {!loading && !rows.length ? (
        <p className="is-muted">No paper portfolios yet — create one in Portefeuille.</p>
      ) : null}
      {rows.length ? (
        <table>
          <thead>
            <tr>
              <th>Wallet / Portfolio</th>
              <th>Status</th>
              <th>Cash</th>
              <th>Equity</th>
              <th>CCY</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>{r.status}</td>
                <td>{r.cash}</td>
                <td>{r.equity}</td>
                <td>{r.currency}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
