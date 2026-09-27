import { TIMEFRAMES } from "./utils/format";

export function PaperTradingToolbar({
  watchlist,
  symbol,
  timeframe,
  indicatorsOpen,
  drawingTool,
  layoutSavedAt,
  onSelectSymbol,
  onAddSymbol,
  onTimeframe,
  onToggleIndicators,
  onToggleDraw,
  onSaveLayout,
  onSelectTool,
  indicators,
  onIndicatorChange,
}: {
  watchlist: string[];
  symbol: string;
  timeframe: string;
  indicatorsOpen: boolean;
  drawingTool: string | null;
  layoutSavedAt: string | null;
  onSelectSymbol: (s: string) => void;
  onAddSymbol: (s: string) => void;
  onTimeframe: (tf: string) => void;
  onToggleIndicators: () => void;
  onToggleDraw: () => void;
  onSaveLayout: () => void;
  onSelectTool: (tool: string | null) => void;
  indicators: { ma20: boolean; ma50: boolean; ma200: boolean; volume: boolean };
  onIndicatorChange: (key: keyof typeof indicators, value: boolean) => void;
}) {
  return (
    <div className="lv-paper-toolbar">
      <div className="lv-paper-symbols" role="tablist" aria-label="Symbols">
        {watchlist.map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={s === symbol}
            className={`lv-paper-chip${s === symbol ? " is-active" : ""}`}
            onClick={() => onSelectSymbol(s)}
          >
            {s}
          </button>
        ))}
        <button
          type="button"
          className="lv-paper-chip is-add"
          onClick={() => {
            const next = window.prompt("Add symbol (e.g. SOLUSDT)");
            if (next) onAddSymbol(next);
          }}
        >
          + Add Symbol
        </button>
      </div>
      <div className="lv-paper-toolbar-right">
        <div className="lv-paper-tf" role="group" aria-label="Timeframes">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              className={`lv-paper-tf-btn${tf === timeframe ? " is-active" : ""}`}
              onClick={() => onTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>
        <div className="lv-paper-tool-actions">
          <div className="lv-paper-menu-wrap">
            <button
              type="button"
              className={`lv-paper-tool-btn${indicatorsOpen ? " is-active" : ""}`}
              onClick={onToggleIndicators}
            >
              Indicators
            </button>
            {indicatorsOpen ? (
              <div className="lv-paper-menu" role="menu">
                {(
                  [
                    ["ma20", "MA 20"],
                    ["ma50", "MA 50"],
                    ["ma200", "MA 200"],
                    ["volume", "Volume"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="lv-paper-menu-item">
                    <input
                      type="checkbox"
                      checked={indicators[key]}
                      onChange={(e) => onIndicatorChange(key, e.target.checked)}
                    />
                    {label}
                  </label>
                ))}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className={`lv-paper-tool-btn${drawingTool ? " is-active" : ""}`}
            onClick={onToggleDraw}
          >
            Draw
          </button>
          {drawingTool !== null ? (
            <div className="lv-paper-draw-tools" role="group" aria-label="Drawing tools">
              {["crosshair", "trend", "fib", "text", "brush"].map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`lv-paper-tool-btn is-mini${drawingTool === t ? " is-active" : ""}`}
                  onClick={() => onSelectTool(drawingTool === t ? null : t)}
                >
                  {t}
                </button>
              ))}
            </div>
          ) : null}
          <button type="button" className="lv-paper-tool-btn" onClick={onSaveLayout}>
            Save Layout{layoutSavedAt ? " ✓" : ""}
          </button>
        </div>
      </div>
    </div>
  );
}
