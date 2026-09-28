import type { ResearchCommandSnapshot } from "../../../types/researchCommand";

export function FeedDrawer({
  open,
  snap,
  busy,
  notice,
  feedName,
  feedUrl,
  latency,
  license,
  onClose,
  onName,
  onUrl,
  onLatency,
  onLicense,
  onCreate,
  onPollAll,
  onPoll,
  onToggle,
  onDelete,
}: {
  open: boolean;
  snap: ResearchCommandSnapshot | null;
  busy: string | null;
  notice: string | null;
  feedName: string;
  feedUrl: string;
  latency: string;
  license: string;
  onClose: () => void;
  onName: (value: string) => void;
  onUrl: (value: string) => void;
  onLatency: (value: string) => void;
  onLicense: (value: string) => void;
  onCreate: () => void;
  onPollAll: () => void;
  onPoll: (feedId: string) => void;
  onToggle: (feedId: string, enabled: boolean) => void;
  onDelete: (feedId: string) => void;
}) {
  if (!open) return null;
  const feeds = snap?.feeds ?? [];
  return (
    <div className="lv-rc-drawer-back" role="presentation" onClick={onClose}>
      <aside className="lv-rc-drawer" role="dialog" aria-label="Feed management" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Feed management</h2>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <p className="lv-rc-muted">Causal boundary remains available_at. Polling does not grant execution authority.</p>
        <div className="lv-rc-form">
          <label>
            Name
            <input value={feedName} onChange={(e) => onName(e.target.value)} />
          </label>
          <label>
            URL (RSS/Atom/JSON)
            <input value={feedUrl} onChange={(e) => onUrl(e.target.value)} />
          </label>
          <label>
            Declared latency (s)
            <input value={latency} onChange={(e) => onLatency(e.target.value)} />
          </label>
          <label>
            License
            <select value={license} onChange={(e) => onLicense(e.target.value)}>
              <option value="UNKNOWN">UNKNOWN</option>
              <option value="DECLARED_FREE">DECLARED_FREE</option>
              <option value="DECLARED_RESTRICTED">DECLARED_RESTRICTED</option>
            </select>
          </label>
          <div className="lv-rc-inline">
            <button type="button" disabled={busy === "feed-create" || !feedName.trim() || !feedUrl.trim()} onClick={onCreate}>
              Add feed
            </button>
            <button type="button" disabled={busy === "poll-all"} onClick={onPollAll}>
              Poll all
            </button>
          </div>
        </div>
        {notice ? <p className="lv-rc-muted">Last poll: {notice}</p> : null}
        {feeds.length === 0 ? <p className="lv-rc-empty">No feeds registered.</p> : null}
        <ul className="lv-rc-feed">
          {feeds.map((feed) => (
            <li key={feed.feedId}>
              <strong>{feed.name}</strong> · {feed.kind} · {feed.enabled ? "on" : "off"} · {feed.licenseState} · last{" "}
              {feed.lastStatus ?? "—"}
              {feed.lastError ? ` (${feed.lastError})` : ""}
              <p className="lv-rc-muted">{feed.url}</p>
              <div className="lv-rc-inline">
                <button type="button" disabled={busy === `poll:${feed.feedId}`} onClick={() => onPoll(feed.feedId)}>
                  Poll
                </button>
                <button type="button" disabled={busy === `feed:${feed.feedId}`} onClick={() => onToggle(feed.feedId, feed.enabled)}>
                  {feed.enabled ? "Disable" : "Enable"}
                </button>
                <button type="button" disabled={busy === `feed-delete:${feed.feedId}`} onClick={() => onDelete(feed.feedId)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

export function EvidenceDrawer({
  open,
  snap,
  onClose,
}: {
  open: boolean;
  snap: ResearchCommandSnapshot | null;
  onClose: () => void;
}) {
  if (!open) return null;
  const decisions = snap?.decisions ?? [];
  return (
    <div className="lv-rc-drawer-back" role="presentation" onClick={onClose}>
      <aside className="lv-rc-drawer" role="dialog" aria-label="Evidence" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Evidence</h2>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <p className="lv-rc-muted">
          Append-only public decision chain, signals, and news already visible at as_of {snap?.truth.asOf || "UNMEASURED"}. Private
          chain-of-thought is not exposed.
        </p>
        <h3 className="lv-rc-subhead">Decisions ({decisions.length})</h3>
        {decisions.length === 0 ? <p className="lv-rc-empty">No decision records.</p> : null}
        <ul className="lv-rc-feed">
          {decisions.map((decision) => (
            <li key={decision.decisionId}>
              <time>{decision.asOf || decision.createdAt || "UNMEASURED"}</time> [{decision.stage}] {decision.role || "—"}
              <p>{JSON.stringify(decision.payload)}</p>
              <em className="lv-rc-muted">mandate {decision.mandateFingerprint || "—"}</em>
            </li>
          ))}
        </ul>
        <h3 className="lv-rc-subhead">Signals ({snap?.signals.length ?? 0})</h3>
        <ul className="lv-rc-feed">
          {(snap?.signals ?? []).map((signal) => (
            <li key={signal.signalId}>
              {signal.direction} · {signal.eventType} · as_of {signal.asOf}
              <p>{signal.rationale || "NOT AVAILABLE"}</p>
            </li>
          ))}
        </ul>
        <h3 className="lv-rc-subhead">Validation</h3>
        <p>
          {snap?.strategyEvolution.bound
            ? `${snap.strategyEvolution.name || snap.strategyEvolution.labId} · ${snap.strategyEvolution.status}`
            : "No lab evidence bound."}
        </p>
      </aside>
    </div>
  );
}

export function FlattenDialog({
  open,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!open) return null;
  return (
    <div className="lv-rc-drawer-back" role="presentation">
      <div className="lv-rc-confirm" role="dialog" aria-label="Flatten paper positions">
        <h2>Flatten all paper positions</h2>
        <p>
          This closes open positions on the bound PAPER portfolio only. It does not route to a live broker. Confirm to continue.
        </p>
        <div className="lv-rc-inline">
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="is-danger" disabled={busy} onClick={onConfirm}>
            Confirm PAPER flatten
          </button>
        </div>
      </div>
    </div>
  );
}
