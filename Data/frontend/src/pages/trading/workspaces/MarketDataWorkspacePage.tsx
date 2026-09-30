import { MarktdataPage } from "../MarktdataPage";
import { TradingWorkspaceShell } from "./TradingWorkspaceShell";

export function MarketDataWorkspacePage() {
  return (
    <TradingWorkspaceShell workspaceId="market_data">
      <MarktdataPage embedded />
    </TradingWorkspaceShell>
  );
}
