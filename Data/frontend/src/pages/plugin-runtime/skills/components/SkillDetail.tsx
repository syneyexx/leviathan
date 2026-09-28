import type { ActionModel, InfoField, SkillDetailTab, SkillRecord } from "../viewModels";
import {
  SKILL_DETAIL_TABS,
  EM_DASH,
  UNMEASURED,
  displayOptional,
  skillCategoryLabel,
  skillStateLabel,
  skillStateTone,
  versionLabel,
} from "../viewModels";

function SkillMark() {
  return (
    <div className="lv-sk-detail-mark" aria-hidden="true">
      <svg viewBox="0 0 48 48" width="40" height="40">
        <path
          d="M24 4 42 14v20L24 44 6 34V14z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        <circle cx="24" cy="24" r="5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="M24 12v5M24 31v5M12 24h5M31 24h5" stroke="currentColor" strokeWidth="1.3" />
      </svg>
    </div>
  );
}

export function SkillDetailHeader({ skill }: { skill: SkillRecord }) {
  const tone = skillStateTone(skill);
  const ver = versionLabel(skill);
  return (
    <header className="lv-sk-detail-header">
      <SkillMark />
      <div className="lv-sk-detail-heading">
        <div className="lv-sk-detail-title-row">
          <h2 className="lv-sk-detail-title">{skill.name}</h2>
          <div className="lv-sk-badges">
            <span className={`lv-sk-badge is-${tone}`}>
              <i />
              {skillStateLabel(skill)}
            </span>
            <span className="lv-sk-badge is-muted">{skillCategoryLabel(skill)}</span>
            {ver ? <span className="lv-sk-badge is-muted">{ver}</span> : null}
          </div>
        </div>
        <p className="lv-sk-detail-desc">{skill.description || skill.trigger_description || "No description"}</p>
      </div>
      <div className="lv-sk-detail-ids">
        <div>
          <span className="lv-sk-id-label">Skill ID</span>
          <code>{skill.skill_id}</code>
        </div>
        <div>
          <span className="lv-sk-id-label">Version</span>
          <code>{ver || EM_DASH}</code>
        </div>
      </div>
    </header>
  );
}

