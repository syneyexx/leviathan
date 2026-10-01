import { Panel } from "../ui";
import type { ConsoleQuickFilter, ConsoleTimeRange } from "../../pages/console/consoleFormat";

type Props = {
  quickFilter: ConsoleQuickFilter;
  onQuickFilter: (v: ConsoleQuickFilter) => void;
  errorCount: number;
  warningCount: number;
  overviewErrors: number | null;
  overviewWarnings: number | null;
  timeRange: ConsoleTimeRange;
  timeRangeOptions: Array<{ id: ConsoleTimeRange; label: string }>;
  onTimeRange: (v: ConsoleTimeRange) => void;
  autoScroll: boolean;
  onAutoScroll: (v: boolean) => void;
  regexText: string;
  onRegexText: (v: string) => void;
  regexError: string | null;
};

const QUICK: Array<{ id: Exclude<ConsoleQuickFilter, null>; label: string; countKey?: "errors" | "warnings" }> = [
  { id: "errors", label: "Errors", countKey: "errors" },
  { id: "warnings", label: "Warnings", countKey: "warnings" },
  { id: "agenten", label: "Agenten" },
  { id: "trading", label: "Trading" },
  { id: "datasets", label: "Datasets" },
  { id: "mcp", label: "MCP" },
  { id: "tools", label: "Tools" },
  { id: "system", label: "System" },
  { id: "http", label: "HTTP" },
  { id: "modules", label: "Modules" },
  { id: "workflows", label: "Workflows" },
];

export function ConsoleFiltersPanel(props: Props) {
  return (
    <Panel className="lv-v2-console-filters" title="Log Filters">
      <div className="lv-v2-console-filters__section">
        <div className="lv-v2-console-filters__label">Snelle filters</div>
        <div className="lv-v2-console-quick">
          {QUICK.map((q) => {
            const count =
              q.countKey === "errors"
                ? (props.overviewErrors ?? props.errorCount)
                : q.countKey === "warnings"
                  ? (props.overviewWarnings ?? props.warningCount)
                  : null;
            const active = props.quickFilter === q.id;
            return (
              <button
                key={q.id}
                type="button"
                className={`lv-v2-console-chip${active ? " is-active" : ""}`}
                onClick={() => props.onQuickFilter(active ? null : q.id)}
              >
                {q.label}
                {count != null ? ` (${count})` : ""}
              </button>
            );
          })}
        </div>
      </div>

      <div className="lv-v2-console-filters__section">
        <div className="lv-v2-console-filters__label">Tijd bereik</div>
        <select
          aria-label="Tijd bereik"
          value={props.timeRange}
          onChange={(e) => props.onTimeRange(e.target.value as ConsoleTimeRange)}
        >
          {props.timeRangeOptions.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
        <label className="lv-v2-console-toggle">
          <input
            type="checkbox"
            checked={props.autoScroll}
            onChange={(e) => props.onAutoScroll(e.target.checked)}
          />
          <span>Auto-scroll (live)</span>
        </label>
      </div>

      <div className="lv-v2-console-filters__section">
        <div className="lv-v2-console-filters__label">Regex filter (optioneel)</div>
        <input
          className={props.regexError ? "is-invalid" : undefined}
          value={props.regexText}
          onChange={(e) => props.onRegexText(e.target.value)}
          placeholder="Bijv. ERROR|WARNING|agent"
          aria-invalid={Boolean(props.regexError)}
          aria-describedby={props.regexError ? "console-regex-error" : undefined}
        />
        {props.regexError ? (
          <p id="console-regex-error" className="lv-v2-console-regex-error" role="alert">
            {props.regexError}
          </p>
        ) : (
          <p className="lv-v2-muted lv-v2-console-regex-hint">
            Alleen op begrensde clientbuffer — geen DB-regex.
          </p>
        )}
      </div>
    </Panel>
  );
}
