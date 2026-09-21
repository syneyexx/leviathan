/** FINALBETA TradingCenter Paper trading — live paper ledger (sim only). */
"use client";

import { useMemo, useState } from "react";
import { useHadesTrading } from "@/components/hades/features/trading/hooks/useHadesTrading";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import { TcFooterBanner, TcPill, TcSpark, TradingWelcome } from "../trading/trading-chrome";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function money(n: number | null | undefined): string {
  if (typeof n !== "number" || Number.isNaN(n)) return "—";
  return n.toLocaleString("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
}

export function TradingPaperPage({ onNavigate }: Props) {
  const live = useHadesTrading();
  const [busy, setBusy] = useState(false);
  const paper = live.paper;
  const wallets = paper?.wallets ?? [];
  const positions = paper?.positions ?? [];
  const orders = paper?.orders ?? [];
  const events = paper?.events ?? [];
  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status === "closed");
  const cash =
    wallets.find((w) => ["EUR", "USD", "USDT"].includes(w.asset))?.balance ?? wallets[0]?.balance;
  const reserved = wallets.reduce((n, w) => n + (w.reserved || 0), 0);
  const realized = positions.reduce((n, p) => n + (p.realized_pnl || 0), 0);

  const kpis = useMemo(
    () => [
      {
        id: "enabled",
        label: "Paper modus",
        value: paper?.settings.enabled ? "AAN" : "UIT",
        hint: paper?.settings.kill_switch ? "Kill-switch ARMED" : "Simulatie only",
        tone: paper?.settings.kill_switch ? ("warn" as const) : ("up" as const),
        spark: [1, 2, 2, 3, 3, 4, paper?.settings.enabled ? 5 : 1],
      },
      {
        id: "cash",
        label: "Cash",
        value: money(cash),
        hint: wallets[0]?.asset || "wallet",
        tone: "up" as const,
        spark: [10, 12, 11, 13, 14, 15, Math.max(1, cash || 1)],
      },
      {
        id: "reserved",
        label: "Reserved",
        value: money(reserved),
        hint: "Margin / holds",
        tone: "flat" as const,
        spark: [2, 3, 2, 4, 3, 5, Math.max(1, reserved || 1)],
      },
      {
        id: "open",
        label: "Open posities",
        value: String(open.length),
        hint: `${closed.length} gesloten`,
        tone: "flat" as const,
        spark: [1, 1, 2, 2, 3, 2, open.length || 1],
      },
      {
        id: "pnl",
        label: "Gerealiseerd P&L",
        value: money(realized),
        hint: "Paper ledger",
        tone: realized < 0 ? ("down" as const) : ("up" as const),
        spark: [5, 6, 4, 7, 8, 6, Math.max(1, Math.abs(realized) || 1)],
      },
      {
        id: "orders",
        label: "Orders",
        value: String(orders.length),
        hint: "Paper orders",
        tone: "up" as const,
        spark: [1, 2, 2, 3, 3, 4, orders.length || 1],
      },
    ],
    [paper, wallets, cash, reserved, open.length, closed.length, realized, orders.length],
  );

  async function togglePaper(enabled: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await live.setEnabled(enabled);
    } finally {
      setBusy(false);
    }
  }

  async function toggleKill(armed: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await live.setKillSwitch(armed);
    } finally {
      setBusy(false);
    }
  }

  const body = (
    <div className="tc-page tc-paper-page" data-live="trading-paper">
      <TradingWelcome
        title={
          <>
            <FbIcon name="file" size={22} style={{ color: "#eab94f" }} />
            Paper trading
          </>
        }
        subtitle="Trade virtueel om signalen en uitvoering te testen — geen echt geld."
        quote="Oefening in de markt bouwt discipline in het echt."
      />

      <div className="tc-panel" style={{ marginBottom: 12, padding: "10px 14px" }}>
        <strong>PAPER ONLY.</strong> Live broker balances worden hier nooit getoond of gefaked.
        {modeBanner(paper?.settings.enabled, paper?.settings.kill_switch)}
      </div>

      {live.error ? (
        <div className="tc-panel" role="alert" style={{ marginBottom: 12, padding: "10px 14px" }}>
          <strong>Paper desk laden mislukt.</strong> {live.error}{" "}
          <button type="button" className="tc-link-btn" onClick={() => void live.refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="tc-kpi-row">
        {kpis.map((kpi) => (
          <article key={kpi.id} className="tc-kpi">
            <div className="tc-kpi-label">{kpi.label}</div>
            <div className="tc-kpi-value">{live.loading && kpi.value === "—" ? "…" : kpi.value}</div>
            <div className="tc-kpi-meta">
              <span className={`tc-kpi-hint ${kpi.tone}`}>{kpi.hint}</span>
              <TcSpark values={kpi.spark} tone={kpi.tone} />
            </div>
          </article>
        ))}
      </div>

      <div className="tc-paper-mid">
        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Paper account</h2>
              <p>Lokale wallets & settings</p>
            </div>
            <TcPill tone={paper?.settings.enabled ? "green" : "gray"}>
              {paper?.settings.enabled ? "ENABLED" : "DISABLED"}
            </TcPill>
          </div>
          <div className="tc-account-grid">
            <div>
              {[
                ["Cash", money(cash)],
                ["Reserved", money(reserved)],
                ["Wallets", String(wallets.length)],
                ["Kill-switch", paper?.settings.kill_switch ? "ARMED" : "clear"],
                ["Updated", paper?.settings.updated_at || "—"],
              ].map(([k, v]) => (
                <div key={k} className="tc-detail-row">
                  <span className="k">{k}</span>
                  <span className="v">{v}</span>
                </div>
              ))}
            </div>
            <div>
              <div className="tc-detail-row">
                <span className="k">Paper trading</span>
                <button
                  type="button"
                  className="tc-link-btn"
                  disabled={busy}
                  onClick={() => void togglePaper(!paper?.settings.enabled)}
                >
                  {paper?.settings.enabled ? "Uitschakelen" : "Inschakelen"}
                </button>
              </div>
              <div className="tc-detail-row">
                <span className="k">Kill-switch</span>
                <button
                  type="button"
                  className="tc-link-btn"
                  disabled={busy}
                  onClick={() => void toggleKill(!paper?.settings.kill_switch)}
                >
                  {paper?.settings.kill_switch ? "Clear" : "Arm"}
                </button>
              </div>
              <div className="tc-detail-row">
                <span className="k">Vernieuwen</span>
                <button type="button" className="tc-link-btn" onClick={() => void live.refresh()}>
                  Nu ophalen
                </button>
              </div>
            </div>
          </div>
          {!wallets.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Wallets laden…" : "Nog geen paper wallets."}
            </p>
          ) : (
            <table className="tc-table" style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Balance</th>
                  <th>Reserved</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {wallets.map((w) => (
                  <tr key={w.asset}>
                    <td>{w.asset}</td>
                    <td>{money(w.balance)}</td>
                    <td>{money(w.reserved)}</td>
                    <td>{w.updated_at || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Open posities</h2>
              <p>Paper positions</p>
            </div>
            <button type="button" className="tc-link-btn" data-fb-page="trading-portfolio">
              Portefeuille
            </button>
          </div>
          {!open.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Posities laden…" : "Geen open paper posities."}
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Symbool</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>P&L</th>
                </tr>
              </thead>
              <tbody>
                {open.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.symbol}</strong>
                    </td>
                    <td>
                      <TcPill tone={p.side === "buy" || p.side === "long" ? "green" : "red"}>{p.side}</TcPill>
                    </td>
                    <td>{p.quantity}</td>
                    <td>{p.entry_price}</td>
                    <td className={p.realized_pnl < 0 ? "neg" : "pos"}>{money(p.realized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <div className="tc-overview-bottom">
        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Orders</h2>
              <p>Paper order log</p>
            </div>
          </div>
          {!orders.length ? (
            <p className="muted" style={{ padding: 12 }}>
              Nog geen paper orders.
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Tijd</th>
                  <th>Symbool</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Prijs</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.slice(0, 12).map((o) => (
                  <tr key={o.id}>
                    <td>{o.created_at}</td>
                    <td>{o.symbol}</td>
                    <td>{o.side}</td>
                    <td>{o.quantity}</td>
                    <td>{o.price}</td>
                    <td>
                      <TcPill tone="blue">{o.status}</TcPill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Journal / events</h2>
              <p>Paper runtime events</p>
            </div>
          </div>
          {!events.length ? (
            <p className="muted" style={{ padding: 12 }}>
              Nog geen events.
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Tijd</th>
                  <th>Niveau</th>
                  <th>Bericht</th>
                </tr>
              </thead>
              <tbody>
                {events.slice(0, 12).map((e) => (
                  <tr key={e.id}>
                    <td>{e.created_at}</td>
                    <td>
                      <TcPill tone={e.level === "error" ? "red" : e.level === "warn" ? "gold" : "blue"}>
                        {e.level}
                      </TcPill>
                    </td>
                    <td>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Paper first. Never fake live balances.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Paper Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">/trading/dashboard · paper</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className={`v ${live.error ? "gold" : "green"}`}>
              {live.loading ? "Laden…" : live.error ? "Fout" : "Live"}
            </span>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="trading-paper"
      appClassName="tc-app"
      mainClassName="tc-main"
      body={body}
      inspector={inspector}
      footer={<TcFooterBanner left="Paper trading" right="Geen live broker" />}
      onNavigate={onNavigate}
    />
  );
}

function modeBanner(enabled?: boolean, kill?: boolean) {
  if (kill) return " Kill-switch is ARMED — nieuwe paper executie geblokkeerd.";
  if (!enabled) return " Paper trading staat UIT.";
  return null;
}
