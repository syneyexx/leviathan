import { useEffect, useRef } from "react";
import { media } from "../assets/media";
import { useShellStatus } from "../hooks/useShellStatus";

type AppHeaderProps = {
  searchPlaceholder?: string;
  /** Retained for page call-sites; live chips replace decorative mode/system rows. */
  modeLabel?: string;
  systemItems?: readonly string[];
  onMenuClick: () => void;
};

function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent);
}

export function AppHeader({
  searchPlaceholder = "Search tasks, projects, agents, or anything...",
  onMenuClick,
}: AppHeaderProps) {
  const searchRef = useRef<HTMLInputElement>(null);
  const status = useShellStatus();
  const kbdHint = isMacPlatform() ? "⌘ K" : "CTRL K";

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      if (event.key.toLowerCase() !== "k") return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) {
        if (target === searchRef.current) {
          event.preventDefault();
          searchRef.current?.blur();
        }
        return;
      }
      event.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const systemTone =
    status.systemState === "online"
      ? "ok"
      : status.systemState === "degraded"
        ? "warn"
        : status.systemState === "offline"
          ? "bad"
          : "muted";

  const agentsTone = status.agentsActive == null ? "muted" : status.agentsActive > 0 ? "info" : "muted";
  const llmTone =
    status.llmAvailable == null ? "muted" : status.llmAvailable ? "gold" : "bad";

  const metaParts: string[] = [];
  if (status.approvalsPending != null && status.approvalsPending > 0) {
    metaParts.push(`${status.approvalsPending} approval${status.approvalsPending === 1 ? "" : "s"}`);
  }
  if (status.jobsQueued != null && status.jobsQueued > 0) {
    metaParts.push(`${status.jobsQueued} job${status.jobsQueued === 1 ? "" : "s"}`);
  }
  const metaLabel = metaParts.length ? metaParts.join(" · ") : null;

  return (
    <header className="lv-header">
      <label className="lv-search">
        <svg className="lv-icon" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
        <input
          ref={searchRef}
          type="search"
          placeholder={searchPlaceholder}
          aria-label="Search"
        />
        <span className="lv-kbd">{kbdHint}</span>
      </label>

      <div className="lv-header-chips" aria-live="polite">
        <div className={`lv-chip lv-chip--${systemTone}`} title={status.error ?? undefined}>
          <span className={`lv-chip-dot lv-chip-dot--${systemTone}`} />
          <span>{status.systemLabel}</span>
        </div>

        <div className={`lv-chip lv-chip--${agentsTone}`}>
          <svg className="lv-icon lv-chip-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="8" r="3.2" />
            <path d="M5 19c1.8-3.2 4.2-4.8 7-4.8s5.2 1.6 7 4.8" />
          </svg>
          <span>{status.agentsLabel}</span>
        </div>

        <div className={`lv-chip lv-chip--${llmTone}`} title={status.health?.llm?.error ?? undefined}>
          <svg className="lv-icon lv-chip-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 4v6M12 10l-6 8M12 10l6 8M7.5 14.5h9" />
            <circle cx="12" cy="4" r="1.4" />
          </svg>
          <span>{status.llmLabel}</span>
        </div>

        {metaLabel ? (
          <div className="lv-chip lv-chip--info">
            <svg className="lv-icon lv-chip-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 16l4.5-5 3.5 3 4-6 4 2" />
            </svg>
            <span>{metaLabel}</span>
          </div>
        ) : null}
      </div>

      <div className="lv-header-end">
        <div className="lv-header-user" aria-label="Operator">
          <img className="lv-header-avatar" src={media.avatar} alt="" width={36} height={36} />
          <div className="lv-header-user-copy">
            <div className="lv-header-user-name">LEVIATHAN</div>
            <div className="lv-header-user-role">Elite Mode</div>
          </div>
        </div>

        <button className="lv-menu-btn" type="button" aria-label="Menu" onClick={onMenuClick}>
          <span />
          <span />
          <span />
        </button>
      </div>
    </header>
  );
}
