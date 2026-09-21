"use client";

import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot, BrainCircuit, Boxes, Check, Circle, CircleUserRound, Clapperboard, FileText,
  Gauge, MessageSquare, PlugZap, Settings,
  Telescope, WalletCards, Waypoints, Workflow, Cable,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Toaster } from "@/components/ui/sonner";
import { ChatPage } from "@/components/hades/pages/chat-page";
import { AppSettings, GlobalSearchResult, hadesApi, SystemHealth } from "@/lib/hades-api";
import { useUiStyle } from "@/components/hades/ui-style";
import { HADES_SETTINGS_UPDATED_EVENT } from "@/components/hades/features/settings/settings-events";
import { RouteErrorBoundary } from "@/components/hades/route-error-boundary";
import { RouteLoadingSkeleton } from "@/components/hades/route-loading-skeleton";
import { LuxShell } from "@/components/hades/lux/lux-shell";
import { useHadesQuery } from "@/hooks/use-hades-query";
import { writePendingChatDraft } from "@/lib/chat-handoff";

const FinalBetaApp = lazy(() =>
  import("@/components/hades/finalbeta/finalbeta-app").then((module) => ({ default: module.FinalBetaApp })),
);

const TasksPage = lazy(() => import("@/components/hades/pages/tasks-page").then((module) => ({ default: module.TasksPage })));
const MissionControlPage = lazy(() => import("@/components/hades/pages/mission-control-page").then((module) => ({ default: module.MissionControlPage })));
const WorkflowsPage = lazy(() => import("@/components/hades/pages/workflows-page").then((module) => ({ default: module.WorkflowsPage })));
const AgentsPage = lazy(() => import("@/components/hades/pages/agents-page").then((module) => ({ default: module.AgentsPage })));
const CodingAgentPage = lazy(() => import("@/components/hades/pages/coding-agent-page").then((module) => ({ default: module.CodingAgentPage })));
const ResearchPage = lazy(() => import("@/components/hades/pages/research-page").then((module) => ({ default: module.ResearchPage })));
const TradingPage = lazy(() => import("@/components/hades/pages/trading-page").then((module) => ({ default: module.TradingPage })));
const MediaPage = lazy(() => import("@/components/hades/pages/media-page").then((module) => ({ default: module.MediaPage })));
const PluginsPage = lazy(() => import("@/components/hades/pages/plugins-page").then((module) => ({ default: module.PluginsPage })));
const McpPage = lazy(() => import("@/components/hades/pages/mcp-page").then((module) => ({ default: module.McpPage })));
const BrainPage = lazy(() => import("@/components/hades/pages/brain-page").then((module) => ({ default: module.BrainPage })));
const ModelsPage = lazy(() => import("@/components/hades/pages/models-page").then((module) => ({ default: module.ModelsPage })));
const MemoryPage = lazy(() => import("@/components/hades/pages/memory-page").then((module) => ({ default: module.MemoryPage })));
const FilesPage = lazy(() => import("@/components/hades/pages/files-page").then((module) => ({ default: module.FilesPage })));
const SettingsPage = lazy(() => import("@/components/hades/pages/settings-page").then((module) => ({ default: module.SettingsPage })));

export type PageId = "chat" | "tasks" | "mission-control" | "workflows" | "agents" | "coding-agent" | "research" | "trading" | "media" | "plugins" | "mcp" | "brain" | "models" | "memory" | "files" | "settings";

export type NavGroupId = "werk" | "kennis" | "systeem";

export type NavItem = { id: PageId; label: string; icon: typeof MessageSquare; ready: boolean; group: NavGroupId };

/** All product pages remain reachable — Lux Atelier IA. */
export const navigation: NavItem[] = [
  { id: "chat", label: "Chat", icon: MessageSquare, ready: true, group: "werk" },
  { id: "tasks", label: "Missies", icon: Waypoints, ready: true, group: "werk" },
  { id: "research", label: "Onderzoek", icon: Telescope, ready: true, group: "werk" },
  { id: "trading", label: "Trading", icon: WalletCards, ready: true, group: "werk" },
  { id: "coding-agent", label: "Coding Agent", icon: Bot, ready: true, group: "werk" },
  { id: "mission-control", label: "Mission Control", icon: Gauge, ready: true, group: "werk" },
  { id: "workflows", label: "Workflows", icon: Workflow, ready: true, group: "werk" },
  { id: "agents", label: "Agents", icon: CircleUserRound, ready: true, group: "werk" },
  { id: "media", label: "Media", icon: Clapperboard, ready: true, group: "werk" },
  { id: "files", label: "Bestanden", icon: FileText, ready: true, group: "kennis" },
  { id: "memory", label: "Geheugen", icon: Bot, ready: true, group: "kennis" },
  { id: "models", label: "Modellen", icon: Boxes, ready: true, group: "kennis" },
  { id: "brain", label: "Brain", icon: BrainCircuit, ready: true, group: "kennis" },
  { id: "plugins", label: "Plugins", icon: PlugZap, ready: true, group: "systeem" },
  { id: "mcp", label: "MCP", icon: Cable, ready: true, group: "systeem" },
  { id: "settings", label: "Instellingen", icon: Settings, ready: true, group: "systeem" },
];

