import { useSearchParams } from "react-router-dom";
import { InstitutionalControlRoomPage } from "../InstitutionalControlRoomPage";
import { OnderzoekPage } from "../OnderzoekPage";
import { CommandHubOverview } from "./CommandHubOverview";
import { TradingWorkspaceShell } from "./TradingWorkspaceShell";
import { getTradingWorkspace, resolveWorkspaceSurface } from "./workspaceConfig";

export function CommandHubPage() {
  const workspace = getTradingWorkspace("command_hub");
  const [params] = useSearchParams();
  const surface = resolveWorkspaceSurface(workspace, params.get("surface"));

  return (
    <TradingWorkspaceShell workspaceId="command_hub">
      {surface.id === "overview" ? <CommandHubOverview /> : null}
      {surface.id === "research-command" ? <OnderzoekPage embedded /> : null}
      {surface.id === "control-room" ? <InstitutionalControlRoomPage embedded /> : null}
    </TradingWorkspaceShell>
  );
}
