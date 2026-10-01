import { useEffect, useRef } from "react";
import { Badge, Button, Panel, StatusDot } from "../ui";
import type { RuntimeEvent } from "../../types/api";
import type { ConsoleSeverityChip } from "../../pages/console/consoleFormat";
import { ConsoleLogView } from "./ConsoleLogView";

type Props = {
  events: RuntimeEvent[];
  connection: string;
  paused: boolean;
  onTogglePause: () => void;
  onClear: () => void;
  onExport: () => void;
  exportBusy?: boolean;
  autoScroll: boolean;
  onAutoScrollChange: (v: boolean) => void;
  search: string;
  onSearch: (v: string) => void;
  level: string;
  onLevel: (v: string) => void;
  service: string;
  onService: (v: string) => void;
  category: string;
  onCategory: (v: string) => void;
  serviceOptions: string[];
  categoryOptions: string[];
  severityChip: ConsoleSeverityChip;
  onSeverityChip: (v: ConsoleSeverityChip) => void;
  focusSequence?: number | null;
  menuOpen: boolean;
  onMenuOpen: (v: boolean) => void;
  onOpenCommands: () => void;
  onOpenResources: () => void;
  liveError?: string | null;
};

const SEV_CHIPS: Array<{ id: ConsoleSeverityChip; label: string }> = [
  { id: "all", label: "Alle" },
  { id: "info", label: "Info" },
  { id: "success", label: "Success" },
  { id: "warning", label: "Warning" },
  { id: "error", label: "Error" },
];

export function ConsolePanel(props: Props) {
  const live = props.connection === "open" && !props.paused;
  const connecting = props.connection === "connecting" || props.connection === "reconnecting";
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!props.menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) props.onMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [props]);

  const statusTone =
    props.connection === "open"
      ? "success"
      : props.connection === "error"
        ? "danger"
        : connecting
          ? "warning"
          : "muted";

  return (
    <Panel
      className="lv-v2-console-main-panel"
      title={
        <span className="lv-v2-console-main-panel__title">
          Console
          <StatusDot tone={statusTone} pulse={live} title={`Stream: ${props.connection}`} />
          {live ? (
            <Badge tone="success" className="lv-v2-console-live-badge">
              LIVE
            </Badge>
          ) : props.paused ? (
            <Badge tone="warning">PAUSED</Badge>
          ) : connecting ? (
            <Badge tone="warning">RECONNECTING</Badge>
          ) : (
            <Badge tone="muted">{props.connection.toUpperCase()}</Badge>
          )}
        </span>
      }
      action={
        <div className="lv-v2-console-toolbar">
          <Button variant="secondary" size="sm" onClick={props.onTogglePause}>
            {props.paused ? "Hervat" : "Pauze"}
          </Button>
          <Button variant="ghost" size="sm" onClick={props.onClear}>
            Wissen
          </Button>
          <Button
            variant="ghost"
            size="sm"
            loading={props.exportBusy}
            onClick={props.onExport}
          >
            Exporteren
          </Button>
          <div className="lv-v2-console-more" ref={menuRef}>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Meer acties"
              onClick={() => props.onMenuOpen(!props.menuOpen)}
            >
              ⋯
            </Button>
            {props.menuOpen ? (
              <div className="lv-v2-console-more__menu" role="menu">
                <button type="button" role="menuitem" onClick={() => { props.onOpenCommands(); props.onMenuOpen(false); }}>
                  Operator commands
                </button>
                <button type="button" role="menuitem" onClick={() => { props.onOpenResources(); props.onMenuOpen(false); }}>
                  Resources
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    props.onAutoScrollChange(true);
                    props.onMenuOpen(false);
                  }}
                >
                  Spring naar live tail
                </button>
              </div>
            ) : null}
          </div>
        </div>
      }
    >
      <p className="lv-v2-console-panel-sub">
        Realtime logs van alle Leviathan componenten. Gebruik filters om specifieke output te bekijken.
      </p>
      <div className="lv-v2-console-filterbar">
        <label className="lv-v2-console-search">
          <span className="sr-only">Zoek in logs</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <circle cx="11" cy="11" r="6" />
            <path d="M16 16l4 4" />
          </svg>
          <input
            value={props.search}
            onChange={(e) => props.onSearch(e.target.value)}
            placeholder="Zoek in logs..."
          />
        </label>
        <select
          aria-label="Niveau"
          value={props.level}
          onChange={(e) => {
            props.onLevel(e.target.value);
            props.onSeverityChip("all");
          }}
        >
          <option value="">Alle niveaus</option>
          {["INFO", "SUCCESS", "WARNING", "ERROR", "DEBUG", "CRITICAL"].map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <select
          aria-label="Service"
          value={props.service}
          onChange={(e) => props.onService(e.target.value)}
        >
          <option value="">Alle services</option>
          {props.serviceOptions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          aria-label="Categorie"
          value={props.category}
          onChange={(e) => props.onCategory(e.target.value)}
        >
          <option value="">Alle categorieën</option>
          {props.categoryOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <div className="lv-v2-console-sev-chips" role="group" aria-label="Severity filters">
          {SEV_CHIPS.map((chip) => (
            <button
              key={chip.id}
              type="button"
              className={`lv-v2-console-chip${props.severityChip === chip.id ? " is-active" : ""}`}
              onClick={() => {
                props.onSeverityChip(chip.id);
                if (chip.id !== "all") props.onLevel("");
              }}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      {props.liveError ? (
        <p className="lv-v2-warn lv-v2-console-stream-warn" role="status">
          Stream: {props.liveError}
        </p>
      ) : null}

      <ConsoleLogView
        events={props.events}
        paused={props.paused}
        autoScroll={props.autoScroll}
        connecting={connecting}
        focusSequence={props.focusSequence}
        onUserScrollAway={() => props.onAutoScrollChange(false)}
      />
    </Panel>
  );
}
