/** FINALBETA TradingCenter Portefeuille — live paper positions (no fake broker). */
"use client";

import { useMemo, useState } from "react";
import { useHadesTrading } from "@/components/hades/features/trading/hooks/useHadesTrading";
import { donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import { TcFooterBanner, TcPill, TcSpark, TradingWelcome } from "../trading/trading-chrome";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function money(n: number | null | undefined): string {
  if (typeof n !== "number" || Number.isNaN(n)) return "—";
  return n.toLocaleString("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
}

export function TradingPortfolioPage({ onNavigate }: Props) {
  const live = useHadesTrading();
  const [tab, setTab] = useState<"open" | "closed" | "all">("open");
  const paper = live.paper;
  const positions = paper?.positions ?? [];
  const wallets = paper?.wallets ?? [];
  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status === "closed");
  const shown = tab === "open" ? open : tab === "closed" ? closed : positions;
  const cash =
    wallets.find((w) => ["EUR", "USD", "USDT"].includes(w.asset))?.balance ?? wallets[0]?.balance;
  const realized = positions.reduce((n, p) => n + (p.realized_pnl || 0), 0);

  const allocation = useMemo(() => {
    const bySymbol = new Map<string, number>();
    for (const p of open) {
      const notional = Math.abs((p.quantity || 0) * (p.entry_price || 0));
      bySymbol.set(p.symbol, (bySymbol.get(p.symbol) || 0) + notional);
    }
    const entries = Array.from(bySymbol.entries()).sort((a, b) => b[1] - a[1]).slice(0, 6);
    const total = entries.reduce((n, [, v]) => n + v, 0) || 1;
    const colors = ["#22d3ee", "#eab94f", "#a78bfa", "#22c55e", "#f87171", "#60a5fa"];
    if (!entries.length) return [{ label: "Cash", count: 1, color: colors[0]!, pct: "100%" }];
    return entries.map(([label, value], i) => ({
      label,
      count: Math.max(1, Math.round(value)),
      color: colors[i % colors.length]!,
      pct: `${Math.round((value / total) * 100)}%`,
    }));
  }, [open]);

  const donut = donutSegments(allocation.map((a) => ({ label: a.label, count: a.count, color: a.color })));

  const kpis = [
    {
      id: "cash",
      label: "Paper cash",
      value: money(cash),
      hint: wallets[0]?.asset || "wallet",
      tone: "up" as const,
      spark: [10, 11, 12, 13, 14, 15, Math.max(1, cash || 1)],
    },
    {
      id: "open",
      label: "Open posities",
      value: String(open.length),
      hint: `${closed.length} gesloten`,
      tone: "flat" as const,
      spark: [1, 2, 2, 3, 3, 2, open.length || 1],
    },
    {
      id: "pnl",
      label: "Gerealiseerd P&L",
      value: money(realized),
      hint: "Paper ledger",
      tone: realized < 0 ? ("down" as const) : ("up" as const),
      spark: [4, 5, 4, 6, 7, 5, Math.max(1, Math.abs(realized) || 1)],
    },
    {
      id: "mode",
      label: "Paper",
      value: paper?.settings.enabled ? "AAN" : "UIT",
      hint: paper?.settings.kill_switch ? "Kill-switch ARMED" : "sim only",
      tone: paper?.settings.kill_switch ? ("warn" as const) : ("up" as const),
      spark: [2, 2, 3, 3, 4, 4, 5],
    },
  ];

  const body = (
    <div className="tc-page tc-port-page" data-live="trading-portfolio">
      <TradingWelcome
        title={
          <>
            <FbIcon name="database" size={22} style={{ color: "#eab94f" }} />
            Portefeuille
          </>
        }
        subtitle="Paper posities en allocatie. Broker balances worden hier nooit gefaked."
        quote="Een sterke portefeuille is gebouwd op discipline, niet op geluk."
      />

      <div className="tc-panel" style={{ marginBottom: 12, padding: "10px 14px" }}>
        <strong>PAPER ONLY.</strong> Tab “Brokers” toont geen live balances — die blijven opt-in elders.
      </div>

      {live.error ? (
        <div className="tc-panel" role="alert" style={{ marginBottom: 12, padding: "10px 14px" }}>
          <strong>Portefeuille laden mislukt.</strong> {live.error}
        </div>
      ) : null}

      <div className="tc-kpi-row">
        {kpis.map((kpi) => (
          <article key={kpi.id} className="tc-kpi">
            <div className="tc-kpi-label">{kpi.label}</div>
            <div className="tc-kpi-value">{kpi.value}</div>
            <div className="tc-kpi-meta">
              <span className={`tc-kpi-hint ${kpi.tone}`}>{kpi.hint}</span>
              <TcSpark values={kpi.spark} tone={kpi.tone === "warn" ? "warn" : kpi.tone} />
            </div>
          </article>
        ))}
      </div>

      <div className="tc-port-mid">
        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Asset allocatie</h2>
              <p>Open paper notional per symbool</p>
            </div>
          </div>
          <div className="tc-donut-body">
            <div className="tc-donut-wrap">
              <svg viewBox="0 0 42 42" className="tc-donut" aria-hidden="true">
                <circle cx="21" cy="21" r="14" fill="none" stroke="rgba(74,163,255,0.12)" strokeWidth="5" />
                {donut.map((seg, index) => (
                  <circle
                    key={allocation[index]!.label}
                    cx="21"
                    cy="21"
                    r="14"
                    fill="none"
                    stroke={seg.color}
                    strokeWidth="5"
                    strokeDasharray={seg.dash}
                    strokeDashoffset={seg.offset}
                    transform="rotate(-90 21 21)"
                  />
                ))}
              </svg>
              <div className="tc-donut-center">
                <strong>{money(cash)}</strong>
                <span>Cash</span>
              </div>
            </div>
            <ul className="tc-donut-legend">
              {allocation.map((slice) => (
                <li key={slice.label}>
                  <i style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <b>{slice.pct}</b>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Posities</h2>
              <p>Paper ledger</p>
            </div>
            <div className="tc-tabs">
              {(
                [
                  ["open", "Open"],
                  ["closed", "Gesloten"],
                  ["all", "Alle"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={`tc-tab${tab === id ? " active" : ""}`}
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {!shown.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Posities laden…" : "Geen posities in deze filter."}
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Symbool</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Status</th>
                  <th>P&L</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.symbol}</strong>
                    </td>
                    <td>{p.side}</td>
                    <td>{p.quantity}</td>
                    <td>{p.entry_price}</td>
                    <td>
                      <TcPill tone={p.status === "open" ? "green" : "gray"}>{p.status}</TcPill>
                    </td>
                    <td className={p.realized_pnl < 0 ? "neg" : "pos"}>{money(p.realized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <section className="tc-panel">
        <div className="tc-panel-head">
          <div>
            <h2>Wallets</h2>
            <p>Paper balances</p>
          </div>
          <button type="button" className="tc-link-btn" data-fb-page="trading-paper">
            Paper desk
          </button>
        </div>
        {!wallets.length ? (
          <p className="muted" style={{ padding: 12 }}>
            Nog geen wallets.
          </p>
        ) : (
          <table className="tc-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Balance</th>
                <th>Reserved</th>
              </tr>
            </thead>
            <tbody>
              {wallets.map((w) => (
                <tr key={w.asset}>
                  <td>{w.asset}</td>
                  <td>{money(w.balance)}</td>
                  <td>{money(w.reserved)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Paper portfolio only — no fake broker equity.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Portfolio Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">/trading/dashboard · paper</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Open</span>
            <span className="v">{open.length}</span>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="trading-portfolio"
      appClassName="tc-app"
      mainClassName="tc-main"
      body={body}
      inspector={inspector}
      footer={<TcFooterBanner left="Portefeuille · paper" right="Geen live broker" />}
      onNavigate={onNavigate}
    />
  );
}
