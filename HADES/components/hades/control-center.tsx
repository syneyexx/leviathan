"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Loader2, RefreshCcw, RotateCcw, Save, Search, ShieldAlert, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { ControlDefinition, ControlEffectiveValue, ControlPreset, hadesApi } from "@/lib/hades-api";

const RISK_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  low: "success",
  medium: "warning",
  high: "danger",
  critical: "danger",
};

function formatValue(value: unknown): string {
  if (value === null) return "Unlimited";
  if (value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatEffective(eff: ControlEffectiveValue | undefined): string {
  if (!eff) return "— (not resolved)";
  const base = formatValue(eff.effective);
  const bits: string[] = [base];
  if (eff.unlimited_requested) bits.push("requested Unlimited");
  if (eff.clamped) bits.push(`clamped${eff.clamp_reason ? `: ${eff.clamp_reason}` : ""}`);
  if (eff.capability_max !== null && eff.capability_max !== undefined) {
    bits.push(`capability_max=${formatValue(eff.capability_max)}`);
  }
  bits.push(`source=${eff.source}`);
  return bits.join(" · ");
}

export function HadesControlCenter() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [definitions, setDefinitions] = useState<ControlDefinition[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [effective, setEffective] = useState<Record<string, ControlEffectiveValue>>({});
  const [presets, setPresets] = useState<ControlPreset[]>([]);
  const [immutable, setImmutable] = useState<Array<Record<string, unknown>>>([]);
  const [limitEvents, setLimitEvents] = useState<Array<Record<string, unknown>>>([]);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [risk, setRisk] = useState<string>("all");
  const [changedOnly, setChangedOnly] = useState(false);
  const [hideUnimplemented, setHideUnimplemented] = useState(true);
  const [schemaVersion, setSchemaVersion] = useState<number | null>(null);
  const [configRevision, setConfigRevision] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [defs, vals, eff, dash, limits] = await Promise.all([
        hadesApi.controlDefinitions(),
        hadesApi.controlValues(),
        hadesApi.controlEffective(),
        hadesApi.controlDashboard(),
        hadesApi.controlLimits(30),
      ]);
      setDefinitions(defs.definitions);
      setCategories(defs.categories);
      setValues(vals.values);
      setDraft({});
      setEffective(eff.effective as Record<string, ControlEffectiveValue>);
      setPresets(dash.presets || []);
      setImmutable(dash.immutable_constraints || []);
      setSchemaVersion(dash.config_schema_version ?? null);
      setConfigRevision(Number(vals.values.config_revision ?? 0));
      setLimitEvents(limits.events || []);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Control Center laden mislukt.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return definitions.filter((item) => {
      if (hideUnimplemented && item.implemented === false) return false;
      if (category !== "all" && item.category !== category) return false;
      if (risk !== "all" && item.risk_level !== risk) return false;
      const current = draft[item.storage_key] !== undefined ? draft[item.storage_key] : values[item.storage_key];
      if (changedOnly && JSON.stringify(current) === JSON.stringify(item.default_value)) return false;
      if (!needle) return true;
      return (
        item.id.toLowerCase().includes(needle) ||
        item.label.toLowerCase().includes(needle) ||
        item.description.toLowerCase().includes(needle) ||
        item.storage_key.toLowerCase().includes(needle)
      );
    });
  }, [definitions, category, risk, query, changedOnly, hideUnimplemented, draft, values]);

  const setDraftValue = (storageKey: string, value: unknown) => {
    setDraft((prev) => ({ ...prev, [storageKey]: value }));
  };

  const save = async () => {
    if (!Object.keys(draft).length) {
      toast.message("Geen wijzigingen om op te slaan.");
      return;
    }
    setSaving(true);
    try {
      const result = await hadesApi.controlPatchSettings(draft, configRevision);
      setValues(result.values);
      setConfigRevision(Number(result.config_revision ?? result.values.config_revision ?? configRevision + 1));
      setDraft({});
      const eff = await hadesApi.controlEffective();
      setEffective(eff.effective as Record<string, ControlEffectiveValue>);
      toast.success(`Control-plane instellingen opgeslagen (rev ${result.config_revision ?? "—"}).`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Opslaan mislukt.");
      if (reason && typeof reason === "object" && "status" in reason && (reason as { status: number }).status === 409) {
        await load();
      }
    } finally {
      setSaving(false);
    }
  };

  const applyPreset = async (presetId: string) => {
    try {
      const result = await hadesApi.controlApplyPreset(presetId);
      setValues(result.values);
      setDraft({});
      const eff = await hadesApi.controlEffective();
      setEffective(eff.effective as Record<string, ControlEffectiveValue>);
      toast.success(`Preset “${presetId}” toegepast.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Preset toepassen mislukt.");
    }
  };

  const resetSetting = async (item: ControlDefinition) => {
    try {
      await hadesApi.controlDeleteOverride(item.id, "global");
      setDraft((prev) => {
        const next = { ...prev };
        delete next[item.storage_key];
        return next;
      });
      await load();
      toast.success(`${item.label} gereset naar default.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Reset mislukt.");
    }
  };

  const exportConfig = async () => {
    try {
      const payload = await hadesApi.controlExport();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "hades-control-config.json";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Export mislukt.");
    }
  };

  const importConfig = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as { values?: Record<string, unknown>; overrides?: unknown[]; config_schema_version?: number };
      await hadesApi.controlImport(parsed);
      await load();
      toast.success("Control-configuratie geïmporteerd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Import mislukt.");
    }
  };

  const renderEditor = (item: ControlDefinition) => {
    const current = draft[item.storage_key] !== undefined ? draft[item.storage_key] : values[item.storage_key];
    const unlimited = item.allow_unlimited && (current === null || current === undefined);

    if (item.type === "boolean") {
      return (
        <Switch
          checked={Boolean(current)}
          onCheckedChange={(checked) => setDraftValue(item.storage_key, checked)}
        />
      );
    }

    if (item.type === "enum") {
      return (
        <Select value={String(current ?? item.default_value)} onValueChange={(value) => setDraftValue(item.storage_key, value)}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {(item.enum_values || []).map((option) => (
              <SelectItem key={option} value={option}>{option}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }

    if (item.type === "string_list") {
      const text = Array.isArray(current) ? (current as string[]).join(", ") : "";
      return (
        <Input
          value={text}
          onChange={(event) =>
            setDraftValue(
              item.storage_key,
              event.target.value.split(",").map((part) => part.trim()).filter(Boolean),
            )
          }
          placeholder="kommagescheiden"
        />
      );
    }

    if (item.type === "object") {
      return (
        <Input
          value={typeof current === "string" ? current : JSON.stringify(current ?? {})}
          onChange={(event) => {
            try {
              setDraftValue(item.storage_key, JSON.parse(event.target.value || "{}"));
            } catch {
              /* keep typing */
            }
          }}
        />
      );
    }

    if (item.type === "string") {
      return (
        <Input
          value={String(current ?? "")}
          onChange={(event) => setDraftValue(item.storage_key, event.target.value)}
        />
      );
    }

    // numeric / nullable integer / duration / bytes / tokens
    return (
      <div className="control-numeric-row">
        {item.allow_unlimited ? (
          <label className="control-unlimited-toggle">
            <Switch
              checked={unlimited}
              onCheckedChange={(checked) =>
                setDraftValue(item.storage_key, checked ? null : (item.default_value ?? 1))
              }
            />
            <span>Unlimited</span>
          </label>
        ) : null}
        {!unlimited ? (
          <Input
            type="number"
            value={current === null || current === undefined ? "" : Number(current)}
            min={item.min ?? undefined}
            max={item.max ?? undefined}
            step={item.type === "float" ? 0.01 : 1}
            onChange={(event) => {
              const raw = event.target.value;
              if (raw === "" && item.allow_unlimited) {
                setDraftValue(item.storage_key, null);
                return;
              }
              setDraftValue(item.storage_key, item.type === "float" ? Number(raw) : Number.parseInt(raw, 10));
            }}
          />
        ) : (
          <StatusBadge tone="warning">Unlimited</StatusBadge>
        )}
      </div>
    );
  };

  if (loading) {
    return <div className="control-center-loading"><Loader2 className="spin" /> Control Center laden…</div>;
  }

  return (
    <div className="control-center">
      <Panel
        title="HADES Control Center"
        actions={
          <div className="button-row">
            <Button variant="outline" onClick={() => void load()}><RefreshCcw />Vernieuwen</Button>
            <Button variant="outline" onClick={() => void exportConfig()}><Download />Export</Button>
            <label className="button-as-file">
              <Button variant="outline" asChild>
                <span><Upload />Import</span>
              </Button>
              <input
                type="file"
                accept="application/json,.json"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void importConfig(file);
                }}
              />
            </label>
            <Button onClick={() => void save()} disabled={saving || !Object.keys(draft).length}>
              {saving ? <Loader2 className="spin" /> : <Save />}Opslaan
            </Button>
          </div>
        }
      >
        <p className="panel-copy">
          Volledige policy-gedreven configuratie. Schema v{schemaVersion ?? "—"}. Wijzigingen gaan via de live control-plane API —
          geen mock data. Unlimited = JSON null.
        </p>
        <div className="control-filters form-grid two">
          <label>
            <span>Zoeken</span>
            <div className="input-with-icon"><Search /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="id, label, beschrijving…" /></div>
          </label>
          <label>
            <span>Categorie</span>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Alle</SelectItem>
                {categories.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>Risico</span>
            <Select value={risk} onValueChange={setRisk}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Alle</SelectItem>
                <SelectItem value="low">low</SelectItem>
                <SelectItem value="medium">medium</SelectItem>
                <SelectItem value="high">high</SelectItem>
                <SelectItem value="critical">critical</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label className="toggle-lines">
            <span><strong>Alleen gewijzigd</strong><small>Toon settings die afwijken van de default.</small></span>
            <Switch checked={changedOnly} onCheckedChange={setChangedOnly} />
          </label>
          <label className="toggle-lines">
            <span><strong>Verberg niet-afgedwongen</strong><small>Settings met <code>implemented=false</code> worden opgeslagen maar niet gehandhaafd.</small></span>
            <Switch checked={hideUnimplemented} onCheckedChange={setHideUnimplemented} />
          </label>
        </div>
      </Panel>

      <Panel title="Presets">
        <div className="button-row" style={{ flexWrap: "wrap", gap: 8 }}>
          {presets.map((preset) => (
            <Button key={preset.id} variant="outline" onClick={() => void applyPreset(preset.id)} title={preset.description}>
              {preset.label}
            </Button>
          ))}
        </div>
        <small>Presets zijn pure waardensets — geen verborgen gedrag. Maximum Autonomy zet HADES-owned limieten op Unlimited.</small>
      </Panel>

      <Panel title={`Settings (${filtered.length})`}>
        <div className="control-settings-list">
          {filtered.map((item) => {
            const current = draft[item.storage_key] !== undefined ? draft[item.storage_key] : values[item.storage_key];
            const eff = effective[item.id];
            return (
              <article key={item.id} className="control-setting-card">
                <header>
                  <div>
                    <strong>{item.label}</strong>
                    <code>{item.id}</code>
                  </div>
                  <div className="control-setting-badges">
                    <StatusBadge tone={RISK_TONE[item.risk_level] || "neutral"}>{item.risk_level}</StatusBadge>
                    <StatusBadge tone="neutral">{item.category}</StatusBadge>
                    <StatusBadge tone="neutral">{item.apply_mode}</StatusBadge>
                    {item.implemented === false ? (
                      <StatusBadge tone="warning">niet afgedwongen</StatusBadge>
                    ) : item.implemented === true ? (
                      <StatusBadge tone="success">afgedwongen</StatusBadge>
                    ) : null}
                  </div>
                </header>
                <p>{item.description}</p>
                {item.implemented === false ? (
                  <p className="panel-copy" role="note">
                    Deze waarde wordt opgeslagen maar heeft geen runtime-consument. Wijzigen verandert het gedrag niet.
                  </p>
                ) : null}
                <div className="control-setting-editor">{renderEditor(item)}</div>
                <dl className="detail-list spaced control-effective-grid">
                  <div><dt>Configured</dt><dd>{formatValue(current)}</dd></div>
                  <div><dt>Effective</dt><dd>{formatEffective(eff)}</dd></div>
                  <div><dt>Configured</dt><dd>{formatValue(eff?.configured)}</dd></div>
                  <div><dt>Source</dt><dd>{eff?.source || "—"}</dd></div>
                  <div><dt>Default</dt><dd>{formatValue(item.default_value)}</dd></div>
                  {eff?.clamped ? <div><dt>Clamped</dt><dd>{eff.clamp_reason || "yes"}</dd></div> : null}
                </dl>
                <div className="button-row end">
                  <Button variant="outline" size="sm" onClick={() => void resetSetting(item)}><RotateCcw />Reset</Button>
                </div>
              </article>
            );
          })}
          {!filtered.length ? <p className="empty-copy">Geen settings voor deze filters.</p> : null}
        </div>
      </Panel>

      <Panel title="Limit Inspector">
        <p className="panel-copy">Waarom stopte HADES? Recente limiet-events uit de control-plane.</p>
        <div className="control-limit-list">
          {limitEvents.map((event, index) => (
            <article key={`${event.constraint_id}-${index}`} className="control-limit-card">
              <header>
                <strong>{String(event.constraint_id)}</strong>
                <StatusBadge tone="warning">{String(event.enforced_by || "runtime")}</StatusBadge>
              </header>
              <dl className="detail-list spaced">
                <div><dt>Configured</dt><dd>{formatValue(event.configured)}</dd></div>
                <div><dt>Effective</dt><dd>{formatValue(event.effective)}</dd></div>
                <div><dt>Current</dt><dd>{formatValue(event.current)}</dd></div>
                <div><dt>Scope</dt><dd>{String(event.scope || "—")}</dd></div>
                <div><dt>Source</dt><dd>{String(event.source || "—")}</dd></div>
                <div><dt>When</dt><dd>{String(event.timestamp || "—")}</dd></div>
              </dl>
              {event.message ? <p>{String(event.message)}</p> : null}
            </article>
          ))}
          {!limitEvents.length ? <p className="empty-copy">Nog geen limiet-events. Events verschijnen wanneer een runtime-plafond wordt bereikt.</p> : null}
        </div>
      </Panel>

      <Panel title="Immutable Constraints">
        <div className="control-immutable-list">
          {immutable.map((item) => (
            <article key={String(item.id)} className="control-immutable-card">
              <header>
                <ShieldAlert />
                <strong>{String(item.label)}</strong>
              </header>
              <dl className="detail-list spaced">
                <div><dt>ID</dt><dd><code>{String(item.id)}</code></dd></div>
                <div><dt>Value</dt><dd>{formatValue(item.value)}</dd></div>
                <div><dt>Source</dt><dd>{String(item.source)}</dd></div>
                <div><dt>Enforced</dt><dd><code>{String(item.enforcement_location)}</code></dd></div>
              </dl>
              <p>{String(item.reason)}</p>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}
