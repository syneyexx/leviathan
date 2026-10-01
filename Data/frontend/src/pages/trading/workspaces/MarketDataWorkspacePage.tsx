import { MarktdataPage } from "../MarktdataPage";
import { MarketDataPrimaryChrome } from "./MarketDataPrimaryChrome";
import { TradingWorkspaceShell } from "./TradingWorkspaceShell";

export function MarketDataWorkspacePage() {
  return (
    <TradingWorkspaceShell workspaceId="market_data">
      <MarketDataPrimaryChrome />
      <MarktdataPage embedded />
    </TradingWorkspaceShell>
  );
}
