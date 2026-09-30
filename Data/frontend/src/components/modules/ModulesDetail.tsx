import type { ReactNode } from "react";
import { Badge, Button, Panel } from "../ui";
import type { LifecycleAction } from "../../pages/plugin-runtime/modules/useModulesWorkspace";
import {
  DETAIL_TABS,
  capabilitiesFromRow,
  declaredOperations,
  dependenciesFromRow,
  formatMeasured,
  healthLabel,
  lifecycleBadges,
  measuredFromHealth,
  moduleDescription,
  moduleId,
  moduleName,
  moduleVersion,
  safeConfiguration,
  statusTone,
  type ActionAvailability,
  type CapabilityItem,
  type DetailTabId,
  type ManagedModuleRow,
  type StatusTone,
} from "../../pages/plugin-runtime/modules/viewModels";
import {
  IconCapabilities,
  IconCopy,
  IconDownload,
  IconEnsure,
  IconHealth,
  IconInstall,
  IconJobs,
  IconModule,
  IconPlay,
  IconRestart,
  IconStop,
  IconUpdate,
  IconVersions,
} from "./ModulesIcons";

type PendingLifecycle = {
  jobId: string;
  action: string;
  moduleId: string;
  acceptedAt: string;
  state: string;
} | null;

type Props = {
  selected: ManagedModuleRow | null;
  detailTab: DetailTabId;
  setDetailTab: (tab: DetailTabId) => void;
  actions: ActionAvailability;
  lifecycleBusy: boolean;
  pendingLifecycle: PendingLifecycle;
  healthPayload: Record<string, unknown> | null;
  logLines: string[] | null;
  jobsPayload: unknown[] | null;
  versionsPayload: unknown[] | null;
  capabilitiesPayload: CapabilityItem[];
  panelJson: string | null;
  lastResult: string | null;
  lastAction: string | null;
  activityEvents: Array<Record<string, unknown>>;
  ops: string[];
  operation: string;
  setOperation: (v: string) => void;
  argsJson: string;
  setArgsJson: (v: string) => void;
  executing: boolean;
  versionRef: string;
  setVersionRef: (v: string) => void;
  versionId: string;
  setVersionId: (v: string) => void;
  onLifecycle: (action: LifecycleAction) => void;
  onExecute: () => void;
  onCancelJob: () => void;
  onOpenInstall: () => void;
};

function badgeTone(tone: StatusTone): "success" | "warning" | "danger" | "info" | "muted" | "trading" | "system" {
  if (tone === "ok") return "success";
  if (tone === "warn") return "warning";
  if (tone === "err") return "danger";
  if (tone === "cyan") return "info";
  if (tone === "gold") return "trading";
  return "muted";
}

