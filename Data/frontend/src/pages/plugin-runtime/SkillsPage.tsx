import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { Panel, Pill, type PillTone } from "./shared";

type SkillRow = {
  skill_id: string;
  name: string;
  description?: string;
  source_repo?: string | null;
  version?: string | null;
  enabled?: boolean;
  catalog_only?: boolean;
  module_id?: string | null;
  content_hash?: string;
};

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Request failed";
}

function tone(skill: SkillRow): PillTone {
  if (skill.catalog_only) return "cyan";
  if (skill.enabled) return "ok";
  return "muted";
}

export function SkillsPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<"installed" | "catalog">("installed");
  const [query, setQuery] = useState("");
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [totals, setTotals] = useState<{ installed: number; catalog: number }>({ installed: 0, catalog: 0 });
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SkillRow | null>(null);
  const [instructions, setInstructions] = useState<string | null>(null);
  const limit = 40;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listSkills({
        query: query.trim() || undefined,
        include_catalog: tab === "catalog",
        enabled_only: tab === "installed",
        limit,
        offset,
      });
      const rows = (res.skills ?? []) as SkillRow[];
      const filtered =
        tab === "catalog"
          ? rows.filter((s) => s.catalog_only)
          : rows.filter((s) => !s.catalog_only);
      setSkills(filtered.length ? filtered : rows);
      setTotals(res.totals ?? { installed: 0, catalog: 0 });
    } catch (err) {
      setError(errorMessage(err));
      setSkills([]);
    } finally {
      setLoading(false);
    }
  }, [query, tab, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const titleCount = useMemo(
    () => (tab === "catalog" ? totals.catalog : totals.installed),
    [tab, totals],
  );

  async function onToggle(skill: SkillRow, enabled: boolean) {
    try {
      const res = await api.setSkillEnabled(skill.skill_id, enabled);
      toast(`${enabled ? "Enabled" : "Disabled"} ${skill.name}`);
      setSelected((res.skill as SkillRow) ?? skill);
      void load();
    } catch (err) {
      toast(errorMessage(err));
    }
  }

  async function onLoadInstructions(skill: SkillRow) {
    try {
      const res = await api.getSkill(skill.skill_id, true);
      setSelected(res.skill as SkillRow);
      setInstructions(String((res.skill as { instructions?: string }).instructions || ""));
    } catch (err) {
      toast(errorMessage(err));
    }
  }

  return (
    <AppShell
      modeLabel="Plugin Mode"
      searchPlaceholder="Search skills…"
      systemItems={["LLM", "NEURAL", "MEMORY", "SKILLS"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime"
    >
      <main className="lv-main lv-pr-main">
        <section className="lv-pr-hero is-image-only" aria-label="Skills">
          <div className="lv-pr-hero-media">
            <div
              className="lv-pr-hero-fallback"
              style={{
                display: "flex",
                flexDirection: "column",
                justifyContent: "flex-end",
                minHeight: 140,
                padding: "28px 32px",
                background:
                  "linear-gradient(135deg, rgba(18,22,30,0.95) 0%, rgba(28,40,34,0.9) 55%, rgba(20,28,36,0.95) 100%)",
                borderBottom: "1px solid rgba(212,175,55,0.25)",
              }}
            >
              <h1 className="lv-pr-hero-title" style={{ margin: 0, fontSize: "1.75rem", letterSpacing: "0.08em" }}>
                SKILLS
              </h1>
              <p className="lv-pr-hero-kicker" style={{ margin: "8px 0 0", opacity: 0.85 }}>
                Installed and catalog skills — metadata search only; instructions load on demand.
              </p>
            </div>
          </div>
        </section>

        <section className="lv-pr-kpi-row" aria-label="Skill KPIs">
          <article className="lv-pr-kpi">
            <div className="lv-pr-kpi-label">Installed</div>
            <div className="lv-pr-kpi-value">{totals.installed}</div>
          </article>
          <article className="lv-pr-kpi">
            <div className="lv-pr-kpi-label">Catalog</div>
            <div className="lv-pr-kpi-value">{totals.catalog}</div>
          </article>
          <article className="lv-pr-kpi">
            <div className="lv-pr-kpi-label">Page</div>
            <div className="lv-pr-kpi-value">{titleCount}</div>
            <div className="lv-pr-kpi-foot">
              <span className="lv-pr-kpi-sub">bounded list</span>
            </div>
          </article>
        </section>

        <section className="lv-pr-perf-mid">
          <Panel
            title={tab === "catalog" ? "Available catalog skills" : "Installed skills"}
            action={
              <div className="lv-pr-mcp-panel-actions">
                <button type="button" className="lv-pr-mcp-btn" onClick={() => { setTab("installed"); setOffset(0); }}>
                  Installed
                </button>
                <button type="button" className="lv-pr-mcp-btn" onClick={() => { setTab("catalog"); setOffset(0); }}>
                  Catalog
                </button>
                <input
                  className="lv-pr-mcp-input"
                  style={{ minWidth: 160 }}
                  value={query}
                  onChange={(e) => { setQuery(e.target.value); setOffset(0); }}
                  placeholder="Search…"
                  aria-label="Search skills"
                />
                <button type="button" className="lv-pr-mcp-btn" onClick={() => void load()} disabled={loading}>
                  {loading ? "Loading…" : "Refresh"}
                </button>
              </div>
            }
          >
            {error ? <p className="lv-muted" role="alert">{error}</p> : null}
            <div className="lv-pr-table-wrap">
              <table className="lv-pr-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Source</th>
                    <th>Version</th>
                    <th>State</th>
                  </tr>
                </thead>
                <tbody>
                  {!loading && skills.length === 0 ? (
                    <tr>
                      <td colSpan={4}>No skills in this page. Discover/install external skill packs first.</td>
                    </tr>
                  ) : null}
                  {skills.map((skill) => (
                    <tr
                      key={skill.skill_id}
                      className={selected?.skill_id === skill.skill_id ? "is-selected" : undefined}
                      style={{ cursor: "pointer" }}
                      onClick={() => {
                        setSelected(skill);
                        setInstructions(null);
                      }}
                    >
                      <td>
                        <strong>{skill.name}</strong>
                        <div className="lv-muted" style={{ fontSize: "0.85em" }}>
                          {(skill.description || "").slice(0, 120)}
                        </div>
                      </td>
                      <td>{skill.source_repo ?? skill.module_id ?? "—"}</td>
                      <td>{skill.version ?? "—"}</td>
                      <td>
                        <Pill tone={tone(skill)}>
                          {skill.catalog_only ? "CATALOG" : skill.enabled ? "ENABLED" : "DISABLED"}
                        </Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="lv-pr-mcp-panel-actions" style={{ marginTop: 12 }}>
              <button
                type="button"
                className="lv-pr-mcp-btn"
                disabled={offset <= 0 || loading}
                onClick={() => setOffset((v) => Math.max(0, v - limit))}
              >
                Prev
              </button>
              <button
                type="button"
                className="lv-pr-mcp-btn"
                disabled={skills.length < limit || loading}
                onClick={() => setOffset((v) => v + limit)}
              >
                Next
              </button>
              <span className="lv-muted">offset {offset}</span>
            </div>
          </Panel>

          <Panel title="Skill detail">
            {selected ? (
              <>
                <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>{selected.name}</h2>
                <Pill tone={tone(selected)}>
                  {selected.catalog_only ? "CATALOG" : selected.enabled ? "ENABLED" : "DISABLED"}
                </Pill>
                <p className="lv-muted" style={{ marginTop: 8 }}>
                  {selected.description || "No description"}
                </p>
                <p className="lv-muted" style={{ fontSize: "0.85em" }}>
                  {selected.skill_id}
                  {selected.content_hash ? ` · hash ${selected.content_hash.slice(0, 12)}` : ""}
                </p>
                <div className="lv-pr-mcp-panel-actions" style={{ marginTop: 12, gap: 8 }}>
                  {!selected.catalog_only ? (
                    <>
                      <button type="button" className="lv-pr-mcp-btn" onClick={() => void onToggle(selected, true)}>
                        Enable
                      </button>
                      <button type="button" className="lv-pr-mcp-btn" onClick={() => void onToggle(selected, false)}>
                        Disable
                      </button>
                    </>
                  ) : null}
                  <button
                    type="button"
                    className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                    onClick={() => void onLoadInstructions(selected)}
                  >
                    Load instructions
                  </button>
                </div>
                {instructions != null ? (
                  <pre
                    className="lv-pr-console-log"
                    style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto", fontSize: 12, marginTop: 12 }}
                  >
                    {instructions || "(empty)"}
                  </pre>
                ) : (
                  <p className="lv-muted" style={{ marginTop: 12 }}>
                    Instructions are not injected into prompts until explicitly loaded.
                  </p>
                )}
              </>
            ) : (
              <p className="lv-muted">Select a skill to inspect metadata and load instructions on demand.</p>
            )}
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
