import { RESEARCH_LAB_TABS, type ResearchLabTab } from "../viewModels";

export function ResearchLabTabBar({
  tab,
  onChange,
  disabled,
}: {
  tab: ResearchLabTab;
  onChange: (t: ResearchLabTab) => void;
  disabled?: boolean;
}) {
  return (
    <nav className="lv-rl-tabs" aria-label="Research Lab sections">
      {RESEARCH_LAB_TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          className={`lv-rl-tab${tab === t.id ? " is-active" : ""}`}
          disabled={disabled}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}
