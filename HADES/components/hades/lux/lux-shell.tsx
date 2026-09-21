"use client";

import { useEffect, useRef, useState, type KeyboardEventHandler, type ReactNode, type RefObject } from "react";
import {
  Activity,
  Boxes,
  BrainCircuit,
  Cable,
  ChevronDown,
  CircleUserRound,
  Clapperboard,
  FileText,
  Gauge,
  Menu,
  MessageSquare,
  Bot,
  PlugZap,
  Search,
  Settings,
  ShieldCheck,
  Telescope,
  WalletCards,
  Waypoints,
  Workflow,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { NavGroupId, PageId } from "@/components/hades/hades-app";
import { AppSettings, SystemHealth } from "@/lib/hades-api";
import { StatusBadge, checkStatusTone, overallHealthLabel, overallHealthTone } from "@/components/hades/ui";
import { reasoningModeLabel } from "@/lib/reasoning-mode";
import { Button } from "@/components/ui/button";
import "@/components/hades/styles/lux/index.css";

export type LuxNavigationItem = {
  id: PageId;
  label: string;
  icon: LucideIcon;
  group: NavGroupId;
};

type LuxShellProps = {
  page: PageId;
  navigation: LuxNavigationItem[];
  navGroups: Array<{ id: NavGroupId; label: string; collapsible?: boolean }>;
  advancedOpen?: boolean;
  onToggleAdvanced?: () => void;
  navigate: (page: PageId) => void;
  health: SystemHealth | null;
  settings: AppSettings | null;
  globalQuery: string;
  onGlobalQueryChange: (value: string) => void;
  onSearchFocus: () => void;
  onSearchKeyDown: KeyboardEventHandler<HTMLInputElement>;
  searchRef: RefObject<HTMLInputElement | null>;
  searchResults?: ReactNode;
  children: ReactNode;
};

const PAGE_CRUMB: Record<PageId, string> = {
  chat: "Chat",
  tasks: "Missies",
  "mission-control": "Mission Control",
  workflows: "Workflows",
  agents: "Agents",
  "coding-agent": "Coding Agent",
  research: "Onderzoek",
  trading: "Trading",
  media: "Media",
  plugins: "Plugins",
  mcp: "MCP",
  brain: "Brain",
  models: "Modellen",
  memory: "Geheugen",
  files: "Bestanden",
  settings: "Instellingen",
};

function LuxMark() {
  return (
    <svg className="lux-mark" viewBox="0 0 48 48" aria-hidden="true">
      <defs>
        <linearGradient id="lux-h-gold" x1="8" y1="6" x2="40" y2="42" gradientUnits="userSpaceOnUse">
          <stop stopColor="#e2c98a" />
          <stop offset="0.5" stopColor="#b8955a" />
          <stop offset="1" stopColor="#8a6a32" />
        </linearGradient>
      </defs>
      <polygon
        points="24,3 43,14 43,34 24,45 5,34 5,14"
        fill="#121316"
        stroke="url(#lux-h-gold)"
        strokeWidth="1.5"
      />
      <path d="M16 15v18M32 15v18M16 24h16" fill="none" stroke="url(#lux-h-gold)" strokeWidth="2.8" strokeLinecap="round" />
    </svg>
  );
}

function LuxNav({
  page,
  navigation,
  navGroups,
  advancedOpen,
  onToggleAdvanced,
  navigate,
  onNavigate,
}: {
  page: PageId;
  navigation: LuxNavigationItem[];
  navGroups: Array<{ id: NavGroupId; label: string; collapsible?: boolean }>;
  advancedOpen: boolean;
  onToggleAdvanced?: () => void;
  navigate: (page: PageId) => void;
  onNavigate?: () => void;
}) {
  return (
    <nav className="lux-nav" aria-label="HADES-navigatie">
      {navGroups.map((group) => {
        const groupItems = navigation.filter((item) => item.group === group.id);
        const isAdvanced = Boolean(group.collapsible);
        const expanded = !isAdvanced || advancedOpen;
        return (
          <div key={group.id}>
            {group.collapsible ? (
              <button type="button" className="lux-nav-label" aria-expanded={expanded} onClick={onToggleAdvanced}>
                {group.label}
                <ChevronDown size={11} style={{ marginLeft: 6, opacity: expanded ? 1 : 0.55, transform: expanded ? undefined : "rotate(-90deg)" }} aria-hidden="true" />
              </button>
            ) : (
              <div className="lux-nav-label">{group.label}</div>
            )}
            {expanded
              ? groupItems.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    className="lux-nav-item"
                    data-active={page === id}
                    aria-current={page === id ? "page" : undefined}
                    onClick={() => {
                      navigate(id);
                      onNavigate?.();
                    }}
                  >
                    <Icon aria-hidden="true" />
                    <span>{label}</span>
                  </button>
                ))
              : null}
          </div>
        );
      })}
    </nav>
  );
}