const navGroups: Array<{ id: NavGroupId; label: string; collapsible?: boolean }> = [
  { id: "werk", label: "Werk" },
  { id: "kennis", label: "Kennis" },
  { id: "systeem", label: "Systeem" },
];

const ADVANCED_NAV_STORAGE_KEY = "hades-nav-werk-extra-open";

export const classicPages: Record<PageId, React.ComponentType> = {
  chat: ChatPage,
  tasks: TasksPage,
  "mission-control": MissionControlPage,
  workflows: WorkflowsPage,
  agents: AgentsPage,
  "coding-agent": CodingAgentPage,
  research: ResearchPage,
  trading: TradingPage,
  media: MediaPage,
  plugins: PluginsPage,
  mcp: McpPage,
  brain: BrainPage,
  models: ModelsPage,
  memory: MemoryPage,
  files: FilesPage,
  settings: SettingsPage,
};

export { RouteLoadingSkeleton } from "@/components/hades/route-loading-skeleton";

function readPageFromHash(): PageId {
  if (typeof window === "undefined") return "chat";
  const value = window.location.hash.replace("#/", "").split("?")[0] as PageId;
  return navigation.some((item) => item.id === value) ? value : "chat";
}

export { HadesOniMark } from "@/components/hades/hades-oni-mark";

