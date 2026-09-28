/** Pure view-model helpers for Skills page — derived only from real API payloads. */

export type SkillRecord = {
  skill_id: string;
  name: string;
  description?: string;
  source_repo?: string | null;
  source_path?: string | null;
  source_ref?: string | null;
  version?: string | null;
  content_hash?: string;
  instruction_artifact?: string | null;
  resource_refs?: string[];
  script_refs?: string[];
  required_capabilities?: string[];
  trigger_description?: string | null;
  enabled?: boolean;
  catalog_only?: boolean;
  module_id?: string | null;
  imported_at?: string | null;
  metadata?: Record<string, unknown>;
  instructions?: string;
  classification?: string;
  declarations?: SkillDeclarations;
  compatibility?: SkillCompatibility;
  truth?: Record<string, boolean>;
};

export type SkillDeclarations = {
  required_capabilities?: string[];
  resource_refs?: string[];
  script_refs?: string[];
  input_schema?: unknown;
  output_schema?: unknown;
  input_rows?: Array<{
    name: string;
    type: string;
    required: boolean;
    description?: string | null;
  }>;
  examples?: unknown;
  example_refs?: string[];
  frontmatter_keys?: string[];
};

export type SkillCompatibility = {
  status?: "COMPATIBLE" | "PARTIAL" | "INCOMPATIBLE" | "UNMEASURED" | string;
  reason?: string | null;
  capabilities?: Array<{ id: string; status: string }>;
  agents?: Array<{ id: string; status: string }>;
  runtimes?: Array<{
    id: string;
    adapter?: string | null;
    status?: string;
    module_status?: string | null;
  }>;
  truth?: Record<string, boolean>;
};

export type SkillTotals = {
  installed: number;
  catalog: number;
  total?: number;
  available?: number | null;
  external_packs?: number | null;
  tools?: number | null;
  issues?: number | null;
  agent_skills?: number | null;
  updates_available?: number | null;
  classifications?: Record<string, number | null | undefined>;
  truth?: Record<string, boolean>;
};

export type SkillFilter = "all" | "core" | "agent" | "external" | "tools";

export type SkillDetailTab =
  | "description"
  | "configuration"
  | "examples"
  | "input_schema"
  | "output_schema"
  | "dependencies"
  | "usage"
  | "version_history"
  | "logs";

export const SKILL_DETAIL_TABS: readonly { id: SkillDetailTab; label: string }[] = [
  { id: "description", label: "Description" },
  { id: "configuration", label: "Configuration" },
  { id: "examples", label: "Examples" },
  { id: "input_schema", label: "Input Schema" },
  { id: "output_schema", label: "Output Schema" },
  { id: "dependencies", label: "Dependencies" },
  { id: "usage", label: "Usage" },
  { id: "version_history", label: "Version History" },
  { id: "logs", label: "Logs" },
] as const;

export const UNMEASURED = "UNMEASURED";
export const EM_DASH = "—";

export function asSkill(raw: Record<string, unknown> | SkillRecord | null | undefined): SkillRecord | null {
  if (!raw || typeof raw !== "object") return null;
  const skillId = String((raw as SkillRecord).skill_id || "").trim();
  if (!skillId) return null;
  return raw as SkillRecord;
}

export function displayMetric(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return UNMEASURED;
  return String(value);
}

export function displayOptional(value: unknown): string {
  if (value == null) return EM_DASH;
  const s = String(value).trim();
  return s || EM_DASH;
}

export type KpiModel = {
  id: string;
  label: string;
  value: string;
  tone: "default" | "cyan" | "gold" | "ok" | "warn" | "err";
  measured: boolean;
};

