import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

const NAV_ITEMS: { label: string; to?: string; icon: ReactNode }[] = [
  {
    label: "Command",
    to: "/",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <circle cx="12" cy="12" r="3" />
        <path d="M12 4v2M12 18v2M4 12h2M18 12h2" />
      </>
    ),
  },
  {
    label: "Chat",
    to: "/chat",
    icon: <path d="M5 6h14v9H8l-3 3V6z" />,
  },
  {
    label: "Status",
    to: "/status",
    icon: <path d="M5 19V9M12 19V5M19 19v-7" />,
  },
  {
    label: "Research",
    icon: (
      <>
        <circle cx="12" cy="9" r="3.5" />
        <path d="M6 19c1.2-3 3.5-4.5 6-4.5s4.8 1.5 6 4.5" />
        <circle cx="12" cy="12" r="9" />
      </>
    ),
  },
  {
    label: "Creation",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M7 17l10-10" />
      </>
    ),
  },
  {
    label: "Agents",
    icon: (
      <>
        <path d="M8 8h8v8H8z" />
        <path d="M10 4h4M10 20h4M4 10v4M20 10v4" />
      </>
    ),
  },
  {
    label: "Projects",
    icon: (
      <>
        <path d="M4 8h16v11H4z" />
        <path d="M8 8V6h8v2" />
      </>
    ),
  },
  {
    label: "Datasets",
    icon: (
      <>
        <ellipse cx="12" cy="6" rx="7" ry="3" />
        <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
        <path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
      </>
    ),
  },
  {
    label: "Knowledge",
    icon: <path d="M12 4l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V7l7-3z" />,
  },
  {
    label: "Memory",
    icon: (
      <>
        <path d="M8 7h8l1 4H7l1-4z" />
        <path d="M7 11v7h10v-7" />
        <path d="M12 11v7" />
      </>
    ),
  },
  {
    label: "Models",
    to: "/models",
    icon: (
      <>
        <path d="M12 4l8 4-8 4-8-4 8-4z" />
        <path d="M4 12l8 4 8-4M4 16l8 4 8-4" />
      </>
    ),
  },
  {
    label: "Model Training",
    to: "/training",
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" />
      </>
    ),
  },
  {
    label: "Brain",
    to: "/brain",
    icon: (
      <>
        <path d="M9 8a3 3 0 015.8-1.2A3 3 0 0118 10c0 4-3 6-6 8-3-2-6-4-6-8a3 3 0 013-3z" />
        <path d="M12 11v5" />
      </>
    ),
  },
  {
    label: "Tools",
    icon: <path d="M14 7l3 3-8 8H6v-3l8-8z" />,
  },
  {
    label: "Automation",
    icon: (
      <>
        <path d="M12 7v5l3 2" />
        <circle cx="12" cy="12" r="8" />
      </>
    ),
  },
  {
    label: "Analytics",
    icon: <path d="M5 19V9M12 19V5M19 19v-7" />,
  },
  {
    label: "Simulation",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M12 8v8M8 12h8" />
      </>
    ),
  },
  {
    label: "Security",
    icon: (
      <>
        <path d="M12 4l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V7l7-3z" />
        <path d="M10 12l1.5 1.5L14.5 10" />
      </>
    ),
  },
  {
    label: "Settings",
    to: "/settings",
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 4v2M12 18v2M4 12h2M18 12h2M6.5 6.5l1.4 1.4M16.1 16.1l1.4 1.4M17.5 6.5l-1.4 1.4M7.9 16.1l-1.4 1.4" />
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
        <img className="lv-ornament-img" src="/assets/ornament.jpg" alt="" width={80} height={80} />
        <div className="lv-motto">Discipline Creates Freedom</div>
      </div>
    </aside>
  );
}
