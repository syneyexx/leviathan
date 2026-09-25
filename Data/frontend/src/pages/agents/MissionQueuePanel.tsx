import { useMemo } from "react";
import { formatElapsed, isActiveJobStatus } from "../../lib/jobStatus";
import type { AgentDefinition, AgentEvent, AgentMission } from "../../types/api";
import { childMissionsOf, filterMissions, missionTabCount, type MissionTab } from "./helpers";
import { Bar, Modal, PanelHead } from "./agentsUi";

const PRIMARY_TABS: MissionTab[] = ["All Tasks", "Running", "Queued", "Completed"];
const MORE_TABS: MissionTab[] = ["Failed", "Cancelled", "Interrupted"];

function tabLabel(tab: MissionTab): string {
  return tab === "All Tasks" ? "All" : tab;
}

export function MissionQueuePanel({
  missions,
  agentById,
  tab,
  selectedMissionId,
  busy,
  canLaunch,
  onTab,
  onSelectMission,
  onCancel,
  onNew,
}: {
  missions: AgentMission[];
  agentById: Record<string, AgentDefinition>;
  tab: MissionTab;
  selectedMissionId: string;
  busy: boolean;
  canLaunch: boolean;
  onTab: (tab: MissionTab) => void;
  onSelectMission: (id: string) => void;
  onCancel: (id: string) => void;
  onNew: () => void;
}) {
  const rows = useMemo(() => filterMissions(missions, tab), [missions, tab]);
  const running = missionTabCount(missions, "Running");

  return (
    <section className="lv-ag-panel lv-ag-missions">
      <PanelHead
        title="Queue / Missions"
        right={
          <>
            <span className="lv-ag-count">{running} running</span>
            <button type="button" className="lv-ag-btn-ghost is-xs" disabled={busy || !canLaunch} onClick={onNew}>
              + New
            </button>
          </>
        }
      />
      <div className="lv-ag-tabs is-xs">
        {PRIMARY_TABS.map((t) => (
          <button key={t} type="button" className={tab === t ? "is-active" : ""} onClick={() => onTab(t)}>
            {tabLabel(t)} ({missionTabCount(missions, t)})
          </button>
        ))}
        <select
          className={`lv-ag-tab-select${MORE_TABS.includes(tab) ? " is-active" : ""}`}
          value={MORE_TABS.includes(tab) ? tab : ""}
          onChange={(e) => e.target.value && onTab(e.target.value as MissionTab)}
          aria-label="More mission filters"
        >
          <option value="">More…</option>
          {MORE_TABS.map((t) => (
            <option key={t} value={t}>
              {t} ({missionTabCount(missions, t)})
            </option>
          ))}
        </select>
      </div>
      <div className="lv-ag-table-wrap">
        <table className="lv-ag-table is-dense">
          <thead>
            <tr>
              <th>Task</th>
              <th>Priority</th>
              <th>Assigned to</th>
              <th className="is-num">Jobs</th>
              <th className="is-num">Elapsed</th>
              <th>Progress</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="lv-ag-empty">
                  No missions in this filter.
                </td>
              </tr>
            ) : (
              rows.map((m) => {
                const pct = Math.round((m.progress || 0) * 100);
                const active = isActiveJobStatus(m.status);
                return (
                  <tr
                    key={m.missionId}
                    className={selectedMissionId === m.missionId ? "is-selected" : ""}
                    onClick={() => onSelectMission(m.missionId)}
                  >
                    <td className="lv-ag-cell-task" title={`${m.title} · ${m.status}`}>
                      {m.title}
                      {m.parentMissionId ? <small className="lv-ag-parent-tag"> child</small> : null}
                    </td>
                    <td>
                      <span className={`lv-ag-prio is-${m.priority}`}>{m.priority}</span>
                    </td>
                    <td className="is-muted">{agentById[m.agentId]?.name ?? m.agentId.slice(0, 8)}</td>
                    <td className="is-num">{m.jobIds.length}</td>
                    <td className="is-num is-muted">{formatElapsed(m.startedAt || m.createdAt, m.finishedAt)}</td>
                    <td>
                      <span className="lv-ag-util">
                        <Bar ratio={m.progress || 0} tone={m.status === "failed" ? "warn" : "cyan"} />
                        <em>{active || m.status === "completed" ? `${pct}%` : m.status}</em>
                      </span>
                    </td>
                    <td>
                      {active ? (
                        <button
                          type="button"
                          className="lv-ag-btn-stop is-xs"
                          disabled={busy}
                          onClick={(e) => {
                            e.stopPropagation();
                            onCancel(m.missionId);
                          }}
                        >
                          ✕
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function MissionDetailModal({
  detail,
  missions,
  agentById,
  busy,
  onSelectMission,
  onCancel,
  onClose,
}: {
  detail: { mission: AgentMission; children: AgentMission[]; events: AgentEvent[] };
  missions: AgentMission[];
  agentById: Record<string, AgentDefinition>;
  busy: boolean;
  onSelectMission: (id: string) => void;
  onCancel: (id: string) => void;
  onClose: () => void;
}) {
  const m = detail.mission;
  const children = detail.children.length > 0 ? detail.children : childMissionsOf(missions, m.missionId);
  return (
    <Modal
      title={`Mission · ${m.title}`}
      onClose={onClose}
      footer={
        isActiveJobStatus(m.status) ? (
          <button type="button" className="lv-ag-btn-stop" disabled={busy} onClick={() => onCancel(m.missionId)}>
            Cancel Mission
          </button>
        ) : undefined
      }
    >
      <ul className="lv-ag-kv">
        <li>
          <span>ID</span>
          <em>{m.missionId}</em>
        </li>
        <li>
          <span>Agent</span>
          <em>{agentById[m.agentId]?.name ?? m.agentId}</em>
        </li>
        <li>
          <span>Status</span>
          <em>
            {m.status} · {Math.round((m.progress || 0) * 100)}%
          </em>
        </li>
        <li>
          <span>Trace</span>
          <em>{m.traceId || "—"}</em>
        </li>
        <li>
          <span>Parent</span>
          <em>{m.parentMissionId || "—"}</em>
        </li>
        <li>
          <span>Jobs</span>
          <em>{m.jobIds.length ? m.jobIds.join(", ") : "—"}</em>
        </li>
        <li>
          <span>Error</span>
          <em>{m.error || "—"}</em>
        </li>
      </ul>
      <h4 className="lv-ag-subhead">Child missions</h4>
      {children.length === 0 ? (
        <p className="lv-ag-muted">No child missions.</p>
      ) : (
        <ul className="lv-ag-member-list">
          {children.map((c) => (
            <li key={c.missionId}>
              <button type="button" className="lv-ag-linkish" onClick={() => onSelectMission(c.missionId)}>
                {c.title}
              </button>
              <span>
                {agentById[c.agentId]?.name ?? c.agentId.slice(0, 8)} · {c.status} ·{" "}
                {Math.round((c.progress || 0) * 100)}%
              </span>
            </li>
          ))}
        </ul>
      )}
      {m.result ? (
        <details className="lv-ag-raw">
          <summary>Technical result / plan</summary>
          <pre>{JSON.stringify(m.result, null, 2)}</pre>
        </details>
      ) : null}
      {detail.events.length > 0 ? (
        <>
          <h4 className="lv-ag-subhead">Events</h4>
          <ul className="lv-ag-logs">
            {detail.events.slice(0, 20).map((e) => (
              <li key={e.eventId}>
                <time>{e.createdAt.slice(11, 19)}</time>
                <span className="lv-ag-log-src">[{e.category}]</span>
                <span className="lv-ag-log-text">{e.message}</span>
                <em>{e.level}</em>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Modal>
  );
}
