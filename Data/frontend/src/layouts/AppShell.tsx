import { useEffect, useState, type ReactNode } from "react";
import { AppFooter } from "../components/AppFooter";
import { AppHeader } from "../components/AppHeader";
import { AppSidebar } from "../components/AppSidebar";
import { AppSidebarV2, type SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { AppTopbarV2 } from "../components/layout/AppTopbarV2";
import { SkipLink } from "../components/SkipLink";

type ShellProps = {
  activeMode?: "explore" | "chat";
  searchPlaceholder?: string;
  modeLabel?: string;
  systemItems?: readonly string[];
  layout?: "standard" | "wide";
  pageClass?: string;
  chatApp?: boolean;
  /** Opt into Leviathan V2 chrome (Screen 1 shell). Legacy remains default. */
  variant?: "legacy" | "v2";
  v2Title?: string;
  v2Subtitle?: string;
  v2Online?: boolean | null;
  v2Refreshing?: boolean;
  onV2Refresh?: () => void;
  v2StatusRows?: readonly SidebarStatusRow[];
  v2Now?: () => Date;
  /** Generic topbar action slot (Chat / future pages). */
  v2Actions?: ReactNode;
  /** Hide default Refresh when page actions replace it. */
  v2HideRefresh?: boolean;
  /** Opt into a real V2 main scroll container instead of the legacy display:contents slot. */
  v2ScrollableMain?: boolean;
  children: ReactNode;
};

export function AppShell({
  searchPlaceholder,
  modeLabel,
  systemItems,
  layout = "standard",
  pageClass,
  chatApp = false,
  variant = "legacy",
  v2Title,
  v2Subtitle,
  v2Online = null,
  v2Refreshing = false,
  onV2Refresh,
  v2StatusRows,
  v2Now,
  v2Actions,
  v2HideRefresh = false,
  v2ScrollableMain = false,
  children,
}: ShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!sidebarOpen) return;
    const onDocClick = (event: MouseEvent) => {
      const sidebar = document.getElementById("sidebar");
      const menuBtn = document.querySelector(".lv-menu-btn, .lv-v2-menu-btn");
      const target = event.target as Node;
      if (!sidebar || sidebar.contains(target)) return;
      if (menuBtn && menuBtn.contains(target)) return;
      setSidebarOpen(false);
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [sidebarOpen]);

  if (variant === "v2") {
    const appClass = ["lv-app", "lv-v2", chatApp ? "lv-chat-app" : "", pageClass ?? ""]
      .filter(Boolean)
      .join(" ");

    return (
      <div className={appClass}>
        <SkipLink />
        <AppTopbarV2
          title={v2Title}
          subtitle={v2Subtitle}
          online={v2Online}
          refreshing={v2Refreshing}
          onRefresh={onV2Refresh}
          onMenuClick={() => setSidebarOpen((value) => !value)}
          now={v2Now}
          actions={v2Actions}
          hideRefresh={v2HideRefresh}
        />
        <div className="lv-body">
          <AppSidebarV2 open={sidebarOpen} statusRows={v2StatusRows} />
          <div
            id="main-content"
            className="lv-main-slot"
            tabIndex={-1}
            style={
              v2ScrollableMain
                ? { display: "block", overflow: "auto", minWidth: 0, minHeight: 0 }
                : undefined
            }
          >
            {children}
          </div>
        </div>
      </div>
    );
  }

  const appClass = [
    "lv-app",
    chatApp ? "lv-chat-app" : "",
    layout === "wide" ? "lv-app--wide" : "",
    pageClass ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={appClass}>
      <SkipLink />
      <AppHeader
        searchPlaceholder={searchPlaceholder}
        modeLabel={modeLabel}
        systemItems={systemItems}
        onMenuClick={() => setSidebarOpen((value) => !value)}
      />
      <div className="lv-body">
        <AppSidebar open={sidebarOpen} />
        <div id="main-content" className="lv-main-slot" tabIndex={-1}>
          {children}
        </div>
      </div>
      <AppFooter />
    </div>
  );
}
