"use client";

import { Mic, MicOff, Phone, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MicLevelMeter } from "@/components/hades/voice/mic-level-meter";

export type VoiceComposerControlsProps = {
  dictationActive?: boolean;
  dictationLevel?: number;
  sessionActive?: boolean;
  speaking?: boolean;
  spokenAnswers?: boolean;
  disabled?: boolean;
  error?: string | null;
  onToggleDictation?: () => void;
  onHoldPushToTalk?: (down: boolean) => void;
  onStartConversation?: () => void;
  onStopConversation?: () => void;
  onSpokenAnswersChange?: (enabled: boolean) => void;
  onStopSpeaking?: () => void;
};

/**
 * Composer strip for dictation and live voice conversation controls.
 * "Gesproken antwoorden" is intentionally owned by the chat title bar so the
 * same setting is not rendered twice in one screen.
 */
export function VoiceComposerControls({
  dictationActive = false,
  dictationLevel = 0,
  sessionActive = false,
  speaking = false,
  disabled = false,
  error,
  onToggleDictation,
  onHoldPushToTalk,
  onStartConversation,
  onStopConversation,
  onStopSpeaking,
}: VoiceComposerControlsProps) {
  return (
    <div className="voice-composer-controls form-stack" style={{ gap: "0.45rem" }}>
      <div className="button-row" style={{ flexWrap: "wrap", gap: "0.45rem", alignItems: "center" }}>
        <Button
          type="button"
          size="sm"
          variant={dictationActive ? "default" : "outline"}
          disabled={disabled || sessionActive}
          aria-pressed={dictationActive}
          aria-label={dictationActive ? "Dictatie stoppen" : "Dictatie starten"}
          onClick={onToggleDictation}
          onPointerDown={(event) => {
            if (!onHoldPushToTalk || sessionActive) return;
            // Hold-to-talk works whether or not toggle-listen is active.
            event.preventDefault();
            onHoldPushToTalk(true);
          }}
          onPointerUp={() => onHoldPushToTalk?.(false)}
          onPointerLeave={() => onHoldPushToTalk?.(false)}
          onPointerCancel={() => onHoldPushToTalk?.(false)}
        >
          {dictationActive ? <MicOff /> : <Mic />}
          Dictatie
        </Button>

        <MicLevelMeter level={dictationLevel} active={dictationActive} label="Dictatieniveau" />

        {!sessionActive ? (
          <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={onStartConversation}>
            <Phone />
            Spraakgesprek
          </Button>
        ) : (
          <Button type="button" size="sm" variant="destructive" disabled={disabled} onClick={onStopConversation}>
            <Phone />
            Gesprek stoppen
          </Button>
        )}

        {speaking ? (
          <Button type="button" size="sm" variant="outline" onClick={onStopSpeaking} aria-label="Stop spreken">
            <Square />
            Stop spreken
          </Button>
        ) : null}
      </div>
      {error ? (
        <div className="inline-error" role="alert" style={{ fontSize: "0.68rem" }}>
          {error}
        </div>
      ) : null}
    </div>
  );
}