export function buildKpiModels(totals: SkillTotals | null): KpiModel[] {
  const t = totals ?? { installed: 0, catalog: 0 };
  const total =
    t.total != null ? t.total : (t.installed ?? 0) + (t.catalog ?? 0);
  return [
    {
      id: "total",
      label: "Total Skills",
      value: displayMetric(total),
      tone: "default",
      measured: true,
    },
    {
      id: "available",
      label: "Available",
      value: displayMetric(t.available),
      tone: "ok",
      measured: t.available != null,
    },
    {
      id: "external_packs",
      label: "External Packs",
      value: displayMetric(t.external_packs),
      tone: "cyan",
      measured: t.external_packs != null,
    },
    {
      id: "agent_skills",
      label: "Agent Skills",
      value: displayMetric(t.agent_skills),
      tone: "cyan",
      measured: t.agent_skills != null,
    },
    {
      id: "issues",
      label: "Issues",
      value: displayMetric(t.issues),
      tone: "err",
      measured: t.issues != null,
    },
    {
      id: "updates",
      label: "Updates Available",
      value: displayMetric(t.updates_available),
      tone: "cyan",
      measured: t.updates_available != null,
    },
  ];
}

export type FilterChipModel = {
  id: SkillFilter;
  label: string;
  count: string;
  enabled: boolean;
  reason?: string;
};

export function buildFilterChips(totals: SkillTotals | null): FilterChipModel[] {
  const c = totals?.classifications ?? {};
  const all = c.all ?? totals?.total ?? ((totals?.installed ?? 0) + (totals?.catalog ?? 0));
  return [
    { id: "all", label: "All", count: displayMetric(all), enabled: true },
    {
      id: "core",
      label: "Core",
      count: displayMetric(c.core ?? totals?.installed),
      enabled: true,
    },
    {
      id: "agent",
      label: "Agent",
      count: displayMetric(c.agent ?? totals?.agent_skills),
      enabled: false,
      reason: "Agent SkillLibrary is not projected on /api/skills",
    },
    {
      id: "external",
      label: "External",
      count: displayMetric(c.external ?? totals?.catalog),
      enabled: true,
    },
    {
      id: "tools",
      label: "Tools",
      count: displayMetric(c.tools ?? totals?.tools),
      enabled: true,
    },
  ];
}

export function skillStateLabel(skill: SkillRecord): string {
  if (skill.catalog_only) return "CATALOG";
  if (skill.enabled) return "AVAILABLE";
  return "DISABLED";
}

export function skillStateTone(skill: SkillRecord): "ok" | "cyan" | "muted" | "warn" | "err" {
  if (skill.catalog_only) return "cyan";
  if (skill.enabled) return "ok";
  return "muted";
}

export function skillCategoryLabel(skill: SkillRecord): string {
  const meta = skill.metadata || {};
  const tagged = meta.category ?? meta.type ?? meta.kind;
  if (typeof tagged === "string" && tagged.trim()) return tagged.trim().toUpperCase();
  if (skill.catalog_only) return "EXTERNAL";
  if ((skill.script_refs || []).length > 0) return "TOOLS";
  return "CORE";
}

export function skillTypeLabel(skill: SkillRecord): string {
  const meta = skill.metadata || {};
  const tagged = meta.type ?? meta.skill_type;
  if (typeof tagged === "string" && tagged.trim()) return tagged.trim();
  if ((skill.script_refs || []).length > 0) return "Script package";
  if (skill.catalog_only) return "Catalog entry";
  return "Instruction skill";
}

export function skillSourceLabel(skill: SkillRecord): string {
  if (skill.source_repo) return String(skill.source_repo);
  if (skill.module_id) return String(skill.module_id);
  if (skill.catalog_only) return "External catalog";
  return "Installed skill fabric";
}

export type ActionModel = {
  id: string;
  label: string;
  enabled: boolean;
  reason?: string;
  primary?: boolean;
};

