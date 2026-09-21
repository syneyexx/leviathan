import { useEffect, useState, type ReactNode } from "react";
import { AppFooter } from "../components/AppFooter";
import { AppHeader } from "../components/AppHeader";
import { AppSidebar } from "../components/AppSidebar";
import { useAppToast } from "../state/useAppToast";

type ShellProps = {
  activeMode: "explore" | "chat";
  searchPlaceholder?: string;
  modeLabel?: string;
  systemItems?: readonly string[];
  layout?: "standard" | "wide";
  pageClass?: string;
  chatApp?: boolean;
  children: ReactNode;
};

export function AppShell({
  activeMode,
  searchPlaceholder,
  modeLabel,
  systemItems,
  layout = "standard",
  pageClass,
  chatApp = false,
  children,
}: ShellProps) {
  const toast = useAppToast();
  const [sidebarOpen, setSidebarOpen] = useState(false);

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

  const onReserved = (label: string) => {
    toast(`${label} is reserved for a later Leviathan step.`);
  };

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
      <AppHeader
        searchPlaceholder={searchPlaceholder}
        modeLabel={modeLabel}
        systemItems={systemItems}
        onMenuClick={() => setSidebarOpen((value) => !value)}
      />
      <div className="lv-body">
        <AppSidebar open={sidebarOpen} onReserved={onReserved} />
        {children}
      </div>
      <AppFooter activeMode={activeMode} onReserved={onReserved} />
    </div>
  );
}
