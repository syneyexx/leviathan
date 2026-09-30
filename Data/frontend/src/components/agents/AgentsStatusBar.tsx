import type { AgentsWorkspace } from "../../hooks/useAgentsWorkspace";
import { formatPct } from "../../pages/agents/helpers";
import { ProgressBar, Sparkline } from "../ui";

type Props = { ws: AgentsWorkspace };

/** Global host resource strip — labeled as system scope, never per-agent. */
export function AgentsStatusBar({ ws }: Props) {
  const { telemetry, dashboard, activitySeries, kpis, summary } = ws;
  const cpu = telemetry?.cpu?.available ? telemetry.cpu.utilizationPct : null;
  const ramPct = telemetry?.memory?.available ? telemetry.memory.utilizationPct : null;
  const ramUsed = telemetry?.memory?.available ? telemetry.memory.usedBytes : null;
  const ramTotal = telemetry?.memory?.available ? telemetry.memory.totalBytes : null;
  const gpuDevices = telemetry?.gpu?.available ? telemetry.gpu.devices : [];
  const gpuAvg =
    gpuDevices.length > 0
      ? gpuDevices.reduce((s, d) => s + (d.utilizationPct ?? 0), 0) /
        gpuDevices.filter((d) => d.utilizationPct != null).length
      : null;
  const vramUsed = gpuDevices.reduce((s, d) => s + (d.vramUsedBytes ?? 0), 0);
  const vramTotal = gpuDevices.reduce((s, d) => s + (d.vramTotalBytes ?? 0), 0);
  const vramPct = vramTotal > 0 ? (vramUsed / vramTotal) * 100 : null;

  const sparkValues = activitySeries.map((n) => n);
  const totalTasks = summary?.recentMissions ?? dashboard?.missions.completedInWindow ?? null;

  return (
    <section className="lv-v2-agents-statusbar" aria-label="Systeemresource gebruik">
      <div className="lv-v2-agents-statusbar__resources">
        <h3>Resource Gebruik — Alle Agents (host)</h3>
        <div className="lv-v2-agents-statusbar__meters">
          <div className="lv-v2-meter-row">
            <div className="lv-v2-meter-row__head">
              <span>CPU</span>
              <span>{cpu != null ? `${Math.round(cpu)}%` : "UNMEASURED"}</span>
            </div>
            <ProgressBar value={cpu} />
          </div>
          <div className="lv-v2-meter-row">
            <div className="lv-v2-meter-row__head">
              <span>RAM</span>
              <span>
                {ramUsed != null && ramTotal != null
                  ? `${(ramUsed / 1024 ** 3).toFixed(1)} / ${(ramTotal / 1024 ** 3).toFixed(0)} GB (${ramPct != null ? Math.round(ramPct) : "—"}%)`
                  : "UNMEASURED"}
              </span>
            </div>
            <ProgressBar value={ramPct} />
          </div>
          <div className="lv-v2-meter-row">
            <div className="lv-v2-meter-row__head">
              <span>GPU</span>
              <span>
                {gpuAvg != null && Number.isFinite(gpuAvg) ? `${Math.round(gpuAvg)}%` : "UNMEASURED"}
              </span>
            </div>
            <ProgressBar value={gpuAvg != null && Number.isFinite(gpuAvg) ? gpuAvg : null} tone="warning" />
          </div>
          <div className="lv-v2-meter-row">
            <div className="lv-v2-meter-row__head">
              <span>VRAM</span>
              <span>
                {vramTotal > 0
                  ? `${(vramUsed / 1024 ** 3).toFixed(1)} / ${(vramTotal / 1024 ** 3).toFixed(0)} GB`
                  : "UNMEASURED"}
              </span>
            </div>
            <ProgressBar value={vramPct} />
          </div>
        </div>
      </div>
      <div className="lv-v2-agents-statusbar__activity">
        <h3>Agent Activiteit</h3>
        <p className="lv-v2-agents-hint">Taken / events per uur (lokaal geaggregeerd)</p>
        <Sparkline values={sparkValues} className="lv-v2-agents-spark" />
        <div className="lv-v2-agents-statusbar__stats">
          <span>
            Totaal taken {totalTasks != null ? totalTasks.toLocaleString("nl-NL") : "UNMEASURED"}
          </span>
          <span>
            Gem. duur{" "}
            {dashboard?.performance.avgDurationMs != null
              ? `${(dashboard.performance.avgDurationMs / 60000).toFixed(1)} min`
              : "UNMEASURED"}
          </span>
          <span>Succesratio {kpis.successRate.available ? kpis.successRate.value : formatPct(null)}</span>
        </div>
      </div>
    </section>
  );
}
