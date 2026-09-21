"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Check, Cpu, Gauge, Loader2, RefreshCcw, RotateCcw, Server, ServerOff, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Panel, StatCard, StatusBadge } from "@/components/hades/ui";
import { DatasetBrainPanel } from "@/components/hades/features/training/dataset-brain-panel";
import { TrainingWorkspace } from "@/components/hades/features/training/training-workspace";
import { hadesApi, LmModel, ModelProfile, ModelsResponse, AppSettings } from "@/lib/hades-api";

const defaultProfile: ModelProfile = {
  model_id: "", temperature: .7, top_p: .95, top_k: 40, max_tokens: 2048,
  repeat_penalty: 1.05, seed: -1,
  system_prompt: "Je bent HADES, een scherpe lokale AI-assistent. Antwoord standaard in het Nederlands, wees feitelijk en benoem onzekerheid duidelijk.",
  is_active: false,
};

function ModelSlider({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return <label className="setting-slider"><span><strong>{label}</strong><output>{value.toLocaleString("nl-NL", { maximumFractionDigits: 2 })}</output></span><Slider value={[value]} min={min} max={max} step={step} onValueChange={([next]) => onChange(next)} /></label>;
}

export function ModelsPage() {
  const [data, setData] = useState<ModelsResponse>({ connected: false, models: [], active_profile: defaultProfile });
  const [selectedId, setSelectedId] = useState("");
  const [profile, setProfile] = useState<ModelProfile>(defaultProfile);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [streamSettings, setStreamSettings] = useState<Pick<AppSettings, "streaming" | "stream_provisional_text" | "progress_events_enabled">>({
    streaming: false,
    stream_provisional_text: true,
    progress_events_enabled: true,
  });
  const [streamSaving, setStreamSaving] = useState(false);
  const [routerSettings, setRouterSettings] = useState<Pick<AppSettings, "model_fallback_order" | "role_model_overrides" | "allow_cloud_model_fallback">>({
    model_fallback_order: [],
    role_model_overrides: {},
    allow_cloud_model_fallback: false,
  });
  const [routerSaving, setRouterSaving] = useState(false);

  const activeId = data.active_profile?.model_id || "";
  const selectedModel = useMemo(() => data.models.find((model) => model.id === selectedId), [data.models, selectedId]);

  const loadProfile = useCallback(async (id: string) => {
    if (!id) { setProfile(defaultProfile); return; }
    setProfile(await hadesApi.modelProfile(id));
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await hadesApi.models();
      setData(result);
      const nextId = result.active_profile?.model_id || result.models[0]?.id || "";
      setSelectedId(nextId);
      await loadProfile(nextId);
      if (!result.connected) toast.warning("LM Studio is niet bereikbaar. Start de server en laad een model.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Modellen vernieuwen is mislukt.");
    } finally {
      setLoading(false);
    }
  }, [loadProfile]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    void hadesApi.settings()
      .then((result) => {
        setStreamSettings({
          streaming: result.values.streaming,
          stream_provisional_text: result.values.stream_provisional_text,
          progress_events_enabled: result.values.progress_events_enabled,
        });
        setRouterSettings({
          model_fallback_order: result.values.model_fallback_order || [],
          role_model_overrides: result.values.role_model_overrides || {},
          allow_cloud_model_fallback: result.values.allow_cloud_model_fallback,
        });
      })
      .catch(() => undefined);
  }, []);

  const saveRouterSettings = async () => {
    setRouterSaving(true);
    try {
      const latest = await hadesApi.settings();
      const saved = await hadesApi.saveSettings({
        ...latest.values,
        model_fallback_order: routerSettings.model_fallback_order,
        role_model_overrides: routerSettings.role_model_overrides,
      });
      setRouterSettings({
        model_fallback_order: saved.values.model_fallback_order || [],
        role_model_overrides: saved.values.role_model_overrides || {},
        allow_cloud_model_fallback: saved.values.allow_cloud_model_fallback,
      });
      toast.success("Lokale modelrouter opgeslagen.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Modelrouter opslaan mislukt.");
    } finally {
      setRouterSaving(false);
    }
  };

  const saveStreamSettings = async () => {
    setStreamSaving(true);
    try {
      const latest = await hadesApi.settings();
      const saved = await hadesApi.saveSettings({ ...latest.values, ...streamSettings });
      setStreamSettings({
        streaming: saved.values.streaming,
        stream_provisional_text: saved.values.stream_provisional_text,
        progress_events_enabled: saved.values.progress_events_enabled,
      });
      toast.success("Streaming-instellingen opgeslagen.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Streaming-instellingen opslaan mislukt.");
    } finally {
      setStreamSaving(false);
    }
  };

  useEffect(() => {
    let interval: number | undefined;
    let cancelled = false;
    void hadesApi.settings().then((result) => {
      if (cancelled) return;
      const seconds = Math.max(10, Math.min(3600, Number(result.values.model_refresh_seconds) || 60));
      interval = window.setInterval(() => {
        void hadesApi.models().then((next) => {
          setData(next);
          setSelectedId((current) => current || next.active_profile?.model_id || next.models[0]?.id || "");
        }).catch(() => undefined);
      }, seconds * 1000);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
      if (interval) window.clearInterval(interval);
    };
  }, []);

  const selectModel = async (model: LmModel) => {
    setSelectedId(model.id);
    try { await loadProfile(model.id); } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Profiel laden is mislukt."); }
  };

  const save = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      const saved = await hadesApi.saveModelProfile(selectedId, {
        temperature: profile.temperature, top_p: profile.top_p, top_k: profile.top_k,
        max_tokens: profile.max_tokens, repeat_penalty: profile.repeat_penalty,
        seed: profile.seed, system_prompt: profile.system_prompt, make_active: true,
      });
      setProfile(saved);
      setData((current) => ({ ...current, active_profile: saved }));
      toast.success("Modelprofiel opgeslagen en geactiveerd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const result = await hadesApi.testConnection();
      if (!result.connected || Number(result.models || 0) <= 0) {
        toast.error("Verbindingstest: geen geladen LM Studio-modellen.");
      } else {
        toast.success(`Verbinding geslaagd: ${result.models} model(len), ${result.latency_ms} ms.`);
      }
      await refresh();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Verbindingstest is mislukt.");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="page page-models">
      <PageHeader title="Modellen" description="Ontdek geladen LM Studio-modellen en beheer echte generatieprofielen." actions={<><Button variant="outline" onClick={test} disabled={testing}>{testing ? <Loader2 className="spin" /> : <Activity />}Verbinding testen</Button><Button onClick={refresh} disabled={loading}>{loading ? <Loader2 className="spin" /> : <RefreshCcw />}Modellen vernieuwen</Button></>} />
      <section className="stat-grid four"><StatCard label="Verbinding" value={data.connected ? "Verbonden" : "Offline"} note="OpenAI-compatible API" icon={data.connected ? <Server /> : <ServerOff />} /><StatCard label="Beschikbaar" value={String(data.models.length)} note="Door LM Studio gemeld" icon={<Sparkles />} /><StatCard label="Actief profiel" value={activeId ? "1" : "0"} note={activeId || "Niet ingesteld"} icon={<Cpu />} /><StatCard label="Laatste test" value={data.latency_ms ? `${data.latency_ms} ms` : "—"} note="GET /v1/models" icon={<Gauge />} /></section>
      {data.gateway ? (
        <Panel title="Model gateway (gedeelde capaciteit)" actions={<StatusBadge tone={data.gateway.active_count ? "info" : "neutral"}>{data.gateway.active_count} actief · wachtrij {data.gateway.queue_depth}</StatusBadge>}>
          <div className="mini-grid">
            <div>
              <span>Modellen in gebruik</span>
              <strong>{(data.gateway.models_in_use || []).join(", ") || "—"}</strong>
              <small>Geen verzonnen VRAM/kwaliteitscijfers</small>
            </div>
            <div>
              <span>Capaciteit</span>
              <strong>
                {String((data.gateway.capacity as { global_inflight?: number })?.global_inflight ?? 0)}
                {" / "}
                {((data.gateway.capacity as { global_limit?: number | null })?.global_limit ?? null) === null
                  ? "Unlimited"
                  : String((data.gateway.capacity as { global_limit?: number | null })?.global_limit)}
              </strong>
              <small>Globaal (None = Unlimited)</small>
            </div>
            <div>
              <span>Fallback-reden</span>
              <strong>{data.gateway.fallback_reason || "—"}</strong>
              <small>Laatste router/gateway fallback</small>
            </div>
            <div>
              <span>Fouten</span>
              <strong>{String((data.gateway.errors as { last_error?: string | null })?.last_error || "geen")}</strong>
              <small>
                mislukt {String((data.gateway.errors as { calls_failed?: number })?.calls_failed ?? 0)} ·
                capaciteit-timeouts {String((data.gateway.errors as { capacity_timeouts?: number })?.capacity_timeouts ?? 0)}
              </small>
            </div>
          </div>
        </Panel>
      ) : null}
      {!data.connected ? <div className="page-warning"><ServerOff /><span><strong>LM Studio is niet verbonden.</strong><small>{data.error || "Start de lokale server op poort 1234 en laad minimaal één model."}</small></span></div> : null}
      <div className="model-layout">
        <Panel title="Ontdekte modellen" actions={<StatusBadge tone={data.connected ? "success" : "warning"}>{loading ? "Vernieuwen…" : `${data.models.length} gevonden`}</StatusBadge>}>
          <div className="model-list">{data.models.map((model) => <article role="button" tabIndex={0} className={model.id === selectedId ? "model-row active functional-model-row" : "model-row functional-model-row"} key={model.id} onClick={() => selectModel(model)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void selectModel(model); } }}><span className="radio-dot">{model.id === selectedId ? <i /> : null}</span><div className="model-name"><strong>{model.id}</strong><small>{model.owned_by || "LM Studio"}</small></div><span><small>Type</small><strong>{model.object || "model"}</strong></span><div className="model-status"><StatusBadge tone="success">Beschikbaar</StatusBadge>{model.id === activeId ? <StatusBadge tone="info">Actief</StatusBadge> : null}</div><div className="model-actions"><StatusBadge tone={model.id === selectedId ? "info" : "neutral"}>{model.id === selectedId ? "Geselecteerd" : "Open profiel"}</StatusBadge></div></article>)}{!data.models.length && !loading ? <div className="table-empty">Geen modellen beschikbaar. Controleer LM Studio en klik daarna op vernieuwen.</div> : null}</div>
        </Panel>
        <div className="details-stack">
          <Panel title={selectedModel?.id || "Modelprofiel"} actions={selectedId && selectedId === activeId ? <StatusBadge tone="success">Actief</StatusBadge> : <StatusBadge>Niet actief</StatusBadge>}>
            {selectedId ? <><div className="slider-grid"><ModelSlider label="Temperatuur" value={profile.temperature} min={0} max={2} step={.05} onChange={(value) => setProfile({ ...profile, temperature: value })} /><ModelSlider label="Top P" value={profile.top_p} min={.05} max={1} step={.05} onChange={(value) => setProfile({ ...profile, top_p: value })} /><ModelSlider label="Top K" value={profile.top_k} min={0} max={200} step={1} onChange={(value) => setProfile({ ...profile, top_k: value })} /><ModelSlider label="Repeat penalty" value={profile.repeat_penalty} min={.5} max={2} step={.05} onChange={(value) => setProfile({ ...profile, repeat_penalty: value })} /></div><div className="form-grid two"><label><span>Max. tokens</span><Input type="number" min={1} max={131072} value={profile.max_tokens} onChange={(event) => setProfile({ ...profile, max_tokens: Number(event.target.value) })} /></label><label><span>Seed <small>-1 is willekeurig</small></span><Input type="number" min={-1} value={profile.seed} onChange={(event) => setProfile({ ...profile, seed: Number(event.target.value) })} /></label></div><label className="prompt-field"><span>Systeemprompt</span><Textarea value={profile.system_prompt} onChange={(event) => setProfile({ ...profile, system_prompt: event.target.value })} /></label><div className="button-row end"><Button variant="outline" onClick={() => loadProfile(selectedId)}><RotateCcw />Niet-opgeslagen herstellen</Button><Button onClick={save} disabled={saving}>{saving ? <Loader2 className="spin" /> : <Check />}Opslaan en activeren</Button></div></> : <p className="empty-copy">Selecteer eerst een model uit LM Studio.</p>}
          </Panel>
          <Panel title="Lokale modelrouter">
            <p className="panel-copy">
              Kies fallback-volgorde en rol→model overrides voor de lokale LM Studio-router. Expliciete chat/taakkeuze blijft leidend.
            </p>
            <div className="form-stack">
              <label>
                <span>Fallback-modellen (kommagescheiden)</span>
                <Input
                  value={(routerSettings.model_fallback_order || []).join(", ")}
                  onChange={(event) => setRouterSettings({
                    ...routerSettings,
                    model_fallback_order: event.target.value.split(",").map((item) => item.trim()).filter(Boolean),
                  })}
                  placeholder="snel-model, diep-model, code-model"
                />
                <small>Alleen lokale model-ID&apos;s uit LM Studio. De router probeert deze volgorde bij bezet of mislukte calls.</small>
              </label>
              <label>
                <span>Rol→model overrides (JSON)</span>
                <Textarea
                  value={JSON.stringify(routerSettings.role_model_overrides || {}, null, 0)}
                  onChange={(event) => {
                    try {
                      setRouterSettings({
                        ...routerSettings,
                        role_model_overrides: JSON.parse(event.target.value || "{}") as Record<string, string>,
                      });
                    } catch {
                      /* keep typing */
                    }
                  }}
                  placeholder='{"build":"local-coder","research":"local-deep"}'
                />
                <small>Bijv. build/research/critic-rollen naar specifieke lokale modellen.</small>
              </label>
              <div className="policy-row">
                <Cpu />
                <span>
                  <strong>Cloud-fallback: {routerSettings.allow_cloud_model_fallback ? "aan" : "uit"}</strong>
                  <small>
                    Blijft uit tenzij je <code>allow_cloud_model_fallback</code> inschakelt onder Instellingen → Prestaties.
                    Lokale data gaat dan niet ongemerkt naar cloud.
                  </small>
                </span>
              </div>
            </div>
            <div className="button-row end">
              <Button variant="outline" onClick={() => void saveRouterSettings()} disabled={routerSaving}>
                {routerSaving ? <Loader2 className="spin" /> : <Check />}
                Router opslaan
              </Button>
            </div>
          </Panel>
          <Panel title="Streaming & events">
            <div className="toggle-lines">
              <label><span><strong>Streamingvoorkeur</strong><small>Voor runtimes die token-streaming ondersteunen.</small></span><Switch checked={streamSettings.streaming} onCheckedChange={(checked) => setStreamSettings({ ...streamSettings, streaming: checked })} /></label>
              <label><span><strong>Voorlopige streamtekst</strong><small>Gescheiden van geverifieerd eindresultaat in Chat.</small></span><Switch checked={streamSettings.stream_provisional_text} onCheckedChange={(checked) => setStreamSettings({ ...streamSettings, stream_provisional_text: checked })} /></label>
              <label><span><strong>Voortgangs-events</strong><small>Live tool/status-events in Chat en Taken.</small></span><Switch checked={streamSettings.progress_events_enabled} onCheckedChange={(checked) => setStreamSettings({ ...streamSettings, progress_events_enabled: checked })} /></label>
            </div>
            <div className="button-row end"><Button variant="outline" onClick={() => void saveStreamSettings()} disabled={streamSaving}>{streamSaving ? <Loader2 className="spin" /> : <Check />}Streaming opslaan</Button></div>
          </Panel>
          <Panel title="Wat deze pagina bestuurt"><div className="policy-row"><Check /><span><strong>Eén profiel per model</strong><small>Chat en Taken gebruiken automatisch het actieve profiel. Laden en ontladen blijft bewust in LM Studio zelf.</small></span></div></Panel>
        </div>
      </div>
      <TrainingWorkspace />
      <DatasetBrainPanel />
    </div>
  );
}