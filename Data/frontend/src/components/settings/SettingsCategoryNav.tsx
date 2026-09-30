import type { SettingsWorkspace } from "../../hooks/useSettingsWorkspace";

type Props = {
  ws: SettingsWorkspace;
};

function CategoryIcon({ name }: { name: string }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
  } as const;
  switch (name) {
    case "brain":
      return (
        <svg {...common} aria-hidden="true">
          <path d="M12 3a5 5 0 0 0-5 5v1a4 4 0 0 0-2 3v2a4 4 0 0 0 4 4h1" />
          <path d="M12 3a5 5 0 0 1 5 5v1a4 4 0 0 1 2 3v2a4 4 0 0 1-4 4h-1" />
          <path d="M12 8v13" />
        </svg>
      );
    case "cpu":
      return (
        <svg {...common} aria-hidden="true">
          <rect x="6" y="6" width="12" height="12" rx="2" />
          <path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" />
        </svg>
      );
    case "shield":
      return (
        <svg {...common} aria-hidden="true">
          <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z" />
        </svg>
      );
    case "agents":
      return (
        <svg {...common} aria-hidden="true">
          <circle cx="9" cy="8" r="3" />
          <circle cx="17" cy="9" r="2.5" />
          <path d="M3 19c1-3 3.5-4.5 6-4.5S14 16 15 19" />
          <path d="M14 19c.4-2 2-3.2 3.5-3.2S21 17 21.5 19" />
        </svg>
      );
    case "memory":
      return (
        <svg {...common} aria-hidden="true">
          <rect x="4" y="6" width="16" height="12" rx="2" />
          <path d="M8 6v12M12 6v12M16 6v12" />
        </svg>
      );
    case "tools":
      return (
        <svg {...common} aria-hidden="true">
          <path d="M14.5 4.5a4 4 0 0 1 5 5L12 17l-4 1 1-4 7.5-9.5z" />
        </svg>
      );
    case "trading":
      return (
        <svg {...common} aria-hidden="true">
          <path d="M4 16l5-5 4 4 7-8" />
          <path d="M15 7h5v5" />
        </svg>
      );
    case "server":
      return (
        <svg {...common} aria-hidden="true">
          <rect x="3" y="4" width="18" height="6" rx="1.5" />
          <rect x="3" y="14" width="18" height="6" rx="1.5" />
          <path d="M7 7h.01M7 17h.01" />
        </svg>
      );
    default:
      return (
        <svg {...common} aria-hidden="true">
          <path d="M4 8h16M4 16h10" />
          <circle cx="18" cy="16" r="2" />
          <circle cx="8" cy="8" r="2" />
        </svg>
      );
  }
}

export function SettingsCategoryNav({ ws }: Props) {
  return (
    <aside className="lv-v2-settings-nav" aria-label="Instellingen categorieën">
      <div className="lv-v2-settings-nav__head">
        <h3>Instellingen Categorieën</h3>
        <p>Selecteer een domein om te configureren</p>
      </div>
      <nav className="lv-v2-settings-nav__list">
        {ws.categories.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`lv-v2-settings-nav__item${item.id === ws.activeId ? " is-active" : ""}`}
            onClick={() => ws.selectCategory(item.id)}
            aria-current={item.id === ws.activeId ? "page" : undefined}
          >
            <span className="lv-v2-settings-nav__icon">
              <CategoryIcon name={item.icon} />
            </span>
            <span className="lv-v2-settings-nav__text">
              <strong>{item.label}</strong>
              <small>{item.description}</small>
            </span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