export function SkillActions({
  actions,
  busy,
  moreOpen,
  onMoreToggle,
  onAction,
}: {
  actions: ActionModel[];
  busy: string | null;
  moreOpen: boolean;
  onMoreToggle: () => void;
  onAction: (id: string) => void;
}) {
  const primary = actions.filter((a) => a.id !== "more");
  return (
    <div className="lv-sk-actions" role="toolbar" aria-label="Skill actions">
      {primary.map((action) => (
        <button
          key={action.id}
          type="button"
          className={`lv-sk-action-btn${action.primary ? " is-primary" : ""}${action.enabled ? "" : " is-disabled"}`}
          disabled={!action.enabled || busy === action.id}
          title={action.reason}
          onClick={() => onAction(action.id)}
        >
          <ActionIcon id={action.id} />
          <span>{busy === action.id ? "…" : action.label}</span>
        </button>
      ))}
      <div className="lv-sk-more-wrap">
        <button
          type="button"
          className="lv-sk-action-btn"
          onClick={onMoreToggle}
          aria-expanded={moreOpen}
        >
          More
          <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
            <path d="M2 4.5 6 8l4-3.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
          </svg>
        </button>
        {moreOpen ? (
          <div className="lv-sk-more-menu" role="menu">
            <button type="button" role="menuitem" onClick={() => onAction("load_instructions")}>
              Load Instructions
            </button>
            <button type="button" role="menuitem" onClick={() => onAction("logs")}>
              Module Logs
            </button>
            <button type="button" role="menuitem" onClick={() => onAction("versions")}>
              Module Versions
            </button>
            <button type="button" role="menuitem" disabled title="No additional mutations">
              No further mutations
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ActionIcon({ id }: { id: string }) {
  const common = { viewBox: "0 0 16 16", width: 12, height: 12, "aria-hidden": true as const };
  switch (id) {
    case "execute":
      return (
        <svg {...common}>
          <path d="M5 3.5v9l8-4.5z" fill="currentColor" />
        </svg>
      );
    case "configure":
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <path d="M8 2.5v1.4M8 12.1v1.4M2.5 8h1.4M12.1 8h1.4M4.1 4.1l1 1M10.9 10.9l1 1M11.9 4.1l-1 1M5.1 10.9l-1 1" stroke="currentColor" strokeWidth="1.1" />
        </svg>
      );
    case "test":
      return (
        <svg {...common}>
          <path d="M5 3.5v9l8-4.5z" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <path d="m4 12 2 1.5 3-4" fill="none" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      );
    case "examples":
      return (
        <svg {...common}>
          <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.1" />
          <rect x="9" y="2.5" width="4.5" height="4.5" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.1" />
          <rect x="2.5" y="9" width="4.5" height="4.5" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.1" />
          <rect x="9" y="9" width="4.5" height="4.5" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.1" />
        </svg>
      );
    case "edit":
      return (
        <svg {...common}>
          <path d="M3 12.5 4.2 8.5 11.5 1.2l2.3 2.3L6.5 10.8z" fill="none" stroke="currentColor" strokeWidth="1.1" />
        </svg>
      );
    case "disable":
      return (
        <svg {...common}>
          <path d="M8 2.5v4M5 4.2a4.5 4.5 0 1 0 6 0" fill="none" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      );
    case "update":
      return (
        <svg {...common}>
          <path d="M3.5 8a4.5 4.5 0 0 1 7.7-3.1M12.5 8a4.5 4.5 0 0 1-7.7 3.1" fill="none" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      );
    case "clone":
      return (
        <svg {...common}>
          <rect x="5" y="5" width="8" height="8" rx="1" fill="none" stroke="currentColor" strokeWidth="1.1" />
          <path d="M3.5 10.5V3.5h7" fill="none" stroke="currentColor" strokeWidth="1.1" />
        </svg>
      );
    default:
      return null;
  }
}

export function SkillInfoCards({
  skill,
  infoFields,
}: {
  skill: SkillRecord;
  infoFields: InfoField[];
}) {
  const caps = skill.required_capabilities || skill.declarations?.required_capabilities || [];
  const rows = skill.declarations?.input_rows || [];
  const compat = skill.compatibility;
  const agents = compat?.agents || [];
  const runtimes = compat?.runtimes || [];

  return (
    <section className="lv-sk-info-grid" aria-label="Skill information cards">
      <article className="lv-sk-card">
        <header className="lv-sk-card-head">
          <span>SKILL INFORMATION</span>
          <span className="lv-sk-card-link">View Details →</span>
        </header>
        <div className="lv-sk-card-watermark" aria-hidden="true">
          i
        </div>
        <dl className="lv-sk-kv">
          {infoFields.map((field) => (
            <div key={field.label} className="lv-sk-kv-row">
              <dt>{field.label}</dt>
              <dd className={field.tone === "ok" ? "is-ok" : undefined}>{field.value}</dd>
            </div>
          ))}
        </dl>
      </article>

      <article className="lv-sk-card">
        <header className="lv-sk-card-head">
          <span>CAPABILITIES &amp; INPUTS</span>
          <span className="lv-sk-card-link">View Schema →</span>
        </header>
        <div className="lv-sk-card-watermark is-cube" aria-hidden="true">
          ▣
        </div>
        <div className="lv-sk-cap-block">
          <div className="lv-sk-subhead">Capabilities</div>
          {caps.length === 0 ? (
            <p className="lv-sk-muted">No required capabilities declared.</p>
          ) : (
            <ul className="lv-sk-cap-list">
              {caps.map((cap) => (
                <li key={cap}>
                  <span className="lv-sk-check">✓</span>
                  <code>{cap}</code>
                </li>
              ))}
            </ul>
          )}
          <div className="lv-sk-subhead">Input Schema</div>
          {rows.length === 0 ? (
            <p className="lv-sk-muted">No input schema declared</p>
          ) : (
            <ul className="lv-sk-schema-list">
              {rows.map((row) => (
                <li key={row.name}>
                  <code>{row.name}</code>
                  <span>{row.type}</span>
                  <span className={row.required ? "is-req" : "is-opt"}>
                    {row.required ? "Required" : "Optional"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </article>

      <article className="lv-sk-card">
        <header className="lv-sk-card-head">
          <span>COMPATIBILITY</span>
        </header>
        <div className="lv-sk-card-watermark is-link" aria-hidden="true">
          ◎
        </div>
        <div className="lv-sk-cap-block">
          <div className="lv-sk-subhead">Status</div>
          <p className="lv-sk-compat-status">
            {compat?.status || UNMEASURED}
            {compat?.reason ? <span className="lv-sk-muted"> — {compat.reason}</span> : null}
          </p>
          <div className="lv-sk-subhead">Compatible Agents</div>
          {agents.length === 0 ? (
            <p className="lv-sk-muted">UNMEASURED — no agent ranking surface</p>
          ) : (
            <ul className="lv-sk-compat-list">
              {agents.map((a) => (
                <li key={a.id}>
                  <i className={`is-${String(a.status).toLowerCase()}`} />
                  {a.id}
                  <span>{a.status}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="lv-sk-subhead">Required Runtimes</div>
          {runtimes.length === 0 ? (
            <p className="lv-sk-muted">{displayOptional(skill.module_id) === EM_DASH ? "No owning module" : "Module runtime unmeasured"}</p>
          ) : (
            <ul className="lv-sk-compat-list">
              {runtimes.map((r) => (
                <li key={r.id}>
                  <i className="is-required" />
                  {r.adapter || r.id}
                  <span>{r.status || "Required"}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </article>
    </section>
  );
}

export function SkillDetailTabs({
  tab,
  onTab,
}: {
  tab: SkillDetailTab;
  onTab: (t: SkillDetailTab) => void;
}) {
  return (
    <nav className="lv-sk-tabs" aria-label="Skill detail tabs">
      {SKILL_DETAIL_TABS.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`lv-sk-tab${tab === item.id ? " is-active" : ""}`}
          onClick={() => onTab(item.id)}
        >
          {item.label}
        </button>
      ))}
    </nav>
  );
}

export function SkillWorkspace({
  skill,
  tab,
  instructions,
  instructionsLoading,
  onLoadInstructions,
  structuredResult,
  onCopy,
}: {
  skill: SkillRecord;
  tab: SkillDetailTab;
  instructions: string | null;
  instructionsLoading: boolean;
  onLoadInstructions: () => void;
  structuredResult: { label: string; format: "json" | "text"; body: string } | null;
  onCopy: () => void;
}) {
  const left = renderTabContent(skill, tab, instructions, instructionsLoading, onLoadInstructions);
  const rightBody =
    structuredResult?.body ??
    (tab === "examples"
      ? "No examples declared."
      : "No example output recorded.");
  const rightLabel = structuredResult?.label ?? (tab === "examples" ? "EXAMPLE OUTPUT" : "EXAMPLE OUTPUT");

  return (
    <section className="lv-sk-workspace">
      <article className="lv-sk-work-left">
        <h3 className="lv-sk-section-label">{tab.replace(/_/g, " ").toUpperCase()}</h3>
        <div className="lv-sk-work-body">{left}</div>
      </article>
      <article className="lv-sk-work-right">
        <header className="lv-sk-code-head">
          <span>{rightLabel}</span>
          <div className="lv-sk-code-actions">
            <span className="lv-sk-format">{structuredResult?.format?.toUpperCase() || "JSON"}</span>
            <button type="button" className="lv-sk-ghost-btn" onClick={onCopy}>
              Copy
            </button>
            <button
              type="button"
              className="lv-sk-ghost-btn is-disabled"
              disabled
              title="Download only when an artifact exists"
            >
              Download
            </button>
          </div>
        </header>
        <pre className="lv-sk-code">
          <code>{rightBody}</code>
        </pre>
      </article>
    </section>
  );
}

function renderTabContent(
  skill: SkillRecord,
  tab: SkillDetailTab,
  instructions: string | null,
  instructionsLoading: boolean,
  onLoadInstructions: () => void,
) {
  switch (tab) {
    case "description":
      return (
        <>
          <p>{skill.description || "No description"}</p>
          {skill.trigger_description ? (
            <>
              <h4>Trigger</h4>
              <p>{skill.trigger_description}</p>
            </>
          ) : null}
          <h4>Provenance</h4>
          <ul>
            <li>Source: {displayOptional(skill.source_repo)}</li>
            <li>Ref: {displayOptional(skill.source_ref)}</li>
            <li>Path: {displayOptional(skill.source_path)}</li>
            <li>Module: {displayOptional(skill.module_id)}</li>
            <li>Hash: {displayOptional(skill.content_hash?.slice(0, 16))}</li>
          </ul>
          <h4>Instructions</h4>
          {instructions == null ? (
            <button type="button" className="lv-sk-ghost-btn is-primary" onClick={onLoadInstructions} disabled={instructionsLoading}>
              {instructionsLoading ? "Loading…" : "Load Instructions"}
            </button>
          ) : (
            <pre className="lv-sk-instructions">{instructions || "(empty)"}</pre>
          )}
          <p className="lv-sk-muted">Instructions load on demand — not prompt-injected from the catalog.</p>
        </>
      );
    case "configuration":
      return (
        <>
          <p>Safe declared metadata only. Secrets are never shown.</p>
          <ul>
            <li>enabled: {String(Boolean(skill.enabled))}</li>
            <li>catalog_only: {String(Boolean(skill.catalog_only))}</li>
            <li>module_id: {displayOptional(skill.module_id)}</li>
            <li>version: {displayOptional(skill.version)}</li>
            <li>
              frontmatter keys:{" "}
              {(skill.declarations?.frontmatter_keys || []).join(", ") || EM_DASH}
            </li>
          </ul>
        </>
      );
    case "examples": {
      const examples = skill.declarations?.examples;
      const refs = skill.declarations?.example_refs || [];
      if (examples == null && refs.length === 0) {
        return <p>No examples declared.</p>;
      }
      return (
        <>
          {examples != null ? (
            <pre className="lv-sk-instructions">
              {typeof examples === "string" ? examples : JSON.stringify(examples, null, 2)}
            </pre>
          ) : null}
          {refs.length ? (
            <>
              <h4>Example refs</h4>
              <ul>
                {refs.map((r) => (
                  <li key={r}>
                    <code>{r}</code>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </>
      );
    }
    case "input_schema":
      return skill.declarations?.input_schema != null ? (
        <pre className="lv-sk-instructions">{JSON.stringify(skill.declarations.input_schema, null, 2)}</pre>
      ) : (
        <p>No input schema declared</p>
      );
    case "output_schema":
      return skill.declarations?.output_schema != null ? (
        <pre className="lv-sk-instructions">{JSON.stringify(skill.declarations.output_schema, null, 2)}</pre>
      ) : (
        <p>No output schema declared</p>
      );
    case "dependencies":
      return (
        <ul>
          <li>
            Required capabilities:{" "}
            {(skill.required_capabilities || []).join(", ") || EM_DASH}
          </li>
          <li>Owning module: {displayOptional(skill.module_id)}</li>
          <li>
            Resources: {(skill.resource_refs || []).join(", ") || EM_DASH}
          </li>
          <li>Scripts: {(skill.script_refs || []).join(", ") || EM_DASH}</li>
        </ul>
      );
    case "usage":
      return <p>{UNMEASURED} — no durable skill usage telemetry on this surface.</p>;
    case "version_history":
      return (
        <p>
          Skill records store a single version string ({displayOptional(skill.version)}). Historical
          versions are module-owned — use More → Module Versions when a parent module exists.
        </p>
      );
    case "logs":
      return (
        <p>
          No per-skill audit log store. Module pack logs are available via More → Module Logs when
          an owning module exists.
        </p>
      );
    default:
      return null;
  }
}
