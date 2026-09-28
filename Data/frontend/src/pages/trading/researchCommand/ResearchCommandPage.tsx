import { AppShell } from "../../../layouts/AppShell";
import "../../../styles/trading-research-command.css";
import { EvidenceDrawer, FeedDrawer, FlattenDialog } from "./ResearchCommandDrawers";
import {
  EvolutionCard,
  GuardrailsCard,
  IntentCard,
  PortfolioCard,
  PositionsCard,
  SessionCard,
  StreamCard,
  TeamCard,
  ThesisCard,
  WatchCard,
} from "./ResearchCommandPanels";
import { useResearchCommand } from "./useResearchCommand";

export function ResearchCommandPage() {
  const model = useResearchCommand();
  const snap = model.snapshot;
  const actions = snap?.actions;

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <main className="lv-main lv-tp-main lv-rc-page">
        <header className="lv-rc-banner">
          <div className="lv-rc-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="22" height="22">
              <path d="M16 3 L19 12 L28 12 L21 18 L24 28 L16 22 L8 28 L11 18 L4 12 L13 12 Z" fill="none" stroke="currentColor" strokeWidth="1.2" />
            </svg>
          </div>
          <div>
            <p className="lv-rc-kicker">Trading Center</p>
            <h1>Research Command</h1>
          </div>
          <p className="lv-rc-banner-note">
            Public rationale only · paper execution · live trading {snap?.truth.liveTrading ?? "BLOCKED"}
          </p>
        </header>

        {model.loading && !snap ? <p className="lv-rc-muted">Loading research command…</p> : null}
        {model.error ? (
          <div className="lv-rc-banner-error" role="alert">
            <span>{model.error}</span>
            <button type="button" onClick={() => void model.refresh()}>
              Retry
            </button>
          </div>
        ) : null}
        {model.notice ? <p className="lv-rc-muted">{model.notice}</p> : null}

        <div className="lv-rc-grid">
          <SessionCard
            snap={snap}
            orchestraId={model.orchestraId}
            portfolioId={model.portfolioId}
            labId={model.labId}
            missionKind={model.missionKind}
            missionAsOf={model.missionAsOf}
            createName={model.createName}
            createUniverse={model.createUniverse}
            createCapital={model.createCapital}
            busy={model.busy}
            onOrchestra={model.setOrchestraId}
            onPortfolio={model.setPortfolioId}
            onLab={model.setLabId}
            onMissionKind={model.setMissionKind}
            onMissionAsOf={model.setMissionAsOf}
            onCreateName={model.setCreateName}
            onCreateUniverse={model.setCreateUniverse}
            onCreateCapital={model.setCreateCapital}
            onCreate={() => void model.createOrchestra()}
            onLaunch={() => void model.launchMission()}
          />
          <TeamCard snap={snap} onOpenAgent={model.openAgent} />
          <PortfolioCard snap={snap} portfolioId={model.portfolioId} onPortfolio={model.setPortfolioId} />
          <WatchCard
            snap={snap}
            tab={model.watchTab}
            asOf={model.asOf}
            watchSymbol={model.watchSymbol}
            watchReason={model.watchReason}
            busy={model.busy}
            onTab={model.setWatchTab}
            onAsOf={model.setAsOf}
            onSymbol={model.setWatchSymbol}
            onReason={model.setWatchReason}
            onAddWatch={() => void model.addWatch()}
            onManageFeeds={() => model.setFeedOpen(true)}
          />
          <StreamCard snap={snap} />
          <div className="lv-rc-side">
            <ThesisCard snap={snap} />
            <IntentCard snap={snap} />
          </div>
          <PositionsCard snap={snap} tab={model.positionTab} onTab={model.setPositionTab} />
          <EvolutionCard snap={snap} busy={model.busy} onEvolve={() => void model.evolve()} />
          <GuardrailsCard snap={snap} busy={model.busy} onKill={() => void model.armKillSwitch()} />
        </div>

        <footer className="lv-rc-actions">
          <button
            type="button"
            className="is-gold"
            disabled={!actions?.start.enabled || model.busy === "start"}
            title={actions?.start.reason || ""}
            onClick={() => void model.startSession()}
          >
            Start Session
          </button>
          <button
            type="button"
            disabled={!actions?.pause.enabled || model.busy === "pause"}
            title={actions?.pause.reason || ""}
            onClick={() => void model.pauseSession()}
          >
            Pause
          </button>
          <button
            type="button"
            className="is-danger"
            disabled={!actions?.flatten.enabled}
            title={actions?.flatten.reason || ""}
            onClick={() => model.setFlattenOpen(true)}
          >
            Flatten All <em>PAPER</em>
          </button>
          <button
            type="button"
            disabled={!actions?.reviewEvidence.enabled}
            title={actions?.reviewEvidence.reason || ""}
            onClick={() => model.setEvidenceOpen(true)}
          >
            Review Evidence
          </button>
          <button type="button" className="is-paper" onClick={model.openPaper}>
            Open Paper Mode
          </button>
        </footer>

        <FeedDrawer
          open={model.feedOpen}
          snap={snap}
          busy={model.busy}
          notice={model.notice}
          feedName={model.feedName}
          feedUrl={model.feedUrl}
          latency={model.latency}
          license={model.license}
          onClose={() => model.setFeedOpen(false)}
          onName={model.setFeedName}
          onUrl={model.setFeedUrl}
          onLatency={model.setLatency}
          onLicense={model.setLicense}
          onCreate={() => void model.addFeed()}
          onPollAll={() => void model.pollFeeds()}
          onPoll={(feedId) => void model.pollFeeds(feedId)}
          onToggle={(feedId, enabled) => void model.toggleFeed(feedId, enabled)}
          onDelete={(feedId) => void model.removeFeed(feedId)}
        />
        <EvidenceDrawer open={model.evidenceOpen} snap={snap} onClose={() => model.setEvidenceOpen(false)} />
        <FlattenDialog
          open={model.flattenOpen}
          busy={model.busy === "flatten"}
          onCancel={() => model.setFlattenOpen(false)}
          onConfirm={() => void model.confirmFlatten()}
        />
      </main>
    </AppShell>
  );
}
