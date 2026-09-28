import { Link } from "react-router-dom";
import { pluginRuntimeHeroes } from "../../assets/pluginRuntimeAssets";
import { AppShell } from "../../layouts/AppShell";
import "../../styles/modules-page.css";
import { useModulesWorkspace, type LifecycleAction } from "./modules/useModulesWorkspace";
import {
  DETAIL_TABS,
  LOCAL_NAV,
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
  updateAvailableFromEvidence,
  type DetailTabId,
  type ManagedModuleRow,
  type StatusTone,
} from "./modules/viewModels";

function IconPuzzle() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M8 4h3a2 2 0 0 1 2 2v1h1a2 2 0 1 1 0 4h-1v2h1a2 2 0 1 1 0 4h-1v1a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-3H5a2 2 0 1 1 0-4h1V9a2 2 0 0 1 2-2V4z" />
    </svg>
  );
}
function IconStack() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M4 8l8-4 8 4-8 4-8-4z" />
      <path d="M4 12l8 4 8-4" />
      <path d="M4 16l8 4 8-4" />
    </svg>
  );
}
function IconPlay() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M10 8l6 4-6 4V8z" fill="currentColor" stroke="none" />
    </svg>
  );
}
function IconWarn() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M12 3l9 16H3L12 3z" />
      <path d="M12 10v4" />
      <circle cx="12" cy="16.5" r="0.8" fill="currentColor" />
    </svg>
  );
}
function IconRefresh() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M20 12a8 8 0 1 1-2.3-5.6" />
      <path d="M20 4v5h-5" />
    </svg>
  );
}
function IconModule() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
    </svg>
  );
}
function IconStar() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2l1.2 8.8L22 12l-8.8 1.2L12 22l-1.2-8.8L2 12l8.8-1.2L12 2z" />
    </svg>
  );
}
function IconSearch() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4 4" />
    </svg>
  );
}

function Badge({ label, tone }: { label: string; tone: StatusTone }) {
  return <span className={`lv-mod-badge is-${tone}`}>{label}</span>;
}