export function buildActionModels(skill: SkillRecord | null): ActionModel[] {
  if (!skill) {
    return [
      "execute",
      "configure",
      "test",
      "examples",
      "edit",
      "disable",
      "update",
      "clone",
      "more",
    ].map((id) => ({
      id,
      label: id === "examples" ? "View Examples" : id === "more" ? "More" : id[0]!.toUpperCase() + id.slice(1),
      enabled: false,
      reason: "Select a skill",
    }));
  }

  const required = skill.required_capabilities || skill.declarations?.required_capabilities || [];
  const hasExecutable = !skill.catalog_only && required.length > 0;
  const hasExamples =
    Boolean(skill.declarations?.examples) ||
    (skill.declarations?.example_refs || []).length > 0 ||
    (skill.resource_refs || []).some((r) => r.toLowerCase().includes("example"));
  const canToggle = !skill.catalog_only;
  const canUpdate = Boolean(skill.module_id);
  const canConfigure = Boolean(skill.module_id);

  return [
    {
      id: "execute",
      label: "Execute",
      enabled: hasExecutable,
      primary: true,
      reason: hasExecutable
        ? undefined
        : skill.catalog_only
          ? "Catalog-only skill; no executable capability"
          : "Instruction-only skill; no executable capability",
    },
    {
      id: "configure",
      label: "Configure",
      enabled: canConfigure,
      reason: canConfigure
        ? "Opens parent module configuration surface"
        : "No owning module configuration surface",
    },
    {
      id: "test",
      label: "Test",
      enabled: true,
      reason: undefined,
    },
    {
      id: "examples",
      label: "View Examples",
      enabled: true,
      reason: hasExamples ? undefined : "No examples declared",
    },
    {
      id: "edit",
      label: "Edit",
      enabled: false,
      reason: "No canonical writable user-owned skill editor",
    },
    {
      id: "disable",
      label: skill.enabled && !skill.catalog_only ? "Disable" : "Enable",
      enabled: canToggle,
      reason: canToggle ? undefined : "Catalog-only skills cannot be enabled as installed authority",
    },
    {
      id: "update",
      label: "Update",
      enabled: canUpdate,
      reason: canUpdate
        ? "Routes through parent module version machinery"
        : "No owning module for update checks",
    },
    {
      id: "clone",
      label: "Clone",
      enabled: false,
      reason: "No canonical user-owned derived-skill model",
    },
    {
      id: "more",
      label: "More",
      enabled: true,
      reason: undefined,
    },
  ];
}

export type InfoField = { label: string; value: string; tone?: "ok" | "default" };

export function buildInfoFields(skill: SkillRecord): InfoField[] {
  return [
    { label: "Name", value: displayOptional(skill.name) },
    { label: "Category", value: skillCategoryLabel(skill) },
    { label: "Type", value: skillTypeLabel(skill) },
    { label: "Source", value: skillSourceLabel(skill) },
    { label: "Author", value: displayOptional((skill.metadata || {}).author) },
    { label: "Created", value: displayOptional(skill.imported_at) },
    {
      label: "Updated",
      value: displayOptional((skill.metadata || {}).updated_at ?? skill.imported_at),
    },
    {
      label: "Usage Count",
      value:
        typeof (skill.metadata || {}).usage_count === "number"
          ? String((skill.metadata || {}).usage_count)
          : UNMEASURED,
    },
    {
      label: "Success Rate",
      value:
        typeof (skill.metadata || {}).success_rate === "number"
          ? `${(skill.metadata || {}).success_rate}%`
          : UNMEASURED,
      tone:
        typeof (skill.metadata || {}).success_rate === "number" ? "ok" : "default",
    },
  ];
}

export function truncate(text: string | null | undefined, max = 90): string {
  const s = (text || "").trim();
  if (!s) return "";
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}

export function versionLabel(skill: SkillRecord): string | null {
  const v = (skill.version || "").trim();
  if (!v) return null;
  return v.startsWith("v") ? v : `v${v}`;
}

export function hasFakeScreenshotMetrics(source: string): boolean {
  // Guard against hardcoded reference screenshot KPI literals in page source.
  const banned = [
    /128\s*Total Skills/i,
    /96\s*Available/i,
    /24\s*External Packs/i,
    /18\s*Agent Skills/i,
    /3\s*Issues/i,
    /5\s*Updates Available/i,
  ];
  return banned.some((re) => re.test(source));
}