function copyText(text: string) {
  void navigator.clipboard?.writeText(text).catch(() => undefined);
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function externalMeta(row: ManagedModuleRow | null): Record<string, unknown> | null {
  const meta = row?.manifest?.metadata;
  if (!meta || typeof meta !== "object") return null;
  const external = (meta as Record<string, unknown>).external;
  return external && typeof external === "object" ? (external as Record<string, unknown>) : null;
}

function formatActivityTime(ev: Record<string, unknown>): string {
  const ms = typeof ev.created_at_ms === "number" ? ev.created_at_ms : null;
  if (ms != null) {
    const d = new Date(ms);
    return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  if (typeof ev.at === "string") return ev.at;
  return "—";
}

function detailPanelText(args: {
  tab: DetailTabId;
  selected: ManagedModuleRow | null;
  healthPayload: Record<string, unknown> | null;
  logLines: string[] | null;
  jobsPayload: unknown[] | null;
  versionsPayload: unknown[] | null;
  panelJson: string | null;
  lastResult: string | null;
}): string {
  const { tab, selected, healthPayload, logLines, jobsPayload, versionsPayload, panelJson, lastResult } = args;
  if (!selected) return "No module selected.";
  if (tab === "configuration") return JSON.stringify(safeConfiguration(selected), null, 2);
  if (tab === "health") {
    const health = healthPayload ?? selected.health ?? null;
    return health ? JSON.stringify(health, null, 2) : "UNMEASURED — run Health to fetch backend health.";
  }
  if (tab === "runtime") {
    return JSON.stringify(
      {
        adapter: selected.adapter ?? null,
        status: selected.status ?? null,
        runtime_state: selected.runtime_state ?? null,
        desired_state: selected.desired_state ?? null,
        active_jobs: selected.active_jobs ?? [],
        error: selected.error ?? null,
        source_path: selected.manifest?.source_path ?? null,
      },
      null,
      2,
    );
  }
  if (tab === "dependencies") {
    const deps = dependenciesFromRow(selected);
    if (deps.kind !== "measured") return "UNMEASURED — dependency versions only when measured by install/manifest.";
    return JSON.stringify(deps.value, null, 2);
  }
  if (tab === "jobs") {
    if (jobsPayload) return JSON.stringify(jobsPayload, null, 2);
    if (selected.active_jobs?.length) return JSON.stringify(selected.active_jobs, null, 2);
    return "No jobs loaded — press Jobs to fetch.";
  }
  if (tab === "logs") {
    if (logLines) return logLines.join("\n") || "(empty)";
    return "No logs loaded — press Logs to fetch.";
  }
  if (tab === "manifest") {
    return JSON.stringify(
      {
        module_id: moduleId(selected),
        name: moduleName(selected),
        version: moduleVersion(selected),
        source_path: selected.manifest?.source_path ?? null,
        isolation: selected.manifest?.isolation ?? null,
        capabilities: selected.manifest?.capabilities ?? [],
        metadata: safeConfiguration(selected).external ? { external: safeConfiguration(selected).external } : {},
      },
      null,
      2,
    );
  }
  if (tab === "versions" || tab === "capabilities") {
    return panelJson ?? (versionsPayload ? JSON.stringify(versionsPayload, null, 2) : "No data loaded yet.");
  }
  if (tab === "execute") {
    return lastResult ?? "No execute result yet.";
  }
  return panelJson ?? "—";
}

type ToolDef = {
  action: LifecycleAction | "install-open";
  label: string;
  icon: ReactNode;
  enabled: boolean;
  reason?: string;
  onClick: () => void;
};

export function ModulesDetail(props: Props) {
  const { selected } = props;
  if (!selected) {
    return (
      <aside className="lv-v2-panel lv-v2-modules-detail lv-v2-modules-detail--empty" aria-label="Module detail">
        <p className="lv-v2-muted">Selecteer een module om lifecycle, health en execute te bekijken.</p>
      </aside>
    );
  }

  const health = healthLabel(selected);
  const healthRec =
    (props.healthPayload as Record<string, unknown> | null) ??
    (selected.health as Record<string, unknown> | null | undefined) ??
    null;
  const lastCheck = measuredFromHealth(healthRec, "checked_at");
  const responseTime = measuredFromHealth(healthRec, "response_time_ms");
  const uptime = measuredFromHealth(healthRec, "uptime");
  const activeJobs =
    selected.active_jobs?.length != null
      ? { kind: "measured" as const, value: selected.active_jobs.length }
      : measuredFromHealth(healthRec, "active_jobs");

  const panelText = detailPanelText({
    tab: props.detailTab,
    selected,
    healthPayload: props.healthPayload,
    logLines: props.logLines,
    jobsPayload: props.jobsPayload,
    versionsPayload: props.versionsPayload,
    panelJson: props.panelJson,
    lastResult: props.lastResult,
  });

  const a = props.actions;
  const tools: ToolDef[] = [
    {
      action: "install-open",
      label: "Install",
      icon: <IconInstall />,
      enabled: a.canInstall,
      reason: a.installReason,
      onClick: props.onOpenInstall,
    },
    {
      action: "start",
      label: "Start",
      icon: <IconPlay />,
      enabled: a.canStart,
      reason: a.startReason,
      onClick: () => props.onLifecycle("start"),
    },
    {
      action: "stop",
      label: "Stop",
      icon: <IconStop />,
      enabled: a.canStop,
      reason: a.stopReason,
      onClick: () => props.onLifecycle("stop"),
    },
    {
      action: "restart",
      label: "Restart",
      icon: <IconRestart />,
      enabled: a.canRestart,
      reason: a.restartReason,
      onClick: () => props.onLifecycle("restart"),
    },
    {
      action: "ensure-ready",
      label: "Ensure Ready",
      icon: <IconEnsure />,
      enabled: a.canEnsureReady,
      reason: a.ensureReadyReason,
      onClick: () => props.onLifecycle("ensure-ready"),
    },
    {
      action: "health",
      label: "Health",
      icon: <IconHealth />,
      enabled: a.canHealth,
      reason: a.healthReason,
      onClick: () => props.onLifecycle("health"),
    },
    {
      action: "jobs",
      label: "Jobs",
      icon: <IconJobs />,
      enabled: a.canJobs,
      onClick: () => props.onLifecycle("jobs"),
    },
    {
      action: "versions",
      label: "Versions",
      icon: <IconVersions />,
      enabled: a.canVersions,
      onClick: () => props.onLifecycle("versions"),
    },
    {
      action: "check-update",
      label: "Check Update",
      icon: <IconUpdate />,
      enabled: a.canCheckUpdate,
      reason: a.checkUpdateReason,
      onClick: () => props.onLifecycle("check-update"),
    },
    {
      action: "capabilities",
      label: "Capabilities",
      icon: <IconCapabilities />,
      enabled: a.canCapabilities,
      onClick: () => props.onLifecycle("capabilities"),
    },
  ];

  const sideEffects =
    selected.declared_side_effects?.length
      ? selected.declared_side_effects.join(" / ")
      : capabilitiesFromRow(selected)
          .flatMap((c) => c.sideEffects)
          .filter((v, i, arr) => arr.indexOf(v) === i)
          .join(" / ") || "—";

  const external = externalMeta(selected);
  const runtime =
    external?.runtime && typeof external.runtime === "object"
      ? (external.runtime as Record<string, unknown>)
      : null;
  const install =
    external?.install && typeof external.install === "object"
      ? (external.install as Record<string, unknown>)
      : null;
  const ops = declaredOperations(selected);
  const deps = dependenciesFromRow(selected);
  const strategies = Array.isArray(install?.strategies) ? (install?.strategies as unknown[]).map(String) : [];
  const depList =
    deps.kind === "measured"
      ? deps.value.map((d) => (typeof d === "string" ? d : Array.isArray(d) ? String(d[0]) : JSON.stringify(d)))
      : [];

  const manifestExcerpt = {
    module_id: moduleId(selected),
    name: moduleName(selected),
    version: moduleVersion(selected),
    adapter: selected.adapter ?? null,
    isolation: selected.manifest?.isolation ?? selected.isolation ?? null,
  };

  const timeout =
    runtime && typeof runtime.timeout_s === "number"
      ? `${runtime.timeout_s}s`
      : runtime && typeof runtime.timeout === "number"
        ? `${runtime.timeout}s`
        : "—";
  const cwd =
    typeof runtime?.working_directory === "string"
      ? String(runtime.working_directory)
      : selected.manifest?.source_path ?? "—";

  return (
    <aside className="lv-v2-panel lv-v2-modules-detail" aria-label="Geselecteerde module">
      <div className="lv-v2-modules-detail__scroll">
        <header className="lv-v2-modules-detail__head">
          <div className="lv-v2-modules-detail__icon" aria-hidden="true">
            <IconModule />
          </div>
          <div className="lv-v2-modules-detail__titles">
            <h2 className="lv-v2-modules-detail__title">{moduleName(selected)}</h2>
            <div className="lv-v2-modules-detail__badges">
              {lifecycleBadges(selected).map((b) => (
                <Badge key={`${b.label}-${b.tone}`} tone={badgeTone(b.tone)}>
                  {b.label}
                </Badge>
              ))}
            </div>
            <p className="lv-v2-modules-detail__meta">
              module_id: <strong>{moduleId(selected)}</strong>
              {" · "}
              versie: <strong>{moduleVersion(selected) ?? "—"}</strong>
            </p>
            {moduleDescription(selected) ? (
              <p className="lv-v2-modules-detail__desc">{moduleDescription(selected)}</p>
            ) : null}
            {selected.error ? (
              <p className="lv-v2-modules-detail__error" role="status">
                Error: {selected.error}
              </p>
            ) : null}
          </div>
        </header>

        <div className="lv-v2-modules-toolbar" aria-label="Lifecycle acties">
          {tools.map((t) => {
            const disabled = !t.enabled || props.lifecycleBusy;
            const title = disabled
              ? t.reason || (props.lifecycleBusy ? "Lifecycle operation in progress" : `${t.label} niet beschikbaar`)
              : t.label;
            return (
              <button
                key={t.action}
                type="button"
                className="lv-v2-modules-tool"
                disabled={disabled}
                title={title}
                aria-label={t.label}
                onClick={t.onClick}
              >
                <span className="lv-v2-modules-tool__icon">{t.icon}</span>
                <span className="lv-v2-modules-tool__label">{t.label}</span>
              </button>
            );
          })}
        </div>

        {props.pendingLifecycle ? (
          <div className="lv-v2-modules-pending" role="status">
            <span>
              Job {props.pendingLifecycle.jobId.slice(0, 8)}… — {props.pendingLifecycle.action} (
              {props.pendingLifecycle.state})
            </span>
            <Button variant="ghost" size="sm" onClick={() => void props.onCancelJob()}>
              Annuleer
            </Button>
          </div>
        ) : null}

        <dl className="lv-v2-modules-state-strip" aria-label="Module state">
          <div>
            <dt>Desired state</dt>
            <dd>{selected.desired_state ?? "—"}</dd>
          </div>
          <div>
            <dt>Runtime state</dt>
            <dd>{selected.runtime_state ?? selected.status ?? "—"}</dd>
          </div>
          <div>
            <dt>Source type</dt>
            <dd>{selected.source_type ?? "—"}</dd>
          </div>
          <div>
            <dt>Ref</dt>
            <dd>{selected.source_ref ?? "—"}</dd>
          </div>
          <div>
            <dt>Resource class</dt>
            <dd>{selected.resource_class ?? "—"}</dd>
          </div>
          <div>
            <dt>Side effects</dt>
            <dd>{sideEffects}</dd>
          </div>
        </dl>

        <div className="lv-v2-modules-tabs" role="tablist" aria-label="Module detail tabs">
          {DETAIL_TABS.map((tab) => {
            const jobsCount =
              tab.id === "jobs" ? props.jobsPayload?.length ?? selected.active_jobs?.length ?? null : null;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={props.detailTab === tab.id}
                className={`lv-v2-modules-tab${props.detailTab === tab.id ? " is-active" : ""}`}
                onClick={() => props.setDetailTab(tab.id)}
              >
                {tab.label}
                {tab.id === "jobs" && jobsCount != null ? ` (${jobsCount})` : ""}
              </button>
            );
          })}
          <button
            type="button"
            role="tab"
            aria-selected={props.detailTab === "execute"}
            className={`lv-v2-modules-tab${props.detailTab === "execute" ? " is-active" : ""}`}
            onClick={() => props.setDetailTab("execute")}
          >
            Execute
          </button>
          <div className="lv-v2-modules-tabs__tools">
            <button type="button" className="lv-v2-modules-icon-btn" title="Kopieer panel" onClick={() => copyText(panelText)}>
              <IconCopy />
            </button>
            <button
              type="button"
              className="lv-v2-modules-icon-btn"
              title="Download JSON"
              onClick={() => downloadText(`${moduleId(selected)}-${props.detailTab}.json`, panelText)}
            >
              <IconDownload />
            </button>
          </div>
        </div>

        {props.detailTab === "runtime" ? (
          <div className="lv-v2-modules-runtime-grid">
            <Panel title="Runtime Informatie" className="lv-v2-modules-subpanel">
              <dl className="lv-v2-modules-kv">
                <dt>Status</dt>
                <dd>{selected.status ?? "—"}</dd>
                <dt>Runtime state</dt>
                <dd>{selected.runtime_state ?? "—"}</dd>
                <dt>Desired state</dt>
                <dd>{selected.desired_state ?? "—"}</dd>
                <dt>Active jobs</dt>
                <dd>{formatMeasured(activeJobs, "0")}</dd>
                <dt>Timeout</dt>
                <dd>{timeout}</dd>
                <dt>Working directory</dt>
                <dd className="lv-v2-modules-path">{cwd}</dd>
              </dl>
            </Panel>

            <Panel title="Health & Performance" className="lv-v2-modules-subpanel">
              <div className={`lv-v2-modules-health-mark is-${health.tone}`} aria-hidden="true">
                {health.tone === "ok" ? "✓" : health.tone === "err" ? "!" : "·"}
              </div>
              <dl className="lv-v2-modules-kv">
                <dt>Response time</dt>
                <dd>
                  {responseTime.kind === "measured" ? `${responseTime.value}ms` : formatMeasured(responseTime)}
                </dd>
                <dt>Uptime</dt>
                <dd>
                  {uptime.kind === "measured"
                    ? typeof uptime.value === "number"
                      ? `${uptime.value}%`
                      : String(uptime.value)
                    : formatMeasured(uptime)}
                </dd>
                <dt>Active jobs</dt>
                <dd>{formatMeasured(activeJobs, "0")}</dd>
                <dt>Last checked</dt>
                <dd>{formatMeasured(lastCheck)}</dd>
              </dl>
            </Panel>

            <Panel title="Beschikbare Operaties" className="lv-v2-modules-subpanel">
              {ops.length === 0 ? (
                <p className="lv-v2-muted">Geen operaties gedeclareerd.</p>
              ) : (
                <table className="lv-v2-modules-ops-table">
                  <thead>
                    <tr>
                      <th>Operatie</th>
                      <th>Side effects</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ops.map((op) => {
                      const cap = props.capabilitiesPayload.find(
                        (c) => c.capabilityId.endsWith(`.${op}`) || c.name === op,
                      );
                      const effects = cap?.sideEffects?.length
                        ? cap.sideEffects.join(", ")
                        : sideEffects !== "—"
                          ? sideEffects
                          : "—";
                      return (
                        <tr key={op}>
                          <td>
                            <code>{op}</code>
                          </td>
                          <td>{effects}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </Panel>

            <Panel title="Manifest (excerpt)" className="lv-v2-modules-subpanel">
              <pre className="lv-v2-modules-code" tabIndex={0}>
                {JSON.stringify(manifestExcerpt, null, 2)}
              </pre>
            </Panel>

            <Panel title="Dependencies & Installatie" className="lv-v2-modules-subpanel">
              <dl className="lv-v2-modules-kv">
                <dt>Strategies</dt>
                <dd>{strategies.length ? strategies.join(", ") : "UNMEASURED"}</dd>
                <dt>Python deps</dt>
                <dd>
                  {depList.length
                    ? depList.join(", ")
                    : deps.kind === "measured"
                      ? "UNMEASURED"
                      : formatMeasured({ kind: deps.kind })}
                </dd>
              </dl>
            </Panel>

            <Panel title="Recente Activiteiten" className="lv-v2-modules-subpanel">
              {props.activityEvents.length ? (
                <ul className="lv-v2-modules-activity">
                  {props.activityEvents.map((ev, i) => (
                    <li key={String(ev.event_id ?? i)}>
                      <time>{formatActivityTime(ev)}</time>
                      <span>{String(ev.label ?? ev.event ?? "event")}</span>
                      <Badge tone="success">{String(ev.status ?? "OK")}</Badge>
                    </li>
                  ))}
                </ul>
              ) : props.lastAction ? (
                <ul className="lv-v2-modules-activity">
                  <li>
                    <span>{props.lastAction}</span>
                    <Badge tone="info">LOCAL</Badge>
                  </li>
                </ul>
              ) : (
                <p className="lv-v2-muted">Nog geen recente activiteit gemeten.</p>
              )}
            </Panel>
          </div>
        ) : props.detailTab === "execute" ? (
          <div className="lv-v2-modules-execute">
            <label className="lv-v2-modules-field">
              Operation
              {props.ops.length > 0 ? (
                <select
                  className="lv-v2-input"
                  value={props.ops.includes(props.operation) ? props.operation : ""}
                  onChange={(e) => props.setOperation(e.target.value)}
                  disabled={!props.actions.canExecute || props.executing}
                >
                  <option value="" disabled>
                    Selecteer operatie…
                  </option>
                  {props.ops.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
              ) : null}
              <input
                className="lv-v2-input"
                value={props.operation}
                onChange={(e) => props.setOperation(e.target.value)}
                disabled={!props.actions.canExecute || props.executing}
                placeholder="operation name"
                aria-label="Operation name"
              />
            </label>
            <label className="lv-v2-modules-field">
              Arguments (JSON object)
              <textarea
                className="lv-v2-modules-textarea"
                value={props.argsJson}
                onChange={(e) => props.setArgsJson(e.target.value)}
                spellCheck={false}
                disabled={!props.actions.canExecute || props.executing}
              />
            </label>
            <div className="lv-v2-modules-version-inputs">
              <label className="lv-v2-modules-field">
                Version ref (install)
                <input
                  className="lv-v2-input"
                  value={props.versionRef}
                  onChange={(e) => props.setVersionRef(e.target.value)}
                  placeholder="e.g. main / v1.2.3"
                  disabled={props.lifecycleBusy}
                />
              </label>
              <label className="lv-v2-modules-field">
                version_id (activate / rollback)
                <input
                  className="lv-v2-input"
                  value={props.versionId}
                  onChange={(e) => props.setVersionId(e.target.value)}
                  placeholder="from Versions list"
                  disabled={props.lifecycleBusy}
                />
              </label>
            </div>
            <Button
              variant="primary"
              size="sm"
              disabled={!props.actions.canExecute || props.executing}
              title={props.actions.executeReason ?? "POST /api/modules/{id}/execute"}
              loading={props.executing}
              onClick={() => void props.onExecute()}
            >
              Execute
            </Button>
            <pre className="lv-v2-modules-code" tabIndex={0}>
              {props.lastResult ?? "Result will appear here after execute."}
            </pre>
          </div>
        ) : (
          <pre className="lv-v2-modules-code" tabIndex={0}>
            {panelText}
          </pre>
        )}
      </div>

      <footer className="lv-v2-modules-footer" aria-label="Module status footer">
        <span>
          <strong>{moduleName(selected)}</strong>
        </span>
        <span className={statusTone(selected.status) === "ok" ? "is-ok" : undefined}>
          Status: {selected.status ?? "—"}
        </span>
        <span>Last Action: {props.lastAction ?? "—"}</span>
        <span>Runtime: {selected.runtime_state ?? "UNMEASURED"}</span>
        <span>Adapter: {selected.adapter ?? "—"}</span>
      </footer>
    </aside>
  );
}
