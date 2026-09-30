import { Link } from "react-router-dom";
import { localNavItems } from "../../pages/plugin-runtime/modules/viewModels";
import type { WorkspaceView } from "../../pages/plugin-runtime/modules/useModulesWorkspace";

type Props = {
  activeView: WorkspaceView;
  onSelectView: (view: WorkspaceView) => void;
};

const WORKSPACE_VIEWS = new Set<string>(["modules", "runtimes", "installation", "environments"]);

export function ModulesLocalNav({ activeView, onSelectView }: Props) {
  const items = localNavItems(activeView);

  return (
    <aside className="lv-v2-modules-rail" aria-label="Modules lokale navigatie">
      <nav className="lv-v2-modules-rail__nav">
        {items.map((item) => {
          const isWorkspace = item.id && WORKSPACE_VIEWS.has(item.id);
          if (item.disabled) {
            return (
              <button
                key={item.id}
                type="button"
                className="lv-v2-modules-rail__link is-disabled"
                disabled
                title={item.title}
              >
                {item.label}
              </button>
            );
          }
          if (isWorkspace) {
            const view = item.id as WorkspaceView;
            const active = item.active || activeView === view;
            return (
              <button
                key={item.id}
                type="button"
                className={`lv-v2-modules-rail__link${active ? " is-active" : ""}`}
                aria-current={active ? "page" : undefined}
                title={item.title}
                onClick={() => onSelectView(view)}
              >
                {item.label}
              </button>
            );
          }
          if (item.to) {
            return (
              <Link key={item.id} to={item.to} className="lv-v2-modules-rail__link" title={item.title}>
                {item.label}
              </Link>
            );
          }
          return (
            <span key={item.id} className="lv-v2-modules-rail__link is-disabled">
              {item.label}
            </span>
          );
        })}
      </nav>
    </aside>
  );
}
