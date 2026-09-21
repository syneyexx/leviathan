/** FINALBETA TradingCenter Broker trading — opt-in protected; never fake live balances. */
"use client";

import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import { TcFooterBanner, TcPill, TradingWelcome } from "../trading/trading-chrome";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

export function TradingBrokerPage({ onNavigate }: Props) {
  const body = (
    <div className="tc-page tc-broker-page" data-live="trading-broker">
      <TradingWelcome
        title={
          <>
            <FbIcon name="link" size={22} style={{ color: "#eab94f" }} />
            Broker trading
          </>
        }
        subtitle="Live brokerverbindingen zijn opt-in en beschermd — geen demo balances."
        quote="Een goede uitvoering verandert strategie in resultaat."
      />

      <div className="tc-panel" style={{ marginBottom: 12, padding: "12px 16px" }} role="status">
        <strong>NIET GECONFIGUREERD / OPT-IN.</strong>
        <p style={{ margin: "8px 0 0" }}>
          HADES toont hier geen live broker balances, blotters of PnL. Paper/sim blijft de
          productiepad tot een expliciete broker-opt-in is aangesloten en geverifieerd.
        </p>
        <p style={{ margin: "8px 0 0" }}>
          Gebruik <button type="button" className="tc-link-btn" data-fb-page="trading-paper">Paper trading</button>{" "}
          of{" "}
          <button type="button" className="tc-link-btn" data-fb-page="trading">TradingCenter overzicht</button>{" "}
          voor simulatie.
        </p>
      </div>

      <div className="tc-kpi-row">
        <article className="tc-kpi">
          <div className="tc-kpi-label">Broker connecties</div>
          <div className="tc-kpi-value">0</div>
          <div className="tc-kpi-meta">
            <span className="tc-kpi-hint warn">Geen opt-in brokers</span>
          </div>
        </article>
        <article className="tc-kpi">
          <div className="tc-kpi-label">Live balances</div>
          <div className="tc-kpi-value">—</div>
          <div className="tc-kpi-meta">
            <span className="tc-kpi-hint flat">Niet beschikbaar</span>
          </div>
        </article>
        <article className="tc-kpi">
          <div className="tc-kpi-label">Orders</div>
          <div className="tc-kpi-value">—</div>
          <div className="tc-kpi-meta">
            <span className="tc-kpi-hint flat">Geblokkeerd zonder opt-in</span>
          </div>
        </article>
        <article className="tc-kpi">
          <div className="tc-kpi-label">Modus</div>
          <div className="tc-kpi-value">
            <TcPill tone="gold">PROTECTED</TcPill>
          </div>
          <div className="tc-kpi-meta">
            <span className="tc-kpi-hint warn">No fake money</span>
          </div>
        </article>
      </div>

      <section className="tc-panel">
        <div className="tc-panel-head">
          <div>
            <h2>Waarom leeg?</h2>
            <p>Productie-eerlijkheid</p>
          </div>
        </div>
        <ul style={{ padding: "8px 20px 16px", margin: 0, lineHeight: 1.55 }}>
          <li>Geen mock broker balances of latency charts in productie.</li>
          <li>Live trading blijft uit tot een aparte, expliciete broker-integratie landt.</li>
          <li>Paper desk en Trading Lab dekken onderzoek/simulatie vandaag.</li>
        </ul>
      </section>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Never fake live balances.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Broker gate</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className="v gold">NOT_CONFIGURED</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Policy</span>
            <span className="v">opt-in only</span>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="trading-broker"
      appClassName="tc-app"
      mainClassName="tc-main"
      body={body}
      inspector={inspector}
      footer={<TcFooterBanner left="Broker trading" right="Opt-in · no fake balances" />}
      onNavigate={onNavigate}
    />
  );
}
