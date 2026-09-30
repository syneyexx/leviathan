import { useSearchParams } from "react-router-dom";
import { ResearchLabPage } from "../ResearchLabPage";
import { SimulatiePage } from "../SimulatiePage";
import { StrategieenPage } from "../StrategieenPage";
import { StrategyLabPrimaryChrome } from "./StrategyLabPrimaryChrome";
import { TradingWorkspaceShell } from "./TradingWorkspaceShell";
import { getTradingWorkspace, resolveWorkspaceSurface } from "./workspaceConfig";

export function StrategyLabWorkspacePage() {
  const workspace = getTradingWorkspace("strategy_lab");
  const [params] = useSearchParams();
  const surface = resolveWorkspaceSurface(workspace, params.get("surface"));

  return (
    <TradingWorkspaceShell workspaceId="strategy_lab">
      <StrategyLabPrimaryChrome />
      {surface.id === "lab" ? <ResearchLabPage embedded /> : null}
      {surface.id === "strategies" ? <StrategieenPage embedded /> : null}
      {surface.id === "simulation" ? <SimulatiePage embedded /> : null}
    </TradingWorkspaceShell>
  );
}