function KpiValue({
  value,
  tone,
}: {
  value: string;
  tone?: "ok" | "err" | "cyan" | "muted";
}) {
  return <div className={`lv-mod-kpi-value${tone ? ` is-${tone}` : ""}`}>{value}</div>;
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

export function ModulesPage() {
  const ws = useModulesWorkspace();
  const selected = ws.selected;
  const health = healthLabel(selected);
  const updateEvidence = selected ? ws.updateEvidenceByModule[moduleId(selected)] : null;
  const updateState = updateAvailableFromEvidence(updateEvidence);
  const healthRec =
    (ws.healthPayload as Record<string, unknown> | null) ??
    (selected?.health as Record<string, unknown> | null | undefined) ??
    null;
  const lastCheck = measuredFromHealth(healthRec, "checked_at");
  const responseTime = measuredFromHealth(healthRec, "response_time_ms");
  const uptime = measuredFromHealth(healthRec, "uptime");
  const activeJobs =
    selected?.active_jobs?.length != null
      ? { kind: "measured" as const, value: selected.active_jobs.length }
      : measuredFromHealth(healthRec, "active_jobs");

  const panelText = detailPanelText({
    tab: ws.detailTab,
    selected,
    healthPayload: ws.healthPayload,
    logLines: ws.logLines,
    jobsPayload: ws.jobsPayload,
    versionsPayload: ws.versionsPayload,
    panelJson: ws.panelJson,
    lastResult: ws.lastResult,
  });

  const toolbar = (
    action: LifecycleAction,
    label: string,
    enabled: boolean,
    title?: string,
    primary?: boolean,
  ) => (
    <button
      key={action}
      type="button"
      className={`lv-mod-btn${primary ? " is-primary" : ""}`}
      disabled={!enabled || ws.lifecycleBusy}
      title={title}
      onClick={() => void ws.onLifecycle(action)}
    >
      {label}
    </button>
  );

  const updateKpi =
    ws.kpis.updateAvailable.kind === "measured"
      ? {
          value: String(ws.kpis.updateAvailable.value),
          tone: ws.kpis.updateAvailable.value > 0 ? ("cyan" as const) : ("ok" as const),
        }
      : {
          value: formatMeasured(ws.kpis.updateAvailable),
          tone: "muted" as const,
        };

  const flagValue = ws.kpis.featureFlag ?? "—";
  const flagTone =
    ws.kpis.featureFlag === "ON" ? ("ok" as const) : ws.kpis.featureFlag == null ? ("muted" as const) : ("muted" as const);
  const numOrDash = (n: number | null) => (n == null ? "—" : String(n));

  return (
    <AppShell
      modeLabel="Plugin Mode"
      searchPlaceholder="Search modules, manifests..."
      systemItems={["LLM", "NEURAL", "MEMORY", "MODULES"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime"
    >
      <main className="lv-main lv-pr-main lv-mod-page">
        <section className="lv-mod-hero" aria-label="Modules">
          <div className="lv-mod-hero-media">
            <img src={pluginRuntimeHeroes.modules} alt="" width={1600} height={240} />
          </div>
          <div className="lv-mod-hero-shade" />
          <div className="lv-mod-hero-content">
            <h1 className="lv-mod-hero-title">Modules</h1>
            <p className="lv-mod-hero-kicker">Plugin &amp; Runtime</p>
            <p className="lv-mod-hero-sub">
              Discover, install and manage LEVIATHAN modules, agents, tools and capabilities.
            </p>
          </div>
        </section>

        <section className="lv-mod-kpi-row" aria-label="Module KPIs">
          <article className="lv-mod-kpi">
            <div className="lv-mod-kpi-icon">
              <IconPuzzle />
            </div>
            <KpiValue value={flagValue} tone={flagTone} />
            <div className="lv-mod-kpi-label">Feature Flag</div>
          </article>
          <article className="lv-mod-kpi">
            <div className="lv-mod-kpi-icon">
              <IconStack />
            </div>
            <KpiValue value={numOrDash(ws.kpis.totalModules)} />
            <div className="lv-mod-kpi-label">Total Modules</div>
          </article>
          <article className="lv-mod-kpi">
            <div className="lv-mod-kpi-icon">
              <IconPlay />
            </div>
            <KpiValue value={numOrDash(ws.kpis.executable)} tone={ws.kpis.executable != null ? "ok" : "muted"} />
            <div className="lv-mod-kpi-label">Executable</div>
          </article>
          <article className={`lv-mod-kpi${ws.kpis.healthIssues ? " is-warn" : ""}`}>
            <div className="lv-mod-kpi-icon">
              <IconWarn />
            </div>
            <KpiValue
              value={numOrDash(ws.kpis.healthIssues)}
              tone={ws.kpis.healthIssues ? "err" : ws.kpis.healthIssues == null ? "muted" : undefined}
            />
            <div className="lv-mod-kpi-label">Health Issues</div>
          </article>
          <article className="lv-mod-kpi">
            <div className="lv-mod-kpi-icon">
              <IconRefresh />
            </div>
            <KpiValue value={updateKpi.value} tone={updateKpi.tone} />
            <div className="lv-mod-kpi-label">Update Available</div>
          </article>
        </section>

        {ws.loadError ? (
          <div className="lv-mod-banner is-error" role="alert">
            {ws.loadError}
          </div>
        ) : null}
        {!ws.managerEnabled && ws.snapshot ? (
          <div className="lv-mod-banner is-off" role="status">
            Module manager feature flag is OFF. Snapshot returns an empty modules list — no fabricated modules.
          </div>
        ) : null}

        <section className="lv-mod-workspace" aria-label="Modules workspace">
          <aside className="lv-mod-rail" aria-label="Modules local navigation">
            <div className="lv-mod-rail-head">
              <IconStar />
              Modules
            </div>
            <nav className="lv-mod-rail-nav">
              {LOCAL_NAV.map((item) => {
                if (item.disabled || !item.to) {
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className="lv-mod-rail-link is-disabled"
                      disabled
                      title={item.title}
                    >
                      {item.label}
                    </button>
                  );
                }
                if (item.active) {
                  return (
                    <span key={item.id} className="lv-mod-rail-link is-active" aria-current="page">
                      {item.label}
                    </span>
                  );
                }
                return (
                  <Link key={item.id} to={item.to} className="lv-mod-rail-link" title={item.title}>
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </aside>

          <section className="lv-mod-list" aria-label="Module list">
            <div className="lv-mod-list-head">
              <div className="lv-mod-list-title">Modules</div>
              <div className="lv-mod-list-actions">
                <button
                  type="button"
                  className="lv-mod-icon-btn"
                  title="Refresh snapshot"
                  disabled={ws.loading || ws.discovering}
                  onClick={() => void ws.load()}
                >
                  <IconRefresh />
                </button>
                <button
                  type="button"
                  className="lv-mod-btn is-primary"
                  style={{ minHeight: 28, padding: "4px 8px" }}
                  disabled={ws.discovering || !ws.managerEnabled}
                  title={ws.managerEnabled ? "POST /api/modules/discover" : "Module manager feature flag OFF"}
                  onClick={() => void ws.onDiscover()}
                >
                  {ws.discovering ? "…" : "Discover"}
                </button>
                <button
                  type="button"
                  className="lv-mod-btn"
                  style={{ minHeight: 28, padding: "4px 8px" }}
                  disabled={ws.lifecycleBusy || !ws.managerEnabled}
                  title="POST /api/modules/sweep-idle"
                  onClick={() => void ws.onLifecycle("sweep-idle")}
                >
                  Sweep Idle
                </button>
              </div>
            </div>
            <div className="lv-mod-search">
              <IconSearch />
              <input
                value={ws.query}
                onChange={(e) => ws.setQuery(e.target.value)}
                placeholder="Search modules..."
                aria-label="Search modules"
              />
            </div>
            <div className="lv-mod-filters" role="tablist" aria-label="Module filters">
              {(
                [
                  ["all", `All (${ws.counts.all})`],
                  ["installed", `Installed (${ws.counts.installed})`],
                  ["not_installed", `Not Installed (${ws.counts.not_installed})`],
                  ["updates", `Updates (${ws.counts.updates})`],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={ws.filter === id}
                  className={`lv-mod-chip${ws.filter === id ? " is-active" : ""}`}
                  onClick={() => ws.setFilter(id)}
                  title={
                    id === "updates" && ws.kpis.updateAvailable.kind !== "measured"
                      ? "Updates filter uses check-update evidence only"
                      : undefined
                  }
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="lv-mod-rows">
              {ws.loading && ws.modules.length === 0 ? (
                <>
                  <div className="lv-mod-skel" style={{ height: 64 }} />
                  <div className="lv-mod-skel" style={{ height: 64 }} />
                  <div className="lv-mod-skel" style={{ height: 64 }} />
                </>
              ) : null}
              {!ws.loading && ws.rows.length === 0 ? (
                <div className="lv-mod-empty">
                  {ws.loadError
                    ? "Module snapshot unavailable — fix backend/API, then Refresh."
                    : ws.snapshot && !ws.managerEnabled
                      ? "Manager OFF — empty list is truthful."
                      : "No modules in snapshot. Use Discover to scan discovery roots."}
                </div>
              ) : null}
              {ws.rows.map((row) => {
                const id = moduleId(row);
                const selectedRow = ws.selectedId === id;
                const tone = statusTone(row.status);
                const desc = moduleDescription(row) || row.adapter || "—";
                const ver = moduleVersion(row);
                return (
                  <button
                    key={id}
                    type="button"
                    className={`lv-mod-row${selectedRow ? " is-selected" : ""}`}
                    onClick={() => ws.selectModule(id)}
                    aria-pressed={selectedRow}
                  >
                    <div className="lv-mod-row-icon">
                      <IconModule />
                    </div>
                    <div className="lv-mod-row-name">{moduleName(row)}</div>
                    <Badge label={(row.status ?? "—").toUpperCase()} tone={tone} />
                    <div className="lv-mod-row-desc" title={desc}>
                      {desc}
                    </div>
                    <div className="lv-mod-row-meta">
                      <span className="lv-mod-row-ver">{row.adapter ?? "—"}</span>
                      <span className="lv-mod-row-ver">{ver ? `v${ver}` : "—"}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="lv-mod-detail" aria-label="Selected module">
            {!selected ? (
              <div className="lv-mod-detail-scroll">
                <div className="lv-mod-empty">Select a module to inspect lifecycle, health, and execute operations.</div>
              </div>
            ) : (
              <>
                <div className="lv-mod-detail-scroll">
                  <header className="lv-mod-detail-head">
                    <div className="lv-mod-detail-icon">
                      <IconModule />
                    </div>
                    <div>
                      <h2 className="lv-mod-detail-title">{moduleName(selected)}</h2>
                      <div className="lv-mod-badges">
                        {lifecycleBadges(selected).map((b) => (
                          <Badge key={`${b.label}-${b.tone}`} label={b.label} tone={b.tone} />
                        ))}
                      </div>
                      <p className="lv-mod-path">
                        {moduleId(selected)}
                        {selected.manifest?.source_path ? ` — ${selected.manifest.source_path}` : ""}
                      </p>
                      {moduleDescription(selected) ? (
                        <p className="lv-mod-desc">{moduleDescription(selected)}</p>
                      ) : null}
                      {selected.error ? (
                        <p className="lv-mod-desc" role="status" style={{ color: "var(--mod-err)" }}>
                          Error: {selected.error}
                        </p>
                      ) : null}
                    </div>
                    <div className="lv-mod-ids">
                      <div>
                        Module ID: <strong>{moduleId(selected)}</strong>
                      </div>
                      <div>
                        Version: <strong>{moduleVersion(selected) ? `v${moduleVersion(selected)}` : "—"}</strong>
                      </div>
                    </div>
                  </header>

                  <div className="lv-mod-toolbar" aria-label="Lifecycle actions">
                    <div className="lv-mod-toolbar-row">
                      {toolbar("install", "Install", ws.actions.canInstall, ws.actions.installReason)}
                      {toolbar("start", "Start", ws.actions.canStart, ws.actions.startReason)}
                      {toolbar("stop", "Stop", ws.actions.canStop, ws.actions.stopReason)}
                      {toolbar("restart", "Restart", ws.actions.canRestart, ws.actions.restartReason)}
                      {toolbar(
                        "ensure-ready",
                        "Ensure Ready",
                        ws.actions.canEnsureReady,
                        ws.actions.ensureReadyReason,
                        true,
                      )}
                      {toolbar("health", "Health", ws.actions.canHealth)}
                      {toolbar("jobs", "Jobs", ws.actions.canJobs)}
                      {toolbar("logs", "Logs", ws.actions.canLogs)}
                      {toolbar("capabilities", "Capabilities", ws.actions.canCapabilities)}
                    </div>
                    <div className="lv-mod-toolbar-row">
                      {toolbar("versions", "Versions", ws.actions.canVersions)}
                      {toolbar("check-update", "Check Update", ws.actions.canCheckUpdate)}
                      {toolbar("install-version", "Install Version", ws.actions.canInstallVersion)}
                      {toolbar(
                        "activate-version",
                        "Activate Version",
                        ws.actions.canActivateVersion,
                        ws.actions.activateReason,
                      )}
                      {toolbar("rollback", "Rollback", ws.actions.canRollback)}
                    </div>
                    <div className="lv-mod-version-inputs">
                      <label className="lv-mod-field">
                        Version ref (install)
                        <input
                          value={ws.versionRef}
                          onChange={(e) => ws.setVersionRef(e.target.value)}
                          placeholder="e.g. main / v1.2.3"
                          disabled={ws.lifecycleBusy}
                        />
                      </label>
                      <label className="lv-mod-field">
                        version_id (activate / rollback)
                        <input
                          value={ws.versionId}
                          onChange={(e) => ws.setVersionId(e.target.value)}
                          placeholder="from Versions list"
                          disabled={ws.lifecycleBusy}
                        />
                      </label>
                    </div>
                  </div>

                  <div className="lv-mod-cards">
                    <article className="lv-mod-card" aria-label="Health">
                      <div className="lv-mod-card-title">Health</div>
                      <div className="lv-mod-health-hero">
                        <div className={`lv-mod-health-mark is-${health.tone}`} aria-hidden="true">
                          {health.tone === "ok" ? "✓" : health.tone === "err" ? "!" : "·"}
                        </div>
                        <div>
                          <div className="lv-mod-health-label">{health.label}</div>
                          <div className="lv-mod-health-detail">{health.detail}</div>
                        </div>
                      </div>
                      <dl className="lv-mod-kv">
                        <dt>Status</dt>
                        <dd>{selected.status ?? "UNMEASURED"}</dd>
                        <dt>Last Check</dt>
                        <dd>{formatMeasured(lastCheck)}</dd>
                        <dt>Response Time</dt>
                        <dd>
                          {responseTime.kind === "measured" ? `${responseTime.value} ms` : formatMeasured(responseTime)}
                        </dd>
                        <dt>Uptime</dt>
                        <dd>{formatMeasured(uptime)}</dd>
                        <dt>Active Jobs</dt>
                        <dd>{formatMeasured(activeJobs, "0")}</dd>
                        <dt>Runtime</dt>
                        <dd>{selected.runtime_state ?? "UNMEASURED"}</dd>
                        <dt>Adapter</dt>
                        <dd>{selected.adapter ?? "—"}</dd>
                      </dl>
                    </article>

                    <article className="lv-mod-card" aria-label="Version information">
                      <div className="lv-mod-card-title">Version Information</div>
                      <dl className="lv-mod-kv">
                        <dt>Installed</dt>
                        <dd>{moduleVersion(selected) ? `v${moduleVersion(selected)}` : "—"}</dd>
                        <dt>Latest Available</dt>
                        <dd>
                          {updateState.kind === "measured"
                            ? updateState.value
                              ? "Update available"
                              : "Up to date"
                            : "NOT CHECKED"}
                        </dd>
                        <dt>Active Version</dt>
                        <dd>{moduleVersion(selected) ? `v${moduleVersion(selected)}` : "—"}</dd>
                        <dt>Update Status</dt>
                        <dd>
                          {updateState.kind === "measured"
                            ? updateState.value
                              ? "UPDATE AVAILABLE"
                              : "CURRENT"
                            : "NOT CHECKED"}
                        </dd>
                      </dl>
                      {ws.versionsPayload?.length ? (
                        <div className="lv-mod-cap-meta">{ws.versionsPayload.length} version record(s) loaded</div>
                      ) : (
                        <div className="lv-mod-cap-meta">Run Versions / Check Update for measured data</div>
                      )}
                      <button
                        type="button"
                        className="lv-mod-linkish"
                        onClick={() => {
                          ws.setDetailTab("versions");
                          void ws.onLifecycle("versions");
                        }}
                      >
                        Manage Versions
                      </button>
                    </article>

                    <article className="lv-mod-card" aria-label="Capabilities">
                      <div className="lv-mod-card-title">Capabilities</div>
                      <div className="lv-mod-cap-list">
                        {ws.capabilitiesPayload.length === 0 ? (
                          <div className="lv-mod-cap-meta">No capabilities registered on manifest</div>
                        ) : (
                          ws.capabilitiesPayload.slice(0, 5).map((cap) => (
                            <div key={cap.capabilityId} className="lv-mod-cap-item">
                              <span className="lv-mod-cap-dot" />
                              <div>
                                <div>{cap.name}</div>
                                <div className="lv-mod-cap-meta">
                                  {cap.capabilityId}
                                  {cap.sideEffects.length ? ` · ${cap.sideEffects.join(", ")}` : ""}
                                </div>
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                      <button
                        type="button"
                        className="lv-mod-linkish"
                        onClick={() => {
                          ws.setDetailTab("capabilities");
                          void ws.onLifecycle("capabilities");
                        }}
                      >
                        View All ({ws.capabilitiesPayload.length})
                      </button>
                    </article>
                  </div>

                  <div className="lv-mod-tabs" role="tablist" aria-label="Module detail tabs">
                    {DETAIL_TABS.map((tab) => {
                      const jobsCount =
                        tab.id === "jobs"
                          ? ws.jobsPayload?.length ?? selected.active_jobs?.length ?? null
                          : null;
                      return (
                        <button
                          key={tab.id}
                          type="button"
                          role="tab"
                          aria-selected={ws.detailTab === tab.id}
                          className={`lv-mod-tab${ws.detailTab === tab.id ? " is-active" : ""}`}
                          onClick={() => ws.setDetailTab(tab.id)}
                        >
                          {tab.label}
                          {tab.id === "jobs" && jobsCount != null ? ` (${jobsCount})` : ""}
                        </button>
                      );
                    })}
                    <button
                      type="button"
                      role="tab"
                      aria-selected={ws.detailTab === "execute"}
                      className={`lv-mod-tab${ws.detailTab === "execute" ? " is-active" : ""}`}
                      onClick={() => ws.setDetailTab("execute")}
                    >
                      Execute
                    </button>
                    <div className="lv-mod-tab-tools">
                      <button type="button" className="lv-mod-icon-btn" title="Copy panel" onClick={() => copyText(panelText)}>
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7">
                          <rect x="9" y="9" width="11" height="11" rx="2" />
                          <path d="M5 15V5a2 2 0 0 1 2-2h10" />
                        </svg>
                      </button>
                      <button
                        type="button"
                        className="lv-mod-icon-btn"
                        title="Download JSON"
                        onClick={() => downloadText(`${moduleId(selected)}-${ws.detailTab}.json`, panelText)}
                      >
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7">
                          <path d="M12 3v12" />
                          <path d="M7 11l5 5 5-5" />
                          <path d="M5 19h14" />
                        </svg>
                      </button>
                    </div>
                  </div>

                  {ws.detailTab === "execute" ? (
                    <div className="lv-mod-execute">
                      <label className="lv-mod-field">
                        Operation
                        {ws.ops.length > 0 ? (
                          <select
                            value={ws.ops.includes(ws.operation) ? ws.operation : ""}
                            onChange={(e) => ws.setOperation(e.target.value)}
                            disabled={!ws.actions.canExecute || ws.executing}
                          >
                            <option value="" disabled>
                              Select operation…
                            </option>
                            {ws.ops.map((op) => (
                              <option key={op} value={op}>
                                {op}
                              </option>
                            ))}
                          </select>
                        ) : null}
                        <input
                          value={ws.operation}
                          onChange={(e) => ws.setOperation(e.target.value)}
                          disabled={!ws.actions.canExecute || ws.executing}
                          placeholder="operation name"
                          aria-label="Operation name"
                          style={{ marginTop: ws.ops.length ? 6 : 0 }}
                        />
                      </label>
                      <label className="lv-mod-field">
                        Arguments (JSON object)
                        <textarea
                          value={ws.argsJson}
                          onChange={(e) => ws.setArgsJson(e.target.value)}
                          spellCheck={false}
                          disabled={!ws.actions.canExecute || ws.executing}
                        />
                      </label>
                      <button
                        type="button"
                        className="lv-mod-btn is-primary"
                        disabled={!ws.actions.canExecute || ws.executing}
                        title={ws.actions.executeReason ?? "POST /api/modules/{id}/execute"}
                        onClick={() => void ws.onExecute()}
                      >
                        {ws.executing ? "Executing…" : "Execute"}
                      </button>
                      <pre className="lv-mod-code" tabIndex={0}>
                        {ws.lastResult ?? "Result will appear here after execute."}
                      </pre>
                      {selected.last_result ? (
                        <>
                          <div className="lv-mod-card-title">Snapshot last_result</div>
                          <pre className="lv-mod-code" tabIndex={0}>
                            {JSON.stringify(selected.last_result, null, 2)}
                          </pre>
                        </>
                      ) : null}
                    </div>
                  ) : (
                    <pre className="lv-mod-code" tabIndex={0}>
                      {panelText}
                    </pre>
                  )}
                </div>

                <footer className="lv-mod-footer" aria-label="Module status footer">
                  <span>
                    <strong>{moduleName(selected)}</strong>
                  </span>
                  <span className={statusTone(selected.status) === "ok" ? "is-ok" : undefined}>
                    Status: {selected.status ?? "—"}
                  </span>
                  <span>Last Action: {ws.lastAction ?? "—"}</span>
                  <span>Runtime: {selected.runtime_state ?? "UNMEASURED"}</span>
                  <span>Adapter: {selected.adapter ?? "—"}</span>
                  <span>
                    Dependencies:{" "}
                    {(() => {
                      const deps = dependenciesFromRow(selected);
                      return deps.kind === "measured" ? String(deps.value.length) : "UNMEASURED";
                    })()}
                  </span>
                </footer>
              </>
            )}
          </section>
        </section>

        {ws.snapshot?.discovery_roots?.length ? (
          <details className="lv-mod-empty">
            <summary>Discovery roots ({ws.snapshot.discovery_roots.length})</summary>
            <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
              {ws.snapshot.discovery_roots.map((root) => (
                <li key={root}>
                  <code>{root}</code>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </main>
    </AppShell>
  );
}
