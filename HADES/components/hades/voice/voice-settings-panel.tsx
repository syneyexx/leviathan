"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Mic, Volume2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { VoiceSetupWizard } from "@/components/hades/voice/voice-setup-wizard";
import { AudioCapture, enumerateAudioDevices, voiceMediaSupported } from "@/lib/hades-voice/audio-capture";
import { voiceApi } from "@/lib/hades-voice/api";
import type { AudioDeviceInfo } from "@/lib/hades-voice/types";
import { AppSettings, hadesApi } from "@/lib/hades-api";

type Props = {
  settings: AppSettings;
  setSettings: (next: AppSettings) => void;
};

export function VoiceSettingsPanel({ settings, setSettings }: Props) {
  const [devices, setDevices] = useState<AudioDeviceInfo[]>([]);
  const [outputDevices, setOutputDevices] = useState<AudioDeviceInfo[]>([]);
  const [voices, setVoices] = useState<Array<Record<string, unknown>>>([]);
  const [doctor, setDoctor] = useState<Record<string, unknown> | null>(null);
  const [testingMic, setTestingMic] = useState(false);
  const [testingVoice, setTestingVoice] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [installing, setInstalling] = useState(false);
  const [recordings, setRecordings] = useState<Array<{ session_id: string; file_count: number }>>([]);
  const [recordingsBusy, setRecordingsBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [status, voiceList, kept] = await Promise.all([
        voiceApi.voiceDoctor(),
        voiceApi.voiceVoices(settings.voice_language === "auto" ? undefined : settings.voice_language).catch(() => ({ voices: [] })),
        voiceApi.voiceRecordingsList().catch(() => ({ sessions: [] })),
      ]);
      setDoctor(status as Record<string, unknown>);
      setVoices((voiceList.voices || []) as Array<Record<string, unknown>>);
      setRecordings((kept.sessions || []).map((item) => ({ session_id: item.session_id, file_count: item.file_count })));
      if (voiceMediaSupported().ok) {
        const list = await enumerateAudioDevices();
        setDevices(list.filter((item) => item.kind === "audioinput"));
        setOutputDevices(list.filter((item) => item.kind === "audiooutput"));
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Spraakstatus laden mislukt.");
    }
  }, [settings.voice_language]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const testMic = async () => {
    const support = voiceMediaSupported();
    if (!support.ok) {
      toast.error(support.reason || "Microfoon niet beschikbaar.");
      return;
    }
    setTestingMic(true);
    let peak = 0;
    const capture = new AudioCapture({
      deviceId: settings.voice_input_device_id || null,
      mode: "push_to_talk",
      onLevel: (level) => {
        const value = Number(level) || 0;
        peak = Math.max(peak, value);
        setMicLevel(value);
      },
    });
    try {
      await capture.requestPermissionAndStart(settings.voice_input_device_id || null);
      capture.holdPushToTalk(true);
      await new Promise((resolve) => window.setTimeout(resolve, 1800));
      capture.holdPushToTalk(false);
      await capture.stop();
      setMicLevel(0);
      if (peak > 0.01) {
        toast.success("Microfoon OK — niveau gemeten.");
      } else {
        toast.message("Microfoon actief, maar geen meetbaar niveau (controleer input/device).");
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Microfoontest mislukt.");
    } finally {
      setTestingMic(false);
    }
  };

  const testVoice = async () => {
    setTestingVoice(true);
    try {
      const sample = settings.voice_language === "en"
        ? "This is a HADES voice test."
        : "Dit is een HADES stemtest.";
      const blob = await hadesApi.voiceSpeak({
        text: sample,
        already_speakable: true,
        language: settings.voice_language === "auto" ? "nl" : settings.voice_language,
        voice_id: settings.voice_tts_voice || undefined,
        speed: settings.voice_tts_speed,
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.volume = Math.max(0, Math.min(1, Number(settings.voice_tts_volume ?? 1)));
      await audio.play();
      toast.success("Stemtest afgespeeld.");
      audio.onended = () => URL.revokeObjectURL(url);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Stemtest mislukt — controleer Piper-installatie.");
    } finally {
      setTestingVoice(false);
    }
  };

  const install = async () => {
    setInstalling(true);
    try {
      const result = await voiceApi.voiceInstall({
        steps: ["deps", "whisper", "piper_voice"],
        voice_asr_model: settings.voice_asr_model,
        voice_tts_voice: settings.voice_tts_voice || "nl_NL-pim-medium",
        approved_network: true,
        approved_subprocess: true,
      });
      if (result.ok) toast.success("Spraakinstallatie voltooid.");
      else toast.error("Spraakinstallatie deels mislukt — zie herstelactie in status.");
      await refresh();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Installatie mislukt.");
    } finally {
      setInstalling(false);
    }
  };

  const ready = Boolean(doctor?.ready);

  return (
    <div className="settings-top-grid">
      <Panel
        title="Spraakstatus"
        actions={<StatusBadge tone={ready ? "success" : "warning"}>{ready ? "Klaar" : "Setup nodig"}</StatusBadge>}
      >
        <p className="panel-copy">
          Lokale ASR (faster-whisper) en TTS (Piper). Gescheiden van Spraak→taak (plak) en VoiceStudio.
        </p>
        <div className="button-row" style={{ flexWrap: "wrap", gap: 8 }}>
          <Button variant="outline" onClick={() => void refresh()}>Status vernieuwen</Button>
          <Button onClick={() => void install()} disabled={installing}>
            {installing ? <Loader2 className="spin" /> : null}
            Installatie / modellen
          </Button>
          <Button variant="outline" onClick={() => void testMic()} disabled={testingMic}>
            {testingMic ? <Loader2 className="spin" /> : <Mic />}
            Test microfoon{testingMic ? ` (${Math.round(micLevel * 100)}%)` : ""}
          </Button>
          <Button variant="outline" onClick={() => void testVoice()} disabled={testingVoice}>
            {testingVoice ? <Loader2 className="spin" /> : <Volume2 />}
            Test stem
          </Button>
        </div>
        {doctor?.checks ? (
          <ul className="health-check-list settings-health-list" style={{ marginTop: "0.75rem" }}>
            {(doctor.checks as Array<Record<string, unknown>>).map((check) => (
              <li key={String(check.id)}>
                <StatusBadge tone={check.ok ? "success" : "warning"}>{check.ok ? "ok" : "check"}</StatusBadge>
                <div>
                  <strong>{String(check.id)}</strong>
                  <small>{String(check.detail || "")}{check.recovery ? ` — ${String(check.recovery)}` : ""}</small>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </Panel>

      <Panel title="Apparaten & providers">
        <div className="toggle-lines">
          <label>
            <span><strong>Spraakfuncties</strong><small>Toon microfoon/TTS-bediening in Chat.</small></span>
            <Switch checked={settings.voice_enabled} onCheckedChange={(checked) => setSettings({ ...settings, voice_enabled: checked })} />
          </label>
          <label>
            <span><strong>Gesproken antwoorden standaard</strong><small>Nieuwe chats starten met voorlezen aan.</small></span>
            <Switch checked={settings.voice_spoken_answers_default} onCheckedChange={(checked) => setSettings({ ...settings, voice_spoken_answers_default: checked })} />
          </label>
          <label>
            <span><strong>Onderbreken tijdens spreken</strong><small>Praat over HADES heen om audio te stoppen.</small></span>
            <Switch checked={settings.voice_barge_in} onCheckedChange={(checked) => setSettings({ ...settings, voice_barge_in: checked })} />
          </label>
          <label>
            <span><strong>Activatiewoord “Hades”</strong><small>Standaard uit. Lokale herkenning via Whisper.</small></span>
            <Switch checked={settings.voice_wake_word_enabled} onCheckedChange={(checked) => setSettings({ ...settings, voice_wake_word_enabled: checked })} />
          </label>
          <label>
            <span><strong>Opnamen bewaren</strong><small>Standaard alleen tijdelijk voor verwerking.</small></span>
            <Switch checked={settings.voice_keep_recordings} onCheckedChange={(checked) => setSettings({ ...settings, voice_keep_recordings: checked })} />
          </label>
        </div>
        {recordings.length ? (
          <div className="form-stack" style={{ marginTop: "0.75rem", gap: "0.4rem" }}>
            <small>Bewaarde sessie-opnamen ({recordings.length})</small>
            {recordings.map((item) => (
              <div key={item.session_id} className="button-row" style={{ justifyContent: "space-between" }}>
                <span style={{ fontSize: "0.75rem" }}>{item.session_id} · {item.file_count} bestand(en)</span>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={recordingsBusy}
                  onClick={() => {
                    setRecordingsBusy(true);
                    void voiceApi.voiceRecordingsDelete(item.session_id)
                      .then((result) => {
                        if (result && result.ok === false) {
                          throw new Error(String((result as { error?: string }).error || "Verwijderen mislukt."));
                        }
                        return refresh();
                      })
                      .then(() => toast.success("Opnamen verwijderd."))
                      .catch((reason) => toast.error(reason instanceof Error ? reason.message : "Verwijderen mislukt."))
                      .finally(() => setRecordingsBusy(false));
                  }}
                >
                  Verwijder
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <small style={{ display: "block", marginTop: "0.5rem" }}>Geen bewaarde opnamen op schijf.</small>
        )}
        <div className="form-grid two">
          <label>
            <span>Invoermicrofoon</span>
            {devices.length ? (
              <Select value={settings.voice_input_device_id || "default"} onValueChange={(value) => setSettings({ ...settings, voice_input_device_id: value === "default" ? "" : value })}>
                <SelectTrigger><SelectValue placeholder="Systeemstandaard" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">Systeemstandaard</SelectItem>
                  {devices.map((device) => (
                    <SelectItem key={device.deviceId} value={device.deviceId}>{device.label || device.deviceId}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input value="Systeemstandaard (browser biedt geen apparaatlijst)" disabled />
            )}
          </label>
          <label>
            <span>Uitvoerapparaat</span>
            {outputDevices.length ? (
              <Select value={settings.voice_output_device_id || "default"} onValueChange={(value) => setSettings({ ...settings, voice_output_device_id: value === "default" ? "" : value })}>
                <SelectTrigger><SelectValue placeholder="Systeemstandaard" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">Systeemstandaard</SelectItem>
                  {outputDevices.map((device) => (
                    <SelectItem key={device.deviceId} value={device.deviceId}>{device.label || device.deviceId}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input value={settings.voice_output_device_id} onChange={(event) => setSettings({ ...settings, voice_output_device_id: event.target.value })} placeholder="leeg = standaard (setSinkId-id)" />
            )}
          </label>
          <label>
            <span>ASR-provider</span>
            <Select value={settings.voice_asr_provider} onValueChange={(value) => setSettings({ ...settings, voice_asr_provider: value })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="faster_whisper">Faster-Whisper</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>ASR-model</span>
            <Select value={settings.voice_asr_model} onValueChange={(value) => setSettings({ ...settings, voice_asr_model: value })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {["tiny", "base", "small", "medium", "large-v3"].map((id) => <SelectItem key={id} value={id}>{id}</SelectItem>)}
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>ASR-apparaat</span>
            <Select value={settings.voice_asr_device} onValueChange={(value: AppSettings["voice_asr_device"]) => setSettings({ ...settings, voice_asr_device: value })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto</SelectItem>
                <SelectItem value="cpu">CPU</SelectItem>
                <SelectItem value="cuda">CUDA</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>ASR compute type</span>
            <Select value={settings.voice_asr_compute_type} onValueChange={(value) => setSettings({ ...settings, voice_asr_compute_type: value })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto</SelectItem>
                <SelectItem value="int8">int8</SelectItem>
                <SelectItem value="float16">float16</SelectItem>
                <SelectItem value="float32">float32</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>TTS-provider</span>
            <Select value={settings.voice_tts_provider} onValueChange={(value: AppSettings["voice_tts_provider"]) => setSettings({ ...settings, voice_tts_provider: value })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="piper">Piper (lokaal)</SelectItem>
                <SelectItem value="browser">Browserstem (client)</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>TTS-stem</span>
            {voices.length ? (
              <Select value={settings.voice_tts_voice || String(voices[0]?.id || "")} onValueChange={(value) => setSettings({ ...settings, voice_tts_voice: value })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {voices.map((voice) => (
                    <SelectItem key={String(voice.id)} value={String(voice.id)}>{String(voice.name || voice.id)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input value={settings.voice_tts_voice} onChange={(event) => setSettings({ ...settings, voice_tts_voice: event.target.value })} placeholder="nl_NL-pim-medium" />
            )}
          </label>
          <label>
            <span>Taal</span>
            <Select value={settings.voice_language} onValueChange={(value: AppSettings["voice_language"]) => setSettings({ ...settings, voice_language: value })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="nl">Nederlands</SelectItem>
                <SelectItem value="en">Engels</SelectItem>
                <SelectItem value="auto">Auto (ASR)</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>Spreekstijl</span>
            <Select value={settings.voice_speak_style} onValueChange={(value: AppSettings["voice_speak_style"]) => setSettings({ ...settings, voice_speak_style: value })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="compact">Compact</SelectItem>
                <SelectItem value="full">Volledig</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>Beurtendetectie</span>
            <Select value={settings.voice_turn_mode} onValueChange={(value: AppSettings["voice_turn_mode"]) => setSettings({ ...settings, voice_turn_mode: value })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="manual">Handmatig / druk-om-te-spreken</SelectItem>
                <SelectItem value="auto">Automatisch (VAD)</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            <span>VAD-gevoeligheid (0–1)</span>
            <Input type="number" min={0} max={1} step={0.05} value={settings.voice_vad_sensitivity} onChange={(event) => setSettings({ ...settings, voice_vad_sensitivity: Number(event.target.value) })} />
          </label>
          <label>
            <span>Eindpauze (ms)</span>
            <Input type="number" min={300} max={5000} value={settings.voice_vad_end_silence_ms} onChange={(event) => setSettings({ ...settings, voice_vad_end_silence_ms: Number(event.target.value) })} />
          </label>
          <label>
            <span>Spreektempo</span>
            <Input type="number" min={0.5} max={2} step={0.05} value={settings.voice_tts_speed} onChange={(event) => setSettings({ ...settings, voice_tts_speed: Number(event.target.value) })} />
          </label>
          <label>
            <span>Volume</span>
            <Input type="number" min={0} max={1} step={0.05} value={settings.voice_tts_volume} onChange={(event) => setSettings({ ...settings, voice_tts_volume: Number(event.target.value) })} />
          </label>
          <label>
            <span>Sessie-inactiviteit (s)</span>
            <Input type="number" min={30} value={settings.voice_session_idle_seconds} onChange={(event) => setSettings({ ...settings, voice_session_idle_seconds: Number(event.target.value) })} />
            <small>Mic/sessie stoppen na stilte (server + client).</small>
          </label>
        </div>
      </Panel>

      <Panel title="Eerste gebruik">
        <label className="form-stack" style={{ marginBottom: "0.75rem" }}>
          <span>Setup voltooid op</span>
          <Input
            value={settings.voice_setup_completed_at}
            onChange={(event) => setSettings({ ...settings, voice_setup_completed_at: event.target.value })}
            placeholder="leeg = nog niet afgerond"
          />
        </label>
        <VoiceSetupWizard
          onComplete={() => {
            setSettings({ ...settings, voice_setup_completed_at: new Date().toISOString() });
            toast.success("Spraaksetup afgerond — sla instellingen op.");
          }}
        />
      </Panel>
    </div>
  );
}
