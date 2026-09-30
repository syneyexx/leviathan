import { useMemo, useState } from "react";
import type {
  ActivityDisplayMode,
  ActivityEvent,
  ActivityProjection,
  DecisionReceipt,
} from "../../types/activity";
import {
  compactHeadline,
  formatActivityDurationMs,
  formatDurationLabel,
  formatMeasuredProgress,
  formatResultCount,
  lifecycleStatusLabel,
} from "../../lib/activityProjector";
import { StatusDot } from "../ui/StatusDot";

export type ActivityTimelineProps = {
  projection: ActivityProjection | null;
  mode?: ActivityDisplayMode;
  streaming?: boolean;
  emptyLabel?: string;
  onModeChange?: (mode: ActivityDisplayMode) => void;
  decisionReceipts?: DecisionReceipt[];
};

function toneForLifecycle(lifecycle: string): "success" | "info" | "warning" | "danger" | "muted" {
  switch (lifecycle) {
    case "completed":
      return "success";
    case "running":
    case "starting":
      return "info";
    case "waiting":
    case "retrying":
    case "degraded":
    case "queued":
      return "warning";
    case "failed":
    case "cancelled":
      return "danger";
    default:
      return "muted";
  }
}

function glyphForLifecycle(lifecycle: string): string {
  switch (lifecycle) {
    case "completed":
      return "✓";
    case "running":
    case "starting":
      return "◉";
    case "failed":
      return "✕";
    case "cancelled":
      return "⊘";
    case "skipped":
      return "–";
    case "queued":
    case "waiting":
      return "○";
    case "degraded":
    case "retrying":
      return "!";
    default:
      return "·";
  }
}

