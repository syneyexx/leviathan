import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { isMainMenuActive, MAIN_MENU } from "../navigation/menu";
import "../styles/sidebar-reference.css";
import { BrandMark } from "./BrandMark";

const ICONS: Record<string, ReactNode> = {
  hades: (
    <>
      <path d="M4 11.5L12 5l8 6.5" />
      <path d="M6.5 10.5V19h11V10.5" />
      <path d="M10 19v-5h4v5" />
    </>
  ),
  llm: (
    <>
      <path d="M12 4v6" />
      <path d="M12 10l-6 8M12 10l6 8" />
      <path d="M7.5 14.5h9" />
      <circle cx="12" cy="4" r="1.4" />
      <circle cx="6" cy="18" r="1.3" />
      <circle cx="18" cy="18" r="1.3" />
    </>
  ),
  media: (
    <>
      <rect x="4" y="6" width="16" height="12" rx="2" />
      <path d="M8 14l3-3 2.5 2.5L16 11l4 4" />
      <circle cx="9" cy="10" r="1.2" />
    </>
  ),
  trading: (
    <>
      <path d="M4 16l4.5-5 3.5 3 4-6 4 2" />
      <path d="M17 6v4h4" />
    </>
  ),
  research: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <circle cx="11" cy="11" r="1.4" fill="currentColor" stroke="none" />
      <path d="M16 16l4 4" />
    </>
  ),
  runtime: (
    <>
      <circle cx="7" cy="8" r="2.2" />
      <circle cx="17" cy="8" r="2.2" />
      <circle cx="12" cy="16.5" r="2.2" />
      <path d="M8.8 9.2l2.4 5.2M15.2 9.2l-2.4 5.2M9.2 8h5.6" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
    </>
  ),
};

type AppSidebarProps = {
  open: boolean;
};

/** HOOFDMENU — left sidebar top-level sections only. */
export function AppSidebar({ open }: AppSidebarProps) {
  const location = useLocation();

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

      <nav className="lv-nav" aria-label="Hoofdmenu">
        {MAIN_MENU.map((item) => {
          const active = isMainMenuActive(item, location.pathname);
          return (
            <NavLink
              key={item.id}
              to={item.to}
              end={item.to === "/"}
              className={() => `lv-nav-item${active ? " is-active" : ""}`}
              style={{ textDecoration: "none" }}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                {ICONS[item.id]}
              </svg>
              {item.label}
            </NavLink>
          );
        })}
      </nav>

      <div className="lv-sidebar-footer">
        <img
          className="lv-sidebar-footer-mark"
          src="/assets/sidebar-reference.svg"
          alt="Discipline creates freedom"
          width={176}
          height={155}
          draggable={false}
          loading="eager"
          decoding="sync"
        />
      </div>
    </aside>
  );
}
