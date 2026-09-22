import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { media } from "../assets/media";
import {
  findMainMenuByPath,
  findSubMenuItem,
  type SubMenuItem,
} from "../navigation/menu";

const DEFAULT_ICON = (
  <>
    <circle cx="12" cy="12" r="7" />
    <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />
  </>
);

const ICONS: Record<string, ReactNode> = {
  chatten: <path d="M5 6h14v9H8l-3 3V6z" />,
  coding: <path d="M8 8l-4 4 4 4M16 8l4 4-4 4" />,
  taken: <path d="M5 19V9M12 19V5M19 19v-7" />,
  modellen: (
    <>
      <path d="M12 4v6M12 10l-6 8M12 10l6 8M7.5 14.5h9" />
      <circle cx="12" cy="4" r="1.4" />
    </>
  ),
  training: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2" />
    </>
  ),
  agents: (
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 4.5v2.2M12 17.3v2.2M4.5 12h2.2M17.3 12h2.2" />
    </>
  ),
  stats: <path d="M5 19V9M12 19V5M19 19v-7" />,
  overzicht: (
    <>
      <rect x="4" y="6" width="16" height="12" rx="2" />
      <path d="M8 14l3-3 2.5 2.5L16 11l4 4" />
    </>
  ),
  youtube: (
    <>
      <rect x="3" y="7" width="18" height="10" rx="2" />
      <path d="M10 10l5 2-5 2z" />
    </>
  ),
  tiktok: (
    <>
      <path d="M14 5v9.5a3.5 3.5 0 11-2-3.15" />
      <path d="M14 8c1.5 1.2 3 1.8 5 2" />
    </>
  ),
  instagram: (
    <>
      <rect x="5" y="5" width="14" height="14" rx="3" />
      <circle cx="12" cy="12" r="3.2" />
      <circle cx="16.2" cy="7.8" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  facebook: (
    <>
      <path d="M14 8h2V5h-2c-2.2 0-4 1.8-4 4v2H8v3h2v7h3v-7h2.2l.8-3H13V9c0-.6.4-1 1-1z" />
    </>
  ),
  queue: <path d="M5 7h14M5 12h14M5 17h10" />,
  viral: (
    <>
      <path d="M12 4l2.2 4.8L19.5 10l-3.7 3.4L17 19l-5-2.8L7 19l1.2-5.6L4.5 10l5.3-1.2L12 4z" />
    </>
  ),
  calendar: (
    <>
      <rect x="4" y="6" width="16" height="14" rx="2" />
      <path d="M8 4v4M16 4v4M4 10h16" />
    </>
  ),
  "media-analytics": <path d="M5 19V9M12 19V5M19 19v-7" />,
  library: <path d="M5 5h4v14H5zM10 5h4v14h-4zM15 5h4v14h-4z" />,
  personas: (
    <>
      <circle cx="12" cy="9" r="3.2" />
      <path d="M6 19c1.2-3 3.5-4.5 6-4.5s4.8 1.5 6 4.5" />
    </>
  ),
  simulatie: <path d="M4 16l4.5-5 3.5 3 4-6 4 2" />,
  strategieen: <path d="M5 18l7-12 7 12z" />,
  marktdata: <path d="M4 16l4.5-5 3.5 3 4-6 4 2" />,
  portefeuille: (
    <>
      <rect x="4" y="8" width="16" height="11" rx="2" />
      <path d="M4 11h16M9 8V6h6v2" />
    </>
  ),
  paper: <path d="M7 4h7l4 4v12H7zM14 4v4h4" />,
  broker: (
    <>
      <path d="M4 18V8l8-4 8 4v10l-8 4-8-4z" />
    </>
  ),
  research: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4 4" />
    </>
  ),
  brain: (
    <>
      <path d="M9 8a3 3 0 015.8-1.2A3 3 0 0118 10c0 4-3 6-6 8-3-2-6-4-6-8a3 3 0 013-3z" />
      <path d="M12 11v5" />
    </>
  ),
  geheugen: <path d="M12 4l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V7l7-3z" />,
  knowledge: <path d="M5 5h6v14H5zM13 5h6v14h-6z" />,
  evidence: (
    <>
      <path d="M12 3.5l6.5 2.4v4.2c0 2.4-.7 4.5-2.1 6.1L12 20.5l-4.4-4.3C6.2 14.6 5.5 12.5 5.5 10.1V5.9L12 3.5z" />
    </>
  ),
  bestanden: <path d="M4 8h6l2 2h8v8H4z" />,
  performance: <path d="M5 19V9M12 19V5M19 19v-7" />,
  modules: (
    <>
      <circle cx="7" cy="8" r="2.2" />
      <circle cx="17" cy="8" r="2.2" />
      <circle cx="12" cy="16.5" r="2.2" />
    </>
  ),
  mcp: (
    <>
      <rect x="5" y="5" width="14" height="14" rx="2" />
      <path d="M9 9h6v6H9z" />
    </>
  ),
  workflows: <path d="M6 7h5v5H6zM13 12h5v5h-5zM11 9.5h2M15.5 12v-2H13" />,
  console: <path d="M5 6h14v12H5zM8 10l2 2-2 2M12 14h4" />,
  algemeen: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2" />
    </>
  ),
  "llm-gedrag": <path d="M5 6.5h14v9H9l-4 3.5V7.5z" />,
  "llm-studio": (
    <>
      <rect x="4" y="5" width="16" height="14" rx="2" />
      <path d="M8 9h8M8 12h5" />
    </>
  ),
  rechten: (
    <>
      <path d="M12 3.5l6.5 2.4v4.2c0 2.4-.7 4.5-2.1 6.1L12 20.5l-4.4-4.3C6.2 14.6 5.5 12.5 5.5 10.1V5.9L12 3.5z" />
      <path d="M10 12.2l1.4 1.4L14.4 10" />
    </>
  ),
  benchmarks: <path d="M5 19V9M12 19V5M19 19v-7" />,
  mediacenter: (
    <>
      <rect x="4" y="6" width="16" height="12" rx="2" />
      <path d="M10 10l5 2-5 2z" />
    </>
  ),
  opslag: (
    <>
      <ellipse cx="12" cy="6" rx="7" ry="3" />
      <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
    </>
  ),
  python: <path d="M8 8l-4 4 4 4M16 8l4 4-4 4" />,
  "settings-console": <path d="M5 6h14v12H5zM8 10l2 2-2 2M12 14h4" />,
  logs: <path d="M6 6h12v12H6zM9 10h6M9 13h4" />,
};

