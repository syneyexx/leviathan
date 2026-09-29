import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { BrandV2 } from "./BrandV2";
import { StatusDot } from "../ui";
import {
  findActiveV2Child,
  isV2NavItemActive,
  shouldAutoExpandV2Group,
  V2_PRIMARY_NAV,
  type V2NavIconId,
  type V2NavItem,
} from "../../navigation/v2Nav";

const ICONS: Record<V2NavIconId, ReactNode> = {
  dashboard: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="1.2" />
      <rect x="13" y="4" width="7" height="7" rx="1.2" />
      <rect x="4" y="13" width="7" height="7" rx="1.2" />
      <rect x="13" y="13" width="7" height="7" rx="1.2" />
    </>
  ),
  chat: <path d="M5 6h14v9H9l-4 3V6z" />,
  tasks: (
    <>
      <path d="M8 7h11M8 12h11M8 17h11" />
      <path d="M5 7h.01M5 12h.01M5 17h.01" />
    </>
  ),
  agents: (
    <>
      <circle cx="12" cy="8" r="3.2" />
      <path d="M5 19c1.8-3.2 4.2-4.8 7-4.8s5.2 1.6 7 4.8" />
    </>
  ),
  research: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4 4" />
    </>
  ),
  trading: (
    <>
      <path d="M4 16l4.5-5 3.5 3 4-6 4 2" />
      <path d="M17 6v4h4" />
    </>
  ),
  lm: (
    <>
      <path d="M12 4v6M12 10l-6 8M12 10l6 8M7.5 14.5h9" />
      <circle cx="12" cy="4" r="1.4" />
    </>
  ),
  training: (
    <>
      <path d="M4 18V8l8-4 8 4v10l-8 4-8-4z" />
      <path d="M12 8v10" />
    </>
  ),
  data: (
    <>
      <ellipse cx="12" cy="7" rx="7" ry="3" />
      <path d="M5 7v10c0 1.7 3.1 3 7 3s7-1.3 7-3V7" />
    </>
  ),
  automation: (
    <>
      <circle cx="7" cy="8" r="2.2" />
      <circle cx="17" cy="8" r="2.2" />
      <circle cx="12" cy="16.5" r="2.2" />
      <path d="M8.8 9.2l2.4 5.2M15.2 9.2l-2.4 5.2M9.2 8h5.6" />
    </>
  ),
  system: (
    <>
      <rect x="4" y="5" width="16" height="12" rx="2" />
      <path d="M8 20h8M12 17v3" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
    </>
  ),
};

export type SidebarStatusRow = {
  id: string;
  label: string;
  value: string;
  tone: "success" | "info" | "warning" | "danger" | "muted";
};

type AppSidebarV2Props = {
  open: boolean;
  statusRows?: readonly SidebarStatusRow[];
};

function NavIcon({ id }: { id: V2NavIconId }) {
  return (
    <svg className="lv-v2-nav-item__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      {ICONS[id]}
    </svg>
  );
}

function NavGroup({ item, pathname }: { item: V2NavItem; pathname: string }) {
  const autoExpand = shouldAutoExpandV2Group(item, pathname);
  const [open, setOpen] = useState(autoExpand);
  const activeChild = findActiveV2Child(item, pathname);
  const groupActive = isV2NavItemActive(item, pathname);

  useEffect(() => {
    if (autoExpand) setOpen(true);
  }, [autoExpand, pathname]);

  if (!item.expandable || !item.children?.length) {
    return (
      <NavLink
        to={item.to}
        end={item.to === "/"}
        className={() => `lv-v2-nav-item${groupActive ? " is-active" : ""}`}
      >
        <NavIcon id={item.icon} />
        <span className="lv-v2-nav-item__label">{item.label}</span>
      </NavLink>
    );
  }

  return (
    <div className={`lv-v2-nav-group${open ? " is-open" : ""}`}>
      <button
        type="button"
        className={`lv-v2-nav-item lv-v2-nav-group__toggle${groupActive ? " is-active" : ""}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <NavIcon id={item.icon} />
        <span className="lv-v2-nav-item__label">{item.label}</span>
        <svg className="lv-v2-nav-item__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      <div className="lv-v2-nav-children" role="group" aria-label={`${item.label} submenu`}>
        {item.children.map((child) => {
          const childActive = activeChild?.id === child.id;
          return (
            <NavLink
              key={child.id}
              to={child.to}
              end={child.to === "/"}
              className={() => `lv-v2-nav-child${childActive ? " is-active" : ""}`}
            >
              {child.label}
            </NavLink>
          );
        })}
      </div>
    </div>
  );
}

/** V2 primary sidebar — Screen 1 navigation + live System Status. */
export function AppSidebarV2({ open, statusRows = [] }: AppSidebarV2Props) {
  const location = useLocation();

  return (
    <aside className={`lv-v2-sidebar${open ? " is-open" : ""}`} id="sidebar">
      <BrandV2 />
      <nav className="lv-v2-sidebar__nav" aria-label="Hoofdmenu">
        {V2_PRIMARY_NAV.map((item) => (
          <NavGroup key={item.id} item={item} pathname={location.pathname} />
        ))}
      </nav>
      <div className="lv-v2-system-status" aria-label="System Status">
        <div className="lv-v2-system-status__title">System Status</div>
        {statusRows.length === 0 ? (
          <div className="lv-v2-system-status__row">
            <StatusDot tone="muted" />
            <span className="lv-v2-system-status__label">Status</span>
            <span className="lv-v2-system-status__value">—</span>
          </div>
        ) : (
          statusRows.map((row) => (
            <div className="lv-v2-system-status__row" key={row.id}>
              <StatusDot tone={row.tone} />
              <span className="lv-v2-system-status__label" title={row.label}>
                {row.label}
              </span>
              <span className="lv-v2-system-status__value">{row.value}</span>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
