import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import {
  platformPromoPosters,
  platformSidebarPosters,
  type MediaPlatformId,
} from "../assets/mediaControlAssets";
import { BrandMark } from "../components/BrandMark";
import { PlatformIcon, StatusDot, VerifiedBadge } from "../components/media/MediaWidgets";
import { useAppToast } from "../state/useAppToast";

export type MediaPlatformShellProps = {
  activePlatform: MediaPlatformId | "media" | "agents";
  searchPlaceholder?: string;
  createAccent?: "red" | "blue" | "gold";
  children: ReactNode;
  statusItems?: readonly { label: string; value: string }[];
  promo?: { image?: string; caption?: string; platform?: MediaPlatformId };
  sidebarPoster?: string;
  sidebarCaption?: string;
};

type NavItem = {
  id: string;
  label: string;
  to?: string;
  reserved?: boolean;
  match?: (pathname: string) => boolean;
  icon: ReactNode;
};

const DEFAULT_STATUS = [
  { label: "Channel Status", value: "Healthy" },
  { label: "Monetization", value: "Enabled" },
  { label: "Community", value: "Good" },
  { label: "Content Warnings", value: "None" },
] as const;

const NAV_ICONS = {
  dashboard: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="1.2" />
      <rect x="13" y="4" width="7" height="7" rx="1.2" />
      <rect x="4" y="13" width="7" height="7" rx="1.2" />
      <rect x="13" y="13" width="7" height="7" rx="1.2" />
    </>
  ),
  media: (
    <>
      <rect x="4" y="6" width="16" height="12" rx="2" />
      <path d="M8 14l3-3 2.5 2.5L16 11l4 4" />
      <circle cx="9" cy="10" r="1.2" />
    </>
  ),
  agents: (
    <>
      <circle cx="8" cy="9" r="2.2" />
      <circle cx="16" cy="9" r="2.2" />
      <circle cx="12" cy="15.5" r="2.2" />
      <path d="M9.6 10.4l1.6 3.4M14.4 10.4l-1.6 3.4" />
    </>
  ),
  analytics: (
    <>
      <path d="M4 17V7M10 17V10M16 17V5M20 17H4" />
    </>
  ),
  reports: (
    <>
      <path d="M7 4h7l4 4v12H7V4z" />
      <path d="M14 4v4h4M9 12h6M9 15h6" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
    </>
  ),
} as const;

function pathActive(to: string, pathname: string, end = false) {
  if (end) return pathname === to;
  return pathname === to || pathname.startsWith(`${to}/`);
}

