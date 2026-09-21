"use client";

import { Square } from "lucide-react";
import { Button } from "@/components/ui/button";

export type VoiceMessageActionsProps = {
  speaking?: boolean;
  isCurrentMessage?: boolean;
  disabled?: boolean;
  onSpeak?: () => void;
  onReplay?: () => void;
  onStop?: () => void;
  className?: string;
};

/**
 * Secondary per-message voice actions.
 * The primary "Voorlezen" button is rendered by ChatPage; this component only
 * exposes replay/stop so the same action is never shown twice.
 */
export function VoiceMessageActions({
  speaking = false,
  isCurrentMessage = false,
  disabled = false,
  onReplay,
  onStop,
  className,
}: VoiceMessageActionsProps) {
  const showStop = speaking && isCurrentMessage;

  return (
    <div className={className ?? "button-row"} style={{ flexWrap: "wrap", gap: "0.25rem" }}>
      {showStop ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 px-2.5 text-[0.68rem]"
          onClick={onStop}
          aria-label="Stop voorlezen"
        >
          <Square />
          Stop
        </Button>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 px-2.5 text-[0.68rem]"
          disabled={disabled}
          onClick={onReplay}
          aria-label="Opnieuw afspelen"
        >
          Opnieuw afspelen
        </Button>
      )}
    </div>
  );
}
