import { useSearchParams } from "react-router-dom";
import { BrokerTradingPage } from "../BrokerTradingPage";
import { PaperTradingPage } from "../PaperTradingPage";
import { PortefeuillePage } from "../PortefeuillePage";
import { AgentWalletsPanel } from "./AgentWalletsPanel";
import { TradingWorkspaceShell } from "./TradingWorkspaceShell";
import { getTradingWorkspace, resolveWorkspaceSurface } from "./workspaceConfig";

export function TradingDeskPage() {
  const workspace = getTradingWorkspace("trading_desk");
  const [params] = useSearchParams();
  const surface = resolveWorkspaceSurface(workspace, params.get("surface"));

  return (
    <TradingWorkspaceShell workspaceId="trading_desk">
      {surface.id === "paper" || surface.id === "portfolio" ? <AgentWalletsPanel /> : null}
      {surface.id === "paper" ? <PaperTradingPage embedded /> : null}
      {surface.id === "portfolio" ? <PortefeuillePage embedded /> : null}
      {surface.id === "broker" ? <BrokerTradingPage embedded /> : null}
    </TradingWorkspaceShell>
  );
}
