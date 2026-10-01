import { AppShell } from "../../../../layouts/AppShell";
import { TradingContextBar } from "../TradingContextBar";
import { tradingCenterStatusRows } from "../tradingStatusRows";
import { useTradingContext } from "../useTradingContext";
import { CommandHubView } from "./CommandHubView";
import "../../../../styles/trading-command-hub.css";

export function CommandHubPage() {
  const ctx = useTradingContext();

  return (
    <AppShell
      variant="v2"
      v2Title="Trading Center / Command Hub"
      v2Subtitle="Centrale overzicht en controle voor autonoom trading onderzoek, simulatie en paper trading."
      v2Online={!ctx.loading}
      v2Refreshing={ctx.loading}
      onV2Refresh={() => void ctx.refresh()}
      v2StatusRows={tradingCenterStatusRows(ctx)}
      pageClass="lv-app--trading-command-hub"
      v2ScrollableMain
    >
      <main className="lv-v2-page lv-v2-page--command-hub">
        <TradingContextBar ctx={ctx} />
        <CommandHubView ctx={ctx} />
      </main>
    </AppShell>
  );
}
