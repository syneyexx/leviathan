import type { FilterChipModel, SkillFilter, SkillRecord } from "../viewModels";
import {
  skillCategoryLabel,
  skillStateLabel,
  skillStateTone,
  truncate,
  versionLabel,
} from "../viewModels";

function SkillGlyph({ skill }: { skill: SkillRecord }) {
  const hue = Math.abs(
    Array.from(skill.skill_id).reduce((acc, ch) => acc + ch.charCodeAt(0), 0),
  ) % 360;
  return (
    <span className="lv-sk-lib-icon" style={{ color: `hsl(${hue} 70% 62%)` }} aria-hidden="true">
      <svg viewBox="0 0 24 24" width="18" height="18">
        <path
          d="M12 2.5 20 7v10l-8 4.5L4 17V7z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
        />
        <circle cx="12" cy="12" r="2.2" fill="currentColor" />
      </svg>
    </span>
  );
}

export function SkillLibrary({
  chips,
  filter,
  onFilter,
  query,
  onQuery,
  skills,
  selectedId,
  onSelect,
  loading,
  error,
  offset,
  limit,
  onPrev,
  onNext,
  onRefresh,
}: {
  chips: FilterChipModel[];
  filter: SkillFilter;
  onFilter: (f: SkillFilter) => void;
  query: string;
  onQuery: (q: string) => void;
  skills: SkillRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
  error: string | null;
  offset: number;
  limit: number;
  onPrev: () => void;
  onNext: () => void;
  onRefresh: () => void;
}) {
  return (
    <aside className="lv-sk-library" aria-label="Skill Library">
      <header className="lv-sk-library-head">
        <h2 className="lv-sk-section-label">SKILL LIBRARY</h2>
        <button type="button" className="lv-sk-icon-btn" onClick={onRefresh} disabled={loading} title="Refresh">
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
            <path d="M3.5 8a4.5 4.5 0 0 1 7.7-3.1M12.5 8a4.5 4.5 0 0 1-7.7 3.1" fill="none" stroke="currentColor" strokeWidth="1.2" />
            <path d="M11 2.8v2.6H8.4M5 13.2v-2.6h2.6" fill="none" stroke="currentColor" strokeWidth="1.2" />
          </svg>
        </button>
      </header>

      <div className="lv-sk-search-row">
        <input
          className="lv-sk-search"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search skills..."
          aria-label="Search skills"
        />
        <button type="button" className="lv-sk-icon-btn" title="Filter" aria-label="Filter">
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
            <path d="M2.5 3.5h11l-4 4.5v4l-3-1.5v-2.5z" fill="none" stroke="currentColor" strokeWidth="1.2" />
          </svg>
        </button>
      </div>

      <div className="lv-sk-filter-chips" role="tablist" aria-label="Skill classifications">
        {chips.map((chip) => (
          <button
            key={chip.id}
            type="button"
            role="tab"
            aria-selected={filter === chip.id}
            className={`lv-sk-chip${filter === chip.id ? " is-active" : ""}${chip.enabled ? "" : " is-disabled"}`}
            title={chip.reason}
            disabled={!chip.enabled && chip.id !== "agent"}
            onClick={() => onFilter(chip.id)}
          >
            <span>{chip.label}</span>
            <span className="lv-sk-chip-count">{chip.count}</span>
          </button>
        ))}
      </div>

      {error ? (
        <p className="lv-sk-error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="lv-sk-lib-list" role="listbox" aria-label="Skills">
        {loading && skills.length === 0 ? (
          <div className="lv-sk-empty">Loading skills…</div>
        ) : null}
        {!loading && skills.length === 0 ? (
          <div className="lv-sk-empty">
            {filter === "agent"
              ? "Agent SkillLibrary is not projected on this surface."
              : "No skills match this query."}
          </div>
        ) : null}
        {skills.map((skill) => {
          const selected = skill.skill_id === selectedId;
          const tone = skillStateTone(skill);
          const ver = versionLabel(skill);
          return (
            <button
              key={skill.skill_id}
              type="button"
              role="option"
              aria-selected={selected}
              className={`lv-sk-lib-row${selected ? " is-selected" : ""}`}
              onClick={() => onSelect(skill.skill_id)}
            >
              <SkillGlyph skill={skill} />
              <div className="lv-sk-lib-main">
                <div className="lv-sk-lib-title-row">
                  <strong className="lv-sk-lib-name">{skill.name}</strong>
                  <span className="lv-sk-lib-cat">{skillCategoryLabel(skill)}</span>
                </div>
                <div className="lv-sk-lib-desc">{truncate(skill.description || skill.trigger_description, 72)}</div>
                <div className="lv-sk-lib-meta">
                  <span className={`lv-sk-state is-${tone}`}>
                    <i />
                    {skillStateLabel(skill)}
                  </span>
                  {ver ? <span className="lv-sk-lib-ver">{ver}</span> : null}
                </div>
              </div>
              <span className="lv-sk-lib-more" aria-hidden="true">
                ···
              </span>
            </button>
          );
        })}
      </div>

      <footer className="lv-sk-lib-pager">
        <button type="button" className="lv-sk-ghost-btn" disabled={offset <= 0 || loading} onClick={onPrev}>
          Prev
        </button>
        <span className="lv-sk-pager-meta">
          {offset}–{offset + skills.length}
        </span>
        <button
          type="button"
          className="lv-sk-ghost-btn"
          disabled={skills.length < limit || loading}
          onClick={onNext}
        >
          Next
        </button>
      </footer>
    </aside>
  );
}