function DockIcon({ item }: { item: SubMenuItem }) {
  return (
    <svg className="lv-icon" viewBox="0 0 24 24" aria-hidden="true">
      {ICONS[item.id] ?? DEFAULT_ICON}
    </svg>
  );
}

/** SUBMENU — footer dock under the middle box, driven by active HOOFDMENU. */
export function AppFooter() {
  const location = useLocation();
  const section = findMainMenuByPath(location.pathname);
  const active = findSubMenuItem(section, location.pathname, location.search);

  return (
    <footer className="lv-footer">
      <div className="lv-user">
        <img className="lv-avatar" src={media.avatar} alt="" width={40} height={40} />
        <div>
          <div className="lv-user-name">LEVIATHAN</div>
          <div className="lv-user-meta">v1.0.0 | Elite Mode</div>
        </div>
      </div>

      <nav className="lv-dock" aria-label={`${section.label} submenu`}>
        {section.submenu.map((item) => {
          const isActive = active?.id === item.id;
          return (
            <NavLink
              key={item.id}
              to={item.to}
              end
              className={() => `lv-dock-item${isActive ? " is-active" : ""}`}
              style={{ textDecoration: "none" }}
              title={item.label}
            >
              <DockIcon item={item} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="lv-ops-wrap">
        <div className="lv-ops">
          <span className="lv-status-online" />
          <strong>{section.label}</strong>
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
