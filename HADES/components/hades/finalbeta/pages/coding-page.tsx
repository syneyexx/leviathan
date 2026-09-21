"use client";

import { useEffect, useState, type ReactNode } from "react";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";
import { useCodingLive } from "../hooks/use-coding-live";
import { buildStatusLabel, loopPhaseLabel } from "@/components/hades/features/coding/coding-runtime-core";
import {
  CodingTabAgents,
  CodingTabBestanden,
  CodingTabBranches,
  CodingTabBuild,
  CodingTabDeploy,
  CodingTabOverzicht,
  CodingTabPullRequests,
  CodingTabSettings,
  CodingTabWijzigingen,
} from "./coding";
import { CodingNewTaskDialog } from "./coding/dialogs/new-task-dialog";

type Props = { onNavigate: FinalBetaNavigate };

const TABS = [
  "Overzicht",
  "Bestanden",
  "Wijzigingen",
  "Branches",
  "Pull requests",
  "Agents",
  "Build & testen",
  "Deploy",
  "Instellingen",
] as const;

type CodingTab = (typeof TABS)[number];

const TAB_ICONS: Record<CodingTab, string> = {
  Overzicht: "grid",
  Bestanden: "folder",
  Wijzigingen: "code",
  Branches: "line",
  "Pull requests": "link",
  Agents: "users",
  "Build & testen": "flask",
  Deploy: "upload",
  Instellingen: "settings",
};

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function readTabFromHash(): CodingTab {
  try {
    const raw = window.location.hash.includes("?")
      ? window.location.hash.slice(window.location.hash.indexOf("?") + 1)
      : "";
    const tab = new URLSearchParams(raw).get("tab");
    if (tab && (TABS as readonly string[]).includes(tab)) return tab as CodingTab;
  } catch {
    /* ignore */
  }
  return "Overzicht";
}

