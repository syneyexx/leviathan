"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { voiceApi } from "@/lib/hades-voice/api";
import { browserTts } from "@/lib/hades-voice/browser-tts";
import { PlaybackQueue, playAudioBlob } from "@/lib/hades-voice/playback-queue";

export type UseVoicePlaybackOptions = {
  language?: string;
  voiceId?: string | null;
  style?: "compact" | "full";
  speed?: number;
  volume?: number;
  outputDeviceId?: string | null;
  /** Prefer local Piper TTS; fall back to browser TTS when backend fails. */
  allowBrowserFallback?: boolean;
  /** When true, skip Piper and use speechSynthesis directly (Settings → Browserstem). */
  preferBrowserTts?: boolean;
  onError?: (message: string) => void;
};

export type UseVoicePlaybackResult = {
  speaking: boolean;
  messageId: string | null;
  lastInterruptLatencyMs: number | null;
  error: string | null;
  speak: (text: string, opts?: { messageId?: string; alreadySpeakable?: boolean }) => Promise<void>;
  stop: () => void;
  replay: () => Promise<void>;
  setVolume: (volume: number) => void;
};

/**
 * Speak / stop / replay for assistant messages via /voice/speak (Blob).
 */
export function useVoicePlayback(options: UseVoicePlaybackOptions = {}): UseVoicePlaybackResult {
  const [speaking, setSpeaking] = useState(false);
  const [messageId, setMessageId] = useState<string | null>(null);
  const [lastInterruptLatencyMs, setLastInterruptLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const queueRef = useRef<PlaybackQueue | null>(null);
  const stopHandleRef = useRef<{ stop: () => number } | null>(null);
  const browserStopRef = useRef<(() => void) | null>(null);
  const lastPayloadRef = useRef<{ text: string; messageId?: string; alreadySpeakable?: boolean } | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    queueRef.current = new PlaybackQueue({
      volume: options.volume ?? 1,
      outputDeviceId: options.outputDeviceId,
      onPlayingChange: setSpeaking,
      onInterrupt: (ms) => setLastInterruptLatencyMs(ms),
      onError: (message) => {
        setError(message);
        optionsRef.current.onError?.(message);
      },
    });
    return () => {
      queueRef.current?.dispose();
      queueRef.current = null;
      browserStopRef.current?.();
      stopHandleRef.current = null;
    };
    // intentionally once
     
  }, []);

  useEffect(() => {
    if (options.volume != null) queueRef.current?.setVolume(options.volume);
  }, [options.volume]);

  useEffect(() => {
    void queueRef.current?.setOutputDevice(options.outputDeviceId ?? null);
  }, [options.outputDeviceId]);

  const stop = useCallback(() => {
    browserStopRef.current?.();
    browserStopRef.current = null;
    if (stopHandleRef.current) {
      const ms = stopHandleRef.current.stop();
      setLastInterruptLatencyMs(ms);
      stopHandleRef.current = null;
    }
    const ms = queueRef.current?.stop("user") ?? null;
    if (ms != null) setLastInterruptLatencyMs(ms);
    setSpeaking(false);
  }, []);

  const speak = useCallback(
    async (text: string, opts?: { messageId?: string; alreadySpeakable?: boolean }) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setError(null);
      stop();
      lastPayloadRef.current = {
        text: trimmed,
        messageId: opts?.messageId,
        alreadySpeakable: opts?.alreadySpeakable,
      };
      setMessageId(opts?.messageId ?? null);

      try {
        if (optionsRef.current.preferBrowserTts) {
          const handle = await browserTts.speak(trimmed, {
            lang: optionsRef.current.language || "nl-NL",
            volume: optionsRef.current.volume,
          });
          browserStopRef.current = handle.stop;
          setSpeaking(true);
          await handle.done;
          setSpeaking(false);
          browserStopRef.current = null;
          return;
        }
        const blob = await voiceApi.voiceSpeak({
          text: trimmed,
          voice_id: optionsRef.current.voiceId || undefined,
          language: optionsRef.current.language || "nl",
          style: optionsRef.current.style || "compact",
          already_speakable: Boolean(opts?.alreadySpeakable),
          message_id: opts?.messageId,
          speed: optionsRef.current.speed,
        });
        const handle = playAudioBlob(blob, {
          volume: optionsRef.current.volume,
          outputDeviceId: optionsRef.current.outputDeviceId,
        });
        stopHandleRef.current = handle;
        setSpeaking(true);
        await handle.done;
        setSpeaking(false);
        stopHandleRef.current = null;
      } catch (err) {
        if (optionsRef.current.allowBrowserFallback) {
          try {
            const handle = await browserTts.speak(trimmed, {
              lang: optionsRef.current.language || "nl-NL",
              volume: optionsRef.current.volume,
            });
            browserStopRef.current = handle.stop;
            setSpeaking(true);
            await handle.done;
            setSpeaking(false);
            browserStopRef.current = null;
            return;
          } catch (fallbackErr) {
            const msg =
              fallbackErr instanceof Error ? fallbackErr.message : "Browser-spraak mislukt.";
            setError(msg);
            optionsRef.current.onError?.(msg);
            setSpeaking(false);
            return;
          }
        }
        const msg = err instanceof Error ? err.message : "Voorlezen mislukt.";
        setError(msg);
        optionsRef.current.onError?.(msg);
        setSpeaking(false);
      }
    },
    [stop],
  );

  const replay = useCallback(async () => {
    const last = lastPayloadRef.current;
    if (!last) {
      setError("Niets om opnieuw af te spelen.");
      return;
    }
    await speak(last.text, { messageId: last.messageId, alreadySpeakable: last.alreadySpeakable });
  }, [speak]);

  const setVolume = useCallback((volume: number) => {
    queueRef.current?.setVolume(volume);
  }, []);

  return {
    speaking,
    messageId,
    lastInterruptLatencyMs,
    error,
    speak,
    stop,
    replay,
    setVolume,
  };
}
