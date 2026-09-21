/** FINALBETA TradingCenter Marktdata — live local bars / lab instruments (sim). */
"use client";

import { useMemo, useState } from "react";
import { useHadesTrading } from "@/components/hades/features/trading/hooks/useHadesTrading";
import { chartPolyline } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import { TcFooterBanner, TcPill, TcSpark, TradingWelcome } from "../trading/trading-chrome";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

export function TradingMarketdataPage({ onNavigate }: Props) {
  const live = useHadesTrading();
  const [selected, setSelected] = useState("");
  const symbols = live.symbols;
  const instruments = live.instruments;
  const datasets = live.datasets;

  const activeSymbol = selected || symbols[0]?.symbol || instruments[0]?.symbol || "";
  const bars = useMemo(
    () => live.bars.filter((b) => !activeSymbol || b.symbol === activeSymbol).slice(-48),
    [live.bars, activeSymbol],
  );
  const closes = bars.map((b) => b.close);
  const chartPath = closes.length >= 2 ? chartPolyline(closes, 640, 180) : "";

  const kpis = [
    {
      id: "symbols",
      label: "Symbolen",
      value: live.loading && !symbols.length ? "…" : String(symbols.length),
      hint: "Lokale marktbars",
      tone: "up" as const,
      spark: [2, 3, 3, 4, 5, 4, symbols.length || 1],
    },
    {
      id: "instruments",
      label: "Lab instrumenten",
      value: String(instruments.length),
      hint: "Trading Lab registry",
      tone: "flat" as const,
      spark: [1, 2, 2, 3, 3, 4, instruments.length || 1],
    },
    {
      id: "datasets",
      label: "Datasets",
      value: String(datasets.length),
      hint: "PIT history",
      tone: "up" as const,
      spark: [1, 1, 2, 2, 3, 3, datasets.length || 1],
    },
    {
      id: "bars",
      label: "Bars (cache)",
      value: String(live.bars.length),
      hint: activeSymbol || "alle",
      tone: "flat" as const,
      spark: [5, 6, 7, 8, 9, 8, Math.max(1, live.bars.length)],
    },
  ];

  const body = (
    <div className="tc-page tc-md-page" data-live="trading-marketdata">
      <TradingWelcome
        title={
          <>
            <FbIcon name="line" size={22} style={{ color: "#eab94f" }} />
            Marktdata
          </>
        }
        subtitle="Lokale bars, lab-instrumenten en datasets — geen fake realtime brokerfeeds."
        quote="Informatie is de grondstof. Bewijs is het voordeel."
      />

      <div className="tc-panel" style={{ marginBottom: 12, padding: "10px 14px" }}>
        <strong>SIMULATIE / LOKAAL.</strong> Orderboek- en live-sentimentclaims worden niet gefaked.
      </div>

      {live.error ? (
        <div className="tc-panel" role="alert" style={{ marginBottom: 12, padding: "10px 14px" }}>
          <strong>Marktdata laden mislukt.</strong> {live.error}{" "}
          <button type="button" className="tc-link-btn" onClick={() => void live.refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="tc-kpi-row">
        {kpis.map((kpi) => (
          <article key={kpi.id} className="tc-kpi">
            <div className="tc-kpi-label">{kpi.label}</div>
            <div className="tc-kpi-value">{kpi.value}</div>
            <div className="tc-kpi-meta">
              <span className={`tc-kpi-hint ${kpi.tone}`}>{kpi.hint}</span>
              <TcSpark values={kpi.spark} tone={kpi.tone} />
            </div>
          </article>
        ))}
      </div>

      <div className="tc-md-mid">
        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Symbolen</h2>
              <p>Lokale bar inventory</p>
            </div>
            <button type="button" className="tc-link-btn" onClick={() => void live.refresh()}>
              Vernieuwen
            </button>
          </div>
          {!symbols.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Symbolen laden…" : "Nog geen marktdata. Seed of importeer CSV via Paper desk / Lab."}
            </p>
          ) : (
            <div className="tc-market-grid">
              {symbols.map((m) => (
                <button
                  key={`${m.symbol}-${m.timeframe}`}
                  type="button"
                  className={`tc-market-card${activeSymbol === m.symbol ? " active" : ""}`}
                  onClick={() => setSelected(m.symbol)}
                  style={{ textAlign: "left", cursor: "pointer" }}
                >
                  <div className="tc-market-card-top">
                    <span className="sym">{m.symbol}</span>
                    <TcPill tone="blue">{m.timeframe}</TcPill>
                  </div>
                  <div className="price">{m.last_close?.toFixed?.(4) ?? m.last_close}</div>
                  <div className="tc-market-card-foot">
                    <span style={{ fontSize: 11 }}>
                      {m.bars} bars · {m.last_ts || "—"}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Prijsreeks {activeSymbol || ""}</h2>
              <p>Laatste lokale closes</p>
            </div>
          </div>
          {closes.length < 2 ? (
            <p className="muted" style={{ padding: 12 }}>
              Onvoldoende bars voor chart.
            </p>
          ) : (
            <div className="tc-chart-wrap">
              <svg viewBox="0 0 640 180" preserveAspectRatio="none" aria-hidden="true">
                <path d={chartPath} fill="none" stroke="#22d3ee" strokeWidth="2" strokeLinejoin="round" />
              </svg>
            </div>
          )}
        </section>
      </div>

      <div className="tc-overview-bottom">
        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Lab instrumenten</h2>
              <p>`/trading/lab/instruments`</p>
            </div>
          </div>
          {!instruments.length ? (
            <p className="muted" style={{ padding: 12 }}>
              Nog geen lab-instrumenten.
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Family</th>
                  <th>Venue</th>
                  <th>Quote</th>
                </tr>
              </thead>
              <tbody>
                {instruments.slice(0, 20).map((i) => (
                  <tr key={i.instrument_id}>
                    <td>
                      <strong>{i.symbol}</strong>
                    </td>
                    <td>{i.family}</td>
                    <td>{i.venue}</td>
                    <td>{i.quote_currency}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Datasets</h2>
              <p>`/trading/lab/datasets`</p>
            </div>
          </div>
          {!datasets.length ? (
            <p className="muted" style={{ padding: 12 }}>
              Nog geen datasets.
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Naam</th>
                  <th>ID</th>
                </tr>
              </thead>
              <tbody>
                {datasets.slice(0, 20).map((d) => (
                  <tr key={d.dataset_id}>
                    <td>
                      <strong>{d.name}</strong>
                    </td>
                    <td>{d.dataset_id}</td>
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
      <p className="mc-insp-quote">“Lokale data first. Geen fake feeds.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Marketdata Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">trading dashboard bars · lab instruments/datasets</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Selected</span>
            <span className="v">{activeSymbol || "—"}</span>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="trading-marketdata"
      appClassName="tc-app"
      mainClassName="tc-main"
      body={body}
      inspector={inspector}
      footer={<TcFooterBanner left="Marktdata · lokaal/lab" right="Geen live brokerfeeds" />}
      onNavigate={onNavigate}
    />
  );
}
