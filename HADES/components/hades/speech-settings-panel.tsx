"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCcw, Volume2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { AppSettings, SpeechStatus, hadesApi } from "@/lib/hades-api";
import { hadesSpeechPlayer } from "@/lib/hades-speech";

type Props = {
  settings: AppSettings;
  setSettings: (next: AppSettings) => void;
};

export function SpeechSettingsPanel({ settings, setSettings }: Props) {
  const [status, setStatus] = useState<SpeechStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await hadesApi.speechStatus());
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Spraakstatus laden mislukt.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, settings.tts_provider, settings.tts_base_url, settings.tts_model, settings.tts_voice_id]);

  const supported = status?.tts?.supported_settings || {};
  const voices = status?.tts?.voices || [];
  const engines = status?.tts?.engines || [];
  const recovery = status?.tts?.recovery || [];

  const preview = async () => {
    setPreviewing(true);
    try {
      await hadesSpeechPlayer.preview();
      toast.success("Voorbeeldstem afgespeeld.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Voorbeeldbeluistering mislukt.");
      await refresh();
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <div className="settings-top-grid">
      <Panel
        title="Gesproken antwoorden (TTS)"
        actions={
          <StatusBadge tone={status?.tts?.available ? "success" : settings.tts_provider === "voicestudio" ? "warning" : "neutral"}>
            {status?.tts?.available ? "VoiceStudio bereikbaar" : settings.tts_provider === "voicestudio" ? "Niet bereikbaar" : "Uit"}
          </StatusBadge>
        }
      >
        <p className="panel-copy">
          Het LM Studio-taalmodel en de stemmotor zijn onafhankelijk. Wisselen van chatmodel reset het stemprofiel niet.
          Geen stille cloud-fallback: zonder VoiceStudio blijft tekstchat werken.
        </p>
        <div className="toggle-lines">
          <label>
            <span>
              <strong>Gesproken antwoorden</strong>
              <small>Lees definitieve assistentantwoorden automatisch voor (geen redenering/tool/code).</small>
            </span>
            <Switch
              checked={settings.spoken_answers_enabled}
              onCheckedChange={(checked) => setSettings({ ...settings, spoken_answers_enabled: checked })}
            />
          </label>
        </div>
        <div className="form-grid two">
          <label>
            <span>TTS-provider</span>
            <Select
              value={settings.tts_provider}
              onValueChange={(value: AppSettings["tts_provider"]) => setSettings({ ...settings, tts_provider: value })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Geen</SelectItem>
                <SelectItem value="voicestudio">VoiceStudio (lokaal)</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>TTS base URL</span>
            <Input
              value={settings.tts_base_url}
              onChange={(event) => setSettings({ ...settings, tts_base_url: event.target.value })}
              placeholder="http://127.0.0.1:3900/v1"
            />
          </label>
        </div>
        {settings.tts_provider === "voicestudio" ? (
          <>
            <div className="form-grid two">
              {supported.model !== false ? (
                <label>
                  <span>TTS-model / engine</span>
                  <Select value={settings.tts_model} onValueChange={(value) => setSettings({ ...settings, tts_model: value })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="tts-1">tts-1 (actieve engine)</SelectItem>
                      <SelectItem value="tts-1-hd">tts-1-hd (actieve engine)</SelectItem>
                      {engines.map((engine) => {
                        const id = String(engine.id || "");
                        if (!id) return null;
                        return (
                          <SelectItem value={id} key={id}>
                            {String(engine.display_name || id)}
                            {engine.available === false ? " (niet beschikbaar)" : ""}
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                </label>
              ) : null}
              {supported.voice !== false ? (
                <label>
                  <span>Standaardstem</span>
                  <Select value={settings.tts_voice_id} onValueChange={(value) => setSettings({ ...settings, tts_voice_id: value })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">default</SelectItem>
                      {voices.map((voice) => {
                        const id = String(voice.voice_id || "");
                        if (!id || id === "default") return null;
                        return (
                          <SelectItem value={id} key={id}>
                            {String(voice.name || id)}
                            {voice.type ? ` · ${String(voice.type)}` : ""}
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                </label>
              ) : null}
            </div>
            <div className="form-grid two">
              {supported.speed !== false ? (
                <label>
                  <span>Snelheid</span>
                  <Input
                    type="number"
                    min={0.25}
                    max={4}
                    step={0.05}
                    value={settings.tts_speed}
                    onChange={(event) => setSettings({ ...settings, tts_speed: Number(event.target.value) })}
                  />
                </label>
              ) : null}
              {supported.language !== false ? (
                <label>
                  <span>TTS-taal</span>
                  <Input value={settings.tts_language} onChange={(event) => setSettings({ ...settings, tts_language: event.target.value })} />
                </label>
              ) : null}
              {supported.response_format !== false ? (
                <label>
                  <span>Audioformaat</span>
                  <Select
                    value={settings.tts_response_format}
                    onValueChange={(value: AppSettings["tts_response_format"]) => setSettings({ ...settings, tts_response_format: value })}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="wav">wav</SelectItem>
                      <SelectItem value="mp3">mp3</SelectItem>
                      <SelectItem value="flac">flac</SelectItem>
                      <SelectItem value="opus">opus</SelectItem>
                      <SelectItem value="aac">aac</SelectItem>
                      <SelectItem value="pcm">pcm</SelectItem>
                    </SelectContent>
                  </Select>
                </label>
              ) : null}
              <label>
                <span>Min. vrij RAM (MB)</span>
                <Input
                  type="number"
                  min={0}
                  value={settings.tts_min_free_ram_mb}
                  onChange={(event) => setSettings({ ...settings, tts_min_free_ram_mb: Number(event.target.value) })}
                />
              </label>
              <label>
                <span>Min. vrije VRAM (MB)</span>
                <Input
                  type="number"
                  min={0}
                  value={settings.tts_min_free_vram_mb}
                  onChange={(event) => setSettings({ ...settings, tts_min_free_vram_mb: Number(event.target.value) })}
                />
                <small>0 = niet afdwingen wanneer VRAM onbekend is.</small>
              </label>
            </div>
            <div className="toggle-lines">
              <label>
                <span>
                  <strong>Zinsgewijze voorleesvolgorde</strong>
                  <small>
                    HADES splitst zinnen voor snellere eerste audio. VoiceStudio zelf levert per verzoek een compleet audioclip
                    (geen PCM/SSE-stream).
                  </small>
                </span>
                <Switch
                  checked={settings.tts_sentence_chunking}
                  onCheckedChange={(checked) => setSettings({ ...settings, tts_sentence_chunking: checked })}
                />
              </label>
            </div>
            {supported.instruct ? (
              <label className="form-stack">
                <span>Instruct (engine-ondersteund)</span>
                <Input value={settings.tts_instruct} onChange={(event) => setSettings({ ...settings, tts_instruct: event.target.value })} />
              </label>
            ) : null}
            {supported.description ? (
              <label className="form-stack">
                <span>Description / voice design (engine-ondersteund)</span>
                <Input value={settings.tts_description} onChange={(event) => setSettings({ ...settings, tts_description: event.target.value })} />
              </label>
            ) : null}
            <label className="form-stack">
              <span>Optionele API-key</span>
              <Input
                type="password"
                value={settings.tts_api_key}
                onChange={(event) => setSettings({ ...settings, tts_api_key: event.target.value })}
                placeholder="alleen als VoiceStudio OMNIVOICE_API_KEY vereist"
              />
            </label>
            <div className="button-row" style={{ flexWrap: "wrap", gap: 8 }}>
              <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
                {loading ? <Loader2 className="spin" /> : <RefreshCcw />}Status vernieuwen
              </Button>
              <Button onClick={() => void preview()} disabled={previewing || !status?.tts?.available}>
                {previewing ? <Loader2 className="spin" /> : <Volume2 />}Voorbeeldbeluisteren
              </Button>
            </div>
            {!status?.tts?.available && settings.tts_provider === "voicestudio" ? (
              <div className="inline-error" style={{ marginTop: 12 }}>
                <div>
                  <strong>VoiceStudio niet beschikbaar</strong>
                  <p>{status?.tts?.error || "Start VoiceStudio lokaal. Tekstchat blijft werken; er is geen stille fallback naar een andere stem of cloud."}</p>
                  <ul>
                    {recovery.map((item) => (
                      <li key={item.id || item.label}>
                        {item.href ? <a href={item.href} target="_blank" rel="noreferrer">{item.label}</a> : item.label}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : null}
            <small>
              Ontdekte API: GET /v1/audio/voices, POST /v1/audio/speech
              {status?.tts?.version ? ` · versiehint: ${status.tts.version}` : " · geen versieveld gerapporteerd"}
              {" · "}streaming_speech={String(Boolean(status?.tts?.streaming_speech))}
            </small>
          </>
        ) : null}
      </Panel>

      <Panel title="Spraakherkenning (STT)" actions={<StatusBadge tone="info">Apart van TTS</StatusBadge>}>
        <p className="panel-copy">
          Microfoon/STT is apart configureerbaar. Standaard blijft het bestaande plakpad (`paste` / local-stt-paste / Taken → Spraak).
          Echo-guard voorkomt dat luidsprekeruitvoer opnieuw als gebruikersinvoer wordt verwerkt.
        </p>
        <div className="form-grid two">
          <label>
            <span>STT-provider</span>
            <Select
              value={settings.stt_provider}
              onValueChange={(value: AppSettings["stt_provider"]) => setSettings({ ...settings, stt_provider: value })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Uit</SelectItem>
                <SelectItem value="paste">Plak / lokale STT (bestaand)</SelectItem>
                <SelectItem value="voicestudio">VoiceStudio ASR</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>Echo-guard (ms)</span>
            <Input
              type="number"
              min={0}
              max={10000}
              value={settings.stt_echo_guard_ms}
              onChange={(event) => setSettings({ ...settings, stt_echo_guard_ms: Number(event.target.value) })}
            />
          </label>
        </div>
        {settings.stt_provider === "voicestudio" ? (
          <div className="form-grid two">
            <label>
              <span>STT base URL</span>
              <Input value={settings.stt_base_url} onChange={(event) => setSettings({ ...settings, stt_base_url: event.target.value })} />
            </label>
            <label>
              <span>STT-model</span>
              <Input value={settings.stt_model} onChange={(event) => setSettings({ ...settings, stt_model: event.target.value })} />
            </label>
            <label>
              <span>STT-taal</span>
              <Input value={settings.stt_language} onChange={(event) => setSettings({ ...settings, stt_language: event.target.value })} />
            </label>
            <label>
              <span>STT API-key</span>
              <Input type="password" value={settings.stt_api_key} onChange={(event) => setSettings({ ...settings, stt_api_key: event.target.value })} />
            </label>
          </div>
        ) : null}
        {status?.echo_guard ? (
          <small>
            Echo-guard nu: {status.echo_guard.blocked ? `geblokkeerd (${status.echo_guard.remaining_ms} ms)` : "vrij"}
          </small>
        ) : null}
      </Panel>
    </div>
  );
}