export function LuxShell({
  page,
  navigation,
  navGroups,
  advancedOpen = true,
  onToggleAdvanced,
  navigate,
  health,
  settings,
  globalQuery,
  onGlobalQueryChange,
  onSearchFocus,
  onSearchKeyDown,
  searchRef,
  searchResults,
  children,
}: LuxShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [healthOpen, setHealthOpen] = useState(false);
  const healthWrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!healthOpen) return;
    // Defer outside-click so the opening click cannot immediately dismiss the panel.
    let active = true;
    const timer = window.setTimeout(() => {
      if (!active) return;
      const onPointerDown = (event: MouseEvent) => {
        if (!healthWrapRef.current?.contains(event.target as Node)) {
          setHealthOpen(false);
        }
      };
      const onKeyDown = (event: KeyboardEvent) => {
        if (event.key === "Escape") setHealthOpen(false);
      };
      document.addEventListener("mousedown", onPointerDown);
      document.addEventListener("keydown", onKeyDown);
      cleanup = () => {
        document.removeEventListener("mousedown", onPointerDown);
        document.removeEventListener("keydown", onKeyDown);
      };
    }, 0);
    let cleanup: (() => void) | undefined;
    return () => {
      active = false;
      window.clearTimeout(timer);
      cleanup?.();
    };
  }, [healthOpen]);

  const tone = health ? overallHealthTone(health) : "danger";
  const healthLabel = health ? overallHealthLabel(health) : "Backend offline";
  const modelLabel = health?.active_model || (health?.lm_studio === "connected" ? "dynamic" : "LM Studio offline");
  const networkLabel = settings?.network_policy === "allow" ? "Local core · web toegestaan" : "Local core";

  return (
    <div className="lux-shell" data-lux-page={page} data-mobile-nav={mobileNavOpen ? "open" : "closed"}>
      <aside className="lux-sidebar">
        <button className="lux-brand" type="button" onClick={() => navigate("chat")} aria-label="Naar Chat">
          <LuxMark />
          <span className="lux-brand-copy">
            <strong>HADES</strong>
            <small>Atelier</small>
          </span>
        </button>

        <LuxNav
          page={page}
          navigation={navigation}
          navGroups={navGroups}
          advancedOpen={advancedOpen}
          onToggleAdvanced={onToggleAdvanced}
          navigate={navigate}
        />

        <div className="lux-sidebar-foot">
          <i aria-hidden="true" />
          <span>Offline-first</span>
        </div>
      </aside>

      {mobileNavOpen ? (
        <div className="lux-mobile-nav" role="dialog" aria-label="Navigatie">
          <div className="lux-mobile-nav-card">
            <div className="lux-mobile-nav-head">
              <strong>Navigatie</strong>
              <button type="button" className="lux-model-chip" aria-label="Sluit navigatie" onClick={() => setMobileNavOpen(false)}>
                <X size={14} />
              </button>
            </div>
            <LuxNav
              page={page}
              navigation={navigation}
              navGroups={navGroups}
              advancedOpen={advancedOpen}
              onToggleAdvanced={onToggleAdvanced}
              navigate={navigate}
              onNavigate={() => setMobileNavOpen(false)}
            />
          </div>
        </div>
      ) : null}

      <div className="lux-main">
        <header className="lux-topbar">
          <button
            type="button"
            className="lux-mobile-trigger lux-model-chip"
            aria-label="Menu openen"
            onClick={() => setMobileNavOpen(true)}
          >
            <Menu size={14} />
          </button>

          <button className="lux-workspace-chip" type="button" onClick={() => navigate("settings")} aria-label="Workspace">
            <CircleUserRound size={14} aria-hidden="true" />
            <span>
              <small>Workspace</small>
              <strong>Privé</strong>
            </span>
          </button>

          <div className="lux-crumb" aria-label="Locatie">
            <span>HADES</span>
            <b>/ {PAGE_CRUMB[page]}</b>
          </div>

          <div className="lux-search">
            <Search aria-hidden="true" />
            <input
              ref={searchRef}
              value={globalQuery}
              onChange={(event) => onGlobalQueryChange(event.target.value)}
              onFocus={onSearchFocus}
              onKeyDown={onSearchKeyDown}
              placeholder="Zoeken…"
              aria-label="Zoeken in HADES (Ctrl+K)"
            />
            <kbd>Ctrl K</kbd>
            {searchResults}
          </div>

          <button className="lux-model-chip" type="button" onClick={() => navigate("models")}>
            <Boxes size={14} aria-hidden="true" />
            <span>LM Studio · {reasoningModeLabel(settings?.reasoning_profile)}</span>
            <strong style={{ fontWeight: 500, maxWidth: "10rem", overflow: "hidden", textOverflow: "ellipsis" }}>{modelLabel}</strong>
            <ChevronDown size={13} aria-hidden="true" />
          </button>

          <span className="lux-network-chip" title={networkLabel}>
            <ShieldCheck size={13} aria-hidden="true" />
            <span>{networkLabel}</span>
          </span>

          <div className="lux-health-wrap" ref={healthWrapRef}>
            <button
              type="button"
              className="lux-health-chip"
              data-tone={tone}
              aria-label="Systeemgezondheid"
              aria-expanded={healthOpen}
              aria-controls="lux-health-panel"
              aria-live="polite"
              onClick={() => setHealthOpen((open) => !open)}
            >
              <i aria-hidden="true" />
              {health?.lm_studio === "connected" ? "Lokaal online" : healthLabel}
              <Activity size={13} aria-hidden="true" />
            </button>
            {healthOpen ? (
              <div className="health-popover lux-health-panel" id="lux-health-panel" role="dialog" aria-label="Systeemgezondheid">
                <div className="health-popover-head">
                  <strong>Systeemgezondheid</strong>
                  <StatusBadge tone={tone}>{healthLabel}</StatusBadge>
                </div>
                {health?.checks?.length ? (
                  <ul className="health-check-list">
                    {health.checks.map((check) => (
                      <li key={check.id}>
                        <StatusBadge tone={checkStatusTone(check.status)}>{check.status}</StatusBadge>
                        <div>
                          <strong>{check.label}</strong>
                          {check.detail ? <small>{check.detail}</small> : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="panel-copy" style={{ margin: "0.55rem 0" }}>
                    {health
                      ? (health.detail || "Geen gedetailleerde checks van de backend.")
                      : "Backend niet bereikbaar — start START_HADES.bat voor live health-checks."}
                  </p>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-2 w-full"
                  onClick={() => {
                    setHealthOpen(false);
                    navigate("chat");
                  }}
                >
                  Open Chat-diagnose
                </Button>
              </div>
            ) : null}
          </div>

          <button className="lux-model-chip" type="button" onClick={() => navigate("settings")} aria-label="Instellingen">
            <Settings size={14} />
          </button>
        </header>

        <div className="lux-content" id="main-content" tabIndex={-1}>
          {children}
        </div>
      </div>
    </div>
  );
}

/** Icons kept exported for tests / callers that mirror nav. */
export const luxNavIcons = {
  MessageSquare,
  Telescope,
  FileText,
  Bot,
  Boxes,
  Settings,
  Waypoints,
  Gauge,
  Workflow,
  CircleUserRound,
  Clapperboard,
  PlugZap,
  Cable,
  BrainCircuit,
  WalletCards,
};
