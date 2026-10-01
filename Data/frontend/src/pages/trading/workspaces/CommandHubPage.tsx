import { useSearchParams } from "react-router-dom";
import { InstitutionalControlRoomPage } from "../InstitutionalControlRoomPage";
import { OnderzoekPage } from "../OnderzoekPage";
import { TradingWorkspaceShell } from "./TradingWorkspaceShell";
import { getTradingWorkspace, resolveWorkspaceSurface } from "./workspaceConfig";

function CommandHubOverview() {
  return (
    <section className="lv-tc-overview" aria-label="Command Hub overview">
      <article className="lv-tc-overview__card">
        <h3>Research sessions</h3>
        <p>Live</p>
        <span>Research Command surface</span>
      </article>
      <article className="lv-tc-overview__card">
        <h3>Qualification</h3>
        <p>Q01–Q11</p>
        <span>Control Room advanced</span>
      </article>
      <article className="lv-tc-overview__card">
        <h3>Promotion queue</h3>
        <p>Paper track</p>
        <span>A2–A4 only · live BLOCKED</span>
      </article>
      <article className="lv-tc-overview__card">
        <h3>Exceptions / audit</h3>
        <p>Institutional</p>
        <span>Advanced Control Room</span>
      </article>
      <p className="lv-tc-overview__note">
        WAVE 1 preserves Research Command and Control Room as embedded surfaces. Dense screenshot
        PRIMARY chrome lands in WAVE 2 without dropping these capabilities.
      </p>
    </section>
  );
}

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
