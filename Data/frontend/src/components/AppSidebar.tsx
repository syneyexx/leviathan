import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { BrandMark, SidebarOrnament } from "./BrandMark";

type NavItem = {
  label: string;
  to?: string;
  icon: ReactNode;
};

const NAV_ITEMS: NavItem[] = [
  {
    label: "Dashboard",
    to: "/",
    icon: (
      <>
        <path d="M4 11.5L12 5l8 6.5" />
        <path d="M6.5 10.5V19h11V10.5" />
        <path d="M10 19v-5h4v5" />
      </>
    ),
  },
  {
    label: "Chat",
    to: "/chat",
    icon: (
      <>
        <path d="M5 6.5h14a1 1 0 011 1V15a1 1 0 01-1 1H9l-4 3.5V7.5a1 1 0 011-1z" />
        <circle cx="9.5" cy="11.5" r="0.9" fill="currentColor" stroke="none" />
        <circle cx="12.5" cy="11.5" r="0.9" fill="currentColor" stroke="none" />
      </>
    ),
  },
  {
    label: "Research",
    icon: (
      <>
        <circle cx="11" cy="11" r="6.5" />
        <circle cx="11" cy="11" r="1.4" fill="currentColor" stroke="none" />
        <path d="M16 16l4 4" />
      </>
    ),
  },
  {
    label: "Creation",
    icon: (
      <>
        <circle cx="12" cy="12" r="7.5" />
        <ellipse cx="12" cy="12" rx="7.5" ry="3.2" transform="rotate(-40 12 12)" />
        <path d="M12 4.5v2.2M12 17.3v2.2" />
      </>
    ),
  },
  {
    label: "Agents",
    icon: (
      <>
        <circle cx="12" cy="12" r="3.2" />
        <path d="M12 4.5v2.2M12 17.3v2.2M4.5 12h2.2M17.3 12h2.2" />
        <path d="M6.8 6.8l1.6 1.6M15.6 15.6l1.6 1.6M17.2 6.8l-1.6 1.6M8.4 15.6l-1.6 1.6" />
      </>
    ),
  },
  {
    label: "Projects",
    icon: (
      <>
        <path d="M4 9.5h16v9.5H4z" />
        <path d="M4 9.5l1.8-3h5.2l1.5 3" />
      </>
    ),
  },
  {
    label: "Knowledge",
    icon: (
      <>
        <path d="M12 3.5l7.2 4.2v.4c0 1.5-.4 5.2-2.6 7.6L12 20.5l-4.6-4.8C5.2 13.3 4.8 9.6 4.8 8.1v-.4L12 3.5z" />
        <path d="M12 3.5l3.6 8.2-3.6 2.4-3.6-2.4L12 3.5z" />
      </>
    ),
  },
  {
    label: "Memory",
    icon: (
      <>
        <path d="M12 4l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V7l7-3z" />
        <path d="M9.2 12.2c0-2 1.4-3.4 2.8-3.4 1.2 0 2.2.7 2.6 1.7" />
        <path d="M10.2 14.5c.6.8 1.5 1.2 2.4 1.2 1.2 0 2-.5 2.4-1.2" />
        <path d="M12 9.5v6.5" />
      </>
    ),
  },
  {
    label: "Models",
    to: "/models",
    icon: (
      <>
        <path d="M12 4v6" />
        <path d="M12 10l-6 8M12 10l6 8" />
        <path d="M7.5 14.5h9" />
        <circle cx="12" cy="4" r="1.4" />
        <circle cx="6" cy="18" r="1.3" />
        <circle cx="18" cy="18" r="1.3" />
      </>
    ),
  },
  {
    label: "Tools",
    icon: (
      <>
        <circle cx="7" cy="8" r="2.2" />
        <circle cx="17" cy="8" r="2.2" />
        <circle cx="12" cy="16.5" r="2.2" />
        <path d="M8.8 9.2l2.4 5.2M15.2 9.2l-2.4 5.2M9.2 8h5.6" />
      </>
    ),
  },
  {
    label: "Automation",
    icon: (
      <>
        <path d="M4 16l4.5-5 3.5 3 4-6 4 2" />
        <path d="M17 6v4h4" />
      </>
    ),
  },
  {
    label: "Analytics",
    icon: (
      <>
        <circle cx="6" cy="16" r="1.4" />
        <circle cx="11" cy="9" r="1.4" />
        <circle cx="16" cy="13" r="1.4" />
        <circle cx="20" cy="6" r="1.4" />
        <path d="M6 16l5-7 5 4 4-7" />
      </>
    ),
  },
  {
    label: "Simulation",
    icon: (
      <>
        <path d="M12 3.8l7 3.2v5.2c0 4.2-3.1 7.4-7 8.6-3.9-1.2-7-4.4-7-8.6V7l7-3.2z" />
        <path d="M12 9v6M9 12h6" />
      </>
    ),
  },
  {
    label: "Security",
    icon: (
      <>
        <path d="M12 3.5l6.5 2.4v4.2c0 2.4-.7 4.5-2.1 6.1L12 20.5l-4.4-4.3C6.2 14.6 5.5 12.5 5.5 10.1V5.9L12 3.5z" />
        <path d="M10 12.2l1.4 1.4L14.4 10" />
      </>
    ),
  },
  {
    label: "Settings",
    to: "/settings",
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
      </>
    ),
  },
];

type AppSidebarProps = {
  open: boolean;
  onReserved: (label: string) => void;
};

export function AppSidebar({ open, onReserved }: AppSidebarProps) {
  return (
    <aside className={`lv-sidebar${open ? " is-open" : ""}`} id="sidebar">
      <NavLink to="/" end className={() => "lv-sidebar-command"} style={{ textDecoration: "none" }}>
        <svg className="lv-icon" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="8" />
          <circle cx="12" cy="12" r="2.4" />
          <path d="M12 4.5v2M12 17.5v2M4.5 12h2M17.5 12h2" />
        </svg>
        <span>Command</span>
      </NavLink>

      <div className="lv-sidebar-brand">
        <div className="lv-sidebar-brand-mark" aria-hidden="true">
          <BrandMark id="sidebar-brand" />
        </div>
        <div className="lv-sidebar-brand-copy">
          <div className="lv-sidebar-brand-title">Leviathan</div>
          <div className="lv-sidebar-brand-tag">Intelligence</div>
        </div>
      </div>

      <nav className="lv-nav" aria-label="Primary">
        {NAV_ITEMS.map((item) => {
          if (item.to) {
            return (
              <NavLink
                key={item.label}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) => `lv-nav-item${isActive ? " is-active" : ""}`}
                style={{ textDecoration: "none" }}
              >
                <svg className="lv-icon" viewBox="0 0 24 24">
                  {item.icon}
                </svg>
                {item.label}
              </NavLink>
            );
          }
          return (
            <button
              key={item.label}
              className="lv-nav-item"
              type="button"
              onClick={() => onReserved(item.label)}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                {item.icon}
              </svg>
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="lv-sidebar-footer">
        <SidebarOrnament />
        <div className="lv-motto">
          <span>Discipline</span>
          <span>Creates Freedom</span>
        </div>
      </div>
    </aside>
  );
}
