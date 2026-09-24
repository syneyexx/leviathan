import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tradingHeroes } from "../../assets/tradingAssets";
import { api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { Panel, TradingHero } from "./shared";

export function BrokerTradingPage() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    void api.marketSimLiveTradingStatus().then(setStatus).catch(() => {
      setStatus({
        LIVE_TRADING_AVAILABLE: "BLOCKED",
        detail: "Unable to load live-trading guard status.",
      });
    });
  }, []);

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <TradingHero title="Broker / Live" image={tradingHeroes.broker} />
      <div className="lv-tp-wrap">
        <Panel title="Live trading status">
          <p className="lv-tp-banner">
            LIVE_TRADING_AVAILABLE = <strong>{String(status?.LIVE_TRADING_AVAILABLE ?? "BLOCKED")}</strong>
          </p>
          <p>{String(status?.detail ?? "")}</p>
          <ul className="lv-tp-list">
            <li>Human authorization required: {String(status?.human_authorization_required ?? true)}</li>
            <li>Agents cannot enable live mode: {String(status?.agent_cannot_enable ?? true)}</li>
            <li>Credentials separated: {String(status?.credentials_separated ?? true)}</li>
            <li>Adapter configured: {String(status?.adapter_configured ?? false)}</li>
          </ul>
          <p className="lv-tp-muted">
            Use historical simulation and live paper trading. Real broker credentials and order
            placement are intentionally unavailable in this build — TradingStub refuses
            POST /api/trading/order.
          </p>
          <p>
            <Link to="/trading/paper">Paper trading</Link>
            {" · "}
            <Link to="/trading/simulatie">Simulation</Link>
          </p>
        </Panel>
      </div>
    </AppShell>
  );
}
