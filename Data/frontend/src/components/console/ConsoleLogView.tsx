import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, EmptyState } from "../ui";
import type { RuntimeEvent } from "../../types/api";
import {
  displayLevel,
  formatConsoleTime,
  severityTone,
} from "../../pages/console/consoleFormat";

const ROW_HEIGHT = 22;
const OVERSCAN = 12;

type Props = {
  events: RuntimeEvent[];
  paused: boolean;
  autoScroll: boolean;
  connecting?: boolean;
  focusSequence?: number | null;
  onUserScrollAway?: () => void;
};

export function ConsoleLogView({
  events,
  paused,
  autoScroll,
  connecting,
  focusSequence,
  onUserScrollAway,
}: Props) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(320);
  const stickRef = useRef(true);
  const lastLen = useRef(0);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight));
    ro.observe(el);
    setViewportH(el.clientHeight);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    stickRef.current = autoScroll;
  }, [autoScroll]);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    if (focusSequence != null) {
      const idx = events.findIndex((e) => e.sequence === focusSequence);
      if (idx >= 0) {
        el.scrollTop = Math.max(0, idx * ROW_HEIGHT - viewportH / 3);
        return;
      }
    }
    if (!paused && stickRef.current && autoScroll && events.length !== lastLen.current) {
      el.scrollTop = el.scrollHeight;
    }
    lastLen.current = events.length;
  }, [autoScroll, events, focusSequence, paused, viewportH]);

  const totalH = events.length * ROW_HEIGHT;
  const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const visibleCount = Math.ceil(viewportH / ROW_HEIGHT) + OVERSCAN * 2;
  const slice = useMemo(
    () => events.slice(start, start + visibleCount),
    [events, start, visibleCount],
  );

  return (
    <div
      ref={scrollerRef}
      className={`lv-v2-console-log${paused ? " is-paused" : ""}`}
      role="log"
      aria-live={paused ? "off" : "polite"}
      onScroll={(e) => {
        const el = e.currentTarget;
        setScrollTop(el.scrollTop);
        const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < ROW_HEIGHT * 3;
        if (!nearBottom && stickRef.current) {
          stickRef.current = false;
          onUserScrollAway?.();
        } else if (nearBottom) {
          stickRef.current = autoScroll;
        }
      }}
    >
      {events.length === 0 ? (
        <EmptyState
          title={connecting ? "Verbinden met eventstream…" : "Geen logs in geselecteerd bereik"}
          detail="Pas filters of tijdvenster aan, of wacht op nieuwe runtime events."
        />
      ) : (
        <div className="lv-v2-console-log__spacer" style={{ height: totalH }}>
          <div
            className="lv-v2-console-log__window"
            style={{ transform: `translateY(${start * ROW_HEIGHT}px)` }}
          >
            {slice.map((line) => {
              const lvl = displayLevel(line.level);
              const tone = severityTone(line.level);
              const focused = focusSequence === line.sequence;
              return (
                <div
                  key={line.event_id}
                  className={`lv-v2-console-log__row${focused ? " is-focused" : ""}`}
                  style={{ height: ROW_HEIGHT }}
                  data-sequence={line.sequence}
                >
                  <span className="time">{formatConsoleTime(line.created_at_ms)}</span>
                  <Badge tone={tone} className="lv-v2-console-sev">
                    {lvl}
                  </Badge>
                  <span className="cat">{line.category || "—"}</span>
                  <span className="comp">{line.subsystem || line.source || "—"}</span>
                  <span className="msg" title={line.message}>
                    {line.name ? `${line.name} · ` : ""}
                    {line.message}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
