import { useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { AppFooter } from "../components/AppFooter";
import { AppHeader } from "../components/AppHeader";
import { AppSidebar } from "../components/AppSidebar";
import { SkipLink } from "../components/SkipLink";
import { findMainMenuByPath } from "../navigation/menu";

type ShellProps = {
  activeMode?: "explore" | "chat";
  searchPlaceholder?: string;
  modeLabel?: string;
  systemItems?: readonly string[];
  layout?: "standard" | "wide";
  pageClass?: string;
  chatApp?: boolean;
  children: ReactNode;
};

export function AppShell({
  searchPlaceholder,
  modeLabel,
  systemItems,
  layout = "standard",
  pageClass,
  chatApp = false,
  children,
}: ShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const section = findMainMenuByPath(location.pathname);

  useEffect(() => {
    if (!sidebarOpen) return;
    const onDocClick = (event: MouseEvent) => {
      const sidebar = document.getElementById("sidebar");
      const menuBtn = document.querySelector(".lv-menu-btn");
      const target = event.target as Node;
      if (!sidebar || sidebar.contains(target)) return;
      if (menuBtn && menuBtn.contains(target)) return;
      setSidebarOpen(false);
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [sidebarOpen]);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname, location.search]);

  const appClass = [
    "lv-app",
    "lv-ritual-shell",
    `lv-section-${section.id}`,
    chatApp ? "lv-chat-app" : "",
    layout === "wide" ? "lv-app--wide" : "",
    pageClass ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={appClass}
      data-lv-section={section.id}
      data-lv-route={location.pathname}
    >
      <SkipLink />
      <AppHeader
        searchPlaceholder={searchPlaceholder}
        modeLabel={modeLabel}
        systemItems={systemItems}
        onMenuClick={() => setSidebarOpen((value) => !value)}
      />
      <div className="lv-body">
        <AppSidebar open={sidebarOpen} />
        {/* Landmark only — pages own `.lv-main` layout; avoid nested main padding. */}
        <div id="main-content" className="lv-main-slot" tabIndex={-1}>
          {children}
        </div>
      </div>
      <AppFooter />
    </div>
  );
}