export function CodingPage({ onNavigate }: Props) {
  const coding = useCodingLive();
  const [now, setNow] = useState(() => new Date());
  const [tab, setTab] = useState<CodingTab>(() =>
    typeof window !== "undefined" ? readTabFromHash() : "Overzicht",
  );
  const [selectedFile, setSelectedFile] = useState(0);
  const [diffTab, setDiffTab] = useState<"Diff" | "Code" | "Voorstel" | "AI Uitleg">("Diff");

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const repo = coding.sourceRepo;
    if (repo) coding.setSymbolsPath((current) => current || repo);
  }, [coding.sourceRepo, coding.setSymbolsPath]);

  const selectTab = (next: CodingTab) => {
    setTab(next);
    try {
      const hash = window.location.hash || "#/fb/coding";
      const path = hash.replace(/^#/, "").split("?")[0];
      const params = new URLSearchParams(hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "");
      params.set("tab", next);
      const job = coding.activeJobId;
      if (job) params.set("codingJob", job);
      window.history.replaceState({}, "", `${window.location.pathname}${window.location.search}#${path}?${params}`);
    } catch {
      /* ignore */
    }
  };

  const fullBleed = tab !== "Overzicht";

  let panel: ReactNode = null;
  if (tab === "Overzicht") {
    panel = (
      <CodingTabOverzicht
        coding={coding}
        selectedFile={selectedFile}
        setSelectedFile={setSelectedFile}
        diffTab={diffTab}
        setDiffTab={setDiffTab}
        onOpenTab={selectTab}
      />
    );
  } else if (tab === "Bestanden") {
    panel = <CodingTabBestanden coding={coding} />;
  } else if (tab === "Wijzigingen") {
    panel = (
      <CodingTabWijzigingen
        coding={coding}
        selectedFile={selectedFile}
        setSelectedFile={setSelectedFile}
        diffTab={diffTab}
        setDiffTab={setDiffTab}
      />
    );
  } else if (tab === "Branches") {
    panel = <CodingTabBranches coding={coding} />;
  } else if (tab === "Pull requests") {
    panel = <CodingTabPullRequests />;
  } else if (tab === "Agents") {
    panel = <CodingTabAgents coding={coding} />;
  } else if (tab === "Build & testen") {
    panel = <CodingTabBuild coding={coding} />;
  } else if (tab === "Deploy") {
    panel = <CodingTabDeploy coding={coding} />;
  } else {
    panel = <CodingTabSettings coding={coding} />;
  }

  const body = (
    <div className="coding-page">
      <div className="coding-welcome coding-welcome-v2">
        <div className="coding-welcome-copy">
          <h1>Ontwikkel. Bouw. Automatiseer.</h1>
        </div>
        <div className="coding-welcome-mid">“Good code turns ideas into reality.”</div>
        <div className="coding-welcome-right">
          <div className="coding-clock">
            <div className="coding-clock-copy">
              <strong>
                {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]}
              </strong>
              <span>
                {pad(now.getHours())}:{pad(now.getMinutes())}
              </span>
            </div>
            <FbIcon name="bolt" size={22} className="coding-sun" />
          </div>
          <div className="coding-welcome-end">“Build today. A smarter tomorrow.”</div>
        </div>
      </div>

      {coding.connectionLost ? (
        <div className="coding-banner warn" role="status">
          Connection lost — reconnecting…
        </div>
      ) : null}
      {coding.metaError ? (
        <div className="coding-banner danger" role="alert">
          {coding.metaError}
        </div>
      ) : null}

      <div className="coding-tabbar">
        <nav className="coding-tabs" aria-label="Coding tabs">
          {TABS.map((item) => (
            <button
              key={item}
              type="button"
              className={`coding-tab${tab === item ? " active" : ""}`}
              onClick={() => selectTab(item)}
            >
              <FbIcon name={TAB_ICONS[item]} size={13} />
              {item}
            </button>
          ))}
        </nav>
        <div className="coding-tabbar-actions">
          <button type="button" className="btn btn-outline" onClick={() => void coding.openInEditor()}>
            <FbIcon name="external" size={13} />
            Open in editor
          </button>
          {tab === "Instellingen" ? (
            <button
              type="button"
              className="btn btn-gold"
              disabled={coding.controlSaving}
              onClick={() =>
                void coding.saveControlPatch({
                  "coding.autonomy.profile": coding.autonomyProfile,
                  "coding.omniroute.enabled_by_default": coding.useOmniroute,
                })
              }
            >
              <FbIcon name="save" size={13} />
              Opslaan
            </button>
          ) : tab === "Branches" ? (
            <button type="button" className="btn btn-outline" disabled title="Branch create niet beschikbaar in HADES API">
              <FbIcon name="plus" size={13} />
              Nieuwe branch
            </button>
          ) : tab === "Pull requests" ? (
            <button type="button" className="btn btn-outline" disabled title="Geen GitHub PR-integratie">
              <FbIcon name="plus" size={13} />
              Nieuwe PR
            </button>
          ) : tab === "Deploy" ? (
            <button type="button" className="btn btn-outline" disabled title="Geen remote deploy-targets">
              <FbIcon name="plus" size={13} />
              Nieuwe deploy
            </button>
          ) : tab === "Build & testen" ? (
            <button type="button" className="btn btn-gold" onClick={() => coding.setNewTaskOpen(true)}>
              <FbIcon name="plus" size={13} />
              Nieuwe run
            </button>
          ) : (
            <button type="button" className="btn btn-gold" onClick={() => coding.startNewRun()}>
              <FbIcon name="plus" size={13} />
              Nieuwe taak
            </button>
          )}
        </div>
      </div>

      {panel}

      <CodingNewTaskDialog coding={coding} open={coding.newTaskOpen} onClose={() => coding.setNewTaskOpen(false)} />
    </div>
  );

  const jobStatus = String(coding.jobSnapshot?.status || coding.selectedRun?.status || "idle");
  const dirtyCount = Array.isArray(coding.gitStatus?.dirty) ? coding.gitStatus.dirty.length : Number(coding.gitStatus?.dirty_count || 0);

  const inspector =
    tab === "Overzicht" ? (
      <>
        <p className="quote coding-inspector-quote">
          “Good code turns ideas into reality.
          <br />
          Build today. A smarter tomorrow.”
        </p>

        <section className="insp-section">
          <h3 className="insp-title">Repository</h3>
          <div className="insp-card">
            <div className="detail-row">
              <span className="k">Workspace</span>
              <span className="v">{coding.workspacePath || "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Branch</span>
              <span className="v">{String(coding.gitStatus?.branch || "—")}</span>
            </div>
            <div className="detail-row">
              <span className="k">Dirty</span>
              <span className="v">{coding.gitStatus ? String(dirtyCount) : "—"}</span>
            </div>
          </div>
        </section>

        <section className="insp-section">
          <h3 className="insp-title">Coding job</h3>
          <div className="insp-card">
            <div className="detail-row">
              <span className="k">Job</span>
              <span className="v">{coding.activeJobId || "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Status</span>
              <span className="v">{buildStatusLabel(jobStatus)}</span>
            </div>
            <div className="detail-row">
              <span className="k">Fase</span>
              <span className="v">{loopPhaseLabel(coding.jobPhase)}</span>
            </div>
            <div className="detail-row">
              <span className="k">Strategy</span>
              <span className="v">{coding.codingStrategy}</span>
            </div>
            <div className="detail-row">
              <span className="k">Autonomy</span>
              <span className="v">{coding.autonomyProfile}</span>
            </div>
          </div>
        </section>

        <section className="insp-section">
          <h3 className="insp-title">Model</h3>
          <div className="insp-card">
            <div className="detail-row">
              <span className="k">Model</span>
              <span className="v">{coding.activeModel || "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">LM Studio</span>
              <span className="v">{coding.lmConnected ? "connected" : "offline"}</span>
            </div>
            <div className="detail-row">
              <span className="k">OmniRoute</span>
              <span className="v">{coding.omnirouteLabel}</span>
            </div>
          </div>
        </section>

        <section className="insp-section">
          <h3 className="insp-title">Verification</h3>
          <div className="insp-card">
            <div className="detail-row">
              <span className="k">Job status</span>
              <span className="v">{buildStatusLabel(jobStatus)}</span>
            </div>
            <div className="detail-row">
              <span className="k">Frontier</span>
              <span className="v">{coding.frontierStatus ? buildStatusLabel(coding.frontierStatus) : "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Conflicts</span>
              <span className="v">{coding.conflicts ? String(coding.conflicts.length) : "—"}</span>
            </div>
          </div>
        </section>

        <section className="insp-section">
          <h3 className="insp-title">Activity</h3>
          <div className="insp-card coding-activity">
            {coding.jobEvents.length === 0 ? (
              <div className="detail-row">
                <span className="k">Events</span>
                <span className="v">geen</span>
              </div>
            ) : (
              coding.jobEvents
                .slice(-6)
                .reverse()
                .map((ev, index) => (
                  <div className="detail-row" key={String(ev.id || ev.seq || index)}>
                    <span className="k">{String(ev.event || ev.type || ev.phase || "event")}</span>
                    <span className="v">{String(ev.message || ev.detail || "").slice(0, 40) || "—"}</span>
                  </div>
                ))
            )}
          </div>
        </section>
      </>
    ) : (
      <div className="coding-insp-placeholder" aria-hidden="true" />
    );

  const footer = (
    <footer className="dash-footer coding-footer">
      <span>{coding.workspacePath || "Geen workspace"}</span>
      <span>{coding.activeJobId ? `job ${coding.activeJobId.slice(0, 8)}…` : "geen actieve job"}</span>
      <span>{buildStatusLabel(jobStatus)}</span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="coding"
      onNavigate={onNavigate}
      body={body}
      inspector={inspector}
      footer={footer}
      appClassName={`coding-app${fullBleed ? " coding-full" : ""}`}
      mainClassName="coding-main"
    />
  );
}
