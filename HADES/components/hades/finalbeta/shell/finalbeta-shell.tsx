"use client";

import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { HadesBrandLogo } from "../brand-logo";
import { useShellHealth } from "../hooks/use-shell-health";
import { FbIcon } from "../icons";
import {
  FINALBETA_HOOFDMENU,
  finalBetaHoofdmenu,
  finalBetaSubmenuFor,
} from "../routes";
import { FinalBetaTopnavIcon } from "../topnav-icon";
import type { FinalBetaNavigate, FinalBetaPageId } from "../types";

type FinalBetaShellProps = {
  page: FinalBetaPageId;
  body: ReactNode;
  inspector: ReactNode;
  onNavigate: FinalBetaNavigate;
  /** Extra class on .app (e.g. dash-app) */
  appClassName?: string;
  /** Extra class on main content */
  mainClassName?: string;
  /** Optional footer below body grid */
  footer?: ReactNode;
  /** Override left sidebar (dashboard global nav) */
  sidebar?: ReactNode;
};

const TOPNAV: {
  id: (typeof FINALBETA_HOOFDMENU)[number]["id"];
  label: string;
  desc: string;
  home: FinalBetaPageId;
  icon: string;
}[] = [
  { id: "hades-ai", label: "Hades AI", desc: "Jouw persoonlijke assistent", home: "dashboard", icon: "brain" },
  { id: "llm", label: "LLM", desc: "Train. Tune. Own.", home: "models", icon: "database" },
  { id: "media-control", label: "Media Control", desc: "Audio, video & live", home: "media", icon: "play" },
  { id: "trading-center", label: "TradingCenter", desc: "Marktdata & strategieën", home: "trading", icon: "chart" },
  { id: "onderzoek", label: "Onderzoek & Kennis", desc: "Analyseer. Ontdek. Bouw.", home: "research", icon: "search" },
  { id: "plugin-runtime", label: "Plugin & Runtime", desc: "Breid uit. Integreer. Automatiseer.", home: "performance", icon: "wrench" },
  { id: "settings", label: "Instellingen", desc: "Voorkeuren & policies", home: "settings-general", icon: "settings" },
];

const STUDIO: Record<string, { title: string; sub: string }> = {
  "hades-ai": { title: "Hades AI", sub: "Persoonlijke assistent" },
  llm: { title: "LLM Studio", sub: "Modellen & training" },
  "media-control": { title: "Media Studio", sub: "Audio, video & live" },
  "trading-center": { title: "TradingCenter", sub: "Marktdata & strategieën" },
  onderzoek: { title: "Onderzoek", sub: "Analyseer. Ontdek. Bouw." },
  "plugin-runtime": { title: "Plugin & Runtime", sub: "Breid uit. Integreer." },
  settings: { title: "Instellingen", sub: "Voorkeuren & policies" },
};

export function FinalBetaShell({
  page,
  body,
  inspector,
  onNavigate,
  appClassName,
  mainClassName,
  footer,
  sidebar,
}: FinalBetaShellProps) {
  const hoofd = finalBetaHoofdmenu(page);
  const submenu = finalBetaSubmenuFor(page);
  const studio = STUDIO[hoofd] ?? STUDIO["hades-ai"];
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);
  const shellHealth = useShellHealth();

  const showToast = (message: string) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 1400);
  };

  useEffect(() => {
    return () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    };
  }, []);

  const onShellClick = (event: MouseEvent<HTMLDivElement>) => {
    const target = (event.target as HTMLElement).closest<HTMLElement>("[data-fb-page]");
    if (target?.dataset.fbPage) {
      event.preventDefault();
      onNavigate(target.dataset.fbPage as FinalBetaPageId);
      return;
    }
    const toastEl = (event.target as HTMLElement).closest<HTMLElement>("[data-toast]");
    if (toastEl?.dataset.toast) {
      event.preventDefault();
      event.stopPropagation();
      showToast(toastEl.dataset.toast);
    }
  };

  return (
    <div className={`app ${appClassName ?? ""}`.trim()} data-fb-page-id={page} onClick={onShellClick}>
      <header className="topbar">
        <div className="brand">
          <HadesBrandLogo className="brand-logo" />
        </div>

        <nav className="topnav" aria-label="Hoofdmenu">
          {TOPNAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`topnav-item${hoofd === item.id ? " active" : ""}`}
              onClick={() => onNavigate(item.home)}
            >
              <span className="topnav-icon">
                <FinalBetaTopnavIcon name={item.icon} size={24} />
              </span>
              <span className="topnav-copy">
                <span className="topnav-label">{item.label}</span>
                <span className="topnav-desc">{item.desc}</span>
              </span>
            </button>
          ))}
        </nav>

        <div className="topright">
          <div
            className={`status-pill status-pill--${shellHealth.tone}`}
            data-shell-health={shellHealth.tone}
            title={shellHealth.detail}
            role="status"
            aria-live="polite"
          >
            <span
              className={`dot ${
                shellHealth.tone === "ok" ? "green" : shellHealth.tone === "degraded" ? "yellow" : "red"
              }`}
              aria-hidden="true"
            />
            <div className="status-pill-copy">
              <span className="status-pill-title">HADES Local</span>
              <span className="status-pill-sub">{shellHealth.label}</span>
            </div>
          </div>
          <button
            className="icon-btn"
            type="button"
            aria-label="Instellingen"
            onClick={() => onNavigate("settings-general")}
          >
            <FbIcon name="settings" size={16} />
          </button>
        </div>
      </header>

      <div className="body">
        <aside className="sidebar">
          <div className="sidebar-scene" aria-hidden="true" />
          <div className="sidebar-inner">
            {sidebar ?? (
              <>
                <div className="studio-card">
                  <div className="studio-icon">
                    <FbIcon name="brain" size={16} />
                  </div>
                  <div>
                    <div className="studio-title">{studio.title}</div>
                    <div className="studio-sub">{studio.sub}</div>
                  </div>
                </div>
                <nav className="side-nav" aria-label="Submenu">
                  {submenu.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`side-item${page === item.id ? " active" : ""}`}
                      onClick={() => onNavigate(item.id)}
                    >
                      <FbIcon name={item.icon} size={18} className="side-ico" />
                      <span className="side-copy">
                        <span className="side-label">{item.label}</span>
                        <span className="side-desc">{item.desc ?? item.id}</span>
                      </span>
                    </button>
                  ))}
                </nav>
                <div className="sidebar-motto">
                  Higher Intelligence
                  <br />
                  A Brighter Tomorrow
                </div>
              </>
            )}
          </div>
        </aside>

        <main className={`main ${mainClassName ?? ""}`.trim()} id="finalbeta-main">
          {body}
        </main>

        <aside className="inspector">
          <div className="inspector-inner">{inspector}</div>
        </aside>
      </div>

      {footer}

      <div className="fb-toast" style={{ opacity: toast ? 1 : 0 }} aria-live="polite">
        {toast ?? "Demoactie"}
      </div>
    </div>
  );
}