export function MediaPlatformShell({
  activePlatform,
  searchPlaceholder = "Search videos, titles, topics, or anything...",
  createAccent = "red",
  children,
  statusItems = DEFAULT_STATUS,
  promo,
  sidebarPoster,
  sidebarCaption = "Bigger audiences, a higher humanity.",
}: MediaPlatformShellProps) {
  const toast = useAppToast();

  const platformPoster =
    activePlatform === "youtube" ||
    activePlatform === "tiktok" ||
    activePlatform === "instagram" ||
    activePlatform === "facebook"
      ? platformSidebarPosters[activePlatform]
      : platformSidebarPosters.youtube;

  const posterSrc = sidebarPoster ?? platformPoster;
  const promoImage =
    promo?.image ??
    (promo?.platform
      ? platformPromoPosters[promo.platform]
      : activePlatform in platformPromoPosters
        ? platformPromoPosters[activePlatform as MediaPlatformId]
        : platformPromoPosters.youtube);

  const navItems: NavItem[] = [
    {
      id: "dashboard",
      label: "Dashboard",
      to: "/",
      match: (p) => p === "/",
      icon: NAV_ICONS.dashboard,
    },
    {
      id: "media",
      label: "Media Control",
      to: "/media",
      match: (p) => p === "/media",
      icon: NAV_ICONS.media,
    },
    {
      id: "youtube",
      label: "YouTube",
      to: "/media/youtube",
      match: (p) => pathActive("/media/youtube", p),
      icon: <PlatformIcon platform="youtube" />,
    },
    {
      id: "tiktok",
      label: "TikTok",
      to: "/media/tiktok",
      match: (p) => pathActive("/media/tiktok", p),
      icon: <PlatformIcon platform="tiktok" />,
    },
    {
      id: "instagram",
      label: "Instagram",
      to: "/media/instagram",
      match: (p) => pathActive("/media/instagram", p),
      icon: <PlatformIcon platform="instagram" />,
    },
    {
      id: "facebook",
      label: "Facebook",
      to: "/media/facebook",
      match: (p) => pathActive("/media/facebook", p),
      icon: <PlatformIcon platform="facebook" />,
    },
    {
      id: "agents",
      label: "Agents",
      to: "/agents",
      match: (p) => pathActive("/agents", p),
      icon: NAV_ICONS.agents,
    },
    {
      id: "analytics",
      label: "Analytics",
      to: "/analytics",
      match: (p) => pathActive("/analytics", p),
      icon: NAV_ICONS.analytics,
    },
    {
      id: "reports",
      label: "Reports",
      reserved: true,
      icon: NAV_ICONS.reports,
    },
    {
      id: "settings",
      label: "Settings",
      to: "/settings",
      match: (p) => pathActive("/settings", p),
      icon: NAV_ICONS.settings,
    },
  ];

  return (
    <div className="mp-shell" data-accent={createAccent} data-platform={activePlatform}>
      <header className="mp-header">
        <NavLink to="/" className="mp-brand" end>
          <div className="mp-brand-mark" aria-hidden="true">
            <BrandMark id="mp-brand" />
          </div>
          <div>
            <div className="mp-brand-title">LEVIATHAN</div>
            <div className="mp-brand-tag">Create a Higher Reality</div>
          </div>
        </NavLink>

        <label className="mp-search">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <input type="search" placeholder={searchPlaceholder} aria-label="Search" />
          <span className="mp-kbd">⌘ K</span>
        </label>

        <div className="mp-header-end">
          <div className="mp-status-pills" aria-label="System status">
            <span className="mp-status-pill">
              <StatusDot tone="green" />
              7 Agents Online
            </span>
            <span className="mp-status-pill">
              <StatusDot tone="green" />
              Studio Ready
            </span>
            <span className="mp-status-pill">
              <StatusDot tone="green" />
              Sync OK
            </span>
          </div>

          <button className="mp-bell" type="button" aria-label="Notifications" onClick={() => toast("Notifications")}>
            <svg viewBox="0 0 24 24">
              <path d="M6 16h12l-1.2-1.2V11a4.8 4.8 0 10-9.6 0v3.8L6 16z" />
              <path d="M10 18a2 2 0 004 0" />
            </svg>
            <span className="mp-bell-badge">3</span>
          </button>

          <div className="mp-user">
            <div className="mp-user-avatar" aria-hidden="true">
              <BrandMark id="mp-user" />
            </div>
            <div className="mp-user-meta">
              <div className="mp-user-name">
                LEVIATHAN
                <VerifiedBadge />
              </div>
              <div className="mp-user-role">Protocol Prime</div>
            </div>
            <svg className="mp-user-chev" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 6l6 6-6 6" />
            </svg>
          </div>
        </div>

        <div className="mp-vertical-quote" aria-hidden="true">
          Discipline Creates Worlds
        </div>
      </header>

      <div className="mp-body">
        <aside className="mp-sidebar" aria-label="Media platform navigation">
          <nav className="mp-nav">
            {navItems.map((item) => {
              if (item.reserved || !item.to) {
                return (
                  <button
                    key={item.id}
                    type="button"
                    className="mp-nav-item"
                    onClick={() => toast(`${item.label} is reserved for a later Leviathan step.`)}
                  >
                    <svg viewBox="0 0 24 24">{item.icon}</svg>
                    <span>{item.label}</span>
                  </button>
                );
              }

              const active =
                item.id === activePlatform ||
                (item.id === "media" && activePlatform === "media") ||
                (item.id === "agents" && activePlatform === "agents");

              return (
                <NavLink
                  key={item.id}
                  to={item.to}
                  end={item.to === "/" || item.to === "/media"}
                  className={({ isActive }) => `mp-nav-item${isActive || active ? " is-active" : ""}`}
                >
                  {item.id === "youtube" ||
                  item.id === "tiktok" ||
                  item.id === "instagram" ||
                  item.id === "facebook" ? (
                    item.icon
                  ) : (
                    <svg viewBox="0 0 24 24">{item.icon}</svg>
                  )}
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </nav>

          <div className="mp-sidebar-poster">
            <img src={posterSrc} alt="" draggable={false} />
            <div className="mp-sidebar-poster-caption">{sidebarCaption}</div>
          </div>
        </aside>

        <div className="mp-main">{children}</div>

        <aside className="mp-rail" aria-label="Utility rail">
          <div className="mp-create-row">
            <button className="mp-create-btn" type="button" onClick={() => toast("Create")}>
              CREATE
              <svg viewBox="0 0 24 24">
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            <button
              className="mp-create-more"
              type="button"
              aria-label="More actions"
              onClick={() => toast("More actions")}
            >
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="6" r="1.2" fill="currentColor" stroke="none" />
                <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
                <circle cx="12" cy="18" r="1.2" fill="currentColor" stroke="none" />
              </svg>
            </button>
          </div>

          <div className="mp-status-list">
            {statusItems.map((item) => (
              <div key={item.label} className="mp-status-list-item">
                <StatusDot tone="green" />
                <div>
                  <strong>{item.label}:</strong> {item.value}
                </div>
              </div>
            ))}
          </div>

          <div className="mp-promo">
            <div className="mp-promo-media">
              <img src={promoImage} alt="" draggable={false} />
              {promo?.platform ? (
                <div className="mp-promo-badge">
                  <PlatformIcon platform={promo.platform} />
                </div>
              ) : activePlatform === "youtube" ||
                activePlatform === "tiktok" ||
                activePlatform === "instagram" ||
                activePlatform === "facebook" ? (
                <div className="mp-promo-badge">
                  <PlatformIcon platform={activePlatform} />
                </div>
              ) : null}
            </div>
            <div className="mp-promo-copy">{promo?.caption ?? "The message reaches further."}</div>
          </div>
        </aside>
      </div>
    </div>
  );
}
