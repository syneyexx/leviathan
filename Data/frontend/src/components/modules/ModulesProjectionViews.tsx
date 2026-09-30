import { Badge, Panel } from "../ui";
import {
  isExecutable,
  isInstalled,
  moduleId,
  moduleName,
  moduleVersion,
  statusTone,
  type ManagedModuleRow,
  type StatusTone,
} from "../../pages/plugin-runtime/modules/viewModels";
import type { ModuleSnapshot } from "../../types/api";

type Props = {
  view: "runtimes" | "installation" | "environments";
  modules: ManagedModuleRow[];
  onSelectModule: (id: string) => void;
  snapshot?: ModuleSnapshot | null;
  selectedId?: string | null;
};

function badgeTone(tone: StatusTone): "success" | "warning" | "danger" | "info" | "muted" | "trading" {
  if (tone === "ok") return "success";
  if (tone === "warn") return "warning";
  if (tone === "err") return "danger";
  if (tone === "cyan") return "info";
  if (tone === "gold") return "trading";
  return "muted";
}

/** Runtimes / Installation / Environments projections from existing module snapshot. */
export function ModulesProjectionViews({ view, modules, onSelectModule, snapshot = null, selectedId = null }: Props) {
  if (view === "runtimes") {
    const runtimeRows = modules.filter((m) => isInstalled(m) || isExecutable(m) || m.runtime_state);
    return (
      <Panel
        title="Runtimes"
        className="lv-v2-modules-projection"
        meta={`${runtimeRows.length} gemeten`}
        bodyClassName="lv-v2-modules-projection__body"
      >
        <p className="lv-v2-muted lv-v2-modules-projection__lead">
          Projectie van ModuleManager + JobRuntime — geen aparte runtime service.
        </p>
        <div className="lv-v2-table-wrap">
          <table className="lv-v2-table">
            <thead>
              <tr>
                <th>Module</th>
                <th>Adapter</th>
                <th>Runtime</th>
                <th>Desired</th>
                <th>Jobs</th>
              </tr>
            </thead>
            <tbody>
              {runtimeRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="lv-v2-modules-empty-cell">
                    Geen runtime state in snapshot.
                  </td>
                </tr>
              ) : (
                runtimeRows.map((row) => {
                  const id = moduleId(row);
                  return (
                    <tr
                      key={id}
                      className={selectedId === id ? "is-selected" : undefined}
                      onClick={() => onSelectModule(id)}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onSelectModule(id);
                        }
                      }}
                    >
                      <td>{moduleName(row)}</td>
                      <td>{row.adapter ?? "—"}</td>
                      <td>
                        <Badge tone={badgeTone(statusTone(row.runtime_state ?? row.status))}>
                          {(row.runtime_state ?? row.status ?? "—").toUpperCase()}
                        </Badge>
                      </td>
                      <td>{row.desired_state ?? "—"}</td>
                      <td>{row.active_jobs?.length ?? 0}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    );
  }

  if (view === "installation") {
    const installed = modules.filter(isInstalled);
    const pending = modules.filter((m) => !isInstalled(m));
    return (
      <div className="lv-v2-modules-projection-grid">
        <Panel title="Geïnstalleerd" className="lv-v2-modules-projection" meta={String(installed.length)}>
          <ul className="lv-v2-modules-projection__list">
            {installed.length === 0 ? (
              <li className="lv-v2-muted">Geen geïnstalleerde modules.</li>
            ) : (
              installed.map((row) => {
                const id = moduleId(row);
                return (
                  <li key={id}>
                    <button type="button" className="lv-v2-linkish" onClick={() => onSelectModule(id)}>
                      {moduleName(row)}
                    </button>
                    <span className="lv-v2-muted">v{moduleVersion(row) ?? "—"}</span>
                    <Badge tone={badgeTone(statusTone(row.status))}>{(row.status ?? "—").toUpperCase()}</Badge>
                  </li>
                );
              })
            )}
          </ul>
        </Panel>
        <Panel title="Nog te installeren" className="lv-v2-modules-projection" meta={String(pending.length)}>
          <ul className="lv-v2-modules-projection__list">
            {pending.length === 0 ? (
              <li className="lv-v2-muted">Alles geïnstalleerd of geen discovered modules.</li>
            ) : (
              pending.map((row) => {
                const id = moduleId(row);
                return (
                  <li key={id}>
                    <button type="button" className="lv-v2-linkish" onClick={() => onSelectModule(id)}>
                      {moduleName(row)}
                    </button>
                    <span className="lv-v2-muted">{row.source_type ?? "—"}</span>
                    <Badge tone={badgeTone(statusTone(row.status))}>{(row.status ?? "—").toUpperCase()}</Badge>
                  </li>
                );
              })
            )}
          </ul>
        </Panel>
        <Panel title="Discovery roots" className="lv-v2-modules-projection">
          {snapshot?.discovery_roots?.length ? (
            <ul className="lv-v2-modules-projection__list">
              {snapshot.discovery_roots.map((root) => (
                <li key={root}>
                  <code>{root}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="lv-v2-muted">Geen discovery roots in snapshot.</p>
          )}
        </Panel>
      </div>
    );
  }

  return (
    <Panel
      title="Environments"
      className="lv-v2-modules-projection"
      meta="isolation projection"
      bodyClassName="lv-v2-modules-projection__body"
    >
      <p className="lv-v2-muted lv-v2-modules-projection__lead">
        Externe module-isolatie uit ModuleSnapshot — geen aparte environment service.
      </p>
      <div className="lv-v2-table-wrap">
        <table className="lv-v2-table">
          <thead>
            <tr>
              <th>Module</th>
              <th>Isolation</th>
              <th>Source path</th>
              <th>Resource</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {modules.length === 0 ? (
              <tr>
                <td colSpan={5} className="lv-v2-modules-empty-cell">
                  Geen modules in snapshot.
                </td>
              </tr>
            ) : (
              modules.map((row) => {
                const id = moduleId(row);
                const isolation = row.isolation ?? row.manifest?.isolation ?? "—";
                return (
                  <tr
                    key={id}
                    className={selectedId === id ? "is-selected" : undefined}
                    onClick={() => onSelectModule(id)}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelectModule(id);
                      }
                    }}
                  >
                    <td>{moduleName(row)}</td>
                    <td>
                      <code>{isolation}</code>
                    </td>
                    <td className="lv-v2-modules-path">{row.manifest?.source_path ?? "—"}</td>
                    <td>{row.resource_class ?? "—"}</td>
                    <td>
                      <Badge tone={badgeTone(statusTone(row.status))}>{(row.status ?? "—").toUpperCase()}</Badge>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