function ActivityNodeView({
  event,
  mode,
  depth = 0,
}: {
  event: ActivityEvent;
  mode: ActivityDisplayMode;
  depth?: number;
}) {
  const [open, setOpen] = useState(depth < 1);
  const children = event.children ?? [];
  const hasChildren = children.length > 0;
  const duration = formatDurationLabel(
    formatActivityDurationMs(event.startedAt, event.finishedAt, event.updatedAt),
  );
  const progressLabel = formatMeasuredProgress(event.progress);
  const countLabel =
    event.resultCount != null
      ? formatResultCount(
          event.resultCount,
          event.category === "KNOWLEDGE" || event.category === "RETRIEVAL" ? "source" : "item",
        )
      : null;
  const actor =
    event.agentRef || event.actorId || (event.actorType !== "system" ? event.actorType : null);

  if (mode === "compact") {
    return null;
  }

  return (
    <li
      className={`lv-v2-activity-node lv-v2-activity-node--${event.lifecycle}`}
      style={{ marginLeft: depth > 0 ? 14 : 0 }}
    >
      <div className="lv-v2-activity-node__row">
        <span className="lv-v2-activity-node__glyph" aria-hidden="true">
          {glyphForLifecycle(event.lifecycle)}
        </span>
        <StatusDot tone={toneForLifecycle(event.lifecycle)} title={lifecycleStatusLabel(event.lifecycle)} />
        <div className="lv-v2-activity-node__main">
          {hasChildren ? (
            <button
              type="button"
              className="lv-v2-activity-node__title-btn"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              <span className="lv-v2-activity-node__title">{event.title}</span>
            </button>
          ) : (
            <span className="lv-v2-activity-node__title">{event.title}</span>
          )}
          {mode === "detailed" || mode === "developer" ? (
            event.summary ? (
            <p className="lv-v2-activity-node__summary">{event.summary}</p>
            ) : null
          ) : null}
          {countLabel ? <p className="lv-v2-activity-node__summary">{countLabel} identified.</p> : null}
          {progressLabel ? (
            <p className="lv-v2-activity-node__summary">Progress: {progressLabel}</p>
          ) : event.progress?.kind === "indeterminate" &&
            (event.lifecycle === "running" || event.lifecycle === "starting") ? (
            <p className="lv-v2-activity-node__summary">Progress indeterminate</p>
          ) : null}
          {event.error ? (
            <p className="lv-v2-activity-node__error" role="alert">
              {event.error.code}: {event.error.message}
            </p>
          ) : null}
        </div>
        <div className="lv-v2-activity-node__meta">
          <span className="lv-v2-activity-node__status">{lifecycleStatusLabel(event.lifecycle)}</span>
          {duration ? <span>{duration}</span> : null}
          {mode === "developer" && actor ? <span title="Actor">{actor}</span> : null}
        </div>
      </div>
      {mode === "developer" ? (
        <dl className="lv-v2-activity-node__dev">
          <div>
            <dt>Category</dt>
            <dd>{event.category}</dd>
          </div>
          <div>
            <dt>Phase</dt>
            <dd>{event.phase}</dd>
          </div>
          {event.traceId ? (
            <div>
              <dt>Trace</dt>
              <dd>{event.traceId}</dd>
            </div>
          ) : null}
          {event.modelRef ? (
            <div>
              <dt>Model</dt>
              <dd>{event.modelRef}</dd>
            </div>
          ) : null}
          {event.workerRef ? (
            <div>
              <dt>Worker</dt>
              <dd>{event.workerRef}</dd>
            </div>
          ) : null}
          {event.capabilityRef ? (
            <div>
              <dt>Capability</dt>
              <dd>{event.capabilityRef}</dd>
            </div>
          ) : null}
          {event.config?.requested || event.config?.effective ? (
            <div>
              <dt>Config</dt>
              <dd>
                req={JSON.stringify(event.config?.requested ?? {})} · eff=
                {JSON.stringify(event.config?.effective ?? {})}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {open && hasChildren ? (
        <ul className="lv-v2-activity-node__children">
          {children.map((child) => (
            <ActivityNodeView key={child.eventId} event={child} mode={mode} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function DecisionReceiptView({ receipt }: { receipt: DecisionReceipt }) {
  return (
    <section className="lv-v2-decision-receipt" aria-label="Decision receipt">
      <header className="lv-v2-decision-receipt__header">
        <strong>{receipt.strategyId || receipt.decisionId}</strong>
        {receipt.decisionResult ? <span>{receipt.decisionResult}</span> : null}
      </header>
      {receipt.checks && receipt.checks.length > 0 ? (
        <ul className="lv-v2-decision-receipt__checks">
          {receipt.checks.map((check) => (
            <li key={`${check.name}-${check.status}`}>
              <span>{check.name}</span>
              <span data-status={check.status}>{check.status}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="lv-v2-activity-node__summary">No authoritative checks attached.</p>
      )}
      {(receipt.warnings?.length || receipt.errors?.length) ? (
        <div className="lv-v2-decision-receipt__notes">
          {receipt.warnings?.map((w) => (
            <p key={w}>Warning: {w}</p>
          ))}
          {receipt.errors?.map((e) => (
            <p key={e} role="alert">
              Error: {e}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function ActivityTimeline({
  projection,
  mode = "detailed",
  streaming = false,
  emptyLabel = "No operational activity reported for this turn.",
  onModeChange,
  decisionReceipts = [],
}: ActivityTimelineProps) {
  const [localMode, setLocalMode] = useState<ActivityDisplayMode>(mode);
  const effectiveMode = onModeChange ? mode : localMode;
  const setMode = (next: ActivityDisplayMode) => {
    if (onModeChange) onModeChange(next);
    else setLocalMode(next);
  };

  const headline = useMemo(() => {
    if (streaming && (!projection || projection.events.length === 0)) {
      return "Operation in progress";
    }
    return compactHeadline(projection);
  }, [projection, streaming]);

  if (effectiveMode === "off") {
    return null;
  }

  const tree = projection?.tree ?? [];
  const flat = projection?.events ?? [];
  const showTree = tree.length > 0 ? tree : flat;
  const banner =
    projection?.disconnected
      ? "Stream disconnected — activity may be incomplete (STALE)."
      : projection?.stale
        ? "Activity state may be stale."
        : null;

  return (
    <section className="lv-v2-activity-timeline" aria-label="Operational activity">
      <div className="lv-v2-activity-timeline__toolbar">
        <button
          type="button"
          className="lv-v2-activity-timeline__toggle"
          aria-expanded={effectiveMode !== "compact"}
          onClick={() =>
            setMode(effectiveMode === "compact" ? "detailed" : effectiveMode === "detailed" ? "developer" : "compact")
          }
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M12 3a6 6 0 0 1 4.5 9.8V16a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-3.2A6 6 0 0 1 12 3z" />
            <path d="M9 19h6" />
          </svg>
          <span>{streaming ? "Activity…" : "Activity"}</span>
          <span className="lv-v2-activity-timeline__headline">{headline}</span>
          <span className="lv-v2-activity-timeline__mode">{effectiveMode}</span>
        </button>
      </div>

      {effectiveMode !== "compact" ? (
        <div className="lv-v2-activity-timeline__body">
          {banner ? (
            <p className="lv-v2-activity-timeline__banner" role="status">
              {banner}
            </p>
          ) : null}
          {showTree.length === 0 ? (
            <p className="lv-v2-activity-timeline__empty">{emptyLabel}</p>
          ) : (
            <ul className="lv-v2-activity-timeline__list">
              {showTree.map((event) => (
                <ActivityNodeView key={event.eventId} event={event} mode={effectiveMode} />
              ))}
            </ul>
          )}
          {decisionReceipts.map((receipt) => (
            <DecisionReceiptView key={receipt.decisionId} receipt={receipt} />
          ))}
        </div>
      ) : (
        <p className="lv-v2-activity-timeline__compact" role="status">
          {headline}
        </p>
      )}
    </section>
  );
}
