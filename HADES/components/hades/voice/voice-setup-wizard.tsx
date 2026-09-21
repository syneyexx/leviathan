"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, Mic, Settings, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Panel, StatusBadge, checkStatusTone, type StatusTone } from "@/components/hades/ui";
import { voiceApi } from "@/lib/hades-voice/api";
import { voiceMediaSupported } from "@/lib/hades-voice/audio-capture";
import { browserTts } from "@/lib/hades-voice/browser-tts";
import { VOICE_SETUP_DONE_KEY, type VoiceStatus } from "@/lib/hades-voice/types";

export type VoiceSetupWizardProps = {
  open?: boolean;
  onComplete?: () => void;
  onClose?: () => void;
};

type StepId = "intro" | "mic" | "backend" | "install" | "done";

function checkTone(ok: boolean): StatusTone {
  return ok ? "success" : "danger";
}

/**
 * First-use voice setup flow (Dutch labels).
 */
export function VoiceSetupWizard({ open = true, onComplete, onClose }: VoiceSetupWizardProps) {
  const [step, setStep] = useState<StepId>("intro");
  const [micOk, setMicOk] = useState<boolean | null>(null);
  const [micMessage, setMicMessage] = useState<string>("");
  const [doctor, setDoctor] = useState<VoiceStatus | null>(null);
  const [browserOffline, setBrowserOffline] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [installLog, setInstallLog] = useState<string>("");

  useEffect(() => {
    if (!open) return;
    void (async () => {
      const status = await browserTts.status();
      setBrowserOffline(status.offline);
    })();
  }, [open]);

  if (!open) return null;

  const requestMic = async () => {
    setError(null);
    const support = voiceMediaSupported();
    if (!support.ok) {
      setMicOk(false);
      setMicMessage(support.reason || "Microfoon niet beschikbaar.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      for (const track of stream.getTracks()) track.stop();
      setMicOk(true);
      setMicMessage("Microfoon toegestaan.");
      setStep("backend");
    } catch (err) {
      setMicOk(false);
      const name = err instanceof DOMException ? err.name : "";
      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        setMicMessage("Toegang geweigerd. Sta de microfoon toe in de browser of Windows-privacyinstellingen.");
      } else {
        setMicMessage(err instanceof Error ? err.message : "Microfoontest mislukt.");
      }
    }
  };

  const runDoctor = async () => {
    setBusy(true);
    setError(null);
    try {
      const report = await voiceApi.voiceDoctor();
      setDoctor(report);
      if (report.ready) setStep("done");
      else setStep("install");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Diagnose mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const runInstall = async () => {
    setBusy(true);
    setError(null);
    setInstallLog("Installatie gestart…");
    try {
      const result = await voiceApi.voiceInstall({
        steps: ["deps", "whisper", "piper_voice"],
        approved_network: true,
        approved_subprocess: true,
      });
      setInstallLog(JSON.stringify(result, null, 2).slice(0, 2000));
      const report = await voiceApi.voiceDoctor();
      setDoctor(report);
      if (report.ready) setStep("done");
      else setError("Installatie afgerond, maar voice is nog niet gereed. Controleer de checks hieronder.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Installatie mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const finish = () => {
    try {
      localStorage.setItem(VOICE_SETUP_DONE_KEY, "1");
    } catch {
      // ignore
    }
    onComplete?.();
    onClose?.();
  };

  return (
    <Panel
      title="Spraak instellen"
      eyebrow="Eerste gebruik"
      actions={
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Sluiten">
          <Settings />
          Later
        </Button>
      }
    >
      <div className="form-stack">
        {step === "intro" ? (
          <>
            <p className="panel-copy">
              HADES spraak werkt lokaal: microfoon in de browser, herkenning en voorlezen via de lokale backend
              (Whisper + Piper). Internet is alleen nodig voor de eerste modeldownload.
            </p>
            <div className="check-list">
              <span>
                <Check /> Nederlandse UI-labels en lokale verwerking
              </span>
              <span>
                <Check /> Browser-TTS telt alleen als offline bij native/lokale stemmen
                {browserOffline === null ? "" : browserOffline ? " (lokaal beschikbaar)" : " (niet offline)"}
              </span>
            </div>
            <Button onClick={() => setStep("mic")}>
              <Mic />
              Beginnen
            </Button>
          </>
        ) : null}

        {step === "mic" ? (
          <>
            <p className="panel-copy">Stap 1 — Microfoontoegang (vereist een gebruikersklik).</p>
            <Button onClick={() => void requestMic()}>
              <Mic />
              Microfoon toestaan
            </Button>
            {micOk != null ? <StatusBadge tone={checkTone(micOk)}>{micMessage}</StatusBadge> : null}
          </>
        ) : null}

        {step === "backend" ? (
          <>
            <p className="panel-copy">Stap 2 — Lokale voice-backend controleren.</p>
            <Button onClick={() => void runDoctor()} disabled={busy}>
              {busy ? <Loader2 className="spin" /> : <Volume2 />}
              Diagnose starten
            </Button>
            {doctor ? (
              <div className="check-list">
                {doctor.checks?.map((check) => (
                  <span key={check.id}>
                    <StatusBadge tone={check.ok ? "success" : checkStatusTone("error")}>
                      {check.id}
                    </StatusBadge>{" "}
                    {check.detail}
                  </span>
                ))}
              </div>
            ) : null}
          </>
        ) : null}

        {step === "install" ? (
          <>
            <p className="panel-copy">
              Stap 3 — Ontbrekende onderdelen installeren (Python-deps, Whisper-model, Piper-stem). Dit kan enkele
              minuten duren en vereist netwerk bij de eerste download.
            </p>
            <Button onClick={() => void runInstall()} disabled={busy}>
              {busy ? <Loader2 className="spin" /> : <Settings />}
              Installeren
            </Button>
            {installLog ? <pre className="log-view" style={{ maxHeight: "8rem", overflow: "auto" }}>{installLog}</pre> : null}
            {doctor ? (
              <div className="check-list">
                {doctor.checks?.map((check) => (
                  <span key={check.id}>
                    <StatusBadge tone={check.ok ? "success" : "danger"}>{check.id}</StatusBadge> {check.detail}
                  </span>
                ))}
              </div>
            ) : null}
          </>
        ) : null}

        {step === "done" ? (
          <>
            <p className="panel-copy">Spraak is gereed. Je kunt dicteren, een spraakgesprek starten of antwoorden laten voorlezen.</p>
            <StatusBadge tone="success">Gereed</StatusBadge>
            <Button onClick={finish}>
              <Check />
              Afronden
            </Button>
          </>
        ) : null}

        {error ? (
          <div className="inline-error" role="alert">
            {error}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

export function isVoiceSetupDone(): boolean {
  try {
    return localStorage.getItem(VOICE_SETUP_DONE_KEY) === "1";
  } catch {
    return false;
  }
}
