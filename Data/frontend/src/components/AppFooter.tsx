import { NavLink } from "react-router-dom";

type AppFooterProps = {
  activeMode: "explore" | "chat";
  onReserved: (label: string) => void;
};

const DOCK = [
  {
    id: "explore" as const,
    label: "Explore",
    to: "/",
    icon: (
      <>
        <path d="M8 8h8v8H8z" />
        <path d="M5 12h2M17 12h2M12 5v2M12 17v2" />
      </>
    ),
  },
  {
    id: "chat" as const,
    label: "Chat",
    to: "/chat",
    icon: <path d="M5 6h14v9H8l-3 3V6z" />,
  },
];

const RESERVED = [
  { label: "Build", icon: <path d="M5 18l7-12 7 12z" /> },
  {
    label: "Analyze",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M12 8v5l3 2" />
      </>
    ),
  },
  {
    label: "Automate",
    icon: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M12 8v8M8 12h8" />
      </>
    ),
  },
  { label: "Monitor", icon: <path d="M5 11l7-6 7 6v8H5v-8z" /> },
];

export function AppFooter({ activeMode, onReserved }: AppFooterProps) {
  return (
    <footer className="lv-footer">
      <div className="lv-user">
        <img className="lv-avatar" src="/assets/avatar.jpg" alt="" width={40} height={40} />
        <div>
          <div className="lv-user-name">LEVIATHAN</div>
          <div className="lv-user-meta">v1.0.0 | Elite Mode</div>
        </div>
      </div>

      <nav className="lv-dock" aria-label="Modes">
        {DOCK.map((item) => (
          <NavLink
            key={item.id}
            to={item.to}
            end={item.to === "/"}
            className={() => `lv-dock-item${activeMode === item.id ? " is-active" : ""}`}
            style={{ textDecoration: "none" }}
          >
            <svg className="lv-icon" viewBox="0 0 24 24">
              {item.icon}
            </svg>
            <span>{item.label}</span>
          </NavLink>
        ))}
        {RESERVED.map((item) => (
          <button
            key={item.label}
            className="lv-dock-item"
            type="button"
            onClick={() => onReserved(item.label)}
          >
            <svg className="lv-icon" viewBox="0 0 24 24">
              {item.icon}
            </svg>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="lv-ops-wrap">
        <div className="lv-ops">
          <span className="lv-status-online" />
          <strong>All Systems Operational</strong>
        </div>
        <button className="lv-grid-btn" type="button" aria-label="Layout">
          <svg className="lv-icon" viewBox="0 0 24 24">
            <path d="M5 5h6v6H5zM13 5h6v6h-6M5 13h6v6H5M13 13h6v6h-6" />
          </svg>
        </button>
      </div>
    </footer>
  );
}