export function HadesApp() {
  const { uiStyle } = useUiStyle();
  const [page, setPage] = useState<PageId>("chat");
  const healthQuery = useHadesQuery<SystemHealth>(
    "hades-system-health",
    (signal) => hadesApi.health(signal),
    { staleTime: 12_000, refetchInterval: 15_000, refetchOnVisibility: true },
  );
  const health = healthQuery.error ? null : healthQuery.data ?? null;
  const [globalQuery, setGlobalQuery] = useState("");
  const [searchResult, setSearchResult] = useState<GlobalSearchResult | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchIndex, setSearchIndex] = useState(0);
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [onboarding, setOnboarding] = useState<{
    completed: boolean;
    completed_at: string | null;
    steps: Array<{ id: string; title: string; done: boolean }>;
    active_model: string | null;
    suggested_first_prompt: string;
  } | null>(null);
  const [onboardingBusy, setOnboardingBusy] = useState(false);
  const [advancedNavOpen, setAdvancedNavOpen] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.localStorage.getItem(ADVANCED_NAV_STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const searchRef = useRef<HTMLInputElement>(null);
  const searchSeq = useRef(0);
  const onboardingDone = useRef(false);

  const toggleAdvancedNav = () => {
    setAdvancedNavOpen((open) => {
      const next = !open;
      try {
        window.localStorage.setItem(ADVANCED_NAV_STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };
  const ActivePage = classicPages[page];
  const routedPage = (
    <RouteErrorBoundary resetKey={page}>
      <Suspense fallback={<RouteLoadingSkeleton />}>
        <ActivePage />
      </Suspense>
    </RouteErrorBoundary>
  );

  useEffect(() => {
    const sync = () => setPage(readPageFromHash());
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  useEffect(() => {
    hadesApi.settings().then((data) => setAppSettings(data.values)).catch(() => undefined);
    const receiveSettings = (event: Event) => {
      const values = (event as CustomEvent<Partial<AppSettings>>).detail;
      if (!values) return;
      setAppSettings((prev) => (prev ? { ...prev, ...values } : (values as AppSettings)));
    };
    window.addEventListener(HADES_SETTINGS_UPDATED_EVENT, receiveSettings);
    hadesApi.onboarding()
      .then((data) => {
        setOnboarding(data);
        if (!data.completed) setOnboardingOpen(true);
      })
      .catch(() => undefined);
    return () => {
      window.removeEventListener(HADES_SETTINGS_UPDATED_EVENT, receiveSettings);
    };
  }, []);

  const finishOnboarding = async (step = "done") => {
    if (onboardingDone.current) {
      setOnboardingOpen(false);
      return;
    }
    onboardingDone.current = true;
    setOnboardingBusy(true);
    try {
      await hadesApi.completeOnboarding(step);
      setOnboarding((prev) => (prev ? { ...prev, completed: true } : prev));
      setOnboardingOpen(false);
    } catch {
      setOnboardingOpen(false);
    } finally {
      setOnboardingBusy(false);
    }
  };

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  useEffect(() => {
    const needle = globalQuery.trim();
    if (!needle) {
      setSearchResult(null);
      setSearchError(null);
      return;
    }
    const seq = ++searchSeq.current;
    const timer = window.setTimeout(() => {
      hadesApi.globalSearch(needle)
        .then((result) => {
          if (seq !== searchSeq.current) return;
          setSearchResult(result);
          setSearchError(null);
          setSearchOpen(true);
          setSearchIndex(0);
        })
        .catch((reason) => {
          if (seq !== searchSeq.current) return;
          setSearchError(reason instanceof Error ? reason.message : "Zoeken mislukt.");
        });
    }, 220);
    return () => window.clearTimeout(timer);
  }, [globalQuery]);

  const flatResults = useMemo(() => {
    const items: Array<{ key: string; title: string; snippet: string; href?: string; group: string; action?: "chat-draft" | "settings-tab"; settingsTab?: string }> = [];
    const rawNeedle = globalQuery.trim();
    const needle = rawNeedle.toLowerCase();

    const productActions: Array<{ key: string; title: string; snippet: string; href: string; match: RegExp }> = [
      { key: "action:new-chat", title: "Nieuw gesprek", snippet: "Start een nieuw Chat-gesprek", href: "#/chat?new=1", match: /nieuw|new\s*chat|gesprek/ },
      { key: "action:pin-folder", title: "Map vastzetten", snippet: "Pin een map in Chat", href: "#/chat?pin=folder", match: /pin|vastzet|map|folder/ },
      { key: "action:start-research", title: "Onderzoek starten", snippet: "Start onderzoek vanuit Chat", href: "#/chat?mode=research", match: /onderzoek|research/ },
      { key: "action:start-coding", title: "Coding starten", snippet: "Start een coding-job vanuit Chat", href: "#/chat?mode=code", match: /coding|code|bug|fix/ },
      { key: "action:settings", title: "Instellingen", snippet: "LM Studio, taal, netwerk, stem", href: "#/settings", match: /instelling|settings|config/ },
    ];
    if (!needle || needle.startsWith(">") || needle === "/") {
      for (const action of productActions) {
        items.push({ key: action.key, title: action.title, snippet: action.snippet, href: action.href, group: "actions" });
      }
    } else {
      for (const action of productActions) {
        if (action.match.test(needle) || action.title.toLowerCase().includes(needle)) {
          items.push({ key: action.key, title: action.title, snippet: action.snippet, href: action.href, group: "actions" });
        }
      }
    }

    const harvestMatch = /^\/harvest(?:\s+(.+))?$/i.exec(rawNeedle) || /^harvest(?:\s+(.+))?$/i.exec(rawNeedle);
    if (harvestMatch) {
      const urlPart = (harvestMatch[1] || "").trim();
      items.push({
        key: "action:harvest-research",
        title: "Site harvest in Onderzoek",
        snippet: urlPart || "Open harvest UI met URL-veld",
        href: "#/research",
        group: "harvest",
      });
      items.push({
        key: "action:harvest-chat",
        title: "Invoegen in chat",
        snippet: urlPart ? `/harvest ${urlPart}` : "/harvest <url>",
        group: "harvest",
        action: "chat-draft",
      });
    }
    if (needle.startsWith("/help") || needle === "help") {
      items.push({ key: "action:help-chat", title: "Chat /help", snippet: "Toon slash-commando's in Chat", href: "#/chat", group: "actions" });
    }
    if (needle.startsWith("/voice") || needle === "voice" || needle.includes("spraak")) {
      const transcript = rawNeedle.replace(/^\/voice\s*/i, "").trim();
      items.push({
        key: "action:voice-tasks",
        title: "Taken · Spraak → taak",
        snippet: "Plak/lokale STT — geen cloud-STT (Chat heeft aparte Spraak-modus)",
        href: "#/tasks?voice=1",
        group: "actions",
      });
      items.push({
        key: "action:voice-chat",
        title: "Chat /voice",
        snippet: transcript || "/voice <transcript>",
        group: "actions",
        action: "chat-draft",
      });
    }
    if (needle.startsWith("/remember") || needle === "remember" || needle.includes("geheugen")) {
      const text = rawNeedle.replace(/^\/remember\s*/i, "").trim();
      items.push({
        key: "action:remember-chat",
        title: "Chat /remember",
        snippet: text || "/remember <feit of voorkeur>",
        group: "actions",
        action: "chat-draft",
      });
    }
    if (needle.includes("coding agent") || needle.includes("code agent")) {
      items.push({ key: "page:coding-agent", title: "Coding", snippet: "FINALBETA Coding / lokale build-agent", href: "#/fb/coding", group: "advanced" });
    }
    if (needle.includes("mission") || needle.includes("eval lab") || needle.includes("flight recorder") || needle.includes("committee") || needle.includes("sandbox") || needle.includes("gen2")) {
      items.push({
        key: "page:mission-control-gen2",
        title: "Mission Control",
        snippet: "Advanced: missies, Eval Lab, Flight Recorder, sandbox, committee",
        href: "#/mission-control",
        group: "advanced",
      });
    }
    if (needle.includes("workflow") || needle.includes("dag") || needle.includes("skill candidate")) {
      items.push({
        key: "page:workflows-gen2",
        title: "Workflows",
        snippet: "Advanced workflows · layered DAG preview",
        href: "#/workflows",
        group: "advanced",
      });
    }
    if (needle.includes("practice") || needle.includes("scenario")) {
      items.push({ key: "page:agents-practice", title: "Practice playground", snippet: "Deterministische scenario's op Agents", href: "#/agents", group: "advanced" });
    }
    if (needle.includes("release") || needle.includes("confidence") || needle.includes("gates") || needle.includes("verify") || needle.includes("beveiliging") || needle.includes("security")) {
      items.push({
        key: "page:release-confidence",
        title: "Release confidence / Beveiliging",
        snippet: "Instellingen · Beveiliging · lokale release gates + capability clarity",
        href: "#/settings",
        group: "settings",
        action: "settings-tab",
        settingsTab: "Beveiliging",
      });
    }
    if (!searchResult && !items.length) return items;
    if (searchResult) {
      for (const cmd of searchResult.commands || []) {
        items.push({ key: `cmd:${cmd.id}`, title: cmd.title, snippet: "Opdracht", href: cmd.href, group: "commands" });
      }
      for (const [group, rows] of Object.entries(searchResult.groups || {})) {
        for (const row of rows) {
          items.push({ key: `${group}:${row.id}`, title: row.title, snippet: row.snippet, href: row.href, group });
        }
      }
    }
    const navHit = needle
      ? navigation.find((item) => item.label.toLowerCase().includes(needle) || item.id.includes(needle))
      : undefined;
    if (navHit && !items.some((item) => item.key === `page:${navHit.id}`)) {
      items.push({ key: `page:${navHit.id}`, title: navHit.label, snippet: navHit.group === "systeem" ? "Systeem" : navHit.group === "kennis" ? "Kennis" : "Werk", href: `#/${navHit.id}`, group: "pages" });
    }
    return items;
  }, [searchResult, globalQuery]);

  const navigate = (next: PageId) => {
    window.location.hash = `/${next}`;
    setPage(next);
    // All nav groups are always visible in Lux Atelier.
  };

  const openHref = (href?: string) => {
    if (!href) return;
    window.location.hash = href.replace(/^#/, "");
    setSearchOpen(false);
    setGlobalQuery("");
    setPage(readPageFromHash());
  };

  const openSearchResult = (item: { href?: string; action?: string; snippet?: string; title?: string; settingsTab?: string }) => {
    if (item.action === "chat-draft") {
      const draft = item.snippet?.startsWith("/") ? item.snippet : `/harvest ${item.snippet || ""}`.trim();
      writePendingChatDraft(draft);
      openHref("#/chat");
      return;
    }
    if (item.action === "settings-tab") {
      sessionStorage.setItem("hades-settings-tab", item.settingsTab || "Beveiliging");
      openHref(item.href || "#/settings");
      return;
    }
    openHref(item.href);
  };

  const runGlobalSearch = () => {
    const current = flatResults[searchIndex] || flatResults[0];
    if (current) openSearchResult(current);
  };

  return (
    <>
      {uiStyle === "finalbeta" ? (
        <>
          <Suspense fallback={<RouteLoadingSkeleton />}>
            <FinalBetaApp />
          </Suspense>
          <Toaster position="bottom-right" richColors closeButton />
        </>
      ) : (
        <>
      <a className="skip-link" href="#main-content">Ga naar hoofdinhoud</a>
      <LuxShell
        page={page}
        navigation={navigation}
        navGroups={navGroups}
        advancedOpen={advancedNavOpen}
        onToggleAdvanced={toggleAdvancedNav}
        navigate={navigate}
        health={health}
        settings={appSettings}
        globalQuery={globalQuery}
        onGlobalQueryChange={setGlobalQuery}
        onSearchFocus={() => setSearchOpen(true)}
        onSearchKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            runGlobalSearch();
          } else if (event.key === "ArrowDown") {
            event.preventDefault();
            setSearchIndex((index) => Math.min(index + 1, Math.max(flatResults.length - 1, 0)));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setSearchIndex((index) => Math.max(index - 1, 0));
          } else if (event.key === "Escape") {
            setSearchOpen(false);
          }
        }}
        searchRef={searchRef}
        searchResults={
          searchOpen && flatResults.length ? (
            <div className="global-search-results" role="listbox">
              {flatResults.slice(0, 24).map((item, index) => (
                <button key={item.key} type="button" className={index === searchIndex ? "active" : ""} onMouseEnter={() => setSearchIndex(index)} onClick={() => openSearchResult(item)}>
                  <strong>{item.title}</strong><small>{item.group} · {item.snippet}</small>
                </button>
              ))}
            </div>
          ) : searchOpen && searchError ? (
            <div className="global-search-results" role="status">
              <div className="global-search-hint"><small className="inline-error">{searchError}</small></div>
            </div>
          ) : searchOpen && globalQuery.trim() && /^(\/harvest|harvest\b)/i.test(globalQuery.trim()) ? (
            <div className="global-search-results" role="listbox">
              <div className="global-search-hint">
                <small>Harvest — kies een actie of typ een URL na <code>/harvest</code></small>
              </div>
            </div>
          ) : null
        }
      >
        <div className="page-viewport">{routedPage}</div>
      </LuxShell>
      <Dialog open={onboardingOpen} onOpenChange={(open) => { if (!open) void finishOnboarding("skip"); else setOnboardingOpen(true); }}>
        <DialogContent className="onboarding-dialog" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Welkom bij HADES</DialogTitle>
            <DialogDescription>Lokale AI-workspace — drie stappen om te starten.</DialogDescription>
          </DialogHeader>
          <ol className="onboarding-steps">
            {(onboarding?.steps || [
              { id: "chat", title: "Chat is HADES — praat met je lokale model", done: false },
              { id: "pins", title: "@ en pins brengen projectkennis/context", done: false },
              { id: "atelier", title: "Werk / Kennis / Systeem — alle consoles blijven bereikbaar", done: false },
            ]).map((step) => (
              <li key={step.id} className={step.done ? "done" : ""}>
                <span className="onboarding-step-icon" aria-hidden="true">
                  {step.done ? <Check /> : <Circle />}
                </span>
                <span>{step.title}</span>
              </li>
            ))}
          </ol>
          <div className="onboarding-links">
            <Button variant="outline" size="sm" onClick={() => { void finishOnboarding("done").then(() => navigate("chat")); }}>Naar Chat</Button>
            <Button variant="outline" size="sm" onClick={() => navigate("models")}>Modellen</Button>
            <Button variant="outline" size="sm" onClick={() => navigate("settings")}>Instellingen</Button>
          </div>
          {onboarding?.suggested_first_prompt ? (
            <p className="onboarding-hint">
              Probeer als eerste: <code>{onboarding.suggested_first_prompt}</code>
            </p>
          ) : null}
          <DialogFooter>
            <Button variant="outline" disabled={onboardingBusy} onClick={() => void finishOnboarding("skip")}>Overslaan</Button>
            <Button disabled={onboardingBusy} onClick={() => void finishOnboarding("done")}>Voltooien</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Toaster position="bottom-right" richColors closeButton />
        </>
      )}
    </>
  );
}

