"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioCapture, blobToBase64, voiceMediaSupported } from "@/lib/hades-voice/audio-capture";
import { voiceApi } from "@/lib/hades-voice/api";
import type { MicState, VoiceCaptureMode } from "@/lib/hades-voice/types";

export type UseVoiceDictationOptions = {
  language?: string;
  /** continuous = VAD while listening; push_to_talk = hold to speak */
  mode?: VoiceCaptureMode;
  onTranscript?: (text: string, meta: { isFinal: boolean; silence?: boolean }) => void;
  requireShouldSend?: boolean;
  endSilenceMs?: number;
  speechThreshold?: number;
  deviceId?: string | null;
};

export type UseVoiceDictationResult = {
  listening: boolean;
  level: number;
  micState: MicState;
  error: string | null;
  partialText: string;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  toggle: () => Promise<void>;
  holdPushToTalk: (down: boolean) => void;
  setMuted: (muted: boolean) => void;
};

/**
 * Dictation into a chat composer: capture → transcribe → onTranscript (never auto-sends).
 * Toggle uses continuous VAD by default; hold uses push-to-talk.
 */
export function useVoiceDictation(options: UseVoiceDictationOptions = {}): UseVoiceDictationResult {
  const [listening, setListening] = useState(false);
  const [level, setLevel] = useState(0);
  const [micState, setMicState] = useState<MicState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [partialText, setPartialText] = useState("");

  const captureRef = useRef<AudioCapture | null>(null);
  const busyRef = useRef(false);
  const holdActiveRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const teardown = useCallback(async () => {
    if (captureRef.current) {
      await captureRef.current.stop();
      captureRef.current = null;
    }
    holdActiveRef.current = false;
    setListening(false);
    setLevel(0);
    setMicState("idle");
  }, []);

  useEffect(() => () => {
    void teardown();
  }, [teardown]);

  const handleUtterance = useCallback(async (blob: Blob, mimeType: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    try {
      const audio_base64 = await blobToBase64(blob);
      const result = await voiceApi.voiceTranscribe({
        audio_base64,
        mime_type: mimeType || blob.type || "audio/webm",
        language: optionsRef.current.language || "nl",
        is_final: true,
      });
      const text = (result.text || "").trim();
      if (result.silence || !text) {
        optionsRef.current.onTranscript?.("", { isFinal: true, silence: true });
        setPartialText("");
        return;
      }
      if (optionsRef.current.requireShouldSend && result.should_send === false) return;
      setPartialText(text);
      optionsRef.current.onTranscript?.(text, { isFinal: true, silence: false });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Dictatie mislukt.";
      setError(msg);
    } finally {
      busyRef.current = false;
    }
  }, []);

  const ensureCapture = useCallback(async (mode: VoiceCaptureMode) => {
    const support = voiceMediaSupported();
    if (!support.ok) {
      setError(support.reason || "Microfoon niet beschikbaar.");
      setMicState(support.reason?.includes("beveiligde") ? "insecure" : "unsupported");
      throw new Error(support.reason || "Microfoon niet beschikbaar.");
    }
    if (captureRef.current) {
      captureRef.current.setMode(mode);
      captureRef.current.updateOptions({
        endSilenceMs: optionsRef.current.endSilenceMs,
        speechThreshold: optionsRef.current.speechThreshold,
        deviceId: optionsRef.current.deviceId,
      });
      return captureRef.current;
    }
    const capture = new AudioCapture({
      mode,
      deviceId: optionsRef.current.deviceId,
      endSilenceMs: optionsRef.current.endSilenceMs,
      speechThreshold: optionsRef.current.speechThreshold,
      onLevel: setLevel,
      onStateChange: setMicState,
      onError: (message) => setError(message),
      onSpeechEnd: (blob, mime) => {
        void handleUtterance(blob, mime);
      },
    });
    captureRef.current = capture;
    await capture.requestPermissionAndStart(optionsRef.current.deviceId);
    setListening(true);
    return capture;
  }, [handleUtterance]);

  const start = useCallback(async () => {
    setError(null);
    // Toggle listen uses continuous VAD so clicking Dictatie actually captures speech.
    const mode: VoiceCaptureMode = optionsRef.current.mode === "push_to_talk" ? "continuous" : (optionsRef.current.mode || "continuous");
    try {
      await ensureCapture(mode);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Microfoon starten mislukt.");
      await teardown();
    }
  }, [ensureCapture, teardown]);

  const stop = useCallback(async () => {
    await teardown();
  }, [teardown]);

  const toggle = useCallback(async () => {
    if (listening) await stop();
    else await start();
  }, [listening, start, stop]);

  const holdPushToTalk = useCallback((down: boolean) => {
    void (async () => {
      try {
        if (down) {
          holdActiveRef.current = true;
          setError(null);
          const capture = await ensureCapture("push_to_talk");
          capture.holdPushToTalk(true);
        } else if (holdActiveRef.current) {
          holdActiveRef.current = false;
          captureRef.current?.holdPushToTalk(false);
          // End hold session so mic does not stay open unnoticed.
          await teardown();
        }
      } catch (err) {
        holdActiveRef.current = false;
        setError(err instanceof Error ? err.message : "Druk-om-te-spreken mislukt.");
        await teardown();
      }
    })();
  }, [ensureCapture, teardown]);

  const setMuted = useCallback((muted: boolean) => {
    captureRef.current?.setMuted(muted);
  }, []);

  return {
    listening,
    level,
    micState,
    error,
    partialText,
    start,
    stop,
    toggle,
    holdPushToTalk,
    setMuted,
  };
}
