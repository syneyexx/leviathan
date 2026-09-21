"use client";

import { Mic, MicOff, PhoneOff, Settings, Square, Volume2, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Panel, StatusBadge, type StatusTone } from "@/components/hades/ui";
import { MicLevelMeter } from "@/components/hades/voice/mic-level-meter";
import type { VoiceCaptureMode, VoiceUiStatus } from "@/lib/hades-voice/types";

function statusTone(status: VoiceUiStatus): StatusTone {
  if (status === "Onderbroken" || status === "Verbinding herstellen") return "warning";
  if (status === "Spreekt" || status === "Luistert") return "success";
  if (status === "Verwerkt spraak" || status === "HADES antwoordt" || status === "Microfoon toestaan") return "info";
  return "neutral";
}

function statusLabel(status: VoiceUiStatus): string {
  if (status === "idle") return "Inactief";
  if (status === "stopped") return "Gestopt";
  return status;
}

export type VoicePanelProps = {
  status: VoiceUiStatus;
  level?: number;
  micActive?: boolean;
  modelGenerating?: boolean;
  audioPlaying?: boolean;
  transcript?: string;
  lastAnswer?: string | null;
  error?: string | null;
  muted?: boolean;
  outputMuted?: boolean;
  turnMode?: VoiceCaptureMode;
  lastInterruptLatencyMs?: number | null;
  onToggleMute?: () => void;
  onToggleOutputMute?: () => void;
  onHoldPushToTalk?: (down: boolean) => void;
  onInterrupt?: () => void;
  onStop?: () => void;
  onStart?: () => void;
  onOpenSettings?: () => void;
  compact?: boolean;
};

/** Compact conversation voice panel for chat. */
export function VoicePanel({
  status,
  level = 0,
  micActive = false,
  modelGenerating = false,
  audioPlaying = false,
  transcript,
  lastAnswer,
  error,
  muted = false,
  outputMuted = false,
  turnMode = "continuous",
  lastInterruptLatencyMs = null,
  onToggleMute,
  onToggleOutputMute,
  onHoldPushToTalk,
  onInterrupt,
  onStop,
  onStart,
  onOpenSettings,
  compact = true,
}: VoicePanelProps) {
  const sessionLive = status !== "idle" && status !== "stopped";

  return (
    <Panel
      className={compact ? "voice-panel voice-panel-compact" : "voice-panel"}
      title="Spraakgesprek"
      eyebrow="Lokaal"
      actions={<StatusBadge tone={statusTone(status)}>{statusLabel(status)}</StatusBadge>}
    >
      <div className="form-stack" style={{ gap: "0.55rem" }}>
        <div className="button-row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <div className="button-row" style={{ gap: "0.65rem" }}>
            {muted ? <MicOff aria-hidden /> : <Mic aria-hidden />}
            <MicLevelMeter level={level} active={micActive && !muted && sessionLive} label="Microfoonniveau" />
          </div>
          <div className="button-row" style={{ flexWrap: "wrap" }}>
            {!sessionLive && onStart ? (
              <Button size="sm" variant="outline" onClick={onStart}>
                <Mic />
                Start
              </Button>
            ) : null}
            {sessionLive && turnMode === "push_to_talk" && onHoldPushToTalk ? (
              <Button
                size="sm"
                variant="outline"
                aria-label="Ingedrukt houden om te spreken"
                onPointerDown={(event) => {
                  event.preventDefault();
                  onHoldPushToTalk(true);
                }}
                onPointerUp={() => onHoldPushToTalk(false)}
                onPointerLeave={() => onHoldPushToTalk(false)}
                onPointerCancel={() => onHoldPushToTalk(false)}
              >
                <Mic />
                Spreek (houd in)
              </Button>
            ) : null}
            {sessionLive && onToggleMute ? (
              <Button size="sm" variant="ghost" onClick={onToggleMute} aria-label={muted ? "Microfoon aanzetten" : "Microfoon dempen"}>
                {muted ? <MicOff /> : <Mic />}
                {muted ? "Mic aan" : "Mic dempen"}
              </Button>
            ) : null}
            {sessionLive && onToggleOutputMute ? (
              <Button size="sm" variant="ghost" onClick={onToggleOutputMute} aria-label={outputMuted ? "Uitvoer aanzetten" : "Uitvoer dempen"}>
                {outputMuted ? <VolumeX /> : <Volume2 />}
                {outputMuted ? "Audio aan" : "Audio dempen"}
              </Button>
            ) : null}
            {(audioPlaying || modelGenerating) && onInterrupt ? (
              <Button size="sm" variant="outline" onClick={onInterrupt}>
                <Square />
                Onderbreek
              </Button>
            ) : null}
            {sessionLive && onStop ? (
              <Button size="sm" variant="destructive" onClick={onStop}>
                <PhoneOff />
                Stop
              </Button>
            ) : null}
            {onOpenSettings ? (
              <Button size="sm" variant="ghost" onClick={onOpenSettings} aria-label="Spraakinstellingen">
                <Settings />
                Instellingen
              </Button>
            ) : null}
          </div>
        </div>

        <div className="button-row" style={{ gap: "0.75rem", flexWrap: "wrap", color: "#6d695f", fontSize: "0.68rem" }}>
          <span>Modus: {turnMode === "push_to_talk" ? "handmatig" : "automatisch"}</span>
          <span>Mic: {micActive ? (muted ? "gedempt" : "aan") : "uit"}</span>
          <span>Model: {modelGenerating ? "bezig" : "wacht"}</span>
          <span className="button-row" style={{ gap: "0.25rem" }}>
            <Volume2 style={{ width: "0.85rem" }} />
            Audio: {outputMuted ? "gedempt" : audioPlaying ? "speelt" : "stil"}
          </span>
          {lastInterruptLatencyMs != null ? (
            <span>Onderbrekingslatentie: {lastInterruptLatencyMs} ms</span>
          ) : null}
        </div>

        {transcript ? (
          <p className="panel-copy" style={{ marginBottom: 0 }}>
            Transcriptie: {transcript}
          </p>
        ) : null}
        {lastAnswer ? (
          <p className="panel-copy" style={{ marginBottom: 0 }}>
            Laatste antwoord: {lastAnswer.length > 220 ? `${lastAnswer.slice(0, 220)}…` : lastAnswer}
          </p>
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
